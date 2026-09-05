# Identity, delegation, and security

Status: accepted architecture contract

The platform is single-tenant but multi-user. Every resource remains user-owned or explicitly
shared. Agent code and agent-supplied data are untrusted.

## Credential classes

Credentials have distinct purposes and are never substituted for one another:

| Credential | Holder | Purpose |
|---|---|---|
| Browser session/access token | Browser and BFF session boundary | User interaction with Portal |
| Delegation grant ID | Platform services | Revocable non-secret reference to user authorization |
| Service credential | Platform service | Audience-scoped service-to-service calls |
| Run capability | One agent attempt | SDK access for one pinned run |
| Delegated user token | One agent attempt | User-authorized MCP Gateway calls |
| Downstream MCP token | MCP Gateway | One MCP resource audience |
| Provider credential | LLM Gateway only | External model provider access |

OIDC ID tokens prove authentication to a client and are not used as MCP API bearer tokens.

## Delegated MCP authorization

1. BFF validates the user session and asks Identity Delegation Service to create or reuse a durable
   delegation grant bound to the user, conversation, allowed release, and maximum scopes.
2. The service returns an opaque `delegation_grant_id`. This identifier is not a bearer credential
   and is safe to place in the Conversation Service outbox and run-admission request.
3. Identity Delegation Service verifies the grant, active run, user access, release request, and
   platform policy at attempt start.
4. It exchanges the server-held user access grant for a short-lived OAuth access token whose
   audience is the MCP Gateway.
5. Effective scopes are the intersection of user rights, agent release requests, and platform
   policy.
6. Runner delivers the delegated token to the exact attempt through an in-memory secret or protected
   tmpfs file after container creation.
7. SDK presents it only to the configured MCP Gateway over TLS.
8. MCP Gateway validates issuer, audience, signature, expiry, scopes, run context, and current tool
   grant.
9. If the MCP server is a distinct OAuth resource, MCP Gateway exchanges for a token restricted to
   that resource and forwards it.

Delegation Service keeps the underlying browser-session authorization encrypted at rest when it
must outlive one request. The grant has an explicit expiry and revocation record. It never contains
the access or refresh token, and possession of the grant ID alone cannot mint a token without the
authorized service identity and matching active run.

Both user authorization and run authorization are required. Possessing a user token does not grant
an agent an undeclared tool; possessing a run capability does not grant a tool the user cannot use.

## Renewal and revocation

Agent code never receives a refresh token. The SDK may request delegated-token renewal through the
Runtime API. Identity Delegation Service renews only if:

- the run and attempt are active;
- the user session/grant remains valid;
- agent access and release policy remain valid;
- requested audience and scopes equal or narrow the pinned grant;
- cancellation, logout, access removal, or administrative revocation has not occurred.

Cancellation, logout, access removal, grant revocation, or conversation deletion immediately blocks
renewal and new gateway calls. Existing bearer tokens remain limited by their short expiry;
sender-constraining may be added where supported. Token exchange must be proven with the selected
Keycloak configuration before dependent implementation begins.

## Run capability

The run capability is separate from delegated identity. It is bound to:

- user, release, run, attempt, and monotonically increasing lease epoch;
- Runtime, State, and LLM API audiences;
- permitted SDK operations;
- model and tool grant identifiers;
- checkpoint namespace;
- byte, call, token, concurrency, and time limits;
- expiry and revocation identity.

It cannot authorize arbitrary NATS access, container control, Registry mutation, or another run.
Runtime API, State API, LLM Gateway, and MCP Gateway reject capabilities from a superseded lease
epoch even if the old container or token has not yet expired.

## Container isolation

Every attempt runs in a new container with:

- numeric non-root UID/GID and no privilege escalation;
- all Linux capabilities dropped;
- read-only image/root filesystem and bounded tmpfs;
- no host paths, devices, runtime socket, or cloud metadata access;
- PID, CPU, memory, disk, output, and elapsed-time limits;
- platform-selected syscall and mandatory-access-control profiles;
- default-deny egress allowing only SDK-facing platform endpoints;
- no service, database, provider, NATS, OCI, or observability credential.

The Runner derives this profile. Agent manifests may request lower limits but cannot weaken policy.

## NATS security

Only platform services connect to NATS. Connections use TLS and authenticated service identities
with least-privilege publish/subscribe subjects, payload limits, quotas, and durable-consumer
permissions. Agent containers use Runtime API and receive no NATS credentials.

No token or secret is allowed in a subject, header, event envelope, message body, or dead-letter
diagnostic. Subjects use opaque IDs where identity is required.

## Data handling

Prompts, messages, tool arguments/results, checkpoints, manifests, files, model responses, and
telemetry attributes are untrusted. Every boundary enforces schema, encoding, byte, item, depth,
rate, and time limits.

Credentials are redacted before logging, persistence, tracing, metrics labels, exception rendering,
or user display. SDK and service tests include representative token patterns. Dead-letter events
contain safe identifiers and error codes, not original sensitive payloads by default.

## Authorization ownership

- Conversation Service authorizes conversation and input ownership.
- Registry authorizes agent discovery, release selection, publication, and deprecation.
- Runner authorizes run inspection and cancellation.
- Runtime API authorizes active attempt communication.
- State API authorizes checkpoint namespaces.
- LLM Gateway authorizes pinned model grants.
- MCP Gateway authorizes delegated user scopes and pinned tool grants.

UI visibility is never an authorization boundary. Services validate token audience and derive the
user from verified claims rather than caller-provided identity fields.

## Supply-chain trust

External CI initially builds agent images from reviewed source with locked dependencies. It emits
an SBOM, provenance, vulnerability results, and signature. Registry publication verifies all
required evidence and pins the OCI digest. Runner rejects mutable tags, missing evidence, digest
mismatch, incompatible SDK/runtime protocols, and revoked signatures.

The platform never executes publisher-provided Docker options, mounts, networks, devices, or
privilege settings.
