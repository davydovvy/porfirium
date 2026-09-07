from __future__ import annotations

import base64
import binascii
import json
import re
from urllib.parse import quote

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from agent_registry.domain import ValidatedRelease, canonical_json
from agent_registry.problems import RegistryProblem

REPOSITORY_PATTERN = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)


class EvidenceVerifier:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        registry_url: str,
        registry_host: str,
        publication_keys: dict[str, Ed25519PublicKey],
        allowed_builders: frozenset[str] = frozenset(),
    ) -> None:
        self.client = client
        self.registry_url = registry_url.rstrip("/")
        self.registry_host = registry_host
        self.publication_keys = publication_keys
        self.allowed_builders = allowed_builders

    async def verify(self, release: ValidatedRelease) -> None:
        if self.allowed_builders and release.provenance.get("builder") not in self.allowed_builders:
            raise RegistryProblem(
                422, "builder_untrusted", "Publication builder identity is not trusted"
            )
        repository = _repository(release.image, expected_host=self.registry_host)
        await self._verify_oci_digest(repository, release.image_digest)
        self._verify_signature(release)

    async def _verify_oci_digest(self, repository: str, digest: str) -> None:
        encoded_digest = quote(digest, safe=":")
        url = f"{self.registry_url}/v2/{repository}/manifests/{encoded_digest}"
        try:
            response = await self.client.head(
                url,
                headers={
                    "Accept": (
                        "application/vnd.oci.image.manifest.v1+json, "
                        "application/vnd.docker.distribution.manifest.v2+json"
                    )
                },
            )
        except httpx.HTTPError as error:
            raise RegistryProblem(
                503, "registry_unavailable", "OCI Registry unavailable", True
            ) from error
        if response.status_code == 404:
            raise RegistryProblem(422, "image_not_found", "OCI image digest was not found")
        try:
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RegistryProblem(
                503, "registry_unavailable", "OCI Registry unavailable", True
            ) from error
        observed = response.headers.get("Docker-Content-Digest")
        if observed != digest:
            raise RegistryProblem(422, "image_digest_mismatch", "OCI image digest did not match")

    def _verify_signature(self, release: ValidatedRelease) -> None:
        key_id = release.provenance["keyId"]
        key = self.publication_keys.get(key_id)
        if key is None:
            raise RegistryProblem(422, "signing_key_untrusted", "Publication key is not trusted")
        signed_provenance = {
            key: value for key, value in release.provenance.items() if key != "signature"
        }
        try:
            signature = base64.b64decode(release.provenance["signature"], validate=True)
            key.verify(signature, canonical_json(signed_provenance))
        except (binascii.Error, InvalidSignature, TypeError, ValueError) as error:
            raise RegistryProblem(
                422, "signature_invalid", "Publication signature is invalid"
            ) from error


def _repository(image: str, *, expected_host: str) -> str:
    location = image.split("@", 1)[0]
    host, separator, repository = location.partition("/")
    if host != expected_host or not separator or REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise RegistryProblem(422, "image_registry_forbidden", "OCI image registry is not allowed")
    return repository


def load_publication_keys(serialized: str) -> dict[str, Ed25519PublicKey]:
    try:
        values = json.loads(serialized)
        if not isinstance(values, dict) or not values:
            raise ValueError
        keys: dict[str, Ed25519PublicKey] = {}
        for key_id, encoded in values.items():
            if not isinstance(key_id, str) or not isinstance(encoded, str) or len(key_id) > 128:
                raise ValueError
            raw = base64.b64decode(encoded, validate=True)
            keys[key_id] = Ed25519PublicKey.from_public_bytes(raw)
        return keys
    except (binascii.Error, json.JSONDecodeError, TypeError, ValueError) as error:
        raise RuntimeError("REGISTRY_PUBLICATION_KEYS must contain Ed25519 public keys") from error
