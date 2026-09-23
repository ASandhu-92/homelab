# keyvault

A small web page I wrote for adding or rotating one key in a SOPS-encrypted
dotenv file, without the value ever touching a command line, a plain-text
file or a log.

## What

My lab keeps API keys and passwords in one SOPS-encrypted dotenv file
(`secrets.enc.env`, age recipients). Services and scripts decrypt it when they
need a value. Adding a key used to mean decrypting, editing and re-encrypting
by hand, and three times a hand edit left a plain-text line inside the
encrypted file.

keyvault is one Python file (standard library only) that serves a form: key
name, value, "overwrite if it exists". It runs as its own user, reachable only
from the reverse proxy, behind SSO with two-factor. The page shows key names
only, never values.

## Why

The write path, for one key, is the point of the tool:

1. **Decrypt in memory.** `sops -d` runs with its output captured by the
   process; the plain text is never written anywhere.
2. **Edit one line in memory.** Every other line, including comments, stays
   as it was.
3. **Encrypt from stdin.** `sops encrypt --input-type dotenv --output-type
   dotenv --filename-override <store> /dev/stdin`, so the value is passed on
   stdin, never in argv where any user can see it in `ps`.
   `--filename-override` makes sops apply the store's creation rule to the
   stdin input.
4. **Write a new temp file** next to the store, created exclusively
   (`O_EXCL`) with mode 0600, then `fsync`.
5. **Verify before replacing.** Decrypt the temp file and check the whole
   content equals what was intended (all other keys unchanged, key count
   right, the new line encrypted). Any mismatch stops here and the store is
   untouched.
6. **Keep the old version** as `<store>.prev`, then **atomically replace**
   the store with `os.replace` and `fsync` the directory so the rename
   survives a crash.
7. **Decrypt the live store once more**, then **audit**: one line with time,
   SSO user, key name, action (added, overwritten, deleted, or the reason it
   was rejected) and source address. Never the value. A rejected key name is
   logged as `-`, because a wrong entry in the name box is often a pasted
   value.

Around that: a thread lock plus `flock` so two writes cannot interleave, a
rate limit, a strict key name pattern, and one-line printable values only.
Requests must come from the proxy network, carry the `X-Kv-Edge` header that
only the Traefik router adds, and name an allowed SSO user in `Remote-User`.
Writes must be JSON from the page's own origin (a CSRF check on top of the
SSO cookie). The page is served with a nonce-based Content Security Policy.

My running copy also has a reveal button (decrypt one value to the page,
audited by name); I left that out of this version.

## Files

| File | Purpose |
|------|---------|
| `keyvault.py` | The service: the write path above, the HTTP gate, the page |
| `keyvault.service` | systemd unit: own user, read-only filesystem except the store directory, network limited to the proxy's Docker network |
| `env.example` | The `KV_*` settings the unit reads from `/etc/keyvault/env` |
| `traefik-keyvault.yml` | LAN-only router with CrowdSec, Authelia and the edge-marker header |
| `tests/test_keyvault.py` | Tests against the real `sops` binary with a throwaway age key |
| `tests/agekey.py` | Makes that throwaway age key in pure Python, so the tests need no `age-keygen` |

## Usage

```bash
sudo useradd --system --create-home keyvault
sudo install -d -o keyvault -g keyvault -m 750 /srv/secrets    # store + .sops.yaml live here
sudo install -D -m 644 keyvault.py /opt/keyvault/keyvault.py
sudo install -D -m 600 env.example /etc/keyvault/env && sudo $EDITOR /etc/keyvault/env
sudo install -m 644 keyvault.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now keyvault
```

Copy `traefik-keyvault.yml` into Traefik's `dynamic/` with the same random
value in `X-Kv-Edge` as `KV_EDGE_SECRET`, and add an Authelia rule that
requires two-factor for the hostname and allows only your user.

Tests:

```bash
python3 -m unittest discover -s tests -v
```

They pass with sops 3.12.1: add, overwrite (refused without the flag),
delete (refused when absent), the value absent from argv, the service log,
every file in the store directory and the audit line, no temp file left
behind, bad names and multi-line values rejected without logging the input,
and the HTTP gate refusing a missing or wrong edge header, an unknown user, a
foreign origin and a non-JSON body.

## Integration

- **Authelia**, provides `Remote-User`. keyvault trusts that header only
  because the edge marker proves the request came through the SSO router.
- **Restarting Authelia** logs everyone out (its sessions are in memory in my
  setup), so expect a fresh login after one.
- **Reading a secret** from a script: `sops -d --input-type dotenv
  --output-type dotenv secrets.enc.env`, on use, piped straight into the
  consumer. Check a write with `grep -c '^NAME=ENC\[' secrets.enc.env` rather
  than by printing the value.
