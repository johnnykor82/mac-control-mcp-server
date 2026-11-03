"""Updating Mac Control must not touch unrelated services such as Hermes WebUI."""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from scripts import install_mac_control as installer
from scripts import maccontrol_manager as manager
from scripts import setup_chatbridge_dependency as dependency


class UpdateDependencyTests(unittest.TestCase):
    def installer_default(self, *args):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(installer.sys, "argv", ["installer", *args, "--root", tmp]), \
             patch.object(installer, "install", return_value={"status": "installed"}) as install, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(), 0)
            return install.call_args.args[1]

    def test_updates_preserve_browser_by_default(self):
        self.assertFalse(self.installer_default("--update"))
        self.assertFalse(self.installer_default("--update", "--without-chatbridge"))

    def test_fresh_install_still_provisions_browser(self):
        self.assertTrue(self.installer_default("--install"))
        self.assertFalse(self.installer_default("--install", "--without-chatbridge"))

    def test_update_opt_in_provisions_browser(self):
        self.assertTrue(self.installer_default("--update", "--with-chatbridge"))

    def test_manager_update_refreshes_only_opted_in_owned_dependency_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MacControlMCP"
            root.mkdir()
            (root / ".mac-control-installer-owned").write_text("owned")
            with patch.object(manager, "latest_beta", return_value=("v0.1.0-beta.27", {})), \
                 patch.object(manager, "verified_archive", return_value=b"test"), \
                 patch.object(manager, "unpack_release", return_value=root), \
                 patch.object(manager.subprocess, "call", return_value=0) as call:
                self.assertEqual(manager.update(root), 0)
                self.assertIn("--with-chatbridge", call.call_args.args[0])
                self.assertEqual(manager.update(root, without_chatbridge=True), 0)
                self.assertNotIn("--with-chatbridge", call.call_args.args[0])
                self.assertIn("--without-chatbridge", call.call_args.args[0])

    def test_cli_opt_in_and_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            for flags, preserve in (([], False), (["--without-chatbridge"], True),
                                    (["--with-chatbridge"], False)):
                with self.subTest(flags=flags), \
                     patch.object(manager, "update", return_value=0) as update:
                    self.assertEqual(manager.main(["--root", tmp, "update", *flags]), 0)
                    self.assertIs(update.call_args.kwargs["without_chatbridge"], preserve)

    def test_foreign_http_404_reports_port_and_does_not_provision(self):
        error = urllib.error.HTTPError(
            dependency.DEFAULT_URL + "/v1/browser/capabilities", 404, "Not Found", {}, None)
        with patch.object(dependency, "verify", side_effect=error), \
             patch.object(dependency, "install_pinned") as install:
            with self.assertRaisesRegex(RuntimeError, "port 8787.*HTTP 404"):
                dependency.ensure()
            install.assert_not_called()

    def test_401_still_requires_a_matching_api_key(self):
        error = urllib.error.HTTPError(dependency.DEFAULT_URL, 401, "Unauthorized", {}, None)
        with patch.object(dependency, "verify", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "API_KEY"):
                dependency.ensure()


if __name__ == "__main__":
    unittest.main()
