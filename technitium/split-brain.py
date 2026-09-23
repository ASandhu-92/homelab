#!/usr/bin/env python3
"""Create the split-brain zone for the lab domain on a Technitium server.

The zone is a Conditional Forwarder zone whose forwarder is "this-server":
names you define locally (apex and wildcard A records pointing at the reverse
proxy) are answered from here, and every other record type or name (MX, TXT,
_dmarc, _acme-challenge, NS, SOA) is resolved recursively and returns the real
public answer. A Primary zone would answer those from its own empty data and
hide them.

Also adds an HTTPS record (priority 1, target ".", alpn=h2) at the apex and the
wildcard so that a public HTTPS record with IP hints never reaches LAN
clients and points them at the public edge instead of the proxy.

Standard library only. Reads from the environment (or a .env next to it):
  TECHNITIUM_URL, DNS_SERVER_ADMIN_PASSWORD, LAB_ZONE, PROXY_IP
Usage:
  python3 split-brain.py            apply (idempotent: records are overwritten)
  python3 split-brain.py --dry-run  print the API calls without sending them
"""
import json
import os
import sys
import urllib.parse
import urllib.request


def load_env(path):
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k, v)


def api(base, path, params, dry):
    shown = {k: ("***" if k in ("pass", "token") else v) for k, v in params.items()}
    print(f"GET {path} {shown}")
    if dry:
        return {"status": "ok", "response": {"token": "dry-run"}}
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        body = json.load(r)
    if body.get("status") != "ok":
        # zone already exists is fine on a re-run
        msg = body.get("errorMessage", "")
        if "already exists" in msg:
            print(f"  note: {msg}")
            return body
        sys.exit(f"  API error: {msg}")
    return body


def main():
    load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    dry = "--dry-run" in sys.argv
    base = os.environ.get("TECHNITIUM_URL", "http://127.0.0.1:5380").rstrip("/")
    zone = os.environ["LAB_ZONE"]
    ip = os.environ["PROXY_IP"]
    login = api(base, "/api/user/login",
                {"user": "admin", "pass": os.environ.get("DNS_SERVER_ADMIN_PASSWORD", "")}, dry)
    tok = login.get("token") or login["response"].get("token")

    api(base, "/api/zones/create", {"token": tok, "zone": zone, "type": "Forwarder",
                                    "forwarder": "this-server", "dnssecValidation": "true"}, dry)
    for name in (zone, f"*.{zone}"):
        api(base, "/api/zones/records/add", {"token": tok, "zone": zone, "domain": name, "type": "A",
                                             "ipAddress": ip, "ttl": "300", "overwrite": "true"}, dry)
        api(base, "/api/zones/records/add", {"token": tok, "zone": zone, "domain": name, "type": "HTTPS",
                                             "svcPriority": "1", "svcTargetName": ".",
                                             "svcParams": "alpn|h2", "ttl": "300",
                                             "overwrite": "true"}, dry)
    api(base, "/api/user/logout", {"token": tok}, dry)
    print("done")


if __name__ == "__main__":
    main()
