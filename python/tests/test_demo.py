"""The plain-script demo pipeline and the lineage-emit command."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from lineage_explorer.cli import main
from lineage_explorer.demo import run_pipeline, write_sample
from lineage_explorer.emitter import LineageEmitter
from lineage_explorer.validate import read_events, summarize

Events = list[dict[str, Any]]


def test_pipeline_writes_correct_csvs_and_one_run_per_script(
    tmp_path: Path, capture: tuple[LineageEmitter, Events]
) -> None:
    em, events = capture
    write_sample(tmp_path)
    rows = run_pipeline(em, tmp_path)
    with (tmp_path / "raw" / "orders.csv").open(encoding="utf-8") as fh:
        raw = list(csv.DictReader(fh))
    paid = [r for r in raw if r["status"] == "paid"]
    assert rows == {"clean_orders": len(paid), "customer_revenue": 8}
    with (tmp_path / "marts" / "customer_revenue.csv").open(encoding="utf-8") as fh:
        mart = list(csv.DictReader(fh))
    assert sum(int(r["orders"]) for r in mart) == len(paid)
    assert round(sum(float(r["revenue"]) for r in mart), 2) == round(
        sum(float(r["amount"]) for r in paid), 2
    )

    order = [(e["job"]["name"], e["eventType"]) for e in events]
    assert order == [
        ("shop_pipeline", "START"),
        ("clean_orders", "START"),
        ("clean_orders", "COMPLETE"),
        ("customer_revenue", "START"),
        ("customer_revenue", "COMPLETE"),
        ("shop_pipeline", "COMPLETE"),
    ]
    s = summarize(events)
    assert s.invalid == []
    assert len(s.runs) == 3
    assert s.columns_with_lineage == 3 + 5
    mart_out = events[4]["outputs"][0]
    assert mart_out["name"].endswith("/marts/customer_revenue.csv")
    sources = {
        f["name"].rsplit("/", 2)[-2]
        for f in mart_out["facets"]["columnLineage"]["fields"]["customer_id"]["inputFields"]
    }
    assert sources == {"raw", "clean"}


def test_a_failing_script_reports_fail_and_stops_the_pipeline(
    tmp_path: Path, capture: tuple[LineageEmitter, Events]
) -> None:
    em, events = capture
    write_sample(tmp_path)
    (tmp_path / "raw" / "customers.csv").unlink()
    with pytest.raises(FileNotFoundError):
        run_pipeline(em, tmp_path)
    assert [(e["job"]["name"], e["eventType"]) for e in events][-3:] == [
        ("customer_revenue", "START"),
        ("customer_revenue", "FAIL"),
        ("shop_pipeline", "FAIL"),
    ]


def test_cli_demo_then_validate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "events.jsonl"
    assert main(["demo", "--dir", str(tmp_path / "work"), "--target", f"file:{log}"]) == 0
    assert "clean_orders=" in capsys.readouterr().out
    assert len(read_events(log)) == 6
    assert main(["validate", str(log)]) == 0
    out = capsys.readouterr().out
    assert "6 events (COMPLETE=3 START=3), 3 runs, 3 jobs" in out
    assert "schema: all valid" in out


def test_cli_validate_fails_on_bad_events(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"eventType": "START"}\n', encoding="utf-8")
    assert main(["validate", str(bad)]) == 1
    assert "INVALID event 0" in capsys.readouterr().out
    assert main(["validate", str(tmp_path / "missing.jsonl")]) == 2
    assert main(["demo", "--dir", str(tmp_path), "--target", "gopher://x"]) == 2
