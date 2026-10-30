"""Shared fixtures: an in-memory transport and a stub OpenLineage HTTP endpoint."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from openlineage.client import OpenLineageClient
from openlineage.client.serde import Serde
from openlineage.client.transport import Transport

from lineage_explorer.emitter import LineageEmitter


class CaptureTransport(Transport):
    """Keeps every emitted event as a plain dict."""

    kind = "capture"

    def __init__(self) -> None:
        """Start with no events."""
        self.events: list[dict[str, Any]] = []

    def emit(self, event: Any) -> None:
        """Store the event exactly as it would be serialised on the wire."""
        self.events.append(json.loads(Serde.to_json(event)))


@pytest.fixture
def capture() -> tuple[LineageEmitter, list[dict[str, Any]]]:
    """An emitter in namespace 'scripts' and the list its events land in."""
    t = CaptureTransport()
    return LineageEmitter("scripts", OpenLineageClient(transport=t)), t.events


class _Handler(BaseHTTPRequestHandler):
    """Records POST bodies and answers 201 like Marquez does."""

    received: list[tuple[str, dict[str, Any]]]

    def do_POST(self) -> None:
        """Store one request."""
        body = self.rfile.read(int(self.headers.get("content-length", "0")))
        self.received.append((self.path, json.loads(body)))
        self.send_response(201)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Keep test output quiet."""


@pytest.fixture
def stub_endpoint() -> Iterator[tuple[str, list[tuple[str, dict[str, Any]]]]]:
    """A local HTTP server standing in for Marquez's POST /api/v1/lineage."""
    received: list[tuple[str, dict[str, Any]]] = []
    handler = type("H", (_Handler,), {"received": received})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", received
    finally:
        server.shutdown()
        server.server_close()
