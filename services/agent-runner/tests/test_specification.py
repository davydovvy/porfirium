import base64
import hashlib
import json
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_runner.models import SignedSpecification
from agent_runner.specification import SpecificationVerificationError, verify_specification


def _signed() -> tuple[SignedSpecification, object]:
    private = Ed25519PrivateKey.generate()
    payload = {"run_id": str(uuid4()), "release": {"image": "repo/image@sha256:" + "a" * 64}}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    spec = SignedSpecification(
        specification_id=uuid4(), run_id=payload["run_id"], payload=payload,
        payload_sha256=hashlib.sha256(encoded).hexdigest(),
        signature=base64.b64encode(private.sign(encoded)).decode(), key_id="current",
    )
    return spec, private.public_key()


def test_signed_specification_is_accepted() -> None:
    specification, public_key = _signed()
    verify_specification(specification, {"current": public_key})


def test_tampered_specification_fails_closed() -> None:
    specification, public_key = _signed()
    specification.payload["release"] = {"image": "attacker/image:latest"}
    with pytest.raises(SpecificationVerificationError):
        verify_specification(specification, {"current": public_key})
