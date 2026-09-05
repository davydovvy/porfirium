#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from concurrent import futures
from pathlib import Path

import grpc
from porfirium.runtime.v1 import runtime_pb2 as pb
from porfirium.runtime.v1 import runtime_pb2_grpc as rpc


class Runtime(rpc.AgentRuntimeServicer):
    def __init__(self, state_path: Path, crash_after: int | None) -> None:
        self.state_path = state_path
        self.crash_after = crash_after

    def _state(self) -> dict:
        return json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            "accepted": [], "attempts": {}
        }

    def Connect(self, request_iterator, context):
        hello = next(request_iterator)
        state = self._state()
        last = max(state["accepted"], default=0)
        resume_after = min(last, hello.hello.last_acknowledged_sequence)
        yield pb.PlatformFrame(
            run_id=hello.identity.run_id,
            attempt_id=hello.identity.attempt_id,
            lease_epoch=hello.identity.lease_epoch,
            sequence=1,
            hello_accepted=pb.HelloAccepted(resume_after_sequence=resume_after),
        )
        for frame in request_iterator:
            sequence = frame.identity.sequence
            state = self._state()
            key = str(sequence)
            state["attempts"][key] = state["attempts"].get(key, 0) + 1
            last = max(state["accepted"], default=0)
            if sequence == last + 1:
                state["accepted"].append(sequence)
            elif sequence > last:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, "out-of-order frame")
            self.state_path.write_text(json.dumps(state, sort_keys=True))
            if self.crash_after == sequence and state["attempts"][key] == 1:
                os._exit(70)
            yield pb.PlatformFrame(
                run_id=frame.identity.run_id,
                attempt_id=frame.identity.attempt_id,
                lease_epoch=frame.identity.lease_epoch,
                sequence=sequence + 1,
                acknowledgement=pb.Acknowledgement(
                    accepted_sequence=sequence,
                    durable_event_id=f"event-{sequence}",
                ),
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--crash-after", type=int)
    args = parser.parse_args()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    rpc.add_AgentRuntimeServicer_to_server(Runtime(args.state, args.crash_after), server)
    server.add_insecure_port(f"127.0.0.1:{args.port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    main()
