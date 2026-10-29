"""Explicit installation payload tests."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import install_mac_control as installer


class InstallPayloadTests(unittest.TestCase):
    def test_untracked_env_excluded_and_installed_copy_can_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source with spaces"
            source.mkdir()
            payload = root / "payload"
            with patch.object(installer, "SOURCE", source):
                (source / "scripts").mkdir()
                (source / "scripts/install_manifest.txt").write_text(
                    "scripts/install_manifest.txt\nscripts/hello world.py\n")
                (source / "scripts/hello world.py").write_text("print('hello')\n")
                (source / "scripts/.env").write_text("private local data\n")
                installer.copy_source(payload)
                original_id = installer.source_id().split("-")[-1]
            self.assertFalse((payload / "scripts/.env").exists())
            with patch.object(installer, "SOURCE", payload):
                self.assertEqual(installer.source_id().split("-")[-1], original_id)
                second = root / "second"
                installer.copy_source(second)
                self.assertTrue((second / "scripts/install_manifest.txt").is_file())

    def test_rejects_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / "scripts").mkdir()
            manifest = source / "scripts/install_manifest.txt"
            with patch.object(installer, "SOURCE", source):
                for entry in ("scripts/../secret", "/tmp/secret", "../secret"):
                    manifest.write_text(entry + "\n")
                    with self.assertRaises(RuntimeError):
                        installer.install_sources()
                (source / "scripts/link").symlink_to(manifest)
                manifest.write_text("scripts/link\n")
                with self.assertRaises(RuntimeError):
                    installer.install_sources()
