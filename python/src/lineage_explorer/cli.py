"""lineage-emit: run the plain-script demo with lineage, or validate captured OpenLineage events."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from lineage_explorer.demo import run_pipeline, write_sample
from lineage_explorer.emitter import LineageEmitter, client_for
from lineage_explorer.validate import read_events, summarize


def _validate(files: list[Path]) -> int:
    """Print a per-file summary; exit 1 if any event breaks the schema."""
    bad = 0
    for path in files:
        try:
            events = read_events(path)
        except (OSError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        s = summarize(events)
        bad += len(s.invalid)
        types = " ".join(f"{k}={v}" for k, v in sorted(s.by_type.items()))
        print(
            f"{path.name}: {s.events} events ({types}), {len(s.runs)} runs, {len(s.jobs)} jobs, "
            f"{len(s.datasets)} datasets, {s.columns_with_lineage} output columns with column lineage"
        )
        for job, counts in sorted(s.jobs.items()):
            print(f"  {job}: {' '.join(f'{k}={v}' for k, v in sorted(counts.items()))}")
        for msg in s.invalid[:20]:
            print(f"  INVALID {msg}")
        print(
            f"  schema: {'all valid' if not s.invalid else f'{len(s.invalid)} problems'} (OpenLineage 2-0-2 + facets)"
        )
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    ap = argparse.ArgumentParser(prog="lineage-emit", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser(
        "validate", help="check JSON-lines event files against the OpenLineage schemas"
    )
    v.add_argument("files", nargs="+", type=Path)
    d = sub.add_parser("demo", help="run two CSV scripts, emitting START/COMPLETE events for each")
    d.add_argument("--dir", type=Path, required=True, help="working folder for the CSV files")
    d.add_argument(
        "--target",
        default=os.environ.get("OPENLINEAGE_URL", "console"),
        help="console, file:<path> or a Marquez base URL (default $OPENLINEAGE_URL or console)",
    )
    d.add_argument("--namespace", default="scripts")
    a = ap.parse_args(argv)
    if a.cmd == "validate":
        return _validate(a.files)
    try:
        client = client_for(a.target)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    write_sample(a.dir)
    rows = run_pipeline(LineageEmitter(a.namespace, client), a.dir)
    client.close(10)
    print(" ".join(f"{k}={v} rows" for k, v in rows.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
