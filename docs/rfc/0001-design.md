# RFC 0001: lineage-explorer design

- **Status:** Accepted for M1
- **Author:** EquinoxWN
- **Created:** 2026-10-23

## Problem

Before a data engineer drops or renames a column, they need to know which jobs read it and which
tables, dashboards and owners depend on it. On most platforms that knowledge is spread over dbt
projects, Spark jobs, Airflow DAGs and ad-hoc Python scripts, and nobody records it consistently.
Lineage collected by hand goes stale; lineage that is only partly collected gives false confidence.

The project answers "what breaks if I drop this column?" in three milestones. M1 builds the
foundation: every run of every tool reports what it read and wrote, in one open format, into one
store that can be queried.

**Users:** data and analytics engineers, and platform teams that run dbt, Spark and Airflow.

## Goals

**M1 (this milestone)**

- dbt, Spark and Airflow emit OpenLineage events on every run, using the official integrations
  (`dbt-ol`, the OpenLineage Spark listener, the Airflow OpenLineage provider), not custom parsers.
- A small custom emitter covers plain Python scripts: START, then COMPLETE or FAIL for each run,
  with input and output datasets, their schema, column-level lineage and a parent-run link.
- Marquez stores datasets, jobs and runs from all four sources and serves them through its REST API;
  a typed TypeScript client and CLI read them back (the data layer the M2 UI will use).
- Every captured event can be checked offline against the official OpenLineage JSON Schemas.

**Later milestones:** a React Flow graph with column tracing and impact search (M2); a tested,
accessible UI (M3).

## Non-goals

- Writing lineage extractors for dbt, Spark or Airflow: the upstream integrations are used as-is.
- Running Marquez as a hosted service; it runs in CI and on a developer's machine with Docker.
- A UI in M1. The CLI is a read and check tool, not an explorer.
- Authentication, multi-tenancy or retention policies for Marquez.

## Critical-to-quality measures (Define)

| CTQ | Target | How it is measured |
|---|---|---|
| Every tool run is reported | each dbt model, the Spark job, each Airflow task and each script has a START and a terminal event | `test_dbt.py`, `test_demo.py`, `test_emitter.py`; the CI `check` step against Marquez |
| Events follow the standard | 0 schema problems against OpenLineage 2-0-2 and the facet schemas | `lineage-emit validate`, used in tests on every captured event |
| Failures are visible | a failing script yields a FAIL event with the error and stack trace, and the exception still propagates | `test_emitter.py`, `test_demo.py` |
| Marquez keeps what was sent | every expected job has a COMPLETED latest run and every expected dataset is found | CI `marquez` job: `test_marquez.py` and `node src/cli.ts check` |
| Column lineage is carried | dbt and the custom emitter report column lineage for every output column | `test_dbt.py`, `test_demo.py` |
| Bounded, safe reads | the client rejects non-http(s) URLs, encodes names, caps body size, item count and time | `marquez.test.ts`, `cli.test.ts` |

## Proposed design

```
plain scripts --(lineage_explorer.emitter)--------\
dbt (dbt-ol, DuckDB) -----------------------------+--> OpenLineage events --> Marquez (Postgres)
Spark (OpenLineageSparkListener) -----------------/        |                        |
Airflow (providers-openlineage listener) --------/         | file transport         | REST API v1
                                                           v                        v
                                             lineage-emit validate      TypeScript client + CLI
                                             (official JSON Schemas)    (list, lineage, check)
```

- **Collect.** dbt runs through `dbt-ol`, which reads dbt's manifest and run results and emits a
  START/COMPLETE pair per model plus a parent run per command, with schema and column-lineage
  facets. Spark gets the OpenLineage listener through `spark-submit --packages ... --conf
  spark.extraListeners=...`; the job file has no lineage code. Airflow loads the OpenLineage
  provider, configured with `AIRFLOW__OPENLINEAGE__*`; task inlets and outlets are OpenLineage
  datasets. Plain scripts use `LineageEmitter.run()` (a context manager) or `@track`, built on
  the official `openlineage-python` client so transports (HTTP, file, console) behave the same as
  in the other integrations.
- **Validate.** `lineage_explorer.validate` ships the OpenLineage 1.54.0 spec files (core 2-0-2 and
  six facet schemas) and resolves them through a local `referencing` registry, so validation never
  fetches anything. Each event is checked against the schema of its kind, then each known facet
  against its own schema.
- **Store and serve.** Marquez 0.51.1 on Postgres 16 receives events on `POST /api/v1/lineage` and
  serves namespaces, datasets (with fields), jobs (with inputs, outputs and latest run), runs,
  search and the lineage graph.
- **Read.** `js/src/marquez.ts` is a typed client for those endpoints: every response is parsed
  from `unknown` with path-specific errors, names are percent-encoded, list endpoints are paged,
  and every request has a timeout and a body-size cap. `js/src/cli.ts` lists what Marquez holds,
  walks the lineage graph up and down (`graph.ts`), and `check` exits non-zero unless the expected
  runs and datasets are present.

## Alternatives considered

| Option | Why not |
|---|---|
| **DataHub or OpenMetadata as the store** | Both ingest OpenLineage, but they are full metadata platforms (Kafka or Elasticsearch, several services). Marquez is the OpenLineage reference implementation, has one service plus Postgres, and its lineage API is what the M2 UI needs. |
| **Parse dbt manifests, Spark plans and Airflow DAGs ourselves** | Duplicates work the OpenLineage integrations already do and keep current with each tool's releases; our parsers would drift. Using the official integrations keeps M1 small and its output standard. |
| **Emit plain-script events with hand-written JSON** | Simpler, but every transport, retry and serialisation rule would be re-implemented, and nothing would stop a malformed facet. Building on `openlineage-python` and validating against the official schemas avoids both (ADR 0002). |
| **Validate events by trusting Marquez to reject bad ones** | Marquez accepts many malformed facets silently and needs a running server; offline schema validation catches problems in unit tests and on any captured file. |

## Measurement plan (Measure)

- `pytest` captures real events from the custom emitter (in-memory transport, file transport and
  HTTP to an in-process stub of `POST /api/v1/lineage`) and from a real `dbt-ol seed` and `dbt-ol
  run` on DuckDB (file transport), and checks counts, inputs, outputs, column lineage and schema.
- `node --test` checks the client and CLI against an in-process HTTP server that returns
  Marquez-shaped bodies.
- The CI `marquez` job starts Postgres and Marquez from digest-pinned images, runs the custom
  emitter, dbt, the Spark job and the Airflow DAG against it, then reads everything back with
  `pytest -m marquez` and `node src/cli.ts check`, and prints the result as a `::notice`.
- Results and the machine are recorded in [docs/results/m1.md](../results/m1.md).

## Milestones

- **M1:** dbt, Spark and Airflow emit OpenLineage events on every run; a custom emitter covers plain
  scripts. Marquez stores datasets, jobs and runs and serves them through its API.
- **M2:** the React Flow UI draws the graph, collapses large subgraphs and traces a single column;
  impact search answers "what breaks if I drop this column?".
- **M3:** prototype and five-user test; keyboard navigation and a colour-blind-safe palette (WCAG AA).

## Risks and open questions

- Dataset naming differs per integration (dbt reports `duckdb://<path>` namespaces, Spark reports
  file paths), so the same physical table can appear twice; M2 needs a naming policy or symlinks.
- Airflow and Spark run only on Linux in CI here (Airflow does not support Windows; local PySpark on
  Windows needs Hadoop native binaries). Their CI checks have to be read from annotations.
- Marquez 0.51.1 is the latest release (March 2025); if the project slows down, the store may need
  to change. The client only uses API v1 endpoints to keep that change small.
