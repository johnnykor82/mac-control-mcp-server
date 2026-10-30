"""Optional watcher credentials use fake keys and temporary owner-only files."""
from __future__ import annotations

import importlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import install_mac_control as installer

SOURCE = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SOURCE))
from mac_control.watcher_runtime import config


class WatcherCredentialsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name).resolve()
        self.keyfile = self.data / "chatbridge_api_key.txt"
        self.addCleanup(patch.stopall)
        patch.object(config, "DATA_ROOT", self.data).start()
        patch.dict(os.environ, {"MACCONTROL_CHATBRIDGE_API_KEY": ""}).start()

    def write_key(self, value="fake-file-key\n", mode=0o600):
        if self.keyfile.is_file():
            self.keyfile.chmod(0o600)
        self.keyfile.write_text(value)
        self.keyfile.chmod(mode)

    def test_absent_optional_key_is_keyless_without_creating_files(self):
        self.assertEqual(config.api_key(), "")
        self.assertEqual(list(self.data.iterdir()), [])
        installer._save_chatbridge_key(self.data)
        self.assertEqual(list(self.data.iterdir()), [])

    def test_environment_precedes_private_file_and_updates_each_call(self):
        self.write_key()
        with patch.dict(os.environ, {"MACCONTROL_CHATBRIDGE_API_KEY": " fake-env-key "}):
            self.assertEqual(config.api_key(), "fake-env-key")
        self.assertEqual(config.api_key(), "fake-file-key")
        self.write_key("replacement-fake-key\n")
        self.assertEqual(config.api_key(), "replacement-fake-key")

    def test_symlink_file_and_parent_are_refused(self):
        other = self.data / "other"
        other.write_text("preserve fake value")
        self.keyfile.symlink_to(other)
        with self.assertRaises((PermissionError, RuntimeError)):
            config.api_key()
        self.assertEqual(other.read_text(), "preserve fake value")
        self.keyfile.unlink()
        actual = self.data / "actual"
        actual.mkdir()
        alias = self.data / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        (actual / self.keyfile.name).write_text("fake-key")
        (actual / self.keyfile.name).chmod(0o600)
        with patch.object(config, "DATA_ROOT", alias):
            with self.assertRaises((PermissionError, RuntimeError)):
                config.api_key()

    def test_shared_or_nonexact_permissions_hardlinks_and_directory_are_refused(self):
        for mode in (0o644, 0o660, 0o400, 0o700):
            with self.subTest(mode=oct(mode)):
                self.write_key(mode=mode)
                with self.assertRaises(PermissionError):
                    config.api_key()
        self.write_key()
        os.link(self.keyfile, self.data / "hardlink")
        with self.assertRaises(PermissionError):
            config.api_key()
        self.keyfile.unlink()
        self.keyfile.mkdir()
        with self.assertRaises(PermissionError):
            config.api_key()

    def test_credential_wrong_owner_is_refused(self):
        self.write_key()
        with patch.object(config.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(PermissionError):
                config.api_key()

    def test_key_size_and_header_line_breaks_are_bounded(self):
        self.write_key("x" * 4096 + "\n")
        self.assertEqual(len(config.api_key()), 4096)
        for value in ("x" * 4097, "fake\nkey", "fake\rkey"):
            with self.subTest(length=len(value)):
                self.write_key(value)
                with self.assertRaises(ValueError):
                    config.api_key()
        with patch.dict(os.environ, {"MACCONTROL_CHATBRIDGE_API_KEY": "fake\nkey"}):
            with self.assertRaises(ValueError):
                config.api_key()

    def test_installer_persists_and_rotates_explicit_key_privately(self):
        with patch.dict(os.environ, {"MACCONTROL_CHATBRIDGE_API_KEY": "fake-install-key"}):
            installer._save_chatbridge_key(self.data)
        self.assertEqual(self.keyfile.stat().st_mode & 0o777, 0o600)
        self.assertEqual(config.api_key(), "fake-install-key")
        with patch.dict(os.environ, {"MACCONTROL_CHATBRIDGE_API_KEY": "fake-rotated-key"}):
            installer._save_chatbridge_key(self.data)
        self.assertEqual(config.api_key(), "fake-rotated-key")
        self.assertEqual([item.name for item in self.data.iterdir()], [self.keyfile.name])

    def test_installer_preserves_existing_key_when_environment_absent(self):
        self.write_key()
        original = self.keyfile.read_bytes()
        installer._save_chatbridge_key(self.data)
        self.assertEqual(self.keyfile.read_bytes(), original)

    def test_installer_rejects_unsafe_symlink_without_overwriting_target(self):
        target = self.data / "unrelated"
        target.write_text("preserve")
        target.chmod(0o644)
        self.keyfile.symlink_to(target)
        with patch.dict(os.environ, {"MACCONTROL_CHATBRIDGE_API_KEY": "fake-install-key"}):
            with self.assertRaises(PermissionError):
                installer._save_chatbridge_key(self.data)
        self.assertTrue(self.keyfile.is_symlink())
        self.assertEqual(target.read_text(), "preserve")
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_installer_refuses_nonexact_private_permissions(self):
        for mode in (0o400, 0o700, 0o644):
            with self.subTest(mode=oct(mode)):
                self.write_key(mode=mode)
                with patch.dict(os.environ, {"MACCONTROL_CHATBRIDGE_API_KEY": "fake-new-key"}):
                    with self.assertRaises(PermissionError):
                        installer._save_chatbridge_key(self.data)
                self.assertEqual(self.keyfile.stat().st_mode & 0o777, mode)

    def test_adapter_import_does_not_resolve_credentials(self):
        with patch.object(config, "gateway", return_value="http://127.0.0.1:8787"):
            adapter = importlib.import_module("mac_control.watcher_runtime.watcher_http_adapter")
            with patch.object(config, "api_key", side_effect=AssertionError("Import read credentials")) as resolve:
                importlib.reload(adapter)
                resolve.assert_not_called()
            importlib.reload(adapter)

    def test_adapter_resolves_optional_key_per_request(self):
        with patch.object(config, "gateway", return_value="http://127.0.0.1:8787"):
            adapter = importlib.import_module("mac_control.watcher_runtime.watcher_http_adapter")
        requests = []
        def respond(request, **kwargs):
            requests.append(request)
            return io.BytesIO(b'{}')
        with patch.object(adapter._HTTP, "open", side_effect=respond):
            adapter.api("GET", "/health")
            self.write_key("fake-first-key\n")
            adapter.api("GET", "/health")
            self.write_key("fake-second-key\n")
            adapter.api("GET", "/health")
        self.assertIsNone(requests[0].get_header("Authorization"))
        self.assertEqual(requests[1].get_header("Authorization"), "Bearer fake-first-key")
        self.assertEqual(requests[2].get_header("Authorization"), "Bearer fake-second-key")


if __name__ == "__main__":
    unittest.main()
