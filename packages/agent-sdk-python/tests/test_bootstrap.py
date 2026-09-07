import base64
import json
from uuid import UUID

import pytest

from porfirium_agent_sdk import PlatformError, RuntimeClient


def capability(payload: object) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{encoded}.opaque-signature"


def test_constructs_runtime_identity_from_environment_capability() -> None:
    run_id = UUID("10000000-0000-0000-0000-000000000001")
    attempt_id = UUID("20000000-0000-0000-0000-000000000002")
    token = capability({"run_id": str(run_id), "attempt_id": str(attempt_id), "lease_epoch": 3})

    runtime = RuntimeClient.from_environment({
        "PORFIRIUM_RUNTIME_URL": "runtime:50051",
        "PORFIRIUM_RUN_CAPABILITY": token,
    })

    assert runtime.endpoint == "runtime:50051"
    assert runtime.run_id == run_id
    assert runtime.attempt_id == attempt_id
    assert runtime.lease_epoch == 3
    assert runtime.run_capability == token


@pytest.mark.parametrize("token", ["", "not-a-capability", capability({"lease_epoch": 0})])
def test_rejects_invalid_environment_capability(token: str) -> None:
    with pytest.raises(PlatformError, match="bootstrap capability|bootstrap configuration"):
        RuntimeClient.from_environment({
            "PORFIRIUM_RUNTIME_URL": "runtime:50051",
            "PORFIRIUM_RUN_CAPABILITY": token,
        })
