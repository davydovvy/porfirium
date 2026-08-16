# Phase 1 runbook

Phase 1 adds the authenticated Porfirium HTTPS portal skeleton, portal API, and application database. Keycloak remains the separately managed prerequisite at `/home/dvy/Projects/KeyCloak`.

## Prerequisites

`keycloak.local` and `portal.local` must resolve to `127.0.0.1`. The standalone Keycloak Compose file mounts `keycloak/genai-platform-realm.json` and must be running:

```bash
cd /home/dvy/Projects/KeyCloak
docker compose -f docker-compose.keycloak.yml up -d
```

## Start and use

Start the portal first so Caddy creates its persistent local CA:

```bash
./scripts/phase1/start.sh
```

Then trust the portal root certificate if the browser does not already trust it:

```bash
cd /home/dvy/Projects/genai-demo-platform
mkdir -p .phase1
docker compose cp portal:/data/caddy/pki/authorities/local/root.crt .phase1/portal-root-ca.crt
```

Import `.phase1/portal-root-ca.crt` into the browser/operating-system trust store. This is public CA material, not a secret.

Open `https://portal.local:8444` and sign in with either local demo account:

| Display name | Username | Password |
|---|---|---|
| Alise | `alise` | `123456` |
| Bob | `bob` | `123456` |

Keycloak normalizes usernames to lowercase. These intentionally simple credentials are only for the isolated local demo.

After login, the portal shows the verified identity and the empty conversation workspace. Use the profile arrow to sign out. Opening `https://portal.local:8444/api/v1/me` without an access token returns HTTP 401.

## Verify and inspect

```bash
./scripts/phase1/verify.sh
./scripts/phase1/status.sh
```

The smoke test signs in both demo accounts without printing tokens, checks the protected identity endpoint, and verifies that their internal user IDs differ.

## Stop and recover

Normal stop preserves the application database and portal CA:

```bash
./scripts/phase1/stop.sh
./scripts/phase1/start.sh
```

Inspect failures with:

```bash
docker compose logs --tail=200 portal portal-api application-postgres
```

Do not use `docker compose down -v` unless intentionally resetting all project state. There is no user-facing conversation deletion operation.

## Phase boundary

Phase 1 intentionally has no chat submission. Direct streaming chat, conversation creation/history, Bifrost calls, and Langfuse application traces arrive in Phase 2. The existing Phase 0 diagnostic services remain available through their original scripts.
