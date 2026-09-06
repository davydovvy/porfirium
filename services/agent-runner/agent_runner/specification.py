from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from agent_runner.models import SignedSpecification


class SpecificationVerificationError(ValueError):
    pass


def load_public_keys(value: str) -> dict[str, Ed25519PublicKey]:
    try:
        parsed = json.loads(value)
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError
        return {
            key_id: Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded, validate=True))
            for key_id, encoded in parsed.items()
            if isinstance(key_id, str) and isinstance(encoded, str)
        }
    except (ValueError, TypeError, binascii.Error) as error:
        raise RuntimeError("invalid Registry run-signing public keys") from error


def verify_specification(
    specification: SignedSpecification, keys: Mapping[str, Ed25519PublicKey]
) -> None:
    encoded = json.dumps(
        specification.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    if hashlib.sha256(encoded).hexdigest() != specification.payload_sha256:
        raise SpecificationVerificationError("specification digest is invalid")
    key = keys.get(specification.key_id)
    if key is None:
        raise SpecificationVerificationError("specification signing key is unknown")
    try:
        signature = base64.b64decode(specification.signature, validate=True)
        key.verify(signature, encoded)
    except (InvalidSignature, ValueError, binascii.Error) as error:
        raise SpecificationVerificationError("specification signature is invalid") from error
