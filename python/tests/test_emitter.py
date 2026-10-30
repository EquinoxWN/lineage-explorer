"""The custom emitter: event order, facets, failures, transports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lineage_explorer.emitter import Column, DatasetRef, LineageEmitter, client_for
from lineage_explorer.validate import validate_event

Events = list[dict[str, Any]]

SRC = DatasetRef("file", "/data/raw/orders.csv", [("order_id", "INTEGER"), ("amount", "DECIMAL")])
DST = DatasetRef(
    "file",
    "/data/clean/orders.csv",
    [("order_id", "INTEGER"), ("amount", "DECIMAL")],
    {
        "order_id": [Column("file", SRC.name, "order_id")],
        "amount": [Column("file", SRC.name, "amount")],
    },
)


def test_success_emits_start_then_complete_for_one_run(
    capture: tuple[LineageEmitter, Events],
) -> None:
    em, events = capture
    with em.run("clean_orders", [SRC], [DST]) as run:
        assert [e["eventType"] for e in events] == ["START"]
    assert [e["eventType"] for e in events] == ["START", "COMPLETE"]
    assert {e["run"]["runId"] for e in events} == {run.run_id}
    done = events[1]
    assert (done["job"]["namespace"], done["job"]["name"]) == ("scripts", "clean_orders")
    assert done["job"]["facets"]["jobType"]["jobType"] == "SCRIPT"
    assert [d["name"] for d in done["inputs"]] == ["/data/raw/orders.csv"]
    out = done["outputs"][0]["facets"]
    assert [f["name"] for f in out["schema"]["fields"]] == ["order_id", "amount"]
    assert out["columnLineage"]["fields"]["amount"]["inputFields"] == [
        {"namespace": "file", "name": SRC.name, "field": "amount", "transformations": []}
    ]
    assert all(validate_event(e) == [] for e in events)


def test_failure_emits_fail_with_error_and_reraises(capture: tuple[LineageEmitter, Events]) -> None:
    em, events = capture
    with pytest.raises(KeyError, match="status"), em.run("broken", [SRC]):
        raise KeyError("status")
    assert [e["eventType"] for e in events] == ["START", "FAIL"]
    err = events[1]["run"]["facets"]["errorMessage"]
    assert err["message"] == "KeyError: 'status'"
    assert err["programmingLanguage"] == "PYTHON"
    assert "raise KeyError" in err["stackTrace"]
    assert validate_event(events[1]) == []


def test_parent_facet_links_child_runs(capture: tuple[LineageEmitter, Events]) -> None:
    em, events = capture
    with em.run("pipeline") as p, em.run("step", parent=("scripts", "pipeline", p.run_id)):
        pass
    child = [e for e in events if e["job"]["name"] == "step"]
    assert len(child) == 2
    assert all(e["run"]["facets"]["parent"]["run"]["runId"] == p.run_id for e in child)
    assert all(validate_event(e) == [] for e in events)


def test_decorator_wraps_a_script_main(capture: tuple[LineageEmitter, Events]) -> None:
    em, events = capture

    @em.track("nightly", [SRC], [DST])
    def main(x: int) -> int:
        return x * 2

    assert main(21) == 42
    assert main.__name__ == "main"
    assert [e["eventType"] for e in events] == ["START", "COMPLETE"]


@pytest.mark.parametrize("bad", ["", "x" * 1025, "tab\there", "nl\n"])
def test_names_are_checked(capture: tuple[LineageEmitter, Events], bad: str) -> None:
    em, events = capture
    with pytest.raises(ValueError, match="printable"):
        DatasetRef("file", bad)
    with pytest.raises(ValueError, match="printable"), em.run(bad):
        pass
    assert events == []


def test_lineage_must_name_declared_columns() -> None:
    with pytest.raises(ValueError, match=r"undeclared columns: \['total'\]"):
        DatasetRef("file", "/x.csv", [("a", "INT")], {"total": [Column("file", "/y.csv", "a")]})


@pytest.mark.parametrize(
    "bad", ["ftp://host", "file:", "localhost:5000", "javascript:alert(1)", "http://"]
)
def test_client_targets_are_validated(bad: str) -> None:
    with pytest.raises(ValueError, match=r"target|path"):
        client_for(bad)


def test_file_target_appends_json_lines(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    em = LineageEmitter("scripts", client_for(f"file:{log}"))
    with em.run("a"):
        pass
    with em.run("b"):
        pass
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [(e["job"]["name"], e["eventType"]) for e in lines] == [
        ("a", "START"),
        ("a", "COMPLETE"),
        ("b", "START"),
        ("b", "COMPLETE"),
    ]


def test_http_target_posts_to_the_marquez_lineage_endpoint(
    stub_endpoint: tuple[str, list[tuple[str, dict[str, Any]]]],
) -> None:
    url, received = stub_endpoint
    client = client_for(url)
    with LineageEmitter("scripts", client).run("clean_orders", [SRC], [DST]):
        pass
    client.close(5)
    assert [p for p, _ in received] == ["/api/v1/lineage", "/api/v1/lineage"]
    assert [b["eventType"] for _, b in received] == ["START", "COMPLETE"]
    assert all(validate_event(b) == [] for _, b in received)
