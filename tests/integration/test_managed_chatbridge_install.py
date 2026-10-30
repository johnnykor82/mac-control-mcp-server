"""The single Mac Control installer provisions and owns its ChatBridge dependency."""
from __future__ import annotations
import hashlib
import io
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import install_mac_control as installer
from scripts import setup_chatbridge_dependency as cb


class ManagedChatBridgeTests(unittest.TestCase):
    def test_chatbridge_installer_targets_mac_control_deps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "deps/chatbridge-source"
            for name in ("install.sh", "LICENSE", "pyproject.toml", "scripts/installer.py"):
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('name = "chatbridge-gateway"\n')
            with patch.object(cb, "assert_installable"), \
                 patch.object(cb, "verify_managed_install"), \
                 patch.object(cb, "verify", return_value={"status": "compatible"}), \
                 patch.object(cb.subprocess, "run",
                              return_value=SimpleNamespace(returncode=0)) as runner:
                cb.install(source, install_root=root)
            args = runner.call_args.args[0]
            self.assertEqual(args[args.index("--prefix") + 1], str(root.resolve() / "deps/chatbridge"))
            self.assertEqual(args[args.index("--state-dir") + 1], str(root.resolve() / "deps/chatbridge-data"))
            self.assertEqual(args[args.index("--port") + 1], "8787")

    def test_existing_service_must_be_owned_within_same_root(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            root = home / "MacControlMCP"
            prefix = root / "deps/chatbridge"
            state = root / "deps/chatbridge-data"
            plist = home / "Library/LaunchAgents/net.chatbridge.gateway.plist"
            plist.parent.mkdir(parents=True)
            config = {"Label": "net.chatbridge.gateway", "ChatBridgeInstaller": "1",
                      "WorkingDirectory": str(prefix / "releases/installed"),
                      "EnvironmentVariables": {"CHATBRIDGE_DB": str(state / "state.db")}}
            with patch.object(cb.Path, "home", return_value=home):
                plist.write_bytes(plistlib.dumps(config))
                cb.verify_managed_install(root)
                config["WorkingDirectory"] = str(home / ".local/share/chatbridge/releases/installed")
                plist.write_bytes(plistlib.dumps(config))
                with self.assertRaisesRegex(RuntimeError, "outside"):
                    cb.verify_managed_install(root)

    def test_compatible_external_endpoint_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cb, "verify", return_value={"status": "compatible"}), \
                 patch.object(cb, "verify_managed_install", side_effect=RuntimeError("external")):
                with self.assertRaisesRegex(RuntimeError, "external"):
                    cb.ensure(install_root=Path(directory))

    def test_default_install_passes_root_to_dependency_manager(self):
        with patch.object(installer, "paths", return_value={}), \
             patch.object(installer.sys, "platform", "darwin"), \
             patch.object(cb, "ensure") as ensure, \
             patch.object(installer, "find_uv", side_effect=RuntimeError("stop-after-dependency")):
            with self.assertRaisesRegex(RuntimeError, "stop-after-dependency"):
                installer.install(Path("unused"))
        ensure.assert_called_once_with(cb.DEFAULT_URL, None, install_root=Path("unused").resolve())

    def test_pinned_release_persisted_under_managed_root(self):
        import tarfile
        from tests.integration.test_chatbridge_bootstrap import archive_bytes
        payload = archive_bytes()
        class Response(io.BytesIO):
            def geturl(self): return cb.RELEASE_URL
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "MacControlMCP"
            root.mkdir()
            with patch.object(cb, "assert_installable"), \
                 patch.object(cb, "RELEASE_SHA256", hashlib.sha256(payload).hexdigest()), \
                 patch.object(cb.urllib.request, "urlopen", return_value=Response(payload)), \
                 patch.object(cb, "install", return_value={"status": "compatible"}) as run:
                cb.install_pinned(install_root=root)
            saved, _, _ = cb.managed_paths(root)
            self.assertTrue((saved / "scripts/installer.py").is_file())
            self.assertEqual(run.call_args.args[0], saved)

    def test_purge_invokes_chatbridge_own_uninstaller_with_owned_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / "MacControlMCP"
            src, prefix, state = cb.managed_paths(root)
            script = src / "scripts/installer.py"
            script.parent.mkdir(parents=True)
            script.write_text("safe test source")
            plist = home / "Library/LaunchAgents/net.chatbridge.gateway.plist"
            plist.parent.mkdir(parents=True)
            plist.write_bytes(plistlib.dumps({
                "Label": "net.chatbridge.gateway",
                "ChatBridgeInstaller": "1",
                "WorkingDirectory": str(prefix / "releases/build"),
                "EnvironmentVariables": {"CHATBRIDGE_DB": str(state / "state.db")}}))
            with patch.object(Path, "home", return_value=home), \
                 patch.object(installer.subprocess, "run",
                              return_value=SimpleNamespace(returncode=0)) as runner:
                self.assertTrue(installer._remove_managed_chatbridge(root))
            args = runner.call_args.args[0]
            for flag in ("uninstall", "--remove-app", "--purge-data", "--yes"):
                self.assertIn(flag, args)
            self.assertEqual(args[args.index("--prefix")+1], str(prefix))
            self.assertEqual(args[args.index("--state-dir")+1], str(state))

    def test_foreign_chatbridge_is_never_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / "MacControlMCP"
            src, prefix, state = cb.managed_paths(root)
            script = src / "scripts/installer.py"
            script.parent.mkdir(parents=True)
            script.write_text("safe test source")
            plist = home / "Library/LaunchAgents/net.chatbridge.gateway.plist"
            plist.parent.mkdir(parents=True)
            plist.write_bytes(plistlib.dumps({
                "Label": "net.chatbridge.gateway", "ChatBridgeInstaller": "1",
                "WorkingDirectory": str(home / ".local/share/chatbridge/releases/build"),
                "EnvironmentVariables": {"CHATBRIDGE_DB": str(home / ".chatbridge/state.db")}}))
            with patch.object(Path, "home", return_value=home), \
                 patch.object(installer.subprocess, "run") as runner:
                with self.assertRaisesRegex(RuntimeError, "outside"):
                    installer._remove_managed_chatbridge(root)
                runner.assert_not_called()

    def test_purge_uninstalls_owned_dependency_before_deleting_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "MacControlMCP"
            root.mkdir()
            (root / ".mac-control-installer-owned").write_text("owned")
            (root / "releases").mkdir()
            (root / "data/workspace").mkdir(parents=True)
            (root / "data/workspace/file").write_text("secret")
            with patch.object(installer, "DEFAULT_ROOT", root), \
                 patch.object(installer, "_remove_managed_chatbridge", return_value=True) as uninstall_cb:
                result = installer.purge(root)
            self.assertEqual(result["managed_chatbridge_removed"], True)
            self.assertFalse(root.exists())
            uninstall_cb.assert_called_once()

    def test_full_purge_stops_before_deleting_if_public_route_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "MacControlMCP"
            root.mkdir()
            (root / ".mac-control-installer-owned").write_text("owned")
            with patch.object(installer, "DEFAULT_ROOT", root), \
                 patch("scripts.setup_network.assert_public_route_safe_for_uninstall",
                       side_effect=RuntimeError("active Funnel")), \
                 patch.object(installer, "_remove_managed_chatbridge") as uninstall_cb:
                with self.assertRaisesRegex(RuntimeError, "active Funnel"):
                    installer.purge(root)
                uninstall_cb.assert_not_called()
                self.assertTrue((root / ".mac-control-installer-owned").is_file())


if __name__ == "__main__":
    unittest.main()
