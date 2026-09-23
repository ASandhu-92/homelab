#!/usr/bin/env python3
"""Tests for the gatehouse reconciler and CLI, run against a copy of example/.

    python3 -m unittest -v test_gatehouse.py
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


class GatehouseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copytree(os.path.join(HERE, "example", "dynamic"), os.path.join(self.tmp, "dynamic"))
        shutil.copy(os.path.join(HERE, "example", "state.json"), os.path.join(self.tmp, "state.json"))
        self.env = dict(os.environ, GATEHOUSE_DYNAMIC_DIR=os.path.join(self.tmp, "dynamic"),
                        GATEHOUSE_STATE=os.path.join(self.tmp, "state.json"),
                        GATEHOUSE_DESIRED_URL="")
        self.out = os.path.join(self.tmp, "dynamic", "gatehouse.yml")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_cli(self, *args):
        r = subprocess.run([sys.executable, os.path.join(HERE, "gatehouse"), *args],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def ext_routers(self):
        with open(self.out) as f:
            return yaml.safe_load(f)["http"]["routers"]

    def test_public_hosts_get_ext_routers_private_do_not(self):
        out = self.run_cli("reconcile")
        self.assertIn("wrote", out)
        r = self.ext_routers()
        self.assertEqual(sorted(r), ["docs-ext", "media-api-ext", "media-ext", "remote-ext"])
        self.assertNotIn("admin-ext", r)
        self.assertEqual(r["docs-ext"]["entryPoints"], ["websecure-ext"])
        # middlewares, priority and TLS are carried over from the internal router
        self.assertEqual(r["docs-ext"]["middlewares"], ["crowdsec", "authelia"])
        self.assertEqual(r["media-api-ext"]["priority"], 100)
        self.assertEqual(r["media-ext"]["tls"], {"certResolver": "letsencrypt"})

    def test_second_run_is_unchanged_and_file_is_world_readable(self):
        self.run_cli("reconcile")
        self.assertIn("unchanged", self.run_cli("reconcile"))
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o644)

    def test_private_then_public(self):
        self.run_cli("private", "media.example.com")
        self.assertNotIn("media-ext", self.ext_routers())
        self.assertNotIn("media-api-ext", self.ext_routers())
        self.run_cli("public", "media.example.com")
        self.assertIn("media-ext", self.ext_routers())

    def test_panic_keeps_protected_and_restore_undoes_it(self):
        self.run_cli("reconcile")
        out = self.run_cli("panic")
        self.assertIn("hid 2 hosts", out)
        self.assertEqual(sorted(self.ext_routers()), ["remote-ext"])
        self.run_cli("restore")
        self.assertEqual(sorted(self.ext_routers()), ["docs-ext", "media-api-ext", "media-ext", "remote-ext"])
        with open(self.env["GATEHOUSE_STATE"]) as f:
            self.assertIsNone(json.load(f)["panic_prev"])

    def test_dry_run_writes_nothing(self):
        out = self.run_cli("reconcile", "--dry-run")
        self.assertIn("would write", out)
        self.assertFalse(os.path.exists(self.out))

    def test_missing_state_means_everything_private(self):
        os.remove(self.env["GATEHOUSE_STATE"])
        self.run_cli("reconcile")
        self.assertEqual(self.ext_routers(), {})


if __name__ == "__main__":
    unittest.main()
