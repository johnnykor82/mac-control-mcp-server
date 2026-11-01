"""Offline verification of Mac Control MCP Server update, rollback, and uninstall safety."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import install_mac_control as ic


class MacControlMCPServerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "releases").mkdir()
        (self.root / "data/workspace").mkdir(parents=True)
        # Real macOS Funnel is intentionally active on the developer machine.
        # This is an isolated fixture: never examine/change the live route.
        self.root.chmod(0o700)
        (self.root / "data").chmod(0o700)
        from scripts import setup_network
        guard = patch.object(setup_network, "assert_public_route_safe_for_uninstall", return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        # The host has real LaunchAgents. Treat this temporary install as
        # independent: it has no owned remote or Watcher service.
        for function in ("_remote_plist_exists", "_watcher_plist_exists"):
            service = patch.object(ic, function, return_value=False)
            service.start()
            self.addCleanup(service.stop)
        self.user = self.root / "data/workspace/do-not-delete.txt"
        self.user.write_text("keep")
        (self.root / ".mac-control-installer-owned").write_text("owned")
        self.first = self.release("one")
        self.second = self.release("two")

    def release(self, name):
        directory = self.root / "releases" / name
        path = directory / "bin/mac-control-stdio-mcp.sh"
        path.parent.mkdir(parents=True)
        path.write_text("#!/bin/sh\n")
        return directory

    def test_rollback_switches_pointers_and_keeps_data(self):
        (self.root / "current").symlink_to(self.second)
        (self.root / "previous").symlink_to(self.first)
        with patch.object(ic, "smoke") as smoke:
            result = ic.rollback(self.root)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual((self.root / "current").resolve(), self.first.resolve())
        self.assertEqual((self.root / "previous").resolve(), self.second.resolve())
        self.assertEqual(self.user.read_text(), "keep")
        smoke.assert_called_once_with(self.first.resolve(), (self.root / "data").resolve())

    def test_uninstall_removes_only_owned_releases_and_keeps_data(self):
        (self.root / "current").symlink_to(self.second)
        (self.root / "previous").symlink_to(self.first)
        result = ic.uninstall(self.root)
        self.assertEqual(result["removed_releases"], 2)
        self.assertFalse(self.first.exists())
        self.assertFalse((self.root / "current").exists())
        self.assertEqual(self.user.read_text(), "keep")

    def test_uninstall_rejects_without_installer_ownership(self):
        (self.root / ".mac-control-installer-owned").unlink()
        with self.assertRaises(RuntimeError):
            ic.uninstall(self.root)
        self.assertTrue(self.second.exists())
        self.assertEqual(self.user.read_text(), "keep")

    def test_uninstall_rejects_unrelated_activation_path(self):
        (self.root / "current").write_text("unrelated")
        with self.assertRaises(RuntimeError):
            ic.uninstall(self.root)
        self.assertEqual((self.root / "current").read_text(), "unrelated")

    def test_uninstall_rejects_unrelated_release_directory(self):
        stranger = self.root / "releases/not-mac-control"
        stranger.mkdir()
        (self.root / "current").symlink_to(self.first)
        with self.assertRaises(RuntimeError):
            ic.uninstall(self.root)
        self.assertTrue(stranger.exists())
        self.assertTrue(self.first.exists())

    def test_owner_gui_bundle_is_optional(self):
        self.assertFalse((self.root / "data/gui-owned.json").exists())
        result = ic.uninstall(self.root)
        self.assertEqual(result["status"], "uninstalled")


if __name__ == "__main__":
    unittest.main()
