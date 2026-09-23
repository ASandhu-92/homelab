# gatehouse

A small tool I wrote that makes a site public or LAN-only with one command,
by generating Traefik routers on a second entrypoint that only the internet
tunnel reaches.

## What

Traefik gets two HTTPS entrypoints. `websecure` on :443 serves the LAN and
VPN, and every router lives there. `websecure-ext` on :9443 is the only port
the public tunnel forwards to. A site is reachable from the internet if and
only if it has a router on `websecure-ext`.

`reconcile.py` reads every router from Traefik's dynamic config directory,
and for each hostname marked `PUBLIC` in a state file it writes a copy of
that router (same rule, service, middlewares, priority and TLS) onto
`websecure-ext`, into one generated file, `gatehouse.yml`. Traefik's file
watcher applies it in a couple of seconds. The `gatehouse` CLI edits the
state and reconciles:

```
gatehouse list
gatehouse private media.example.com     # gone from the internet, still fine on the LAN
gatehouse public  media.example.com
gatehouse panic                         # hide everything that is not protected
gatehouse restore                       # undo the panic
gatehouse protect remote.example.com    # never hidden by panic
```

## Why

- **The toggle is structural.** Hiding a site is the absence of a router,
  not an IP rule or an auth rule that could be misconfigured. A private site
  answers 404 on the internet path, and nothing about its LAN route changes.
- **No second proxy.** Off-the-shelf tools that do this (Pangolin and
  similar) bring their own proxy and auth. I already had Traefik, Authelia
  and CrowdSec working and did not want to replace them.
- **Instant and reversible.** A change is a file write; the panic button
  hides everything except the protected hosts (the ones my remote access
  depends on) in one command, and `restore` puts it back.
- **Safe to run often.** The reconciler writes a temp file and renames it,
  and only when the content changes, so it can run from a timer every few
  seconds and from the CLI at the same time.

In my lab a web dashboard is the source of truth and a systemd timer runs
`reconcile.py` every 15 seconds; the reconciler asks the dashboard's API
first (`GATEHOUSE_DESIRED_URL`) and falls back to the local state file if the
API is unreachable. This folder is the core without the dashboard.

## Files

| File | Purpose |
|------|---------|
| `reconcile.py` | Reads routers and desired state, writes `gatehouse.yml` atomically (PyYAML needed) |
| `gatehouse` | The CLI: list, public, private, panic, restore, protect, reconcile |
| `traefik-entrypoints.yml` | The two entrypoints for Traefik's static config, and the tunnel side |
| `example/state.json` | Four hosts: two public, one protected, one private |
| `example/dynamic/services.yml` | Example internal routers to copy from, including one host with two routers |
| `test_gatehouse.py` | Tests that run the CLI against a copy of `example/` |
| `POSTMORTEM.md` | The 25-minute ingress outage while adding the second entrypoint, and the rules from it |

## Usage

```bash
# Try it against a copy of the example, nothing touches Traefik
cp -r example /tmp/gh
export GATEHOUSE_DYNAMIC_DIR=/tmp/gh/dynamic GATEHOUSE_STATE=/tmp/gh/state.json
./gatehouse reconcile --dry-run
./gatehouse private media.example.com
cat /tmp/gh/dynamic/gatehouse.yml

# Tests
python3 -m unittest -v test_gatehouse.py
```

For real use, add the `websecure-ext` entrypoint (read `POSTMORTEM.md`
first: check the port is free), point the tunnel at :9443, set
`GATEHOUSE_DYNAMIC_DIR` to Traefik's dynamic directory, and run
`reconcile.py` from a timer or after each CLI change.

The tests pass (6 tests: public hosts get `-ext` routers and private ones do
not, a second run reports unchanged and leaves the file mode 0644, private
then public, panic keeps the protected host and restore undoes it, dry run
writes nothing, a missing state file means everything private).

## Integration

- **Traefik**, the only coupling is the dynamic directory and the entrypoint
  name. `gatehouse.yml` is written 0644 on purpose: another tool of mine that
  reads Traefik's config went silently stale for weeks when this file was
  0600.
- **Tunnel**, every public hostname in the tunnel config points at
  `https://127.0.0.1:9443`. The tunnel only decides which names reach the
  host; gatehouse decides which of those Traefik answers.
- **Limits**, gatehouse only adds or removes the `-ext` router. A LAN-only
  host that has no public DNS record or tunnel entry cannot be made public
  from here; that still needs the DNS record and the tunnel route.
