# homelab-boilerplates

> Production-tested self-hosted infrastructure templates for a Docker homelab.

## What this is

Nine deployment templates distilled from a real, long-running homelab. Every
template here has run in production: reverse proxying, single sign-on,
network-wide DNS, uptime monitoring, backups, workflow automation, private
search, a browser IDE, and home automation.

Nothing in this repo contains real hostnames, IPs, domains, or secrets. Every
example uses placeholder values (`example.com`, TEST-NET `192.0.2.0/24`,
`admin@example.com`) so the templates can be lifted directly into your own
environment and customized.

## Services

| Service | What it does |
|---------|--------------|
| `traefik` | Reverse proxy, TLS termination, Let's Encrypt DNS-01, Authelia middleware chain |
| `authelia` | Single sign-on + TOTP 2FA forward-auth portal |
| `adguard-home` | Network-wide DNS, ad/tracker blocking, wildcard rewrite for LAN service resolution |
| `gatus` | Uptime and health monitoring with alerting |
| `kopia` | Encrypted, deduplicated backups with retention policies |
| `n8n` | Self-hosted workflow automation |
| `searxng` | Private metasearch engine |
| `code-server` | Browser-based VS Code development environment |
| `home-assistant` | Home automation hub |

Each service directory is self-contained: a valid `compose.yaml`, an
`.env.example`, supporting config, and a README following a
What / Why / Files / Usage / Integration structure.

## Placeholder convention

Every domain is `example.com`, every LAN address is inside the TEST-NET-1
range `192.0.2.0/24`, and every host name is generic (`hv-1`, `hv-2`,
`workstation-a`). Secret-shaped values in `.env.example` files are either
empty or an obvious short placeholder such as `CHANGE_ME`, never a
real-looking value, so a leak scanner never has to guess what is a
placeholder and what is real. Copy `.env.example` to `.env`, fill in your own
values, and `.env` stays out of git (see `.gitignore`).

## CI leak scanning

`.github/workflows/leak-scan.yml` runs gitleaks on every push and pull
request, using `.gitleaks.toml` plus the built-in ruleset. It also supports an
optional `GITLEAKS_PRIVATE_CONFIG` repository secret for a stricter, private
ruleset that never has to be disclosed in this public repo.

## Quickstart

```bash
# 1. Pick a service
cd boilerplates/traefik

# 2. Copy and fill in the environment template
cp .env.example .env
$EDITOR .env            # set your domain + Cloudflare API token

# 3. Review the compose file and adjust volumes/ports for your host
$EDITOR compose.yaml

# 4. Bring it up
docker compose up -d

# 5. Check logs
docker compose logs -f
```

Deploy `traefik` and `authelia` first, most other services route through
them. Read each service README before deploying; the Integration section
explains how the pieces connect.

## A note on how these were made

Templates drafted with Claude Code from stacks I run, reviewed and maintained
by me.

## License

MIT. See [LICENSE](./LICENSE). Templates are provided as-is; review and adapt
security-sensitive settings for your own threat model before production use.
