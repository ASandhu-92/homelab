# crowdsec

CrowdSec reading Traefik's access log, plus a forward-auth bouncer so Traefik
refuses banned IPs before a request reaches any service.

## What

Two containers. The engine tails the Traefik container's log through the
Docker API, parses each request, and runs scenarios over them (HTTP probing,
admin-page scanning, WordPress scans, brute force). When a client trips a
scenario it gets a ban decision. The bouncer is a small web service that
Traefik asks on every request, through a `forwardAuth` middleware: 200 means
let it through, 403 means banned.

## Why

- **One choke point.** Every public request already goes through Traefik, so
  one middleware covers every service, including ones that have no rate
  limiting of their own.
- **Before SSO, not after.** The `crowdsec` middleware runs ahead of the SSO
  middleware on each router, so a banned scanner never gets to hammer the
  login page.
- **Community blocklist.** The engine also pulls the shared CrowdSec
  blocklist, so known-bad IPs are refused before they do anything here.

### Banning your own users

This is the lesson from running it. A media server whose cached artwork had
gone missing answered about 40 image requests per screen with 404. Eleven
404s in a short window is enough for `crowdsecurity/http-probing`, so the
engine banned my own phone and then my home IP, again and again. The tell in
the Traefik access log is a 403 with a 9-byte body and no backend (`"-"`):
that is a middleware answering, not the app.

Unbanning (`cscli decisions delete -i <ip>`) does not fix it; the ban comes
back within seconds while the 404s continue. An IP allowlist does not fix it
either: a phone's mobile IPv6 address changes. What held is a **path-scoped
parser whitelist**: a 404 on the artwork URL pattern is ignored, and every
other 404 from the same client still counts. That file is
`config/parsers/s02-enrich/media-artwork-whitelist.yaml`.

Always test a whitelist with a positive control, not just the happy path.
`cscli explain` on an artwork 404 must say `ignored by whitelist`, and a
`/wp-login.php` 404 must still reach `crowdsecurity/http-probing`. Only the
second result proves the whitelist is narrow.

## Files

| File | Purpose |
|------|---------|
| `compose.yaml` | Engine `v1.8.1` and bouncer `0.5.0` on the proxy network; the bouncer key is registered from the environment |
| `config/acquis.yaml` | Read the `traefik` container's log as Traefik access logs |
| `config/parsers/s02-enrich/media-artwork-whitelist.yaml` | The path-scoped whitelist described above |
| `dynamic/crowdsec.yml` | The Traefik `forwardAuth` middleware; copy into Traefik's `dynamic/` |
| `.env.example` | The shared bouncer key |

## Usage

```bash
cp .env.example .env
$EDITOR .env                        # CROWDSEC_BOUNCER_KEY=$(openssl rand -hex 32)
docker compose up -d
cp dynamic/crowdsec.yml ../traefik/dynamic/
```

Then add `crowdsec@file` in front of the other middlewares on each router.

Useful commands:

```bash
docker exec crowdsec cscli decisions list               # who is banned and why
docker exec crowdsec cscli decisions delete -i <ip>     # lift one ban
docker exec crowdsec cscli metrics                      # lines parsed, buckets, bans
docker exec crowdsec cscli explain --type traefik \
  --log '<one access log line>'                         # which parser and scenario a line hits
```

Tested on Docker with this folder (network renamed for the test): both
containers went healthy, the bouncer key registered on start, the two
`cscli explain` controls gave `ignored by whitelist` for the artwork 404 and
`crowdsecurity/http-probing` for the `/wp-login.php` 404, and the bouncer
answered 200 for a clean IP and 403 after `cscli decisions add` for that IP.
Not tested here: a live Traefik in front, and the community blocklist pull
(it needs a console enrollment).

## Integration

- **Traefik**, must have `--accesslog=true` and the container name
  `traefik` (or change `acquis.yaml`). Both are on the `proxy` network so
  Traefik can reach `crowdsec-bouncer:8080`.
- **Authelia**, put `crowdsec@file` before `authelia@file` in each router's
  middleware list.
- **Restarts**, the parser whitelist is read at start; after editing it run
  `docker restart crowdsec`.
