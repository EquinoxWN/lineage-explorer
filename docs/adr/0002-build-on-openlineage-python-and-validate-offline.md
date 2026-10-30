# ADR 0002: Build the script emitter on openlineage-python and validate events offline

- **Status:** Accepted

## Context

Plain Python scripts have no OpenLineage integration, so M1 needs a small emitter for them. It can
either write the event JSON itself or use the official `openlineage-python` client. Separately,
something has to prove that the events from all four sources (scripts, dbt, Spark, Airflow) are
well formed, without a running Marquez in unit tests.

## Decision

- The emitter (`lineage_explorer.emitter`) builds events with `openlineage-python` 1.54.0 classes
  and sends them through its transports (HTTP, file, console). It adds only what scripts need: a
  context manager and decorator that emit START, then COMPLETE or FAIL (with an `errorMessage`
  facet, then re-raising), name checks, schema and column-lineage facets, and a parent-run facet.
- `lineage_explorer.validate` ships the OpenLineage 1.54.0 JSON Schemas (core 2-0-2 plus the
  schema, columnLineage, errorMessage, jobType, parent and sql facets, Apache-2.0, see
  `schemas/NOTICE`) and resolves them through a local registry; it never downloads a schema.

## Consequences

- Positive: the emitter's events use the same serialisation and transports as dbt-ol and the
  Airflow provider (which also use `openlineage-python`), so a transport configured once works
  everywhere. Validation runs in milliseconds, offline, on any JSON-lines file.
- Positive: date-time and UUID formats are enforced (`rfc3339-validator` is a dependency for that),
  which caught nothing in our events but does catch hand-edited ones (`test_validate.py`).
- Negative: `openlineage-python` pulls in `requests`, `attrs`, `pyyaml` and others for a few
  hundred lines of emitter; a hand-written emitter would have no dependencies.
- Negative: the bundled schemas must be updated by hand when the OpenLineage version is raised;
  the version is pinned (`==1.54.0`) in the same place so the two move together.
