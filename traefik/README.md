# traefik

Traefik v3 reverse proxy with automatic TLS and an Authelia SSO middleware chain.

## What

A single ingress point for every service on the network. Traefik listens on
ports 80/443, redirects HTTP to HTTPS, terminates TLS with Let's Encrypt
certificates, and routes each request to the right backend based on its
hostname. Authentication is enforced in front of protected services via a
forward-auth middleware to Authelia.

## Why

- **DNS-01 over HTTP-01.** Certificates are obtained through Cloudflare's API
  by proving control of DNS, not by exposing port 80 to the internet. This is
  the only ACME method that works behind CGNAT / with no inbound port-forward,
  and it supports wildcard certs.
- **Socket proxy, not raw socket.** Traefik needs to read container labels but
  never needs to *write* to Docker. A `docker-socket-proxy` sidecar exposes a
  read-only subset of the Docker API on an internal network, so a compromised
  Traefik cannot start/stop/exec containers on the host.
- **File provider for shared config.** Middlewares that many services reuse
  (auth, security headers, rate limiting) live in `dynamic/` as file config
  rather than being repeated across dozens of container labels.

## Files

| File | Purpose |
|------|---------|
| `compose.yaml` | Traefik + docker-socket-proxy services |
| `dynamic/middlewares.yml` | Authelia forward-auth, security headers, rate limit |
| `.env.example` | Domain, ACME email, Cloudflare token template |
| `letsencrypt/acme.json` | Cert storage (auto-created; chmod 600; git-ignored) |

## Usage

```bash
cp .env.example .env
$EDITOR .env                      # DOMAIN, ACME_EMAIL, CF_DNS_API_TOKEN

# acme.json must exist and be private before first start
touch letsencrypt/acme.json && chmod 600 letsencrypt/acme.json

docker compose up -d
docker compose logs -f traefik    # watch the first cert get issued
```

The dashboard is served at `https://traefik.<your-domain>` behind Authelia.

### Exposing a service

Add labels to any container on the `proxy` network:

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.myapp.rule=Host(`myapp.example.com`)"
  - "traefik.http.routers.myapp.entrypoints=websecure"
  - "traefik.http.routers.myapp.tls.certresolver=letsencrypt"
  - "traefik.http.routers.myapp.middlewares=secured@file"
```

Or define it as file config in `dynamic/` for backends that are not Docker
containers (a service on another host, a VM, etc.).

Tested on Docker (published ports removed): both containers went healthy; the
Traefik `/ping` endpoint answered `OK` and the socket proxy answered
`/version`. Fixed during that test: the socket-proxy tag is `v0.5.0` (there is
no `0.5.0` tag), and the healthcheck needed `--ping=true`. Not tested here:
certificate issuance (it needs a real domain and DNS token).

## Integration

- **Authelia**, the `authelia@file` middleware (and the `secured@file` chain
  that includes it) forward-auths to the Authelia container. Deploy the
  `authelia` folder on the same `proxy` network first. The middleware
  chain runs auth -> security headers -> rate limit, in that order.
- **AdGuard Home**, a wildcard DNS rewrite (`*.example.com` -> this proxy's IP)
  makes every router hostname resolve to Traefik from inside the LAN. See the
  `adguard-home` folder.
- **Public services**, front external access with a tunnel (for example a
  cloud tunnel provider) pointing at port 443; DNS-01 certs remain valid
  regardless of the ingress path.
