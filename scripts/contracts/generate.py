#!/usr/bin/env python3
"""Generate deterministic, implementation-neutral artifacts from source contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages" / "contracts"
GENERATED = CONTRACTS / "generated"


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def source_documents() -> list[Path]:
    return sorted(
        path for path in CONTRACTS.rglob("*")
        if path.is_file() and path.suffix in {".json", ".proto"}
        and "generated" not in path.parts and "compatibility" not in path.parts
    )


def render() -> dict[Path, bytes]:
    sources = source_documents()
    index = {
        "format_version": 1,
        "sources": {
            str(path.relative_to(CONTRACTS)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
    }
    catalog = json.loads((CONTRACTS / "events" / "catalog-v1.json").read_text())["events"]
    py = (
        '"""Generated event registry. Do not edit."""\n\n'
        f"EVENTS = {repr(catalog)}\n"
    )
    ts = (
        "// Generated event registry. Do not edit.\n"
        "export const events = "
        f"{json.dumps(catalog, ensure_ascii=False, sort_keys=True)} as const\n"
        "export type EventType = keyof typeof events\n"
    )
    result = {
        Path("contract-index.json"): canonical(index).encode(),
        Path("python/porfirium_contracts/__init__.py"): (
            '"""Generated Porfirium contract metadata."""\n'
            "from .event_catalog import EVENTS\n\n__all__ = [\"EVENTS\"]\n"
        ).encode(),
        Path("python/porfirium_contracts/event_catalog.py"): py.encode(),
        Path("typescript/eventCatalog.ts"): ts.encode(),
    }
    with tempfile.TemporaryDirectory(prefix="porfirium-protobuf-") as directory:
        descriptor = Path(directory) / "runtime-v1.pb"
        sources_proto = sorted((CONTRACTS / "protobuf").rglob("*.proto"))
        subprocess.run(
            ["protoc", f"--proto_path={CONTRACTS / 'protobuf'}", "--proto_path=/usr/include",
             f"--descriptor_set_out={descriptor}", "--include_imports", *map(str, sources_proto)],
            check=True, capture_output=True,
        )
        result[Path("protobuf/runtime-v1.pb")] = descriptor.read_bytes()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render()
    stale: list[str] = []
    for relative, content in rendered.items():
        target = GENERATED / relative
        if args.check:
            if not target.exists() or target.read_bytes() != content:
                stale.append(str(relative))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    expected = set(rendered)
    if GENERATED.exists():
        unexpected = {
            path.relative_to(GENERATED) for path in GENERATED.rglob("*") if path.is_file()
        } - expected
        stale.extend(f"unexpected:{path}" for path in sorted(unexpected))
    if stale:
        raise SystemExit("generated contracts are stale: " + ", ".join(stale))
    action = "check" if args.check else "write"
    print(f"Contract generation {action} passed: {len(rendered)} artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
