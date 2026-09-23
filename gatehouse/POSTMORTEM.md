# Postmortem: ingress outage while adding the gatehouse entrypoint

**Date:** 2026-07-09
**Duration:** about 25 minutes
**Impact:** every service behind the reverse proxy was unreachable, from the
LAN and from outside. That included the remote shell access path, the
management API, and the VPN control plane, because all of them are routed
through the same Traefik.
**Cause, in one line:** the running Traefik container was removed before its
replacement had been shown to start, and the replacement could not start
because the port chosen for it was already in use.

## Context

The change was made by the Claude Code agent I use for lab operations,
working under my rules for this lab, and I did the recovery. I am writing it
up the same way I would for a change made by a person: the gaps were in the
procedure, and the rules below now apply to both of us.

The work was Phase 0 of gatehouse: add a second HTTPS entrypoint to Traefik
(`websecure-ext`) so internet traffic could be separated from LAN traffic.
That meant a new published port in Traefik's compose file and a recreate of
the container.

## Timeline

1. Port 8443 was picked for the new entrypoint and added to the compose file
   and the static config. Nobody checked whether anything on the host was
   already listening on 8443.
2. `docker rm -f traefik` removed the old container, with the plan to bring
   the new one up right after.
3. `docker compose up -d` failed: another container's `docker-proxy` already
   held 8443. Traefik was now gone, not restarting.
4. Every route died with it. The remote shell path, the management API and
   the VPN all go through Traefik, so every normal way to fix it was cut off
   too.
5. I restored from the Proxmox console: copied back the pre-change compose
   and config backups, then ran `docker compose -p traefik up -d`. Service
   came back.
6. The change was redone later with port 9443, checked free first, and the
   container recreated with `docker compose up -d` instead of a manual
   remove. No interruption the second time.

## What went wrong

- **No free-port check.** This is the root cause. With a port conflict the
  new container cannot start, whichever way you recreate it.
- **A manual `docker rm -f` on the only ingress.** It guaranteed there was
  nothing running while the new config was being tried for the first time,
  and it turned "the change did not apply" into "the proxy is gone".
- **One path in.** The tools for fixing the proxy depended on the proxy.
  The only way in that did not was the hypervisor console, and only I could
  use it.

## What went right

- Pre-change backups of the compose file and every edited config existed,
  so the restore was a copy and one command.
- The console path (hypervisor, not network) still worked.

## Rules that came out of it

1. **Check the port is free before choosing it:** `ss -tlnp | grep :<port>`
   on the host, for every new published port.
2. **Never `docker rm -f` a running Traefik.** Change the files, then
   `docker compose -p traefik up -d`, and have the rollback command ready.
3. **Back up every file you touch** with a timestamped suffix, before the
   change, so a rollback is a copy.
4. **Know the way in that does not depend on the thing you are changing**
   (for me, the hypervisor console) before a risky change, not during one.
5. **Change one thing, prove it, then continue.** The second attempt added
   the entrypoint, confirmed every public site answered exactly as before
   through the new port, and only then moved the tunnel over.
