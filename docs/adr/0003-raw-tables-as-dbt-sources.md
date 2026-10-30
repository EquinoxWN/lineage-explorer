# ADR 0003: Read raw tables as dbt sources, not seed refs

- **Status:** Accepted

## Context

The dbt project loads two CSV seeds (`raw_orders`, `raw_customers`) and builds `stg_orders`,
`stg_customers` and `customer_revenue` from them. In the first local run the staging models used
`ref('raw_orders')`. `dbt-ol` 1.54.0 then reported the staging runs with **no input datasets**:
it maps model and source dependencies to OpenLineage inputs, but not seed dependencies. The
lineage graph would have started at the staging tables, hiding where the data came from.

## Decision

Declare the seeded tables as a dbt source (`models/staging/sources.yml`, schema `main`) and read
them with `source('raw', 'raw_orders')` in the staging models. Seeds still load the data.

## Consequences

- Positive: every model run now reports its inputs; `test_dbt.py` asserts the full chain
  `raw_* -> stg_* -> customer_revenue`, including column lineage through the rename
  `name -> customer_name`.
- Positive: this is also how real projects read raw data (from sources loaded by another tool),
  so the example shows the shape users will have.
- Negative: dbt no longer orders `seed` before `run` through the DAG; the seed must be run first
  (`dbt-ol seed` then `dbt-ol run`), which the tests, Makefile and CI do.
- Negative: the seed step itself produces only the command-level parent run in OpenLineage, with
  no datasets; seeds are treated as setup, not as lineage.
