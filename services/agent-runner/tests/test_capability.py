import base64
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from agent_runner.capability import issue_run_capability


def test_capability_is_bound_to_exact_attempt_and_epoch() -> None:
    claims = {
        "user_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "thread_id": str(uuid4()),
        "run_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "lease_epoch": 7,
    }
    token = issue_run_capability(claims, "test-secret", datetime.now(UTC) + timedelta(minutes=1))
    encoded, _ = token.split(".", 1)
    decoded = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))

    assert decoded["attempt_id"] == claims["attempt_id"]
    assert decoded["lease_epoch"] == 7
    assert decoded["deadline"] > int(time.time())
    assert decoded["operations"] == ["runtime:connect"]
