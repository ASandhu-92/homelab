# homelab

[![validate](https://github.com/ASandhu-92/homelab/actions/workflows/validate.yml/badge.svg)](https://github.com/ASandhu-92/homelab/actions/workflows/validate.yml)
[![leak-scan](https://github.com/ASandhu-92/homelab/actions/workflows/leak-scan.yml/badge.svg)](https://github.com/ASandhu-92/homelab/actions/workflows/leak-scan.yml)

Configs from the homelab I run at home: two Proxmox hosts, a handful of
Docker hosts, and the services on them. One folder per service. Real names,
addresses and secrets are replaced with placeholders, so each folder can be
copied and adapted. The READMEs say what I ran to test each one and what I
did not.

## Index

| Folder | What it is | Tested here |
|--------|------------|-------------|
| **Ingress and access** | | |
| [traefik](traefik/) | Reverse proxy, Let's Encrypt DNS-01 certificates, read-only Docker socket proxy | started, healthy |
| [authelia](authelia/) | Single sign-on and two-factor login in front of the proxy | started, healthy |
| [gatehouse](gatehouse/) | My tool: make a site public or LAN-only by generating Traefik routers on a second entrypoint, plus a postmortem | unit tests |
| [teleport](teleport/) | Certificate-based SSH for every machine, instead of SSH keys | cluster up, node joined |
| **Security** | | |
| [crowdsec](crowdsec/) | Bans abusive IPs from Traefik's access log; the lesson about banning your own users | started, bans enforced |
| [keyvault](keyvault/) | My tool: add or rotate a key in a SOPS-encrypted file without the value touching disk, argv or logs | tests with real sops |
| **DNS and network** | | |
| [technitium](technitium/) | Recursive DNS with blocklists and a split-brain zone for the lab domain | started, zone answers checked |
| [adguard-home](adguard-home/) | The DNS server I used before Technitium | started, healthy after setup |
| [netbird](netbird/) | Self-hosted WireGuard mesh VPN with its own identity provider | started, API answering |
| **Monitoring and backup** | | |
| [gatus](gatus/) | Uptime checks and status page, config in one YAML file | started, responding |
| [kopia](kopia/) | Encrypted, deduplicated backups with a web UI | started, healthy after repo create |
| **Automation and AI** | | |
| [n8n](n8n/) | Workflow automation on Postgres | started, responding |
| [local-ai](local-ai/) | Ollama models behind a LiteLLM gateway with a cache, and a search-grounded chat UI | started, chat through the gateway |
| [searxng](searxng/) | Private metasearch, with a JSON API for the AI tools | started, JSON search answered |
| **Apps** | | |
| [code-server](code-server/) | VS Code in the browser, auth left to the proxy | started, healthy |
| [home-assistant](home-assistant/) | Home automation | started, healthy (bridge network in the test) |
| **Proxmox** | | |
| [proxmox](proxmox/) | Unprivileged LXCs with Docker, shared bind mounts with ACLs, VM settings | notes only |
| [arcane](arcane/) | Web UI for Docker and compose across all the hosts, with edge agents | manager started, healthy |

"Tested here" means I started the folder's compose file on a test Docker
host with the published ports removed and dummy secrets, and checked the
result named in the column. Each README has the details and the gaps.

## Placeholders

| Placeholder | Stands for |
|-------------|------------|
| `example.com`, `*.example.com` | the lab domain |
| `192.0.2.0/24` | LAN addresses (TEST-NET-1, never routed) |
| `hv-1`, `hv-2` | Proxmox hosts |
| `workstation-a` | a desktop machine |
| `/srv/...` | host paths |
| empty value or `CHANGE_ME` in `.env.example` | a secret you generate |

## Using a folder

```bash
cd traefik
cp .env.example .env        # fill in; .env is git-ignored
$EDITOR compose.yaml        # adjust ports, paths, networks for your host
docker compose up -d
docker compose logs -f
```

Start with `traefik` and `authelia`; most other folders assume a `proxy`
network and route through them. Each README has What, Why, Files, Usage and
Integration sections.

## CI

- **validate** (`.github/workflows/validate.yml`): `scripts/validate.sh` runs
  `docker compose config` on every compose file with its `.env.example`;
  a Trivy scan of the repo files (secrets and misconfiguration) that fails on
  HIGH or CRITICAL; and a Trivy scan of every pinned image as a report only,
  so upstream CVEs do not fail the build.
- **leak-scan** (`.github/workflows/leak-scan.yml`): gitleaks over the full
  history with `.gitleaks.toml`, plus a private ruleset from a repository
  secret when present.

Run the compose check locally with `./scripts/validate.sh`.

## Credit

Written and tested with Claude Code from the stacks I run; reviewed and
maintained by me.

## License

MIT. See [LICENSE](LICENSE).
