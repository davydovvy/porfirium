# Rootless container isolation gate

Status: **accepted on rootless Podman 6.1.0 with runc**

This gate exercises the Runner's proposed Podman isolation controls against a real rootless
runtime. It verifies:

- numeric non-root UID/GID, zero effective capabilities, seccomp filtering, and no privilege
  escalation;
- a read-only root filesystem with a size-bounded, `noexec`, `nosuid`, `nodev` temporary area;
- no network interface except loopback, runtime socket, host block device, or host mount;
- PID, CPU, memory, file-descriptor, and elapsed-time limits;
- cleanup by exact container identity without affecting another running container.

Run it as an unprivileged user with subordinate UID/GID ranges:

```bash
./scripts/feasibility/rootless-container-isolation/verify.sh
```

The default probe image is `docker.io/library/alpine:3.22`. Set
`PORFIRIUM_ISOLATION_IMAGE` to test a locally mirrored or digest-pinned equivalent. The probe uses
unique, process-scoped container names and removes only those exact containers on exit.

## Accepted observation

On 2026-09-05 all checks passed with Podman 6.1.0, `runc`, rootless overlay storage, the default
`/usr/share/containers/seccomp.json` syscall profile, and Alpine 3.22. A forced timeout required
SIGKILL after the one-second graceful-stop budget; the exact attempt container was then removed and
an unrelated running sentinel container remained untouched.

Decision: use rootless Podman as the first Runner backend. Runner must construct the fixed security
arguments and address containers by its recorded ID; agent manifests may not provide Podman flags.
Production deployment must additionally select and verify an available mandatory-access-control
profile because this development host has neither AppArmor nor SELinux enabled.
