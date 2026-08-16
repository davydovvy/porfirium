# Phase 0 dependency and license inventory

> Historical Phase 0 inventory. It remains evidence for that increment and is not a current Phase 1 SBOM or full dependency review.

Status: Historical runtime inventory. MinIO exception accepted for the local demo on 2026-08-16; verify pinned image SBOMs again before production distribution.

| Component | Phase 0 selection | License | Policy status |
|---|---|---|---|
| Bifrost | v1.6.11 image digest pinned in `compose.yaml` | Apache-2.0 | Preferred |
| Diagnostic MCP server | Project code | Apache-2.0 (planned repository license) | Preferred |
| Python MCP SDK | Locked in `services/diagnostic-mcp/uv.lock` | MIT | Preferred |
| Langfuse core | 3.225.2, web/worker digests pinned in `compose.yaml` | MIT core | Preferred; enterprise features excluded |
| ClickHouse | 25.12 | Apache-2.0 | Preferred |
| PostgreSQL | 17.6 | PostgreSQL License | Exception: permissive, required persistence |
| Redis | 7.2.5 | BSD-3-Clause generation | Exception: permissive; pinned before Redis licensing change |
| MinIO (Chainguard image) | Official Langfuse Compose dependency shape | AGPL-3.0 upstream | Accepted local-demo exception |
| Caddy | Existing Keycloak TLS proxy; proposed portal proxy | Apache-2.0 | Preferred |
| Keycloak | Existing 26.1 deployment | Apache-2.0 | Preferred |

Notes:

- The project preference is Apache-2.0 or MIT, not an assertion that all transitive runtime software already meets it.
- The official low-scale Langfuse topology requires PostgreSQL, ClickHouse, Redis-compatible caching/queues, and S3-compatible object storage.
- MinIO is accepted for this local demo because it preserves the supported Langfuse topology. Reassess licensing and replacement options before production redistribution or materially changing the deployment model.
- All external Phase 0 runtime images are pinned by digest in `compose.yaml`; the MCP build base is pinned in its Dockerfile. `scripts/phase0/licenses.sh` reports the locally resolved evidence.
- Magic: The Gathering card data, rules text, art, symbols, trademarks, and price-source terms require a separate content/IP review; software licenses do not cover that dataset.
