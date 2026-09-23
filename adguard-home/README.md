# adguard-home

Network-wide DNS: ad/tracker blocking plus a wildcard rewrite that makes every
service subdomain resolve to the reverse proxy from inside the LAN.

## What

AdGuard Home is the DNS server every device on the network points at (pushed via
DHCP). It filters ads and trackers against blocklists, and, crucially for a
homelab, answers `*.example.com` locally so service hostnames resolve to the
Traefik host without ever leaving the LAN.

## Why

- **Split-horizon DNS, done simply.** A single wildcard rewrite
  (`*.example.com` -> the proxy IP) means you never touch DNS again when adding a
  new service. The public DNS record for a subdomain is irrelevant to LAN
  clients; AdGuard intercepts the query first and returns the internal IP.
- **Blocking at the resolver.** Filtering at DNS covers every device, phones,
  TVs, IoT, with no per-device client. A blocked domain simply never resolves.
- **Own the upstream.** Point AdGuard at an encrypted upstream (DoH/DoT) so
  queries that do leave the network are private from the ISP.

## Files

| File | Purpose |
|------|---------|
| `compose.yaml` | AdGuard Home service (host networking for port 53) |
| `conf/AdGuardHome.yaml` | Created by the setup wizard; holds rewrites + upstreams |
| `work/` | Runtime data: query log, statistics (git-ignored) |

## Usage

```bash
docker compose up -d

# First run only: open the setup wizard and create the admin account.
#   http://<host-ip>:3000    (user: admin)
# After setup the admin UI moves to port 80.
```

Then push AdGuard's IP as the DNS server from your DHCP server (router /
firewall) so every client uses it.

### Wildcard rewrite

In the UI: **Filters > DNS rewrites**, add:

| Domain | Answer |
|--------|--------|
| `*.example.com` | `192.0.2.10` (your reverse-proxy IP) |
| `example.com` | `192.0.2.10` |

Equivalent YAML in `conf/AdGuardHome.yaml`:

```yaml
rewrites:
  - domain: '*.example.com'
    answer: 192.0.2.10
  - domain: example.com
    answer: 192.0.2.10
```

### Encrypted upstreams (DoH / DoT)

Set under **Settings > DNS settings > Upstream DNS servers**:

```
https://dns.quad9.net/dns-query
tls://dns.quad9.net
https://cloudflare-dns.com/dns-query
```

Enable **Use parallel requests** off / **Load balancing** to taste, and turn on
DNSSEC.

Tested on Docker (bridge network instead of host mode, to avoid binding port
53 on the test host): healthy before setup, then the setup API moved the UI
from :3000 to :80. The old healthcheck only probed :3000 and would have gone
unhealthy after setup; it now checks both. Not tested here: serving DNS to a
LAN.

## Integration

- **Traefik**, the wildcard rewrite target is the Traefik host IP. Every router
  hostname (`traefik.example.com`, `auth.example.com`, ...) resolves here to the
  proxy, which then routes by Host header. Deploy Traefik first and use its IP.
- **Split-horizon note**, keep admin-only services as LAN-only: point their
  public DNS at the proxy's private IP (unreachable externally) while the AdGuard
  wildcard still resolves them internally. Only tunnel the services that truly
  need external access.
- **Upstream resolver**, for full recursion + DNSSEC validation, chain AdGuard
  to a local Unbound instance as its upstream instead of a public DoH endpoint.
