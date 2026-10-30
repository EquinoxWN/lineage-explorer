# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub:
**Security > Report a vulnerability** on this repository
(`https://github.com/EquinoxWN/lineage-explorer/security/advisories/new`). Do not open a public issue.

Include what you found, how to reproduce it, and the impact you expect. You will get an answer
within 7 days. Fixes are released as soon as they are ready, and you are credited unless you ask
not to be.

## Supported versions

This project is pre-1.0. Only the latest commit on `main` receives fixes.

## Scope

- **In scope:** the emitter sending events somewhere other than the configured target, the
  validator or client reading unbounded input, request paths that can be changed through dataset
  or job names, and secrets leaking into events.
- **Out of scope:** Marquez itself (report to the Marquez project) and running Marquez without
  authentication on a public network, which this project does not do.

## How this repository protects itself

- Every GitHub Action is pinned to a full commit SHA, container images are pinned by digest, and
  workflows run with read-only permissions and without persisted credentials.
- Dependabot update pull requests are paused (`open-pull-requests-limit: 0`) so the repository keeps a single `main` branch; dependencies are updated by hand and checked by the CI audit.
- CI runs lint, strict type checks, tests and a known-vulnerability check (`pip-audit`, `npm audit`)
  on every push and pull request.
