.PHONY: setup lint test audit demo dbt-events check-marquez ci

PY ?= python
# Where captured events go for the local targets (git-ignored).
OUT ?= .tmp/events

setup:
	$(PY) -m pip install --upgrade pip && $(PY) -m pip install -e "python[dev,dbt]"
	cd js && npm ci

# ruff (package and integrations), ruff format, mypy --strict; tsc --strict on the TypeScript.
lint:
	cd python && $(PY) -m ruff check . ../integrations && $(PY) -m ruff format --check . ../integrations && $(PY) -m mypy
	cd js && npm run -s lint

# Python: emitter, validation, demo, and a real dbt-ol run on DuckDB (test_marquez.py needs
# MARQUEZ_URL and runs in CI). TypeScript: Marquez client, graph walk and CLI against a stub.
test:
	cd python && $(PY) -m pytest -q -rs
	cd js && npm test

# Known vulnerabilities in the installed Python packages and the npm lockfile.
audit:
	$(PY) -m pip_audit --skip-editable --cache-dir .tmp/pip-audit
	cd js && npm audit --audit-level=low

# Custom emitter: run the two CSV scripts, capture their events and validate them.
demo:
	mkdir -p $(OUT) && rm -f $(OUT)/scripts.jsonl
	lineage-emit demo --dir .tmp/scripts --target file:$(OUT)/scripts.jsonl
	lineage-emit validate $(OUT)/scripts.jsonl

# dbt-ol seed and run on DuckDB with OpenLineage's file transport, then validate the events.
dbt-events:
	mkdir -p $(OUT) && rm -f $(OUT)/dbt.jsonl
	DBT_TARGET_PATH=.tmp/dbt/target DBT_LOG_PATH=.tmp/dbt/logs DBT_DUCKDB_PATH=.tmp/dbt/shop.duckdb \
	DBT_SEND_ANONYMOUS_USAGE_STATS=false DBT_HINTS_ENABLED=false HOME=$(CURDIR)/.tmp/dbt USERPROFILE=$(CURDIR)/.tmp/dbt OPENLINEAGE_NAMESPACE=dbt \
	OPENLINEAGE__TRANSPORT__TYPE=file OPENLINEAGE__TRANSPORT__LOG_FILE_PATH=$(OUT)/dbt.jsonl OPENLINEAGE__TRANSPORT__APPEND=true \
	sh -c 'dbt-ol seed --project-dir integrations/dbt --profiles-dir integrations/dbt && dbt-ol run --project-dir integrations/dbt --profiles-dir integrations/dbt'
	lineage-emit validate $(OUT)/dbt.jsonl

# Against a running Marquez (MARQUEZ_URL): what it stores, per namespace.
check-marquez:
	cd js && node src/cli.ts summary

ci: setup lint test
