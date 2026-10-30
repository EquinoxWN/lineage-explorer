"""Real dbt-ol seed and run against DuckDB, with events captured by OpenLineage's file transport."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from lineage_explorer.validate import read_events, summarize

pytest.importorskip("openlineage.dbt", reason="needs the dbt extra")
pytestmark = pytest.mark.dbt

PROJECT = Path(__file__).resolve().parents[2] / "integrations" / "dbt"


@pytest.fixture(scope="module")
def dbt_events(tmp_path_factory: pytest.TempPathFactory) -> list[dict[str, Any]]:
    """Run dbt-ol seed and dbt-ol run once and return every event they emitted."""
    work = tmp_path_factory.mktemp("dbt")
    log = work / "events.jsonl"
    scripts = Path(sys.executable).parent
    env = {
        **os.environ,
        "PATH": f"{scripts}{os.pathsep}{os.environ.get('PATH', '')}",
        "DBT_TARGET_PATH": str(work / "target"),
        "DBT_LOG_PATH": str(work / "logs"),
        "DBT_DUCKDB_PATH": str(work / "shop.duckdb"),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        "DBT_HINTS_ENABLED": "false",
        # dbt writes ~/.dbt/hint_ts.json; keep its home inside the test folder.
        "HOME": str(work),
        "USERPROFILE": str(work),
        "OPENLINEAGE__TRANSPORT__TYPE": "file",
        "OPENLINEAGE__TRANSPORT__LOG_FILE_PATH": str(log),
        "OPENLINEAGE__TRANSPORT__APPEND": "true",
        "OPENLINEAGE_NAMESPACE": "dbt",
    }
    dbt_ol = shutil.which("dbt-ol", path=str(scripts))
    assert dbt_ol, "dbt-ol not installed next to this Python"
    for cmd in ("seed", "run"):
        done = subprocess.run(
            [dbt_ol, cmd, "--project-dir", str(PROJECT), "--profiles-dir", str(PROJECT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    return read_events(log)


def test_every_model_run_has_start_and_complete(dbt_events: list[dict[str, Any]]) -> None:
    s = summarize(dbt_events)
    models = {k: v for k, v in s.jobs.items() if ".shop." in k}
    assert sorted(models) == [
        "dbt/shop.main.shop.customer_revenue",
        "dbt/shop.main.shop.stg_customers",
        "dbt/shop.main.shop.stg_orders",
    ]
    assert all(c == {"START": 1, "COMPLETE": 1} for c in models.values())
    # One parent job run per dbt command (seed and run).
    assert s.jobs["dbt/dbt-run-shop"] == {"START": 2, "COMPLETE": 2}


def test_dbt_events_pass_the_openlineage_schemas(dbt_events: list[dict[str, Any]]) -> None:
    assert summarize(dbt_events).invalid == []


def test_inputs_outputs_and_column_lineage_follow_the_models(
    dbt_events: list[dict[str, Any]],
) -> None:
    done = {
        e["job"]["name"].rsplit(".", 1)[-1]: e
        for e in dbt_events
        if e["eventType"] == "COMPLETE" and e.get("outputs")
    }
    io = {
        k: (sorted(d["name"] for d in e["inputs"]), [d["name"] for d in e["outputs"]])
        for k, e in done.items()
    }
    assert io == {
        "stg_orders": (["shop.main.raw_orders"], ["shop.main.stg_orders"]),
        "stg_customers": (["shop.main.raw_customers"], ["shop.main.stg_customers"]),
        "customer_revenue": (
            ["shop.main.stg_customers", "shop.main.stg_orders"],
            ["shop.main.customer_revenue"],
        ),
    }
    mart = done["customer_revenue"]["outputs"][0]["facets"]
    assert [f["name"] for f in mart["schema"]["fields"]] == [
        "customer_id",
        "customer_name",
        "country",
        "orders",
        "revenue",
    ]
    revenue = mart["columnLineage"]["fields"]["revenue"]["inputFields"]
    assert [(f["name"], f["field"]) for f in revenue] == [("shop.main.stg_orders", "amount")]
    renamed = done["stg_customers"]["outputs"][0]["facets"]["columnLineage"]["fields"][
        "customer_name"
    ]
    assert [f["field"] for f in renamed["inputFields"]] == ["name"]
