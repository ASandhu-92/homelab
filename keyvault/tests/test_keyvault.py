#!/usr/bin/env python3
"""Tests for keyvault against a real sops binary and a throwaway age key.

    python3 -m unittest discover -s tests -v      (from the keyvault folder)

Skipped when `sops` is not on PATH.
"""
import contextlib
import glob
import http.client
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import http.server

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import agekey  # noqa: E402
import keyvault  # noqa: E402

SOPS = shutil.which("sops")
VALUE = "v4lue-that-must-never-leak-9f3a"


@unittest.skipUnless(SOPS, "sops not installed")
class VaultTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        sk, pk = agekey.keypair()
        with open(os.path.join(self.d, "keys.txt"), "w") as f:
            f.write(sk + "\n")
        os.environ["SOPS_AGE_KEY_FILE"] = os.path.join(self.d, "keys.txt")
        self.cfg = os.path.join(self.d, ".sops.yaml")
        with open(self.cfg, "w") as f:
            f.write(f"creation_rules:\n  - path_regex: secrets\\.enc\\.env$\n    age: {pk}\n")
        self.store = os.path.join(self.d, "secrets.enc.env")
        plain = b"# lab secrets\nALPHA_KEY=one\nBETA_KEY=two\n"
        r = subprocess.run([SOPS, "--config", self.cfg, "encrypt", "--input-type", "dotenv",
                            "--output-type", "dotenv", "--filename-override", self.store, "/dev/stdin"],
                           input=plain, capture_output=True, check=True)
        with open(self.store, "wb") as f:
            f.write(r.stdout)
        self.audit = os.path.join(self.d, "audit.log")
        self.v = keyvault.Vault(self.store, self.cfg, self.audit, SOPS)

    def tearDown(self):
        shutil.rmtree(self.d)
        os.environ.pop("SOPS_AGE_KEY_FILE", None)

    def plain(self):
        rc, out, _ = self.v._decrypt(self.store)
        self.assertEqual(rc, 0)
        return keyvault.parse_dotenv(out.decode())[1]

    def test_add_then_overwrite_then_delete(self):
        st, body = self.v.set_key("alice", "GAMMA_KEY", VALUE, False, "192.0.2.5")
        self.assertEqual((st, body["action"], body["n_keys"]), (200, "added", 3))
        self.assertEqual(self.plain(), {"ALPHA_KEY": "one", "BETA_KEY": "two", "GAMMA_KEY": VALUE})
        self.assertIn("GAMMA_KEY", self.v.list_keys())
        self.assertTrue(os.path.exists(self.store + ".prev"))

        st, body = self.v.set_key("alice", "GAMMA_KEY", "new-value-123", False, "192.0.2.5")
        self.assertEqual((st, body["error"]), (409, "exists"))
        st, body = self.v.set_key("alice", "GAMMA_KEY", "new-value-123", True, "192.0.2.5")
        self.assertEqual((st, body["action"]), (200, "overwritten"))
        self.assertEqual(self.plain()["GAMMA_KEY"], "new-value-123")

        st, body = self.v.unset_key("alice", "GAMMA_KEY", "192.0.2.5")
        self.assertEqual((st, body["action"], body["n_keys"]), (200, "deleted", 2))
        st, body = self.v.unset_key("alice", "GAMMA_KEY", "192.0.2.5")
        self.assertEqual((st, body["error"]), (409, "absent"))
        self.assertEqual(self.plain(), {"ALPHA_KEY": "one", "BETA_KEY": "two"})

    def test_value_never_leaks(self):
        argvs = []
        real = self.v._run_sops

        def spy(args, stdin=None):
            argvs.append(list(args))
            return real(args, stdin)

        self.v._run_sops = spy
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            st, _ = self.v.set_key("alice", "GAMMA_KEY", VALUE, False, "192.0.2.5")
        self.assertEqual(st, 200)
        self.assertFalse(any(VALUE in a for args in argvs for a in args), "value reached argv")
        self.assertNotIn(VALUE, buf.getvalue(), "value reached the service log")
        for p in glob.glob(os.path.join(self.d, "*")) + glob.glob(os.path.join(self.d, ".*")):
            if os.path.isfile(p) and not p.endswith("keys.txt"):
                with open(p, "rb") as f:
                    self.assertNotIn(VALUE.encode(), f.read(), f"value in plain text in {p}")
        with open(self.audit) as f:
            line = f.read().strip()
        self.assertRegex(line, r" alice GAMMA_KEY added 192\.0\.2\.5$")
        self.assertEqual(glob.glob(os.path.join(self.d, ".kvtmp.*")), [], "temp file left behind")

    def test_bad_input_is_rejected_and_not_logged(self):
        st, _ = self.v.set_key("alice", "looks-like-a-value-abc123", "x", False, "192.0.2.5")
        self.assertEqual(st, 422)
        st, _ = self.v.set_key("alice", "OK_NAME", "two\nlines", False, "192.0.2.5")
        self.assertEqual(st, 422)
        with open(self.audit) as f:
            log = f.read()
        self.assertNotIn("looks-like-a-value", log)
        self.assertIn("rejected-badkey", log)
        self.assertIn("rejected-value-unprintable", log)


@unittest.skipUnless(SOPS, "sops not installed")
class HttpGateTest(VaultTest):
    """The same store, reached through the HTTP handler."""

    def setUp(self):
        super().setUp()
        keyvault.Handler.vault = self.v
        keyvault.Handler.cfg = {"nets": [keyvault.ipaddress.ip_network("127.0.0.0/8")], "users": {"alice"},
                                "origin": "https://kv.example.com", "edge": "edge-marker-for-tests"}
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), keyvault.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        super().tearDown()

    def req(self, method, path, body=None, **hdr):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"X-Kv-Edge": "edge-marker-for-tests", "Remote-User": "alice",
             "Origin": "https://kv.example.com", "Content-Type": "application/json"}
        h.update({k.replace("_", "-"): v for k, v in hdr.items()})
        h = {k: v for k, v in h.items() if v is not None}
        with contextlib.redirect_stdout(io.StringIO()):
            c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
            r = c.getresponse()
            return r.status, r.read()

    def test_gate(self):
        self.assertEqual(self.req("GET", "/api/keys")[0], 200)
        self.assertEqual(self.req("GET", "/api/keys", X_Kv_Edge=None)[0], 403)
        self.assertEqual(self.req("GET", "/api/keys", X_Kv_Edge="wrong")[0], 403)
        self.assertEqual(self.req("GET", "/api/keys", Remote_User="mallory")[0], 403)
        body = {"key": "HTTP_KEY", "value": VALUE, "overwrite": False}
        self.assertEqual(self.req("POST", "/api/set", body, Origin="https://evil.example.net")[0], 403)
        self.assertEqual(self.req("POST", "/api/set", body, Content_Type="text/plain")[0], 403)
        st, raw = self.req("POST", "/api/set", body)
        self.assertEqual(st, 200, raw)
        self.assertNotIn(VALUE.encode(), raw)
        self.assertIn("HTTP_KEY", json.loads(self.req("GET", "/api/keys")[1])["keys"])
        st, raw = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b"keyvault", raw)

    # the Vault tests are not repeated here
    test_add_then_overwrite_then_delete = None
    test_value_never_leaks = None
    test_bad_input_is_rejected_and_not_logged = None


if __name__ == "__main__":
    unittest.main()
