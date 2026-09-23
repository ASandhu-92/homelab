# netbird

Self-hosted NetBird mesh VPN, the all-in-one setup: one combined server
container with the embedded identity provider, plus the dashboard, behind
Traefik.

## What

NetBird builds a WireGuard mesh between your devices. The self-hosted server
does three jobs: management (who is allowed to talk to whom), signal (helps
peers find each other) and relay (carries traffic when a direct connection is
impossible). The combined image runs all three on one HTTP port, and adds an
embedded OIDC identity provider, so there is no separate Zitadel, Keycloak or
Authelia integration to maintain. Users, passwords and TOTP live in the
server's own SQLite store.

I use it for remote access to the LAN from a phone and laptops, in place of
exposing services to the internet.

## Why

- **One container, one port.** Management, signal, relay and the IdP are all
  behind `:80` in the container, path-routed by Traefik. Fewer moving parts
  than the older multi-container layout.
- **Embedded IdP.** For a single household, a separate identity stack is more
  to break than it is worth. The embedded one supports TOTP.
- **gRPC needs h2c.** The management and signal APIs are gRPC. Traefik must
  forward those paths as HTTP/2 cleartext (`h2c://`), which is why
  `traefik/netbird.yml` has a separate service for them.

### Lessons

- **Tunnels can block the control plane.** When I first published NetBird
  through a cloud tunnel, the web dashboard and relay worked from outside,
  but the gRPC management calls got HTTP 403 at the tunnel edge. Peers on
  Wi-Fi at home worked (they took the LAN path) and peers on cellular never
  connected. The fix was a direct path: a DNS-only hostname, a port forward
  on the router to Traefik on a dedicated entrypoint that serves only the
  NetBird routers, and `exposedAddress` set to that URL.
- **Switching authenticator apps.** Turning MFA off in the dashboard only
  stops requiring it; the enrolled TOTP secret stays in the IdP database, so
  enrolling a new app keeps validating against the old one. To really reset
  it: stop the server, back up `idp.db`, clear the user's stored MFA secret
  in that database, start the server, enroll again. There is no `sqlite3`
  binary in the image; use Python's `sqlite3` module from the host.
- **Back up the volume.** `netbird-data` holds `store.db` (peers, accounts,
  policies) and `idp.db` (users, password hashes, MFA). Losing `idp.db` loses
  every login.

## Files

| File | Purpose |
|------|---------|
| `compose.yaml` | Combined server `0.79.0` and dashboard `v2.92.0`, both bound to one LAN address for Traefik |
| `config.yaml.example` | Server config: public URL, embedded IdP issuer and redirect URIs, trusted proxy, SQLite store |
| `setup-secrets.sh` | Writes `config.yaml` with a random relay secret and store encryption key (mode 600, refuses to overwrite) |
| `.env.example` | Public hostname and bind address |
| `traefik/netbird.yml` | The three path-based Traefik routers (gRPC as h2c, REST and IdP, dashboard) |

## Usage

```bash
cp .env.example .env && $EDITOR .env
./setup-secrets.sh
$EDITOR config.yaml             # exposedAddress, issuer, redirect URIs, trusted proxy
docker compose up -d
cp traefik/netbird.yml ../traefik/dynamic/   # edit the hostname and backend IP
```

Open `https://<NB_DOMAIN>` and create the first user. Clients connect with
`netbird up --management-url https://<NB_DOMAIN>`.

Tested on Docker (published ports removed, `example.com` config from
`setup-secrets.sh`): both containers started, the dashboard went healthy and
served its page, the server's OIDC discovery document returned 200 with issuer
`https://nb.example.com/oauth2`, and the REST API answered 401 without a token.
Not tested here: a real peer joining, relay traffic, and the health port 9000,
which refused connections in one run and returned 404 at `/` in another.

## Integration

- **Traefik**, one hostname, three routers by path. If peers connect from
  outside, see the tunnel lesson above.
- **DNS**, give NetBird a nameserver group pointing at your LAN resolver
  (see `technitium`) so remote peers resolve lab names. If the resolver
  restricts recursion to private networks, add the NetBird range
  (`100.64.0.0/10`) to its allowed networks or remote peers get REFUSED for
  public names.
- **Monitoring**, probe the OIDC discovery URL for a 200.
