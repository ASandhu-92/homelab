# n8n: Workflow Automation

## What
Self-hosted, fair-code workflow automation ("if-this-then-that" on steroids):
a visual editor plus hundreds of integration nodes, backed here by PostgreSQL
for durable execution history and credentials.

## Why
n8n replaces a pile of brittle cron jobs and glue scripts with versioned,
observable workflows, and, unlike hosted automation SaaS, keeps the data and
the credentials on infrastructure you control. Postgres (rather than the
default SQLite) is used so execution data survives, backs up cleanly, and
handles concurrent workflows.

## Files
| File | Purpose |
|------|---------|
| `compose.yaml` | n8n (`2.30.5`) + Postgres (`18-alpine`), with DB healthcheck gating startup. |
| `.env.example` | DB credentials, public URL, and the credential encryption key. |

## Usage
```bash
cp .env.example .env
openssl rand -hex 32          # paste into N8N_ENCRYPTION_KEY
docker compose up -d
```
Open the editor on `:5678` (or your proxy hostname) and create the owner
account on first launch.

### Webhook URL behind a reverse proxy
n8n listens on plain HTTP inside the container but must advertise its **external
HTTPS URL** to the outside world, otherwise webhook nodes hand third parties a
callback address they can't reach. That is the job of `WEBHOOK_URL` (and
`N8N_EDITOR_BASE_URL`). Set them to the public URL your proxy serves, e.g.
`https://n8n.example.com/`. `N8N_PROXY_HOPS=1` tells n8n to trust exactly one
proxy hop's `X-Forwarded-*` headers so it reconstructs the right scheme/host.

### Hardening notes
- **Terminate TLS at the proxy** and never expose `:5678` directly.
- **Put an auth/SSO middleware in front**, n8n's own login protects the app,
  but defense in depth at the proxy limits exposure of the editor and API.
- **`N8N_ENCRYPTION_KEY`** encrypts stored credentials at rest. Generate it
  once, back it up, and never rotate casually, changing it orphans every saved
  credential.
- **`N8N_SECURE_COOKIE=true`** and **`N8N_DIAGNOSTICS_ENABLED=false`** are set to
  require HTTPS cookies and disable outbound telemetry.
- Restrict which webhook paths are reachable at the proxy if only a subset needs
  to be public.

Tested on Docker (published port removed): Postgres went healthy and n8n
answered `/healthz` with `{"status":"ok"}`. Fixed during that test: Postgres
18 refuses a volume at `/var/lib/postgresql/data`, so the volume now mounts at
`/var/lib/postgresql`.

## Integration
Route `n8n.example.com` at your reverse proxy to `n8n:5678`, add an SSO
middleware for the editor, and (optionally) allow unauthenticated access only to
the `/webhook/` path prefix so external services can trigger flows while the UI
stays protected. Back up the Postgres volume and the encryption key together, 
one is useless without the other.
