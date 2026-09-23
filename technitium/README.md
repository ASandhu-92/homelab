# technitium

Technitium DNS Server as the LAN resolver: recursive from the root servers,
DNSSEC validation, blocklists, and a split-brain zone that sends the lab's
service names to the reverse proxy.

## What

Every device on the network uses this server for DNS (the router hands out
its address over DHCP). It resolves public names itself, starting at the root
servers, and validates DNSSEC. It blocks ad and tracker domains from two
Hagezi lists. For the lab domain it answers `example.com` and
`*.example.com` with the reverse proxy's LAN address, so a new service needs
no DNS change: add a proxy route and the name already resolves.

I replaced AdGuard Home with it. The `adguard-home` folder is the older
setup and still works.

## Why

- **Recursive, no forwarders.** The server does its own resolution. Nothing
  upstream sees the full query stream, and there is no forwarder to loop
  back (see below).
- **A Conditional Forwarder zone, not a Primary zone.** This is the part
  worth copying. The zone for the lab domain has forwarder `this-server`.
  Records I define (the apex and wildcard A records) come from the zone.
  Every type I do not define (MX, TXT, `_dmarc`, NS, SOA, `_acme-challenge`)
  falls through to normal recursion and returns the real public record. A
  Primary zone would answer those from its own empty data. That silently
  breaks mail authentication checks, and it breaks the ACME DNS-01
  propagation check, which looks up `_acme-challenge` through the local
  resolver. My old AdGuard rewrite had been doing exactly that, and I only found out
  during the migration.
- **An HTTPS record override.** A public HTTPS (SVCB) record for the domain
  can carry `ipv4hint`/`ipv6hint` values that point browsers at the public
  edge. The zone publishes `HTTPS 1 . alpn="h2"` at the apex and wildcard so
  LAN clients never see those hints.

### The forwarding loop

My router's own resolver forwards everything to this server, and VPN clients
use the router for DNS. If this server were ever set to forward to the router,
queries would go server, router, server, and so on. The symptom is confusing:
lab names keep working (they are answered from the local zone) while public
names time out or SERVFAIL. The rule: the resolver at the end of the chain
must recurse itself or forward to a public resolver, never to anything that
forwards back to it. After any change, check both ends:

```bash
dig @192.0.2.53 cloudflare.com A       # must resolve, with the "ad" flag
dig @192.0.2.1  svc.example.com A      # the router path must return the proxy IP
```

## Files

| File | Purpose |
|------|---------|
| `compose.yaml` | Technitium `15.4.0`, DNS on 53, console on 5380, config volume, `dig` healthcheck |
| `.env.example` | First-start settings: server name, admin password, blocklist URLs; plus the values `split-brain.py` reads |
| `split-brain.py` | Creates the Conditional Forwarder zone and its A and HTTPS records through the HTTP API (stdlib only, `--dry-run` supported) |

## Usage

```bash
cp .env.example .env
$EDITOR .env                  # admin password, LAB_ZONE, PROXY_IP
docker compose up -d
python3 split-brain.py        # creates the zone; safe to re-run
```

Then point DHCP at the server's address. Blocklists load in the background
about a minute after first start.

Health checks I run after a change or a reboot:

```bash
dig @192.0.2.53 svc.example.com A          # proxy IP (local zone)
dig @192.0.2.53 _dmarc.example.com TXT     # the real public record (forwarding path)
dig @192.0.2.53 dnssec-failed.org A        # SERVFAIL (DNSSEC is validating)
dig @192.0.2.53 googlesyndication.com A    # NXDOMAIN (blocklist loaded)
```

Tested on Docker with this folder as-is (published ports removed, dummy
password): the container went healthy, the API reported recursion
`AllowOnlyForPrivateNetworks`, blocking on and no forwarders, the two lists
loaded about 1.06 million blocked domains, and `split-brain.py` produced the
answers above: `foo.example.com` and `example.com` returned the local IP, the
HTTPS record returned `1 . alpn="h2"`, and `_dmarc.example.com TXT` returned
the real public DMARC record.

## Integration

- **Traefik**, the wildcard A record points at the proxy, so every router
  hostname resolves on the LAN. DNS-01 certificates keep working because
  `_acme-challenge` is not shadowed.
- **Router**, if the router runs its own resolver, have it forward to this
  server, and keep this server recursive (the loop above).
- **Monitoring**, have Gatus (see `gatus`) query a lab name through this
  server so a DNS failure pages you. Any monitor that alerts on DNS being
  down needs a second, independent resolver for its own lookups, or it
  cannot resolve the alert webhook.
- After a reboot, the server answers queries about 10 to 15 seconds before
  the blocklists finish loading, so ad domains resolve briefly. Check blocking
  a minute after boot, not immediately.
