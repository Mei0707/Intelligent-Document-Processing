import unittest
from unittest.mock import patch
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from app import telemetry


class ObservabilityTests(unittest.TestCase):
    def test_job_carrier_preserves_parent_and_errors_omit_sensitive_messages(self):
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        with patch.object(telemetry, "tracer", provider.get_tracer("test")):
            with telemetry.span("upload") as parent:
                carrier = telemetry.trace_carrier()
            with telemetry.span("job", carrier=carrier) as child:
                try:
                    with telemetry.span("llm"):
                        raise RuntimeError("private document content")
                except RuntimeError:
                    pass
        spans = {s.name: s for s in exporter.get_finished_spans()}
        self.assertEqual(spans["job"].parent.span_id, parent.get_span_context().span_id)
        self.assertEqual(spans["llm"].parent.span_id, child.get_span_context().span_id)
        self.assertEqual(spans["llm"].status.description, "RuntimeError")
        self.assertNotIn("private document content", str(spans["llm"].events))
        provider.shutdown()


if __name__ == "__main__":
    unittest.main()
