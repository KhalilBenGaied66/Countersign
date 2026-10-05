"""Spans leave the process over OTLP/HTTP, and a receiver decodes what arrives.

The receiver is a local HTTP server that answers the one request of the protocol the
exporter sends. It stands in for a collector (Jaeger, Tempo, an APM agent): the export
has never been pointed at a real one.
"""

import gzip
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from countersign.obs.tracing import SERVICE_NAME, configure_tracing
from tests.support import LARGE_MODEL, SMALL_MODEL, invoice_data

ROOT = Path(__file__).resolve().parent.parent


class Collector(ThreadingHTTPServer):
    """Keeps every export request it is sent, decoded."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.received: list[tuple[str, str, ExportTraceServiceRequest]] = []

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1/traces"

    def spans(self) -> list[tuple[dict[str, str], Any]]:
        """Every span received, with the attributes of the resource it came from."""
        found = []
        for _, _, message in self.received:
            for group in message.resource_spans:
                resource = _attributes(group.resource)
                found += [(resource, span) for scope in group.scope_spans for span in scope.spans]
        return found


class _Handler(BaseHTTPRequestHandler):
    server: Collector

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        message = ExportTraceServiceRequest()
        message.ParseFromString(body)
        self.server.received.append((self.path, self.headers.get("Content-Type", ""), message))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Nothing on the error stream for a request that went well."""


def _attributes(carrier: Any) -> dict[str, str]:
    return {item.key: item.value.string_value for item in carrier.attributes}


@pytest.fixture
def collector() -> Iterator[Collector]:
    server = Collector()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()


def test_an_endpoint_receives_what_the_configured_provider_records(
    collector: Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The provider of the process is left alone: other tests read their spans from it.
    monkeypatch.setattr(trace, "set_tracer_provider", lambda provider: None)
    provider = configure_tracing(collector.endpoint)
    assert provider is not None
    try:
        with provider.get_tracer(SERVICE_NAME).start_as_current_span("countersign.process") as span:
            span.set_attribute("countersign.outcome", "approved")
        assert provider.force_flush()
    finally:
        provider.shutdown()

    [(path, content_type, _)] = collector.received
    assert path == "/v1/traces"
    assert content_type == "application/x-protobuf"
    [(resource, exported)] = collector.spans()
    assert resource["service.name"] == SERVICE_NAME
    assert exported.name == "countersign.process"
    assert _attributes(exported) == {"countersign.outcome": "approved"}


# What a worker does with one document, in a process of its own: the tracer of the
# process is the one `configure_tracing` installs, and nothing flushes it by hand.
_ONE_DOCUMENT = """
import sys

from countersign.datagen.render import render_pdf
from countersign.eval.run import MemoryLedger
from countersign.obs.tracing import configure_tracing
from countersign.pipeline.process import Pipeline, PipelineConfig, Tier
from tests.support import (
    LARGE_MODEL,
    SMALL_MODEL,
    TODAY,
    ScriptedModel,
    invoice_data,
    master_data,
    perfect_reply,
)

configure_tracing(sys.argv[1])
data = invoice_data("forez")
misread = perfect_reply(data)
misread["total_gross"] += 100
model = ScriptedModel({SMALL_MODEL: misread, LARGE_MODEL: perfect_reply(data)})
tiers = (Tier("small", SMALL_MODEL), Tier("large", LARGE_MODEL))
pipeline = Pipeline(PipelineConfig(tiers=tiers), model, master_data())
print(pipeline.process(render_pdf(data), ledger=MemoryLedger(), today=TODAY).outcome)
"""


def test_a_document_read_in_another_process_arrives_as_one_trace(collector: Collector) -> None:
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _ONE_DOCUMENT, collector.endpoint],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split() == ["approved"]

    # Pending spans are sent when the interpreter exits: the process flushed nothing.
    spans = collector.spans()
    assert sorted(span.name for _, span in spans) == [
        "countersign.extract",
        "countersign.extract",
        "countersign.parse",
        "countersign.process",
        "countersign.verify",
        "countersign.verify",
    ]
    assert {resource["service.name"] for resource, _ in spans} == {SERVICE_NAME}
    assert len({span.trace_id for _, span in spans}) == 1
    models = {
        _attributes(span)["gen_ai.request.model"]
        for _, span in spans
        if span.name == "countersign.extract"
    }
    assert models == {SMALL_MODEL, LARGE_MODEL}

    # What crosses the network says how the document went, never what it contains.
    data = invoice_data("forez")
    sent = "\n".join(str(message) for _, _, message in collector.received)
    assert "countersign.outcome" in sent
    for content in (data.number, data.vendor.name, data.vendor.iban or "-", f"{data.gross}"):
        assert content not in sent
