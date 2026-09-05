# OpenTelemetry-to-Langfuse correlation gate

Status: **accepted on OpenTelemetry Python 1.44.0 and Collector 0.132.0**

This gate places an OpenTelemetry Collector between attempt-side emitters and Langfuse. SDK and
gateway processes receive only the OTLP endpoint and W3C trace context. The collector alone holds
the Langfuse authorization header and exports both spans into one trace.

```bash
./scripts/feasibility/otel-langfuse/verify.sh
```

## Accepted observation

On 2026-09-05 separate SDK and gateway emitters exported spans through the Collector. Langfuse
returned observations named `gate.sdk` and `gate.gateway` under the same W3C trace ID. Both
emitters ran with a scrubbed environment containing the OTLP endpoint but no Langfuse public key,
secret key, authorization header, or other credential.

Decision: agents and gateways export OTLP to the platform Collector. Only the Collector holds the
Langfuse ingestion credential. Trace context crosses SDK, Runtime, and gateway boundaries using
W3C `traceparent`; telemetry failure remains non-fatal to product state.
