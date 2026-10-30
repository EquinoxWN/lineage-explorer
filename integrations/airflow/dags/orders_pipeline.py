"""Airflow 3 DAG whose task runs are reported by the apache-airflow-providers-openlineage listener.

The provider needs no code here: it is configured with AIRFLOW__OPENLINEAGE__* variables (see the
CI workflow). Inlets and outlets are OpenLineage datasets, which the provider reports as the
inputs and outputs of each task run.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG
from openlineage.client.event_v2 import Dataset

SEEDS = Path(os.environ.get("SHOP_SEEDS", "/opt/shop/seeds"))
WORK = Path(os.environ.get("SHOP_WORK", "/tmp/shop"))  # noqa: S108 - overridden in CI
NS = "file"
RAW = Dataset(namespace=NS, name=str(SEEDS / "raw_orders.csv"))
PAID = Dataset(namespace=NS, name=str(WORK / "paid_orders.csv"))
TOTALS = Dataset(namespace=NS, name=str(WORK / "revenue_total.txt"))


def extract_paid() -> int:
    """Copy paid orders to the work folder; returns the row count."""
    WORK.mkdir(parents=True, exist_ok=True)
    rows = 0
    with (
        (SEEDS / "raw_orders.csv").open(newline="") as fi,
        (WORK / "paid_orders.csv").open("w", newline="") as fo,
    ):
        reader = csv.DictReader(fi)
        writer = csv.DictWriter(fo, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            if row["status"] == "paid":
                writer.writerow(row)
                rows += 1
    return rows


def total_revenue() -> str:
    """Sum the paid amounts into a one-line text file."""
    with (WORK / "paid_orders.csv").open(newline="") as fh:
        total = sum(float(r["amount"]) for r in csv.DictReader(fh))
    (WORK / "revenue_total.txt").write_text(f"{total:.2f}\n")
    return f"{total:.2f}"


with DAG(dag_id="orders_pipeline", schedule=None, catchup=False, tags=["lineage-explorer"]):
    extract = PythonOperator(
        task_id="extract_paid", python_callable=extract_paid, inlets=[RAW], outlets=[PAID]
    )
    total = PythonOperator(
        task_id="total_revenue", python_callable=total_revenue, inlets=[PAID], outlets=[TOTALS]
    )
    extract >> total
