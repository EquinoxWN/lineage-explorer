"""Offline validation against the bundled OpenLineage 2-0-2 and facet schemas."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from lineage_explorer import validate
from lineage_explorer.validate import read_events, summarize, validate_event

SCHEMA_URL = (
    "https://openlineage.io/spec/facets/1-2-0/SchemaDatasetFacet.json#/$defs/SchemaDatasetFacet"
)
GOOD: dict[str, Any] = {
    "eventType": "COMPLETE",
    "eventTime": "2026-10-23T10:00:00+00:00",
    "producer": "https://github.com/EquinoxWN/lineage-explorer/tree/main/python",
    "schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent",
    "run": {"runId": "0192b1d4-8f3e-7c2a-9d1e-1f2a3b4c5d6e", "facets": {}},
    "job": {"namespace": "scripts", "name": "clean_orders", "facets": {}},
    "inputs": [],
    "outputs": [
        {
            "namespace": "file",
            "name": "/data/clean/orders.csv",
            "facets": {
                "schema": {
                    "_producer": "https://example.org/p",
                    "_schemaURL": SCHEMA_URL,
                    "fields": [{"name": "order_id", "type": "INTEGER"}],
                }
            },
        }
    ],
}
DELETE = object()


def broken(path: list[str | int], value: Any) -> dict[str, Any]:
    """A copy of GOOD with one value replaced, or removed when value is DELETE."""
    ev = copy.deepcopy(GOOD)
    target: Any = ev
    for p in path[:-1]:
        target = target[p]
    if value is DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return ev


def test_a_valid_event_has_no_problems() -> None:
    assert validate_event(GOOD) == []


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (["run", "runId"], "not-a-uuid", "uuid"),
        (["run"], DELETE, "'run' is a required property"),
        (["job", "name"], DELETE, "'name' is a required property"),
        (["eventTime"], "yesterday", "date-time"),
        (["producer"], 42, "is not of type 'string'"),
        (
            ["outputs", 0, "facets", "schema", "fields", 0, "name"],
            DELETE,
            "'name' is a required property",
        ),
        (
            ["outputs", 0, "facets", "schema", "_producer"],
            DELETE,
            "'_producer' is a required property",
        ),
    ],
)
def test_schema_violations_are_reported_with_their_path(
    path: list[str | int], value: Any, message: str
) -> None:
    problems = validate_event(broken(path, value))
    assert any(message in p for p in problems), problems


def test_unknown_custom_facets_are_allowed_but_must_be_objects() -> None:
    custom = {"_producer": "https://x", "_schemaURL": "https://x#/y", "k": 1}
    assert validate_event(broken(["run", "facets"], {"myFacet": custom})) == []
    assert validate_event(broken(["run", "facets"], {"myFacet": 3}))


def test_read_events_rejects_bad_lines(tmp_path: Path) -> None:
    f = tmp_path / "e.jsonl"
    f.write_text('{"a": 1}\n\n[1]\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"e.jsonl:3: expected a JSON object"):
        read_events(f)
    f.write_text('{"a": 1}\n{nope\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"e.jsonl:2: not JSON"):
        read_events(f)
    f.write_text('{"a": 1}\n' * 3, encoding="utf-8")
    with pytest.raises(ValueError, match="more than 2 events"):
        read_events(f, max_events=2)


def test_read_events_rejects_oversized_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(validate, "MAX_LINE_BYTES", 64)
    f = tmp_path / "big.jsonl"
    f.write_text('{"pad": "' + "x" * 100 + '"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="longer than 64 bytes"):
        read_events(f)


def test_summary_counts_jobs_runs_and_lineage_columns() -> None:
    start = broken(["eventType"], "START")
    lineage = {
        "_producer": "https://x",
        "_schemaURL": "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json#/$defs/ColumnLineageDatasetFacet",
        "fields": {
            "order_id": {
                "inputFields": [{"namespace": "file", "name": "/raw.csv", "field": "order_id"}]
            }
        },
    }
    done = broken(["outputs", 0, "facets", "columnLineage"], lineage)
    s = summarize([start, done, broken(["run", "runId"], "bad")])
    assert s.events == 3
    assert s.by_type == {"START": 1, "COMPLETE": 2}
    assert s.jobs == {"scripts/clean_orders": {"START": 1, "COMPLETE": 2}}
    assert len(s.runs) == 2
    assert s.columns_with_lineage == 1
    assert len(s.invalid) == 1
    assert s.invalid[0].startswith("event 2: run/runId")
