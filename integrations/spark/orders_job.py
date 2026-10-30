"""PySpark job: paid revenue per customer from the shop CSVs, written as Parquet.

Lineage comes from OpenLineage's Spark listener, configured on the spark-submit command line
(see the `marquez` job in the CI workflow); this file has no lineage code at all.

usage: spark-submit [OpenLineage --conf flags] orders_job.py <seeds dir> <output dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

from pyspark.sql import SparkSession
from pyspark.sql import functions as F  # noqa: N812


def main(seeds: Path, out: Path) -> None:
    """Read orders and customers, keep paid orders, aggregate and write Parquet."""
    spark = SparkSession.builder.appName("orders_job").getOrCreate()
    try:
        orders = (
            spark.read.option("header", True)
            .option("inferSchema", True)
            .csv(str(seeds / "raw_orders.csv"))
        )
        customers = (
            spark.read.option("header", True)
            .option("inferSchema", True)
            .csv(str(seeds / "raw_customers.csv"))
        )
        revenue = (
            customers.join(orders.where(F.col("status") == "paid"), "customer_id", "left")
            .groupBy("customer_id", "name", "country")
            .agg(
                F.count("order_id").alias("orders"),
                F.coalesce(F.sum("amount"), F.lit(0)).alias("revenue"),
            )
        )
        revenue.write.mode("overwrite").parquet(str(out / "customer_revenue"))
        print(f"orders_job: wrote {revenue.count()} rows to {out / 'customer_revenue'}")
    finally:
        spark.stop()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
