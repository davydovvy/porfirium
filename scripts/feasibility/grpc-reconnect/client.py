#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time

import grpc
from porfirium.runtime.v1 import runtime_pb2 as pb
from porfirium.runtime.v1 import runtime_pb2_grpc as rpc


def identity(sequence: int) -> pb.FrameIdentity:
    return pb.FrameIdentity(
        protocol_version="v1",
        run_id="run-feasibility",
        attempt_id="attempt-feasibility",
        lease_epoch=1,
        sequence=sequence,
        idempotency_key=f"frame-{sequence}",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    acknowledged = 0
    deadline = time.monotonic() + 20
    while acknowledged < 4 and time.monotonic() < deadline:
        try:
            with grpc.insecure_channel(args.target) as channel:
                stub = rpc.AgentRuntimeStub(channel)

                def frames():
                    yield pb.AgentFrame(
                        identity=identity(0),
                        hello=pb.Hello(last_acknowledged_sequence=acknowledged, sdk_version="gate"),
                    )
                    for sequence in range(acknowledged + 1, 5):
                        yield pb.AgentFrame(
                            identity=identity(sequence),
                            message_delta=pb.MessageDelta(
                                message_id="message-feasibility",
                                chunk_sequence=sequence,
                                content_utf8=f"chunk-{sequence}".encode(),
                            ),
                        )

                for response in stub.Connect(frames(), timeout=5):
                    if response.HasField("hello_accepted"):
                        acknowledged = max(
                            acknowledged, response.hello_accepted.resume_after_sequence
                        )
                    elif response.HasField("acknowledgement"):
                        accepted = response.acknowledgement.accepted_sequence
                        if accepted < acknowledged or accepted > acknowledged + 1:
                            raise RuntimeError("non-monotonic acknowledgement")
                        acknowledged = max(acknowledged, accepted)
        except grpc.RpcError:
            time.sleep(0.2)
    if acknowledged != 4:
        raise RuntimeError(f"only acknowledged through sequence {acknowledged}")
    print("PASS: SDK reconnected and acknowledged ordered sequence 1..4")


if __name__ == "__main__":
    main()
