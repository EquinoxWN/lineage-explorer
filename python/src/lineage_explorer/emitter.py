"""A small OpenLineage emitter for plain Python scripts: START, then COMPLETE or FAIL, per run."""

from __future__ import annotations

import re
import traceback
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from typing import ParamSpec, TypeVar
from urllib.parse import urlsplit

from openlineage.client import OpenLineageClient
from openlineage.client.event_v2 import (
    InputDataset,
    Job,
    OutputDataset,
    Run,
    RunEvent,
    RunState,
)
from openlineage.client.facet_v2 import (
    DatasetFacet,
    RunFacet,
    column_lineage_dataset,
    error_message_run,
    job_type_job,
    parent_run,
    schema_dataset,
)
from openlineage.client.transport import Transport
from openlineage.client.transport.console import ConsoleConfig, ConsoleTransport
from openlineage.client.transport.file import FileConfig, FileTransport
from openlineage.client.transport.http import HttpConfig, HttpTransport
from openlineage.client.uuid import generate_new_uuid

PRODUCER = "https://github.com/EquinoxWN/lineage-explorer/tree/main/python"
_NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,1024}$")
P = ParamSpec("P")
R = TypeVar("R")


def _check_name(kind: str, value: str) -> str:
    """Reject empty, oversized or control-character names."""
    if not _NAME.fullmatch(value):
        raise ValueError(f"{kind} must be 1 to 1024 printable characters, got {value!r}")
    return value


@dataclass(frozen=True)
class Column:
    """One input column that an output column is computed from."""

    namespace: str
    name: str
    field: str


@dataclass(frozen=True)
class DatasetRef:
    """A dataset a run reads or writes, with its columns and, for outputs, column lineage."""

    namespace: str
    name: str
    fields: Sequence[tuple[str, str]] = ()
    column_lineage: Mapping[str, Sequence[Column]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate names and that lineage only names declared columns."""
        _check_name("dataset namespace", self.namespace)
        _check_name("dataset name", self.name)
        declared = {f for f, _ in self.fields}
        unknown = set(self.column_lineage) - declared
        if self.fields and unknown:
            raise ValueError(f"column lineage for undeclared columns: {sorted(unknown)}")

    def facets(self) -> dict[str, DatasetFacet]:
        """Schema and column-lineage facets for this dataset."""
        out: dict[str, DatasetFacet] = {}
        if self.fields:
            out["schema"] = schema_dataset.SchemaDatasetFacet(
                fields=[
                    schema_dataset.SchemaDatasetFacetFields(name=n, type=t) for n, t in self.fields
                ]
            )
        if self.column_lineage:
            out["columnLineage"] = column_lineage_dataset.ColumnLineageDatasetFacet(
                fields={
                    col: column_lineage_dataset.Fields(
                        inputFields=[
                            column_lineage_dataset.InputField(
                                namespace=c.namespace, name=c.name, field=c.field
                            )
                            for c in sources
                        ]
                    )
                    for col, sources in self.column_lineage.items()
                }
            )
        return out


def client_for(target: str) -> OpenLineageClient:
    """Client for 'console', 'file:<path>' or an http(s) Marquez/OpenLineage base URL."""
    transport: Transport
    if target == "console":
        transport = ConsoleTransport(ConsoleConfig())
    elif target.startswith("file:"):
        path = target.removeprefix("file:")
        if not path:
            raise ValueError("file: target needs a path")
        transport = FileTransport(FileConfig(log_file_path=path, append=True))
    else:
        parts = urlsplit(target)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(
                f"target must be console, file:<path> or an http(s) URL, got {target!r}"
            )
        transport = HttpTransport(HttpConfig(url=target, endpoint="api/v1/lineage", timeout=10.0))
    return OpenLineageClient(transport=transport)


@dataclass
class RunHandle:
    """The run in progress; scripts may add output datasets before it completes."""

    run_id: str
    outputs: list[DatasetRef]


class LineageEmitter:
    """Emits OpenLineage run events for jobs in one namespace."""

    def __init__(self, namespace: str, client: OpenLineageClient) -> None:
        """Bind a job namespace to a configured client."""
        self.namespace = _check_name("job namespace", namespace)
        self.client = client

    def _event(
        self,
        state: RunState,
        run_id: str,
        job: str,
        inputs: Sequence[DatasetRef],
        outputs: Sequence[DatasetRef],
        run_facets: dict[str, RunFacet],
    ) -> RunEvent:
        """Build one run event."""
        return RunEvent(
            eventType=state,
            eventTime=datetime.now(UTC).isoformat(),
            run=Run(runId=run_id, facets=run_facets),
            job=Job(
                namespace=self.namespace,
                name=job,
                facets={
                    "jobType": job_type_job.JobTypeJobFacet(
                        processingType="BATCH", integration="PYTHON", jobType="SCRIPT"
                    )
                },
            ),
            inputs=[
                InputDataset(namespace=d.namespace, name=d.name, facets=d.facets()) for d in inputs
            ],
            outputs=[
                OutputDataset(namespace=d.namespace, name=d.name, facets=d.facets())
                for d in outputs
            ],
            producer=PRODUCER,
        )

    @contextmanager
    def run(
        self,
        job: str,
        inputs: Sequence[DatasetRef] = (),
        outputs: Sequence[DatasetRef] = (),
        parent: tuple[str, str, str] | None = None,
    ) -> Iterator[RunHandle]:
        """Emit START now, then COMPLETE on success or FAIL (and re-raise) on an exception."""
        _check_name("job name", job)
        handle = RunHandle(run_id=str(generate_new_uuid()), outputs=list(outputs))
        facets: dict[str, RunFacet] = {}
        if parent is not None:
            p_ns, p_job, p_run = parent
            facets["parent"] = parent_run.ParentRunFacet(
                job=parent_run.Job(namespace=p_ns, name=p_job), run=parent_run.Run(runId=p_run)
            )
        self.client.emit(
            self._event(RunState.START, handle.run_id, job, inputs, handle.outputs, facets)
        )
        try:
            yield handle
        except BaseException as exc:
            error = error_message_run.ErrorMessageRunFacet(
                message=f"{type(exc).__name__}: {exc}"[:4096],
                programmingLanguage="PYTHON",
                stackTrace="".join(traceback.format_exception(exc))[-16384:],
            )
            fail_facets: dict[str, RunFacet] = {**facets, "errorMessage": error}
            self.client.emit(
                self._event(RunState.FAIL, handle.run_id, job, inputs, handle.outputs, fail_facets)
            )
            raise
        self.client.emit(
            self._event(RunState.COMPLETE, handle.run_id, job, inputs, handle.outputs, facets)
        )

    def track(
        self, job: str, inputs: Sequence[DatasetRef] = (), outputs: Sequence[DatasetRef] = ()
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorator form of run() for a script's main function."""

        def wrap(fn: Callable[P, R]) -> Callable[P, R]:
            """Wrap one function in a tracked run."""

            @wraps(fn)
            def inner(*args: P.args, **kwargs: P.kwargs) -> R:
                """Call the function inside a run."""
                with self.run(job, inputs, outputs):
                    return fn(*args, **kwargs)

            return inner

        return wrap
