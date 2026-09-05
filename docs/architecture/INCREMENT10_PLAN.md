# Executable agent isolation proposal

Status: Design candidate; isolation spike and threat-model review required before implementation
Prerequisite: the current declarative runtime and publication contracts remain green

## Outcome

This proposal allows an authorized operator to publish and run one narrowly supported class of
independently supplied executable agent without loading its code or dependencies into the Portal
API, Temporal orchestration worker, or Agentgateway processes. Each version is built once into an
immutable OCI image, identified by digest, and executed for one turn in an ephemeral constrained
container. The accepted run snapshot pins both the agent release and runner image digest.

The platform remains the only authority for model and tool access. Executable code receives a
bounded run contract and calls a platform-owned run bridge; it receives no database URL, provider
key, MCP credential, browser token, Docker socket, host mount, or general network access. A
runner failure, timeout, resource exhaustion, malformed response, or attempted escape produces a
bounded failed turn without changing the release, snapshot, conversation, or another run.

This increment supports filesystem publication of Python 3.12 source with a fully locked,
hash-verified dependency set and one fixed platform SDK/entrypoint contract. Portal source
editing/upload, arbitrary images, native extensions, shell entrypoints, multiple languages,
user-delegated credentials, write-capable tools, distributed build infrastructure, and production
Kubernetes scheduling remain deferred.

The increment is complete when a benign executable can be validated, built, published, selected,
and run without rebuilding the Portal API or existing workers, while adversarial fixtures prove
that code cannot reach protected services, credentials, the host, another run, or exceed its
resource and behavioral limits.

## Scope

Included:

- manifest schema v3 with `runtime.kind = "python"` and `runtime.contract_version = 1`;
- one exact package shape, Python version, SDK contract, and entrypoint;
- offline source validation and a quarantined, network-disabled build from a reviewed dependency
  mirror/cache;
- immutable OCI runner images pinned everywhere by `sha256` digest;
- an application-owned build/publication state machine and bounded provenance evidence;
- a dedicated executable Temporal task queue and runner pool, separate from declarative work;
- one ephemeral non-root container per turn with read-only filesystems, no host mounts or Docker
  socket, dropped capabilities, seccomp/AppArmor, PID/process, CPU, memory, disk, and time limits;
- default-deny network policy allowing only the platform run bridge;
- run-scoped, single-turn bridge authorization and continued platform enforcement of exact model,
  tool, schema, argument, result, token, and call limits;
- immutable executable run snapshots, audit, cancellation, recovery, and bounded diagnostics;
- negative isolation tests, live adversarial acceptance, rollback, and a clean-checkout verification
  script.

Deferred:

- portal code editor, archive upload, Git clone, webhooks, or automatic builds;
- publisher-provided Dockerfiles, base images, binaries, native extensions, OS packages, lifecycle
  hooks, shell commands, or arbitrary environment variables;
- PyPI or internet access during validation, build, or execution;
- signing infrastructure, transparency logs, remote registries, promotion, and multi-environment
  attestations beyond local digest/provenance capture;
- JavaScript, JVM, Wasm, GPU, multi-container, long-lived service, or background-task runtimes;
- write-capable or approval-required tools and user-delegated secrets;
- horizontal multi-host scheduling and production orchestrator selection;
- executable draft testing in the portal; current draft tests remain declarative-only;
- artifact deletion, image garbage collection, release replacement, or mutation.

## Threat model and trust boundaries

Treat source, dependencies, manifest text, stdout/stderr, bridge requests, model output, tool
arguments, and tool results as malicious. The protected assets are host control, platform and
observability credentials, databases, Temporal, Agentgateway and MCP services, other runner
containers, other users' conversations, immutable artifacts/snapshots, and service availability.

The first implementation targets containment of malicious application code within the documented
container-runtime boundary. It does not claim protection from a kernel or container-runtime
zero-day. Before implementation, the feasibility workstream must record the local runtime,
rootless mode,
seccomp/AppArmor availability, cgroup v2 enforcement, and the later production isolation class.
If the local host cannot enforce the required controls, the spike fails closed; it must not fall
back to a subprocess, virtual environment, `--privileged`, shared worker process, or writable host
mount.

The boundaries are:

```text
Portal API / publisher -> build coordinator -> quarantined builder -> immutable image digest
Temporal orchestration -> executable task queue -> runner supervisor -> ephemeral run container
ephemeral run container -> run bridge -> existing model/tool authorization -> Agentgateway
```

Only platform-owned components may access the container runtime. The runner supervisor exposes a
narrow create/cancel/status contract and validates a complete allowlist of container settings.
Agent code never receives its control socket. Compromise of agent code must not imply control of
the supervisor; compromise of the supervisor remains infrastructure compromise and is reduced by
rootless operation and a dedicated runner host/pool in non-local deployments.

## Fixed design decisions

1. Executable and declarative releases are distinct runtime kinds. Declarative releases continue
   unchanged through `AgentRunWorkflow` on `porfirium-agent-runtime-v1`; executable releases use
   a new platform-owned `ExecutableAgentWorkflow` and `porfirium-agent-python-untrusted-v1`.
2. Version 1 supports Python 3.12 only. The package cannot select an interpreter, workflow,
   activity, task queue, container image, command, user, network, mount, or security profile.
3. The accepted filesystem package is one regular-file tree containing `manifest.json`,
   `agent.py`, and `requirements.lock`. Symlinks, hard links, devices, sockets, FIFOs, hidden
   files, bytecode, archives, nested package managers, extra lockfiles, and files outside explicit
   count/per-file/total-size bounds are rejected.
4. `agent.py` exports the fixed SDK function `async def run(context: RunContext) -> RunResult`.
   Import has a deadline and no side-effect authority. Input/output cross a length-prefixed JSON
   protocol with a versioned schema; pickle, stdin command shells, arbitrary RPC, and dynamic
   module names are prohibited.
5. Dependencies are exact `name==version --hash=sha256:...` entries from a repository-configured
   allowlist and immutable wheel mirror. Wheels must match the supported pure-Python platform;
   sdists, VCS/URL/path dependencies, editable installs, dependency confusion fallback, install
   scripts, and unreviewed transitive packages fail validation.
6. Builds do not have internet or platform-service access. A platform-owned, digest-pinned builder
   consumes only canonical source bytes, the reviewed wheel set, fixed SDK, and fixed base image.
   Build instructions are not supplied by the package.
7. The output is an OCI image addressed by manifest digest, not a mutable tag. Publication stores
   source digest, lock digest, SDK/base/builder digests, output image digest, validation report,
   SBOM, and bounded build provenance. A successful rebuild must produce the same digest or fail
   `build_not_reproducible`.
8. Build and publication are separate durable states: `candidate -> building -> built ->
   published` or `build_failed`. Only a built digest can enter the existing atomic publisher.
   Publication never sets an agent default and preserves current conflict/idempotency rules.
9. Executable images are never run by the Portal API or generic worker. Each accepted turn creates
   one ephemeral container from the snapshot-pinned digest through the runner supervisor. A
   container is not reused across turns, users, versions, retries, or tests.
10. The run container uses a numeric non-root UID/GID, `no-new-privileges`, all capabilities
    dropped, read-only root and artifact filesystems, bounded tmpfs, PID limit, cgroup CPU/memory,
    seccomp and AppArmor profiles, init/reaping, and an elapsed deadline. It has no host path,
    device, runtime socket, metadata endpoint, or ambient environment secrets.
11. Egress is default-deny at the network boundary, not an SDK convention. The only permitted
    destination is the run bridge on a dedicated runner network; DNS and direct access to Portal
    API, databases, Temporal, Agentgateway, MCP, Keycloak, Langfuse, the internet, and other run
    containers are denied and tested.
12. The bridge accepts a random, hashed-at-rest, run-scoped capability created after turn
    acceptance. It is bound to run/snapshot/user, audience, expiry, call counters, and the exact
    resolved model/tool grants. It cannot query catalogs or choose another run. It is revoked on
    terminal state and is never persisted in Temporal history, events, logs, or artifacts.
13. The bridge is an enforcement point, not a credential forwarder. It performs every existing
    model/tool authorization check, calls Agentgateway with platform credentials, applies byte and
    token limits, records audits, and returns bounded normalized results. Agent code receives no
    provider, MCP, browser, database, or observability credential.
14. Executable snapshot contract v1 pins image/source/lock/SDK/base digests, entrypoint contract,
    trust class, resolved model/tools, and all resource and behavioral limits. Runtime never
    resolves a mutable tag, current release, default, grant, alias, or package directory.
15. Workflow code remains deterministic and contains no container API calls. Activities create
    the capability, ask the supervisor to execute/cancel, persist bounded events/results, and
    reconcile an already-started run idempotently after retries or worker restart.
16. stdout and stderr are untrusted diagnostic streams: UTF-8 replacement, line/rate/total bounds,
    secret redaction, and truncation apply before persistence. They never become assistant output.
    The sole assistant response is a schema-valid bounded `RunResult` accepted atomically.
17. CPU, memory, PIDs, writable bytes, stdout/stderr, input/output, model tokens, tool calls,
    bridge calls, and elapsed time have platform maxima. A manifest may only request lower values.
    Resource exhaustion is non-retryable for that attempt and maps to a stable safe error.
18. Cancellation revokes the bridge capability first, asks the supervisor to terminate within a
    grace period, then force-removes only the resolved run container. Startup reconciliation
    removes orphaned terminal containers and never targets by an unvalidated prefix or broad label.
19. No secrets are supported in executable manifests or runs in this proposal. The contract
    reserves named secret references, but validation rejects nonempty requests until a separate
    secure-delivery design is accepted.
20. Migrations are additive. Published artifacts, build evidence, snapshots, run records, audits,
    and Temporal histories are immutable and retained. Rollback closes executable admission and
    removes no evidence.

## Package and manifest contract

The first executable package is:

```text
agents/
  python-canary/
    1.0.0/
      manifest.json
      agent.py
      requirements.lock
```

Schema v3 retains identity, model, instructions, tools, and behavioral limits, and adds only
platform-bounded runtime/resource declarations:

```json
{
  "schema_version": 3,
  "runtime": {"kind": "python", "contract_version": 1},
  "resources": {
    "cpu_millis": 500,
    "memory_mib": 128,
    "tmp_mib": 16,
    "max_processes": 32,
    "timeout_seconds": 30,
    "max_stdout_bytes": 16384,
    "max_stderr_bytes": 16384
  }
}
```

Exact maxima belong in one server-owned limits module and are repeated by validator, publisher,
snapshot builder, supervisor, bridge, and tests. Unknown fields fail closed. The canonical source
artifact is a deterministic tar stream with normalized path order, separators, modes, ownership,
and timestamps. Its digest covers every accepted source byte and the manifest; the release digest
identifies this canonical source artifact. The separately pinned execution-image digest identifies
what actually runs, and both are required in publication and snapshot evidence.

Extend the CLI without changing declarative behavior:

```text
porfirium agents validate agents/python-canary/1.0.0 [--json]
porfirium agents build agents/python-canary/1.0.0 [--json]
porfirium agents publish agents/python-canary/1.0.0 [--json]
porfirium agents status python-canary:1.0.0 [--json]
```

`publish` may resume an already successful build but may not perform an implicit networked build,
accept a tag, bypass a failed check, or rebuild a published version. Stable errors distinguish
package validation, dependency policy, build availability, reproducibility, image verification,
publication conflict, and unsupported runtime.

## Build and publication contract

Add immutable build records keyed by candidate digest and builder contract. A build request is
idempotent; concurrent requests converge on one durable build. The coordinator must:

1. validate and canonicalize the complete package before scheduling;
2. resolve every locked dependency to one reviewed wheel and record its digest;
3. persist a bounded build intent before external work starts;
4. run the fixed builder with no network, credentials, host source mount, or Docker socket inside
   build steps;
5. generate and validate the OCI image, SBOM, and provenance against the intent;
6. scan the unpacked result for forbidden file types, setuid/setgid bits, unexpected executables,
   writable application paths, and size limits;
7. rebuild independently for the acceptance canary and compare digests;
8. mark the build usable only after every digest and policy check succeeds.

The container-runtime control surface used by the platform-owned builder/supervisor must be
isolated from both build steps and run containers. For local Compose, feasibility work must choose
and document a rootless implementation and demonstrate that its narrow adapter rejects images,
mounts, networks, privileges, devices, and security options not derived from platform policy.
Production deployment must place this control component on a dedicated untrusted-runner pool;
sharing the Portal API or orchestration-worker host is not an accepted production topology.

The existing publisher gains an executable candidate adapter but keeps one atomic publication
boundary. It verifies completed build evidence and creates the source artifact, agent version,
exact grants, executable artifact linkage, publication audit, and published state in one
transaction. Failed or abandoned builds never create selectable versions.

## Execution and bridge contract

An executable turn is accepted only when the selected release is published, nondeprecated, has
complete immutable build evidence, and its runtime trust class is enabled. The snapshot includes:

```text
runtime kind/contract and trust class
source, lock, runner image, SDK, base image, and builder digests
fixed entrypoint/protocol version
resolved model target and exact reviewed tool definitions/grants
behavioral limits plus CPU, memory, PID, tmpfs, stream, and elapsed limits
```

`ExecutableAgentWorkflow` orchestrates these idempotent activities:

1. load and validate the pinned executable plan;
2. mark the turn running and issue a bridge capability outside workflow history;
3. request `start_run` with a stable run ID and the complete platform-derived sandbox profile;
4. wait through bounded heartbeats while the supervisor owns container execution;
5. validate the terminal result, persist the assistant message/events, and revoke capability; or
6. on cancellation/failure/timeout, revoke capability, terminate the exact container, persist one
   stable terminal outcome, and retain bounded evidence.

The agent SDK exposes only `generate`, `call_tool`, cancellation/deadline inspection, and final
result construction. Each bridge operation is bound to the snapshot and uses idempotency keys.
The bridge rejects unknown operations, replay across runs, calls after expiry/terminal state,
undeclared tools, changed schemas, oversized payloads, excessive concurrency/counters, and model
or tool authority not present in the snapshot.

## Implementation sequence

### Workstream 1 — Isolation feasibility and threat-model gate

- inventory local kernel/runtime capabilities and select the rootless builder/supervisor adapter;
- write the data-flow threat model and enumerate protected assets and assumed infrastructure;
- prove cgroup, PID, filesystem, user, capability, syscall, network, timeout, and exact-container
  cleanup controls with a throwaway image;
- prove the run container cannot reach the runtime socket, host, protected Compose services,
  metadata addresses, internet, or a sibling container;
- benchmark cold-start and cancellation and define enforceable platform maxima;
- record why the selected boundary is suitable for the local demo and what stronger production
  pool/sandbox is required.

Checkpoint: automated adversarial probes pass on a clean host. If any required control is absent
or merely advisory, stop this work without adding executable manifests or publication paths.

### Workstream 2 — Package, dependency, and reproducible build contracts

- add schema v3, strict package traversal, deterministic source artifacts, and stable errors;
- pin the Python SDK, base, builder, dependency allowlist, and immutable wheel inputs;
- add durable idempotent build records, SBOM/provenance schemas, and immutability constraints;
- implement network-disabled builds and independent digest comparison;
- extend CLI validate/build/status while preserving current declarative output and behavior.

Checkpoint: benign packages rebuild identically; path tricks, duplicate JSON keys, lock drift,
sdists, native code, install hooks, unexpected files, network attempts, and tampered outputs fail
before a selectable release exists.

### Workstream 3 — Runner supervisor and platform run bridge

- implement the narrow supervisor contract and complete server-derived sandbox profile;
- implement ephemeral per-turn execution, reconciliation, cancellation, bounded diagnostics, and
  exact-container cleanup;
- add the isolated bridge network and run-scoped capability lifecycle;
- reuse existing model/tool policy and gateway adapters behind the bridge;
- test forged/replayed/expired capabilities and all model/tool/byte/token/call limits.

Checkpoint: an SDK contract test can generate and call one reviewed read-only tool, while direct
networking, credentials, undeclared tools, cross-run calls, resource abuse, forks, and oversized
I/O are denied with complete bounded audit evidence.

### Workstream 4 — Durable executable orchestration and publication

- add executable artifact linkage and atomic publication through the shared publisher;
- add immutable executable snapshot contract v1 and runtime admission checks;
- add `ExecutableAgentWorkflow` and its dedicated worker/task queue;
- preserve idempotency, event ordering, cancellation, restart, replay, tracing, deprecation, and
  explicit selection semantics;
- keep declarative routing and workers unchanged and prove queue/trust-class separation.

Checkpoint: an active executable turn survives an orchestration-worker restart without starting a
second container or changing digests; a newer publication, deprecation, or catalog change cannot
alter it; declarative turns continue through their existing workflow and queue.

### Workstream 5 — Adversarial acceptance and handoff

- add a benign Python canary and repository-owned malicious fixtures, never publish the latter;
- add executable-runtime procedures to `docs/OPERATIONS.md` and a focused verification script;
- run clean-checkout build/publication/execution, isolation, restart, cancellation, and rollback;
- capture image/source/build/snapshot/run/workflow digests and bounded resource evidence;
- update current architecture and operator/security documentation only after acceptance.

Checkpoint: the complete matrix passes and M5 is ready for user acceptance.

## Test and acceptance matrix

Automated verification must cover:

- schema/package bounds, traversal, symlink/hard-link/special-file, canonicalization, and digest
  stability;
- dependency hashes, allowlist, transitive closure, offline resolution, tampering, and build
  reproducibility;
- atomic build/publication state, retries, concurrency, conflicts, injected rollback, and database
  immutability;
- image digest pinning with no tag fallback and snapshot agreement across every stored digest;
- root UID, capabilities, privilege escalation, syscall policy, filesystem writes, host paths,
  devices, runtime socket, environment, cgroup resources, PIDs, tmpfs, timeout, and cleanup;
- default-deny egress to DNS, internet, metadata, databases, Temporal, Agentgateway, MCP, Keycloak,
  Langfuse, Portal API, supervisor control, and sibling runs;
- bridge scope, expiry, revocation, replay, concurrency, idempotency, exact grants, schema, arguments,
  result bytes, tokens, call counters, and audit redaction;
- malformed protocol, import hang/crash, fork bomb, memory/CPU/disk exhaustion, output flooding,
  ignored cancellation, and partial supervisor/worker restart;
- owner isolation, role checks, selection, deprecation, immutable accepted runs, and safe errors;
- unchanged generic runtime, CLI publication, portal builder,
  migration, Compose, secret-policy, and dependency/license gates.

Live acceptance:

1. Start from the current verified baseline; record migrations, images, queues, defaults, and
   protected service addresses; verify executable admission is initially disabled.
2. Validate and build the benign canary twice with networking disabled; require identical source
   and image digests plus complete SBOM/provenance.
3. Publish it without changing a default, retry idempotently, select it explicitly, and complete
   no-tool and reviewed-tool turns through the dedicated executable queue.
4. During a long bounded turn, restart the executable Temporal worker and require one run
   container, the original snapshot/digests, and one terminal assistant response.
5. Cancel a turn and prove capability revocation, bounded forced termination, exact cleanup, and
   no later bridge call or assistant completion.
6. Run adversarial fixtures for filesystem escape, protected-service/internet access, credential
   discovery, sibling access, fork/memory/CPU/disk/output exhaustion, malformed protocol, and
   ignored cancellation. Require denial or bounded termination without protected-state change.
7. Stop the runner pool and prove executable admission/execution fails safely while declarative
   conversations remain available; restore it and reconcile without duplicate execution.
8. Deprecate the non-default canary and prove new selection is blocked while its accepted run and
   evidence remain readable and immutable.
9. Run the new focused verification script, then the current publication, portal-authoring, and
   generic-runtime regressions; inspect logs/events/traces for bounded data and absence of
   credentials.

## Rollout

1. Complete and review the feasibility workstream before applying schema or publication changes.
2. Apply additive build/artifact/snapshot migrations with executable admission disabled.
3. Deploy the bridge, rootless runner supervisor/pool, and executable Temporal worker on separate
   networks/queue; verify isolation before accepting artifacts.
4. Enable build/publication only for designated publishers and one canary identity.
5. Publish without changing defaults, explicitly select the canary, and complete the full live
   adversarial gate.
6. Enable executable selection only for intended users after acceptance. Keep declarative routing
   and rollback independently operable.

## Rollback

Disable executable admission and new build/publication requests first. Revoke live bridge
capabilities, allow bounded graceful termination, then have the supervisor remove only reconciled
executable run containers. Stop the executable worker, runner pool, bridge, and builder while
leaving declarative API/workers and Agentgateway operating.

Select a prior declarative or accepted executable release for new conversations as appropriate.
Do not repoint an executable release to another image, mutate snapshots or grants, delete images
needed by retained evidence, rewrite conversations, downgrade past additive migrations, or expose
the runtime socket to restore service.

## Exit gate

The proposal is accepted only when a locked Python package can be reproducibly built into
an immutable digest-pinned image, atomically published, explicitly selected, and executed through
the dedicated untrusted runner path; every run is pinned, ephemeral, non-root, resource-bounded,
and network-confined to the enforcing bridge; agent code receives no platform credential or
control-plane access; malicious and failing fixtures cannot affect the host, protected services,
another run, or declarative availability; restart, cancellation, deprecation, audit, and rollback
preserve immutable evidence; and all current declarative behavior remains green.
