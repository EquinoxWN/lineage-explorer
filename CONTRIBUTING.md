# Contributing

Thanks for helping. This is a Python and TypeScript project; issues and pull requests are welcome.

## Set up and check your change

Needs Python 3.11+, Node.js 24+ and GNU make. Caches and virtual environments stay in git-ignored
folders inside the repo.

```bash
make setup        # install dependencies (Python package with dev and dbt extras, npm ci)
make lint         # ruff, ruff format, mypy --strict, tsc --strict
make test         # full test suite (includes a real dbt-ol run on DuckDB)
make audit        # known-vulnerability check (as in CI)
make demo         # custom emitter -> captured events -> schema validation
```

A pull request is ready when `make lint` and `make test` pass and CI is green (including the
`marquez` job, which runs every integration against a real Marquez).

## Guidelines

- Keep each change focused; explain the problem it solves in the pull request.
- Add or update a test for every behaviour change, and update `docs/results/` when numbers change.
- When raising the OpenLineage version, update the bundled schemas in
  `python/src/lineage_explorer/schemas/` from the same tag.
- Significant design changes need an ADR in `docs/adr/` (copy `0001` for the format).
- Keep function comments to one short phrase; let names and tests explain the rest.
- Report security problems privately, as described in [SECURITY.md](SECURITY.md).

By contributing you agree that your work is released under the [MIT License](LICENSE).
