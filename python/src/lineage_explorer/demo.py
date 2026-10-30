"""Two plain Python scripts over CSV files, each run reported through the custom emitter."""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from pathlib import Path

from lineage_explorer.emitter import Column, DatasetRef, LineageEmitter

NS = "file"
ORDER_FIELDS = [
    ("order_id", "INTEGER"),
    ("customer_id", "INTEGER"),
    ("amount", "DECIMAL"),
    ("status", "VARCHAR"),
]
CUSTOMER_FIELDS = [("customer_id", "INTEGER"), ("name", "VARCHAR"), ("country", "VARCHAR")]
CLEAN_FIELDS = ORDER_FIELDS[:3]
MART_FIELDS = [*CUSTOMER_FIELDS, ("orders", "INTEGER"), ("revenue", "DECIMAL")]


def _name(path: Path) -> str:
    """Dataset name for a local file: its absolute POSIX path."""
    return path.resolve().as_posix()


def write_sample(root: Path, seed: int = 7) -> None:
    """Write a small deterministic raw/orders.csv and raw/customers.csv."""
    rng = random.Random(seed)  # noqa: S311 - sample data, not security
    raw = root / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    countries = ["DE", "FR", "KE", "US"]
    with (raw / "customers.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f for f, _ in CUSTOMER_FIELDS])
        for c in range(1, 9):
            w.writerow([c, f"customer {c}", countries[c % len(countries)]])
    with (raw / "orders.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f for f, _ in ORDER_FIELDS])
        for o in range(1, 41):
            status = rng.choice(["paid", "paid", "paid", "refunded"])
            w.writerow([o, rng.randint(1, 8), f"{rng.randint(500, 20000) / 100:.2f}", status])


def clean_orders(em: LineageEmitter, root: Path, parent: tuple[str, str, str] | None = None) -> int:
    """Keep paid orders and drop the status column; returns rows written."""
    src, dst = root / "raw" / "orders.csv", root / "clean" / "orders.csv"
    inp = DatasetRef(NS, _name(src), ORDER_FIELDS)
    out = DatasetRef(
        NS,
        _name(dst),
        CLEAN_FIELDS,
        {f: [Column(NS, inp.name, f)] for f, _ in CLEAN_FIELDS},
    )
    with em.run("clean_orders", [inp], [out], parent):
        dst.parent.mkdir(parents=True, exist_ok=True)
        rows = 0
        with (
            src.open(newline="", encoding="utf-8") as fi,
            dst.open("w", newline="", encoding="utf-8") as fo,
        ):
            w = csv.writer(fo)
            w.writerow([f for f, _ in CLEAN_FIELDS])
            for r in csv.DictReader(fi):
                if r["status"] == "paid":
                    w.writerow([r["order_id"], r["customer_id"], r["amount"]])
                    rows += 1
        return rows


def customer_revenue(
    em: LineageEmitter, root: Path, parent: tuple[str, str, str] | None = None
) -> int:
    """Orders and revenue per customer; returns rows written."""
    orders, customers = root / "clean" / "orders.csv", root / "raw" / "customers.csv"
    dst = root / "marts" / "customer_revenue.csv"
    o_ref = DatasetRef(NS, _name(orders), CLEAN_FIELDS)
    c_ref = DatasetRef(NS, _name(customers), CUSTOMER_FIELDS)
    lineage = {
        "customer_id": [
            Column(NS, c_ref.name, "customer_id"),
            Column(NS, o_ref.name, "customer_id"),
        ],
        "name": [Column(NS, c_ref.name, "name")],
        "country": [Column(NS, c_ref.name, "country")],
        "orders": [Column(NS, o_ref.name, "order_id")],
        "revenue": [Column(NS, o_ref.name, "amount")],
    }
    out = DatasetRef(NS, _name(dst), MART_FIELDS, lineage)
    with em.run("customer_revenue", [o_ref, c_ref], [out], parent):
        count: defaultdict[str, int] = defaultdict(int)
        cents: defaultdict[str, int] = defaultdict(int)
        with orders.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                count[r["customer_id"]] += 1
                cents[r["customer_id"]] += round(float(r["amount"]) * 100)
        dst.parent.mkdir(parents=True, exist_ok=True)
        with (
            customers.open(newline="", encoding="utf-8") as fi,
            dst.open("w", newline="", encoding="utf-8") as fo,
        ):
            w = csv.writer(fo)
            w.writerow([f for f, _ in MART_FIELDS])
            rows = 0
            for c in csv.DictReader(fi):
                cid = c["customer_id"]
                w.writerow([cid, c["name"], c["country"], count[cid], f"{cents[cid] / 100:.2f}"])
                rows += 1
        return rows


def run_pipeline(em: LineageEmitter, root: Path) -> dict[str, int]:
    """Run both scripts as children of one pipeline run."""
    with em.run("shop_pipeline") as pipeline:
        parent = (em.namespace, "shop_pipeline", pipeline.run_id)
        return {
            "clean_orders": clean_orders(em, root, parent),
            "customer_revenue": customer_revenue(em, root, parent),
        }
