# Target Compose topology

The target architecture is intentionally separate from the legacy root `compose.yaml`. Start the
Phase 2 infrastructure with secrets supplied from an uncommitted environment file:

```bash
docker compose --env-file .env.target --profile target \
  -f deploy/compose/target.yaml up -d
```

The PostgreSQL container creates a distinct database and login role for each state-owning service.
The NATS bootstrap job declaratively creates the streams in the messaging contract and can be run
again safely after configuration changes. The registry is private to the Compose network. The
collector initially uses its bounded debug exporter; Langfuse export is connected when the target
observability deployment is added.

NATS requires a distinct password for its bootstrap administrator and every messaging service.
Application identities are limited to their owned subjects; none receives the bootstrap password
or an unrestricted publish/subscribe grant. Supply all passwords through `.env.target`, never in
the Compose or NATS configuration committed to the repository.

The eight target control-plane services are independently buildable FastAPI packages. Their
readiness endpoints currently report process readiness only; dependency-specific readiness is
added with each service's persistence and messaging implementation.

Run `./scripts/target-phase2/verify.sh` for offline structural validation. Run
`./scripts/target-phase2/verify-nats.sh` to create an isolated, temporary Compose project and prove
authenticated stream bootstrap plus an allowed and denied service publish. The verifier removes
its containers, network, and test-only JetStream volume on exit.

`./scripts/target-phase2/verify-durability.sh` exercises the Runner-owned transactional outbox and
inbox against PostgreSQL and JetStream. It restarts NATS after publication, deliberately exits one
consumer after its inbox commit but before acknowledgement, then verifies that redelivery causes
exactly one durable scheduling effect. Like the NATS permission verifier, it uses and removes a
uniquely named test project.

`./scripts/target-phase2/verify-stack.sh` starts every target service and verifies dependency-aware
readiness plus database connection isolation. `./scripts/target-phase2/acceptance.sh` is the
aggregate Phase 2 entry point and runs all structural and live checks. Phase 2 is accepted when
that command passes from a clean set of temporary Compose projects.
