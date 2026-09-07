from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def prepare(
    template: dict[str, Any], image: str, private_key_value: str, key_id: str, builder: str
) -> dict[str, object]:
    if template.get("spec", {}).get("image") != "${IMAGE}":
        raise ValueError("manifest template must contain the exact image placeholder")
    if "@sha256:" not in image or len(image.rsplit("@sha256:", 1)[1]) != 64:
        raise ValueError("image must be digest-pinned")
    manifest = json.loads(json.dumps(template))
    manifest["spec"]["image"] = image
    digest = image.rsplit("@", 1)[1]
    provenance = {"subjectDigest": digest, "keyId": key_id, "builder": builder}
    try:
        raw_key = base64.b64decode(private_key_value.strip(), validate=True)
        private_key = Ed25519PrivateKey.from_private_bytes(raw_key)
    except (TypeError, ValueError) as error:
        raise ValueError("publication key must be a base64 raw Ed25519 private key") from error
    provenance["signature"] = base64.b64encode(
        private_key.sign(canonical_json(provenance))
    ).decode()
    return {"manifest": manifest, "image": image, "provenance": provenance}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--private-key-file", type=Path, required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--builder", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    template = json.loads(arguments.template.read_text())
    request = prepare(
        template,
        arguments.image,
        arguments.private_key_file.read_text(),
        arguments.key_id,
        arguments.builder,
    )
    arguments.output.write_bytes(canonical_json(request))


if __name__ == "__main__":
    main()
