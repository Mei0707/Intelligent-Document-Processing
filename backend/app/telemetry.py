"""Content-free spans; trace context follows durable jobs into worker threads."""
from contextlib import contextmanager
from opentelemetry import trace
from opentelemetry.propagate import inject, extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from .config import settings

tracer = trace.get_tracer("idp")


def configure_telemetry(service: str):
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    if settings.otel_exporter_otlp_endpoint:
        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    return provider


def trace_carrier():
    carrier = {}
    inject(carrier)
    return carrier


@contextmanager
def span(name, carrier=None, **attributes):
    context = extract(carrier) if carrier else None
    with tracer.start_as_current_span(name, context=context, attributes=attributes,
                                      record_exception=False, set_status_on_exception=False) as current:
        try:
            yield current
        except Exception as error:
            current.set_status(trace.Status(trace.StatusCode.ERROR, type(error).__name__))
            current.add_event("exception", {"exception.type": type(error).__name__})
            raise
