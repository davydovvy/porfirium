# Runtime-only agent network gate

Status: **accepted on rootless Podman 6.1.0 with netavark 2.1.0**

This gate proves the network primitive required by target agent attempts. Each attempt receives a
fresh rootless Podman internal network containing only that attempt and a platform-controlled
Runtime endpoint. The attempt can reach Runtime by its fixed alias but cannot reach the host,
public internet, cloud metadata, gateways, or containers on another attempt network.

The result does not authorize a shared agent network. Runner must create and record one network per
attempt, attach the Runtime endpoint, and remove the exact network during cleanup. Runner and
Runtime must therefore use the same rootless Podman control plane; the current Docker Compose
Runner image does not satisfy that deployment requirement.

## Accepted observation

On 2026-09-06 the probe passed with one internal network per attempt. The constrained attempt
reached the platform-selected Runtime alias and could not reach public internet, cloud metadata,
the host gateway, a container on another internal network, or a container-runtime socket.

Run as the unprivileged Podman owner:

```bash
./scripts/feasibility/runtime-only-network/verify.sh
```
