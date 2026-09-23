# code-server: Browser IDE

## What
Full VS Code running as a service and served over the browser, so the same
editor, extensions, and workspace are available from any device, including
tablets and machines you can't install tooling on.

## Why
A persistent, always-on development environment that lives next to your data and
compute instead of on a laptop. It's also an ideal home for long-running
coding-agent sessions: the environment stays up, keeps state, and is reachable
from anywhere, so an agent's work survives you closing the lid.

## Files
| File | Purpose |
|------|---------|
| `compose.yaml` | code-server (`4.137.0`), built-in auth disabled, loopback-bound, healthcheck. |
| `.env.example` | Host UID/GID for correct file ownership + timezone. |

## Usage
```bash
cp .env.example .env       # set PUID/PGID from `id -u` / `id -g`
mkdir -p workspace         # create it as your user, or Docker creates it root-owned
docker compose up -d
```
The container binds to `127.0.0.1:8080` only, reach it through the reverse
proxy, not directly.

### Reverse-proxy auth (defer to SSO)
The compose file starts code-server with `--auth none`, deliberately disabling
its built-in password login. **Authentication is delegated to an SSO/auth
middleware at the reverse proxy** instead. Two reasons:
1. code-server's password is a single shared secret with no MFA, per-user
   identity, or central revocation, an SSO layer gives all three.
2. It avoids a confusing double login and keeps auth policy in one place with
   the rest of your services.

Because auth is deferred, the container **must never be exposed without that
middleware in front**, an unauthenticated code-server is a remote shell for
anyone who finds it. The loopback port bind is a second guardrail so it can't be
reached except through the proxy.

### Persistence
- `code-server-config` (named volume) holds IDE settings, installed extensions,
  and state, survives restarts and image upgrades.
- `./workspace` (bind mount) holds your actual projects. Back this up like any
  source directory; the config volume is convenience, the workspace is data.

### Pairing with terminal multiplexers for long-lived agent sessions
The browser IDE tab is ephemeral, refresh, network blip, or device switch and
the integrated terminal's foreground process is gone. Run long-lived work
(build watchers, dev servers, and especially autonomous coding-agent sessions)
inside a terminal multiplexer such as **tmux** or **screen** in the integrated
terminal. The agent process is then owned by the multiplexer, not the browser
tab: you can detach, close the laptop, reconnect from a phone hours later, and
`tmux attach` straight back into the still-running session with full scrollback.
This decoupling is what makes code-server a durable host for agent work rather
than just a convenient editor.

Tested on Docker (published port removed): healthy, `/healthz` answered. Fixed
during that test: the image ignores PUID/PGID, and a volume on
`/home/coder/.config` alone came up root-owned (EACCES); it now runs with
`user:` and keeps the whole home directory in the volume.

## Integration
Route your IDE hostname at the reverse proxy to `code-server:8080`, put an
SSO/auth middleware in front (this is mandatory given `--auth none`), and
terminate TLS there. Keep the port bound to loopback so the proxy is the only
path in.
