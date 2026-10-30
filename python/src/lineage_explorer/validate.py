"""Check OpenLineage events against the official JSON Schemas, offline, and summarise them."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CORE = "https://openlineage.io/spec/2-0-2/OpenLineage.json"
# Facet key -> schema file shipped in lineage_explorer/schemas (OpenLineage 1.54.0).
FACET_SCHEMAS = {
    "schema": "SchemaDatasetFacet.json",
    "columnLineage": "ColumnLineageDatasetFacet.json",
    "errorMessage": "ErrorMessageRunFacet.json",
    "jobType": "JobTypeJobFacet.json",
    "parent": "ParentRunFacet.json",
    "sql": "SQLJobFacet.json",
}
MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_EVENTS = 100_000


def _load(name: str) -> dict[str, Any]:
    """One bundled schema file as a dict."""
    text = resources.files("lineage_explorer").joinpath("schemas", name).read_text("utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


@cache
def _validators() -> tuple[dict[str, Draft202012Validator], dict[str, Draft202012Validator]]:
    """Validators for each event kind and each known facet, resolved without network access."""
    docs = [_load("OpenLineage.json"), *(_load(f) for f in FACET_SCHEMAS.values())]
    registry: Registry[Any] = Registry().with_resources(
        (d["$id"], Resource.from_contents(d)) for d in docs
    )
    fmt = Draft202012Validator.FORMAT_CHECKER
    core = {
        kind: Draft202012Validator(
            {"$ref": f"{CORE}#/$defs/{kind}"}, registry=registry, format_checker=fmt
        )
        for kind in ("RunEvent", "DatasetEvent", "JobEvent")
    }
    facets = {
        key: Draft202012Validator(_load(file), registry=registry, format_checker=fmt)
        for key, file in FACET_SCHEMAS.items()
    }
    return core, facets


def _facet_maps(event: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every facets object in an event, with a path for messages."""
    for owner in ("run", "job"):
        part = event.get(owner)
        if isinstance(part, dict) and isinstance(part.get("facets"), dict):
            yield f"{owner}.facets", part["facets"]
    for side in ("inputs", "outputs"):
        datasets = event.get(side)
        if not isinstance(datasets, list):
            continue
        for i, ds in enumerate(datasets):
            if isinstance(ds, dict) and isinstance(ds.get("facets"), dict):
                yield f"{side}[{i}].facets", ds["facets"]


def validate_event(event: Any) -> list[str]:
    """Schema problems in one event; an empty list means it is valid."""
    core, facets = _validators()
    # Pick the event kind by shape so messages point at the field, not at a failed oneOf.
    kind = "RunEvent"
    if isinstance(event, dict) and "eventType" not in event and "run" not in event:
        kind = "DatasetEvent" if "dataset" in event else "JobEvent"
    errors = [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in core[kind].iter_errors(event)
    ]
    if not isinstance(event, dict):
        return errors
    for path, facet_map in _facet_maps(event):
        for key, value in facet_map.items():
            validator = facets.get(key)
            if validator is None:
                continue
            errors += [
                f"{path}.{key}/{'/'.join(map(str, e.absolute_path))}: {e.message}"
                for e in validator.iter_errors({key: value})
            ]
    return errors


def read_events(path: Path, max_events: int = MAX_EVENTS) -> list[dict[str, Any]]:
    """Parse a JSON-lines file of events, refusing oversized lines or files."""
    events: list[dict[str, Any]] = []
    with path.open("rb") as fh:
        for n, raw in enumerate(iter(lambda: fh.readline(MAX_LINE_BYTES + 1), b""), start=1):
            if len(raw) > MAX_LINE_BYTES:
                raise ValueError(f"{path}:{n}: line longer than {MAX_LINE_BYTES} bytes")
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{n}: not JSON ({e.msg})") from None
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{n}: expected a JSON object")
            events.append(value)
            if len(events) > max_events:
                raise ValueError(f"{path}: more than {max_events} events")
    return events


@dataclass
class Summary:
    """What a set of events says about jobs, runs and datasets."""

    events: int = 0
    invalid: list[str] = field(default_factory=list)
    by_type: Counter[str] = field(default_factory=Counter)
    jobs: dict[str, Counter[str]] = field(default_factory=dict)
    runs: set[str] = field(default_factory=set)
    datasets: set[str] = field(default_factory=set)
    columns_with_lineage: int = 0
    producers: set[str] = field(default_factory=set)


def summarize(events: Iterable[dict[str, Any]]) -> Summary:
    """Validate every event and collect counts per job and event type."""
    s = Summary()
    for i, ev in enumerate(events):
        s.events += 1
        s.invalid += [f"event {i}: {msg}" for msg in validate_event(ev)]
        etype = str(ev.get("eventType", "-"))
        s.by_type[etype] += 1
        job = ev.get("job") or {}
        key = f"{job.get('namespace')}/{job.get('name')}"
        s.jobs.setdefault(key, Counter())[etype] += 1
        s.runs.add(str((ev.get("run") or {}).get("runId")))
        s.producers.add(str(ev.get("producer", "")))
        for side in ("inputs", "outputs"):
            for ds in ev.get(side) or []:
                s.datasets.add(f"{ds.get('namespace')}/{ds.get('name')}")
                if side == "outputs" and etype == "COMPLETE":
                    cl = ((ds.get("facets") or {}).get("columnLineage") or {}).get("fields") or {}
                    s.columns_with_lineage += len(cl)
    return s
