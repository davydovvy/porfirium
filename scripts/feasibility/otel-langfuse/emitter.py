#!/usr/bin/env python3
from __future__ import annotations

import argparse

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("sdk", "gateway"), required=True)
    parser.add_argument("--parent")
    args = parser.parse_args()
    provider = TracerProvider(resource=Resource.create({"service.name": f"gate-{args.role}"}))
    provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    context = extract({"traceparent": args.parent}) if args.parent else None
    with trace.get_tracer("porfirium.feasibility").start_as_current_span(
        f"gate.{args.role}", context=context
    ) as span:
        span.set_attribute("porfirium.run_id", "run-otel-gate")
        span_context = span.get_span_context()
        traceparent = f"00-{span_context.trace_id:032x}-{span_context.span_id:016x}-01"
        print(traceparent)
    provider.shutdown()


if __name__ == "__main__":
    main()
