# Runtime gRPC reconnect gate

Status: **accepted on gRPC Python 1.83.1**

This gate generates Python bindings from the canonical Runtime v1 protobuf and exercises its
bidirectional `Connect` stream. The Runtime API durably accepts sequence 2 and exits before sending
its acknowledgement. The same SDK process reconnects to a new Runtime API process, retransmits its
unacknowledged frame, and continues through sequence 4.

Acceptance requires sequence 2 to have at least two delivery attempts while durable state contains
each ordered sequence exactly once.

```bash
./scripts/feasibility/grpc-reconnect/verify.sh
```

The verifier installs its locked gRPC dependencies under `/tmp`, generates bindings under a unique
temporary directory, and removes all state and processes on exit.

## Accepted observation

On 2026-09-05 the Runtime API durably accepted sequence 2 and terminated with injected exit status
70 before acknowledging it. The SDK retained the frame in memory, reconnected to a new Runtime API
process, retransmitted sequence 2, and received monotonically ordered acknowledgements through
sequence 4. The durable record was exactly `[1, 2, 3, 4]`, while sequence 2 had two delivery
attempts.

Decision: use the Runtime v1 bidirectional gRPC stream with durable-before-ack processing. The SDK
retains a bounded unacknowledged frame window for the current attempt; Runtime deduplicates by
attempt identity, lease epoch, sequence, and idempotency key before emitting durable events.
