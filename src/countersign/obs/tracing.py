"""OpenTelemetry tracing.

The pipeline always creates spans through the OpenTelemetry API; without a configured
provider they cost nothing and go nowhere. `configure_tracing` installs a provider that
exports them over OTLP/HTTP to a collector (Jaeger, Tempo, an APM).

Model calls follow the GenAI semantic conventions (`gen_ai.request.model`,
`gen_ai.usage.input_tokens`, ...), so a trace backend can show them like any other
LLM call. Span attributes carry sizes, outcomes and check names, never invoice content.
"""

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

SERVICE_NAME = "countersign"


def tracer() -> trace.Tracer:
    return trace.get_tracer(SERVICE_NAME)


def configure_tracing(
    endpoint: str | None, exporter: SpanExporter | None = None
) -> TracerProvider | None:
    """Export spans to `endpoint` (OTLP/HTTP), or to `exporter` when one is given."""
    if exporter is None:
        if not endpoint:
            return None
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
                OTLPSpanExporter,
            )
        except ImportError as error:
            raise RuntimeError(
                "COUNTERSIGN_OTLP_ENDPOINT is set but the exporter is not installed: "
                "pip install 'countersign[otlp]'"
            ) from error
        exporter = OTLPSpanExporter(endpoint=endpoint)
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider
