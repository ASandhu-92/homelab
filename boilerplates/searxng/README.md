# SearXNG: Private Metasearch

## What
A self-hosted metasearch engine that aggregates results from ~200 upstream
engines (web, images, news, code, science) behind one privacy-respecting
front end. No user tracking, no profiling, no ads. Valkey backs the rate
limiter and result cache.

## Why
Two payoffs. For humans: a single search box that queries many engines while
leaking nothing about you. For automation: a **free, self-hosted search API**
you fully control, which is the reason it's in this portfolio (see below).

## Files
| File | Purpose |
|------|---------|
| `compose.yaml` | SearXNG (date-pinned) + Valkey (`9-alpine`), dropped capabilities, healthchecks. |
| `settings/settings.yml` | Enables the JSON output format and the Valkey-backed limiter. |
| `.env.example` | Base URL + signing secret (copy to `.env`). |

## Usage
```bash
cp .env.example .env
openssl rand -hex 32        # paste into SEARXNG_SECRET
docker compose up -d
```
Human UI on `:8080`. JSON query:
```bash
curl 'http://localhost:8080/search?q=example+query&format=json'
```

### Self-hosted search as an LLM-agent tool
Paid search APIs meter every query and bill per call, which gets expensive
fast when an autonomous agent fans out dozens of searches per task. Pointing
agents at a local SearXNG instead gives them **unmetered, zero-marginal-cost
web discovery**: the agent hits `/search?q=...&format=json`, parses the
structured results, and fetches the promising URLs, no API key, no
per-query charge, no rate-limit surprises from a vendor. This is the pattern
this boilerplate is built around: SearXNG becomes the "search" tool in an
agent's toolbelt, reserving paid/premium search only for the rare cases that
need judgment-grade ranking. Enabling `format: json` in `settings.yml` is
what makes this work.

## Integration
Front SearXNG with a reverse proxy for TLS. For a purely internal agent tool,
you can keep it on the private network with no public exposure at all. If you do
expose the human UI publicly, put an auth/SSO middleware in front and keep the
JSON endpoint reachable only from your agent hosts (e.g. an allowlist at the
proxy) so it isn't abused as an open search relay. The `limiter: true` +
Valkey combo throttles per-client bursts.
