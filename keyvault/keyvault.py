#!/usr/bin/env python3
"""keyvault: a small web page for adding or rotating one key in a SOPS dotenv store.

Python 3.12+, standard library only, plus the `sops` binary. Meant to run as an
unprivileged service user, bound to an address only the reverse proxy can
reach, behind forward-auth SSO.

The write path, for one key:
  1. decrypt the store in memory (sops -d, output captured, never written out)
  2. change one line in memory
  3. encrypt from stdin (sops encrypt ... /dev/stdin) into a new temp file,
     created with O_EXCL and mode 0600, then fsync
  4. decrypt the temp file and check the whole result equals what we meant
     to write (every other key unchanged, key count right)
  5. keep the current ciphertext as <store>.prev
  6. os.replace the temp file over the store, fsync the directory
  7. decrypt the live store once more, then write one audit line

The value never appears in argv (it goes through stdin), on disk in plain
text, in the audit log, or in the service log. The audit log records
timestamp, user, key name, action and source address.

Settings (environment):
  KV_STORE          path of the encrypted dotenv store   (/srv/secrets/secrets.enc.env)
  KV_SOPS_CONFIG    .sops.yaml with the creation rule   (/srv/secrets/.sops.yaml)
  KV_SOPS           sops binary                         (sops)
  KV_AUDIT          audit log file                      (/var/log/keyvault/keyvault.log)
  KV_BIND           host:port                           (127.0.0.1:8094)
  KV_TRUSTED_NETS   comma-separated source networks     (127.0.0.0/8)
  KV_ALLOWED_USERS  comma-separated SSO user names allowed to write
  KV_ORIGIN         the page's exact origin, for the CSRF check (https://kv.example.com)
  KV_EDGE_SECRET    value the proxy puts in X-Kv-Edge; empty = refuse everything
"""
import fcntl
import hmac
import http.server
import ipaddress
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
# Key names from the ciphertext: NAME=ENC[...] (or NAME= for an empty value).
ENC_NAME_RE = re.compile(r"^([^=#\s]+)=(?:ENC\[|$)")
MAX_VALUE = 4096
MAX_BODY = 8192
RATE_N, RATE_WINDOW = 20, 600          # writes per window, per process


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg):
    print(f"{now_iso()} {msg}", flush=True)


def redact(text, values):
    """Replace every value (raw and JSON-escaped) in text with ***."""
    for v in values:
        if v:
            for form in {v, json.dumps(v)[1:-1]}:
                text = text.replace(form, "***")
    return text


def parse_dotenv(text):
    """Plain dotenv -> (lines, {name: value}, number of key lines)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    kv, n = {}, 0
    for line in lines:
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep:
            kv[name] = value
            n += 1
    return lines, kv, n


def clean_value(raw):
    """-> (value, None) or (None, reason)."""
    if not isinstance(raw, str):
        return None, "type"
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    if not v:
        return None, "empty"
    if len(v) > MAX_VALUE:
        return None, "toolong"
    if "\r" in v or "\n" in v or not v.isprintable():
        return None, "unprintable"
    return v, None


class Vault:
    def __init__(self, store, sops_config, audit, sops="sops"):
        self.store, self.sops_config, self.audit, self.sops = store, sops_config, audit, sops
        self.dir = os.path.dirname(os.path.abspath(store))
        self.lock_path = os.path.join(self.dir, ".keyvault.lock")
        self._lock = threading.Lock()
        self._writes = deque()

    # ---- helpers -------------------------------------------------------
    def _run_sops(self, args, stdin=None):
        return subprocess.run([self.sops, "--config", self.sops_config, *args],
                              input=stdin, capture_output=True, check=False)

    def _decrypt(self, path):
        r = self._run_sops(["-d", "--input-type", "dotenv", "--output-type", "dotenv", path])
        return r.returncode, r.stdout, r.stderr.decode("utf-8", "replace")

    def _audit(self, user, key, action, src):
        line = f"{now_iso()} {user} {key} {action} {src}"
        try:
            fd = os.open(self.audit, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
            try:
                os.write(fd, (line + "\n").encode())
            finally:
                os.close(fd)
        except OSError as e:
            log(f"audit-write-failed {type(e).__name__}")
        log(f"audit {line}")

    def _rate_ok(self):
        t = time.monotonic()
        while self._writes and t - self._writes[0] > RATE_WINDOW:
            self._writes.popleft()
        if len(self._writes) >= RATE_N:
            return False
        self._writes.append(t)
        return True

    @staticmethod
    def _write_new(path, data, mode):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

    # ---- public API ----------------------------------------------------
    def list_keys(self):
        """Key names only, read from the ciphertext (no decryption)."""
        names = []
        with open(self.store, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = ENC_NAME_RE.match(line.rstrip("\r\n"))
                if m and not m.group(1).startswith("sops_"):
                    names.append(m.group(1))
        return names

    def set_key(self, user, key, value, overwrite, src):
        """Add or overwrite one key. -> (http status, dict). Never raises, never logs the value."""
        if not self._rate_ok():
            self._audit(user, "-", "rejected-rate", src)
            return 429, {"ok": False, "error": "rate limited"}
        if not isinstance(key, str) or not KEY_RE.match(key):
            # the raw input might be a pasted value, so it is not logged
            self._audit(user, "-", "rejected-badkey", src)
            return 422, {"ok": False, "error": "bad key name"}
        value, reason = clean_value(value)
        if reason:
            self._audit(user, key, f"rejected-value-{reason}", src)
            return 422, {"ok": False, "error": f"bad value ({reason})"}
        if not isinstance(overwrite, bool):
            return 422, {"ok": False, "error": "overwrite must be true or false"}
        return self._locked(user, key, src, lambda tmps: self._set(user, key, value, overwrite, src, tmps))

    def unset_key(self, user, key, src):
        if not self._rate_ok():
            self._audit(user, "-", "rejected-rate", src)
            return 429, {"ok": False, "error": "rate limited"}
        if not isinstance(key, str) or not KEY_RE.match(key):
            self._audit(user, "-", "rejected-badkey", src)
            return 422, {"ok": False, "error": "bad key name"}
        return self._locked(user, key, src, lambda tmps: self._unset(user, key, src, tmps))

    # ---- write path ----------------------------------------------------
    def _locked(self, user, key, src, fn):
        """Run fn under a thread lock and an flock; any exception -> 500, temp files removed."""
        tmps = []
        try:
            with self._lock:
                lf = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
                try:
                    fcntl.flock(lf, fcntl.LOCK_EX)
                    return fn(tmps)
                finally:
                    os.close(lf)
        except Exception as e:  # noqa: BLE001 - a traceback could carry the value
            log(f"write-failed {type(e).__name__}")
            self._audit(user, key, "failed-exception", src)
            return 500, {"ok": False, "error": "write failed"}
        finally:
            for p in tmps:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def _set(self, user, key, value, overwrite, src, tmps):
        rc, plain, err = self._decrypt(self.store)
        if rc != 0:
            log(f"decrypt-failed rc={rc} {redact(err, [value]).strip()}")
            self._audit(user, key, "failed-decrypt", src)
            return 500, {"ok": False, "error": "write failed"}
        lines, kv, n = parse_dotenv(plain.decode())
        existed = key in kv
        if existed and not overwrite:
            self._audit(user, key, "rejected-exists", src)
            return 409, {"ok": False, "error": "exists"}
        line = f"{key}={value}"
        if existed:
            new_lines = [line if (not l.startswith("#") and l.partition("=")[0] == key) else l for l in lines]
        else:
            new_lines = lines + [line]
        expected = dict(kv, **{key: value})
        return self._commit(user, key, new_lines, expected, n + (0 if existed else 1),
                            "overwritten" if existed else "added", src, tmps, value)

    def _unset(self, user, key, src, tmps):
        rc, plain, err = self._decrypt(self.store)
        if rc != 0:
            log(f"decrypt-failed rc={rc} {err.strip()}")
            self._audit(user, key, "failed-decrypt", src)
            return 500, {"ok": False, "error": "write failed"}
        lines, kv, n = parse_dotenv(plain.decode())
        if key not in kv:
            self._audit(user, key, "rejected-absent", src)
            return 409, {"ok": False, "error": "absent"}
        new_lines = [l for l in lines if l.startswith("#") or l.partition("=")[0] != key]
        expected = {k: v for k, v in kv.items() if k != key}
        return self._commit(user, key, new_lines, expected, n - 1, "deleted", src, tmps, "")

    def _commit(self, user, key, new_lines, expected, n_expected, action, src, tmps, value):
        fail = (500, {"ok": False, "error": "write failed"})
        scrub = [value, *expected.values()]
        plain = ("\n".join(new_lines) + "\n").encode()

        # 3. encrypt from stdin into a fresh temp file next to the store
        tmp = os.path.join(self.dir, f".kvtmp.{secrets.token_hex(4)}.{os.path.basename(self.store)}")
        tmps.append(tmp)
        r = self._run_sops(["encrypt", "--input-type", "dotenv", "--output-type", "dotenv",
                            "--filename-override", self.store, "/dev/stdin"], stdin=plain)
        if r.returncode != 0 or not r.stdout:
            log(f"encrypt-failed rc={r.returncode} {redact(r.stderr.decode('utf-8', 'replace'), scrub).strip()}")
            self._audit(user, key, "failed-encrypt", src)
            return fail
        self._write_new(tmp, r.stdout, 0o600)

        # 4. verify: decrypts, content equal to what we meant, key line encrypted, count right
        rc, plain2, err = self._decrypt(tmp)
        if rc != 0:
            log(f"verify-decrypt-failed rc={rc} {redact(err, scrub).strip()}")
            self._audit(user, key, "failed-verify", src)
            return fail
        _, kv2, n2 = parse_dotenv(plain2.decode())
        enc_line = any(l.startswith(f"{key}=ENC[") for l in r.stdout.decode().split("\n"))
        if kv2 != expected or n2 != n_expected or enc_line != (key in expected):
            log(f"verify-mismatch equal={kv2 == expected} count={n2}/{n_expected} enc_line={enc_line}")
            self._audit(user, key, "failed-verify", src)
            return fail
        os.chmod(tmp, 0o640)

        # 5. keep the current ciphertext as .prev
        prev_tmp = os.path.join(self.dir, f".kvprev.{secrets.token_hex(4)}.{os.path.basename(self.store)}")
        tmps.append(prev_tmp)
        with open(self.store, "rb") as f:
            self._write_new(prev_tmp, f.read(), 0o600)
        os.replace(prev_tmp, self.store + ".prev")

        # 6. atomic replace, then fsync the directory so the rename is durable
        os.replace(tmp, self.store)
        dfd = os.open(self.dir, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)

        # 7. the live store must still decrypt; then audit
        rc, plain3, err = self._decrypt(self.store)
        if rc != 0:
            log(f"final-decrypt-failed rc={rc} {redact(err, scrub).strip()}")
            self._audit(user, key, "failed-final", src)
            return 500, {"ok": False, "error": "write failed after replace; restore from .prev"}
        self._audit(user, key, action, src)
        return 200, {"ok": True, "key": key, "action": action, "n_keys": parse_dotenv(plain3.decode())[2]}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>keyvault</title>
<style nonce="__NONCE__">
body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem;background:#faf7f2;color:#2b2a28}
input,button{font:inherit;padding:.4rem .6rem;margin:.2rem 0;width:100%;box-sizing:border-box}
button{width:auto;cursor:pointer}#out{margin-top:1rem;font-family:monospace}li{font-family:monospace}
@media (prefers-color-scheme:dark){body{background:#1f1e1c;color:#ece8e1}}
</style></head><body>
<h1>keyvault</h1>
<p>Add or rotate one key. The value is encrypted into the store and never shown again.</p>
<label>Key name <input id="k" autocomplete="off" placeholder="SERVICE_API_KEY"></label>
<label>Value <input id="v" type="password" autocomplete="off"></label>
<label><input id="o" type="checkbox" style="width:auto"> overwrite if it exists</label>
<button id="save">Save</button>
<div id="out"></div>
<h2>Keys in the store</h2><ul id="keys"></ul>
<script nonce="__NONCE__">
const out=document.getElementById('out');
async function keys(){const r=await fetch('/api/keys');const d=await r.json();
 const ul=document.getElementById('keys');ul.textContent='';
 (d.keys||[]).forEach(k=>{const li=document.createElement('li');li.textContent=k;ul.appendChild(li);});}
document.getElementById('save').onclick=async()=>{
 const body={key:document.getElementById('k').value.trim(),value:document.getElementById('v').value,
   overwrite:document.getElementById('o').checked};
 const r=await fetch('/api/set',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const d=await r.json();document.getElementById('v').value='';
 out.textContent=d.ok?`${d.key}: ${d.action} (${d.n_keys} keys)`:`error: ${d.error}`;keys();};
keys();
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "keyvault"
    sys_version = ""
    vault = None
    cfg = {}

    def log_message(self, fmt, *args):   # method, path without query, status, source only
        pass

    def log_request(self, code="-", size="-"):
        log(f"req {self.client_address[0]} {self.command} {self.path.split('?')[0]} {code}")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send(self, status, body, ctype="application/json", extra=None):
        data = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _ip_ok(self):
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return any(ip in net for net in self.cfg["nets"])

    def _gate(self):
        """Source network + proxy marker header + SSO user. -> user, or None after a 403."""
        edge = self.headers.get("X-Kv-Edge", "")
        want = self.cfg["edge"]
        user = self.headers.get("Remote-User", "")
        if (self._ip_ok() and want and hmac.compare_digest(edge.encode(), want.encode())
                and user in self.cfg["users"]):
            return user
        self._send(403, {"ok": False, "error": "forbidden"})
        return None

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, "ok", "text/plain") if self._ip_ok() else self._send(403, {"ok": False})
        if self._gate() is None:
            return
        if self.path == "/":
            nonce = secrets.token_urlsafe(16)
            csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                   "connect-src 'self'; frame-ancestors 'none'; form-action 'none'")
            return self._send(200, PAGE.replace("__NONCE__", nonce), "text/html; charset=utf-8",
                              {"Content-Security-Policy": csp})
        if self.path == "/api/keys":
            names = self.vault.list_keys()
            return self._send(200, {"keys": names, "n_keys": len(names)})
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        user = self._gate()
        if user is None:
            return
        if self.path not in ("/api/set", "/api/unset"):
            return self._send(404, {"ok": False, "error": "not found"})
        # CSRF: JSON only, from the page's own origin
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype != "application/json" or self.headers.get("Origin") != self.cfg["origin"]:
            return self._send(403, {"ok": False, "error": "forbidden"})
        try:
            length = int(self.headers.get("Content-Length", ""))
            if not 0 < length <= MAX_BODY:
                raise ValueError
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self._send(422, {"ok": False, "error": "bad body"})
        src = self.client_address[0]
        if self.path == "/api/unset":
            status, body = self.vault.unset_key(user, data.get("key"), src)
        else:
            status, body = self.vault.set_key(user, data.get("key"), data.get("value"),
                                              data.get("overwrite", False), src)
        self._send(status, body)


def config_from_env():
    e = os.environ.get
    return {
        "store": e("KV_STORE", "/srv/secrets/secrets.enc.env"),
        "sops_config": e("KV_SOPS_CONFIG", "/srv/secrets/.sops.yaml"),
        "sops": e("KV_SOPS", "sops"),
        "audit": e("KV_AUDIT", "/var/log/keyvault/keyvault.log"),
        "bind": e("KV_BIND", "127.0.0.1:8094"),
        "nets": [ipaddress.ip_network(n.strip()) for n in e("KV_TRUSTED_NETS", "127.0.0.0/8").split(",") if n.strip()],
        "users": {u.strip() for u in e("KV_ALLOWED_USERS", "").split(",") if u.strip()},
        "origin": e("KV_ORIGIN", "https://kv.example.com"),
        "edge": e("KV_EDGE_SECRET", ""),
    }


def serve(cfg):
    Handler.cfg = cfg
    Handler.vault = Vault(cfg["store"], cfg["sops_config"], cfg["audit"], cfg["sops"])
    host, _, port = cfg["bind"].rpartition(":")
    srv = http.server.ThreadingHTTPServer((host, int(port)), Handler)
    log(f"listening on {cfg['bind']} store={cfg['store']}")
    if not cfg["edge"]:
        log("KV_EDGE_SECRET is empty: every request will be refused")
    srv.serve_forever()


if __name__ == "__main__":
    try:
        serve(config_from_env())
    except KeyboardInterrupt:
        sys.exit(0)
