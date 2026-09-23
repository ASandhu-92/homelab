# teleport

Teleport as the only way to get a shell on any machine in the lab: one
cluster container (auth + proxy), a node agent on every host, short-lived
certificates instead of SSH keys.

## What

`tsh login` gets a certificate from the cluster after password and a second
factor. `tsh ssh user@node` then connects through the proxy. Every session is
recorded and every login is in the audit log. The cluster runs in Docker on
the main host; every other machine (hypervisors, workstations, a game
console) runs the node agent as a systemd service and registers with the
auth service.

## Why Teleport instead of SSH keys

- **Certificates expire.** A login gives a certificate valid for hours, not a
  key that works until someone remembers to remove it from
  `authorized_keys` on every host. A laptop that gets lost stops working on
  its own.
- **One place to see everything.** Who logged in, where, when, and a
  recording of what they typed. With keys, that is scattered across every
  host's auth log.
- **Second factor on every login**, enforced by the cluster
  (`cap.yaml`), not by each host's sshd config.
- **Roles, not key copies.** Access is granted by role and node labels
  (`env=lab`, `agent-access=true`). An automation account gets a role that
  reaches only the nodes it needs.

The rule I hold myself and my automation to: remote access is `tsh` only.
No plain `ssh` fallback, no password-over-stdin helpers, no raw keys copied
around. If `tsh` fails, stop and fix Teleport; a fallback path that works
"just this once" is the one that ends up unaudited forever.

### The LAN node gotcha

Nodes on the LAN register with `auth_server: <host>:3025`, the auth port
published straight from the container. They do not use
`proxy_server: tp.example.com:443`. The public name goes through Traefik,
which terminates TLS; the node's reverse-tunnel connection needs Teleport's
own TLS and ALPN handshake, so it fails with
`ssh: handshake failed` when it goes through the proxy on 443.

## Files

| File | Purpose |
|------|---------|
| `compose.yaml` | Cluster container, distroless `18.11.0`, ports 3080 (web), 3023 (SSH proxy), 3025 (auth) |
| `teleport.yaml.example` | Cluster config: auth + proxy + the host's own SSH service |
| `cap.yaml` | Cluster auth preference requiring OTP or WebAuthn as a second factor |
| `node/teleport.yaml.example` | Node agent config: direct auth server, join token from a file, CA pin |
| `node/teleport.service` | systemd unit for a tarball install (which ships none) |

## Usage

Cluster:

```bash
cp teleport.yaml.example teleport.yaml && $EDITOR teleport.yaml
docker compose up -d
docker exec -i teleport tctl create -f < cap.yaml     # stdin: distroless, no host files inside
docker exec teleport tctl users add admin --roles=editor,access --logins=root
```

Route `tp.example.com` through Traefik to port 3080.

Each node:

```bash
docker exec teleport tctl tokens add --type=node --ttl=1h    # on the cluster host
docker exec teleport tctl status                             # note the CA pin

# on the node (tarball install from the Teleport download page)
sudo ./install
sudo install -m 600 /dev/stdin /var/lib/teleport/join-token <<< '<token>'
sudo cp node/teleport.yaml.example /etc/teleport.yaml && sudo $EDITOR /etc/teleport.yaml
sudo cp node/teleport.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now teleport
```

Tested on Docker (published ports removed): the cluster came up
(`tctl status` shows cluster `lab`, version 18.11.0), `cap.yaml` applied and
`tctl get cap` shows `second_factors: [otp, webauthn]`, and a second
container started from `node/teleport.yaml.example` (with the real CA pin,
`auth_server` pointed at the cluster and a join token in the token file)
registered and was listed by `tctl nodes ls` with its labels. Not tested
here: logins through the public name and Traefik, and the systemd unit.

## Integration

- **Traefik**, routes the public name to the web port 3080. Nodes skip
  Traefik entirely (port 3025).
- **Careful with the chain**, if tsh, your web UI and your automation all
  reach Teleport through the same reverse proxy, a broken proxy locks you out
  of the tool you would use to fix it. Keep a console path to the host that
  does not depend on it (see `gatehouse/POSTMORTEM.md`).
- **Tokens**, node join tokens are single-purpose and short-lived; the file
  is only needed for the first join and can be deleted afterwards.
