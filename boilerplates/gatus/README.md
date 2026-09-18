# Gatus: Uptime Monitoring & Status Page

## What
A self-hosted, developer-oriented uptime monitor with a built-in status page
and alerting. Every monitor is defined declaratively in `config/config.yaml`,
so the entire observability surface lives in version control.

## Why
Most homelab/self-hosted stacks fail silently: a certificate expires, a DNS
resolver dies, or a database port stops accepting connections, and nobody
notices until a user does. Gatus is intentionally tiny (single Go binary, no
external database required) and its config-as-code model means a new service is
one commit away from being monitored. The killer pattern here is **cert-expiry
monitoring**, see below.

## Files
| File | Purpose |
|------|---------|
| `compose.yaml` | Service definition, pinned to `v5.36.0`, with healthcheck + persistent volume. |
| `config/config.yaml` | Declarative endpoints, grouped by `web` / `dns` / `infra`, plus a generic webhook alerting stub. |
| `.env.example` | Template for the alert webhook secret (copy to `.env`). |

## Usage
```bash
cp .env.example .env         # then edit ALERT_WEBHOOK_URL
docker compose up -d
docker compose logs -f gatus # confirm endpoints load
```
The status page is served on `:8080`. Edit `config/config.yaml` and restart to
add or change monitors.

### Cert-expiry monitoring pattern
For any HTTPS endpoint, add a condition on `[CERTIFICATE_EXPIRATION]`:
```yaml
conditions:
  - "[CERTIFICATE_EXPIRATION] > 336h"   # fail with >= 14 days remaining
```
Gatus reads the live TLS certificate on every probe and marks the endpoint
DOWN (and fires the alert) *before* the certificate actually expires. This
converts a class of silent, weekend-ruining outages into a routine ticket with
days of lead time, especially valuable for services whose renewal automation
can quietly break.

### Condition types used here
- **HTTPS**, `[STATUS]`, `[RESPONSE_TIME]`, `[CERTIFICATE_EXPIRATION]`.
- **DNS**, real query via the `dns:` block, asserting on `[DNS_RCODE]`.
- **TCP**, `tcp://host:port` + `[CONNECTED] == true` for ports with no HTTP.

## Integration
Put Gatus behind a reverse proxy and let an SSO/auth middleware protect the
status page rather than exposing `:8080` directly. A common layout is a public
status page (unauthenticated, curated endpoints) plus an internal instance
behind auth for the full infrastructure view. The `custom` alerting provider
posts JSON to any webhook, so it drops straight into a chat app, ntfy, or an
Alertmanager receiver.
