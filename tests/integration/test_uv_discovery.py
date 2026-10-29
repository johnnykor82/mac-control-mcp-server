"""Fresh-Mac uv discovery without modifying PATH or installing anything."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import install_mac_control as installer, release_preflight as preflight
from scripts import runtime_tools


class UvDiscoveryTests(unittest.TestCase):
    def test_path_takes_precedence(self):
        with patch.object(runtime_tools.shutil, "which", return_value="/approved/bin/uv"):
            self.assertEqual(runtime_tools.find_uv(), "/approved/bin/uv")

    def test_fresh_install_without_path_update_is_visible_to_both_consumers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            uv = root / ".local/bin/uv"
            uv.parent.mkdir(parents=True)
            uv.touch(mode=0o700)
            with patch.object(runtime_tools.shutil, "which", return_value=None), \
                 patch.object(runtime_tools.Path, "home", return_value=root):
                self.assertEqual(installer.find_uv(), str(uv))
                self.assertEqual(preflight.command("uv"), str(uv))
                self.assertTrue(preflight.inspect()["tools"]["uv"])

    def test_guided_install_readiness_requires_discoverable_uv(self):
        for available in (False, True):
            with patch.object(preflight.platform, "system", return_value="Darwin"), \
                 patch.object(preflight.os, "geteuid", return_value=501), \
                 patch.object(preflight, "addresses", return_value={"ipv4": [], "ipv6": []}), \
                 patch.object(preflight, "output", return_value=""), \
                 patch.object(preflight, "command", side_effect=lambda name: "/tool" if name != "uv" or available else None):
                self.assertEqual(preflight.inspect()["ready_for_guided_install"], available)

    def test_fallbacks_require_an_executable_file_in_order(self):
        expected = [str(Path.home() / ".local/bin/uv"),
                    "/opt/homebrew/bin/uv", "/usr/local/bin/uv"]
        for selected in expected:
            with patch.object(runtime_tools.shutil, "which", return_value=None), \
                 patch.object(runtime_tools.Path, "is_file", return_value=True), \
                 patch.object(runtime_tools.os, "access", side_effect=lambda path, mode: str(path) == selected):
                self.assertEqual(runtime_tools.find_uv(), selected)
        with patch.object(runtime_tools.shutil, "which", return_value=None), \
             patch.object(runtime_tools.Path, "is_file", return_value=False), \
             patch.object(runtime_tools.os, "access", return_value=True):
            self.assertIsNone(runtime_tools.find_uv())
        with patch.object(runtime_tools.shutil, "which", return_value=None), \
             patch.object(runtime_tools.Path, "is_file", return_value=True), \
             patch.object(runtime_tools.os, "access", return_value=False):
            self.assertIsNone(runtime_tools.find_uv())


class UserEnvironmentTests(unittest.TestCase):
    def test_owner_fallback_in_terminal_and_both_package_paths(self):
        import importlib
        import json
        from types import SimpleNamespace
        from mac_control.legacy_handlers import command_plugins, package_ops
        with patch.dict(os.environ, {}, clear=True), \
             patch("getpass.getuser", return_value="new-owner"):
            importlib.reload(command_plugins)
            self.assertEqual(command_plugins.ENVIRONMENT["USER"], "new-owner")
            with patch.object(package_ops.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
                package_ops._run(["unused"])
                self.assertEqual(run.call_args.kwargs["env"]["USER"], "new-owner")
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    (root / "test-job").mkdir()
                    (root / "test-job/status.json").write_text(json.dumps({}))
                    with patch.object(package_ops, "STATE", root), \
                         patch.object(package_ops, "brew", return_value="/unused/brew"):
                        self.assertEqual(package_ops._worker("test-job", "git"), 0)
                    self.assertEqual(run.call_args.kwargs["env"]["USER"], "new-owner")
        importlib.reload(command_plugins)
