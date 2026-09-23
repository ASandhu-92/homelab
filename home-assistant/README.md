# Home Assistant: Home Automation Hub

## What
Home Assistant (Container install), a local-first automation platform that
unifies thousands of smart-home devices and services behind one API, dashboard,
and automation engine, with state and control kept on your own hardware.

## Why
Local-first control means automations keep working when the internet (or a
vendor's cloud) is down, and device data never leaves the house. The Container
image is the right fit when you already run Docker and want HA as one service in
a larger stack rather than a dedicated appliance OS.

## Files
| File | Purpose |
|------|---------|
| `compose.yaml` | HA (`2026.9.2`) on host networking, config volume, healthcheck. |
| `.env.example` | Timezone + optional long-lived token for AI/MCP integration. |

## Usage
```bash
cp .env.example .env
docker compose up -d
```
First boot takes a minute; then open `http://<host>:8123` and complete onboarding.

### Why host network mode
HA is configured with `network_mode: host`. Device discovery, mDNS/Zeroconf
(Chromecast, HomeKit, printers), SSDP/DLNA, and DHCP-based discovery, depends on
broadcast and multicast traffic that a bridged Docker network silently drops.
On host networking HA shares the host's network stack, sees those packets, and
listens directly on the host's `:8123` (so there is no `ports:` mapping, host
mode ignores it). The trade-offs: the container isn't network-isolated and the
port can't be remapped. For a trusted home hub whose entire job is to talk to
LAN devices, that's the accepted and recommended configuration.

### Exposing HA to AI assistants (MCP / REST)
Home Assistant exposes a full **REST API** (and, in recent versions, a native
**MCP server**) that lets an AI assistant read device state and call services, 
"is the garage door open?", "set the thermostat to 21C". The integration
pattern, genericized:

1. In the HA UI, create a **long-lived access token**
   (*Profile -> Security -> Long-Lived Access Tokens*). This is a scoped API
   credential, not your login password.
2. Store it in an **env file / secret manager** as `HA_TOKEN` (see
   `.env.example`), never in code or git, and rotate it periodically.
3. An external MCP or REST client authenticates with
   `Authorization: Bearer $HA_TOKEN` against `$HA_URL`, e.g.
   `GET /api/states` to read entities or `POST /api/services/<domain>/<service>`
   to act. The AI assistant then talks to *that client*, so the token stays on
   the server side and is never handed to the model.

Security posture for this: keep HA on the private network, put any external
exposure behind a reverse proxy + auth/SSO, treat the token as a high-value
secret (rotate on schedule, revoke instantly if leaked), and expose only the
entities the assistant actually needs.

Tested on Docker with a bridge network instead of host mode and `privileged`
off (both changed only for the test): healthy, `manifest.json` returned 200.
Not tested here: device discovery, which is the reason for host mode.

## Integration
Because HA owns the host's `:8123`, route your HA hostname at the reverse proxy
to `http://<host>:8123` and terminate TLS there. Add an auth/SSO middleware for
any access from outside the LAN. Back up the `./config` directory, it contains
the database, automations, and the tokens, and is the entire recoverable state
of the instance.
