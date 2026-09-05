# Porfirium contracts

This package is the source of truth for interfaces shared between independently deployed
Porfirium components. It contains specifications and fixtures, not service implementation or
persistence models.

## Layout

- `openapi/` contains versioned synchronous HTTP APIs.
- `protobuf/` contains the Agent SDK to Agent Runtime API protocol.
- `events/` contains JSON Schemas for durable JetStream commands and events.
- `fixtures/` contains valid contract examples used by producers and consumers.
- `compatibility/` records the reviewed v1 semantic surface.
- `generated/` contains deterministic indexes, registries, and protobuf descriptors.

Compatibility is additive within a major version. Removing a field, changing its meaning, making
an optional field required, or reusing an enum value requires a new major version and a documented
migration window.

Run the contract checks from the repository root:

```bash
./scripts/contracts/verify.sh
```

After deliberately changing source contracts, regenerate deterministic artifacts with:

```bash
python3 scripts/contracts/generate.py
```

Changing the compatibility baseline requires explicit review because it acknowledges a new stable
v1 surface:

```bash
python3 scripts/contracts/compatibility.py --write-baseline
```

Ordinary generation never updates that baseline. A breaking change should normally introduce v2
contracts instead.

Python consumers can add `generated/python` to their package build and import
`porfirium_contracts.EVENTS`. TypeScript consumers can import `generated/typescript/eventCatalog.ts`.
The descriptor set in `generated/protobuf/runtime-v1.pb` supports protocol linting and compatibility
tools without importing the Runtime service implementation.

Generated clients will be added under `generated/` once the service framework and generator
versions are pinned. Generated artifacts must never become a route for importing another
service's ORM or repository code.
