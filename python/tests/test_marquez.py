"""Custom emitter to a real Marquez, read back through its API (CI service; skipped without MARQUEZ_URL)."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

import pytest

from lineage_explorer.emitter import Column, DatasetRef, LineageEmitter, client_for

pytestmark = pytest.mark.marquez
URL = os.environ.get("MARQUEZ_URL", "")


def get(path: str) -> Any:
    """GET a Marquez API path and decode the JSON body."""
    with urllib.request.urlopen(f"{URL}/api/v1/{path}", timeout=10) as r:
        return json.loads(r.read())


@pytest.mark.skipif(not URL.startswith(("http://", "https://")), reason="needs MARQUEZ_URL")
def test_marquez_stores_the_job_run_datasets_and_columns() -> None:
    ns = f"e2e-{int(time.time())}"
    src = DatasetRef(
        "e2e-files", f"{ns}/orders.csv", [("order_id", "INTEGER"), ("amount", "DECIMAL")]
    )
    dst = DatasetRef(
        "e2e-files",
        f"{ns}/revenue.csv",
        [("revenue", "DECIMAL")],
        {"revenue": [Column("e2e-files", src.name, "amount")]},
    )
    client = client_for(URL)
    with LineageEmitter(ns, client).run("revenue_job", [src], [dst]) as run:
        pass
    client.close(10)

    job: dict[str, Any] = {}
    for _ in range(30):
        job = get(f"namespaces/{ns}/jobs/revenue_job")
        if (job.get("latestRun") or {}).get("state") == "COMPLETED":
            break
        time.sleep(1)
    assert job["latestRun"]["id"] == run.run_id
    assert job["latestRun"]["state"] == "COMPLETED"
    assert [d["name"] for d in job["inputs"]] == [src.name]
    assert [d["name"] for d in job["outputs"]] == [dst.name]

    ds = get(f"namespaces/e2e-files/datasets/{urllib.parse.quote(dst.name, safe='')}")
    assert [f["name"] for f in ds["fields"]] == ["revenue"]
    lineage = get(f"lineage?nodeId={urllib.parse.quote(f'dataset:e2e-files:{dst.name}')}&depth=2")
    ids = {n["id"] for n in lineage["graph"]}
    assert {f"job:{ns}:revenue_job", f"dataset:e2e-files:{src.name}"} <= ids
