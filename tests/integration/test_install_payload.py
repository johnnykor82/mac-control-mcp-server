"""Explicit installation payload tests."""
import os
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

    def test_release_id_depends_on_execute_bits_but_not_private_file_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "scripts").mkdir(parents=True)
            (source / "bin").mkdir()
            (source / "scripts/install_manifest.txt").write_text(
                "bin/mac-control-remote-mcp.sh\nscripts/install_manifest.txt\n"
            )
            launcher = source / "bin/mac-control-remote-mcp.sh"
            launcher.write_text("#!/bin/sh\nexit 0\n")
            launcher.chmod(0o600)
            with patch.object(installer, "SOURCE", source), patch.object(
                installer, "run", side_effect=OSError("test source is not a git repo")
            ):
                nonexec = installer.source_id()
                launcher.chmod(0o644)
                self.assertEqual(installer.source_id(), nonexec)
                launcher.chmod(0o700)
                executable = installer.source_id()
                self.assertNotEqual(executable, nonexec)
                self.assertNotEqual(installer.paths(root)["release"],
                                    root / "releases" / nonexec)
                copied = root / "copied-release"
                installer.copy_source(copied)
                self.assertTrue(os.access(
                    copied / "bin/mac-control-remote-mcp.sh", os.X_OK
                ))

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
