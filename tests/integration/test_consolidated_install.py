"""Offline checks for a single-directory Mac Control installation and updater."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import install_mac_control as install
from scripts import maccontrol_manager as manager


def archive_for(tag, *, bad_link=False):
    stream = io.BytesIO()
    prefix = "mac-control-mcp-server-" + tag
    files = {
        prefix + "/scripts/install_mac_control.py": b"print('fixture')\n",
        prefix + "/scripts/install_manifest.txt": b"scripts/install_mac_control.py\n",
    }
    with tarfile.open(fileobj=stream, mode="w:gz") as output:
        for path, content in files.items():
            entry = tarfile.TarInfo(path)
            entry.size = len(content)
            output.addfile(entry, io.BytesIO(content))
        if bad_link:
            entry = tarfile.TarInfo(prefix + "/bad")
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
            output.addfile(entry)
    return stream.getvalue()


class ConsolidatedInstallTests(unittest.TestCase):
    def test_default_root_is_in_home_and_gui_within_root(self):
        self.assertEqual(install.DEFAULT_ROOT, Path.home() / "MacControlMCP")
        from scripts import setup_remote_service, setup_watcher_service, build_mac_control_gui
        self.assertEqual(setup_remote_service.DEFAULT_ROOT, install.DEFAULT_ROOT)
        self.assertEqual(setup_watcher_service.DEFAULT_ROOT, install.DEFAULT_ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(build_mac_control_gui, "verify_owned", return_value=False):
                self.assertFalse((root / "apps/MacControlMCPServer.app").exists())

    def test_latest_complete_prerelease_and_hash_verification(self):
        one = "v0.1.0-beta.18"
        archive = archive_for(one)
        name = "mac-control-mcp-server-" + one + ".tar.gz"
        a = {"name": name, "browser_download_url": "https://github.com/asset.tar.gz"}
        h = {"name": "SHA256SUMS.txt", "browser_download_url": "https://github.com/sums"}
        meta = [{"tag_name": "v0.1.0-beta.19", "prerelease": True, "draft": True,
                 "assets": [a, h]},
                {"tag_name": one, "prerelease": True, "draft": False, "assets": [a, h]}]
        checksum = hashlib.sha256(archive).hexdigest() + "  " + name + "\n"
        def read(url, limit, *, api=False):
            return json.dumps(meta).encode() if api else (checksum.encode() if url.endswith("/sums") else archive)
        with patch.object(manager, "_read_url", side_effect=read):
            tag, assets = manager.latest_beta()
            self.assertEqual(tag, one)
            self.assertEqual(manager.verified_archive(tag, assets), archive)
        with tempfile.TemporaryDirectory() as temp:
            source = manager.unpack_release(archive, tag, Path(temp))
            self.assertTrue((source / "scripts/install_mac_control.py").is_file())

    def test_hash_mismatch_never_reaches_installer(self):
        tag = "v0.1.0-beta.18"
        name = "mac-control-mcp-server-" + tag + ".tar.gz"
        assets = {name: "https://github.com/asset", "SHA256SUMS.txt": "https://github.com/sums"}
        with patch.object(manager, "_read_url",
                          side_effect=lambda url, limit: (("0"*64+"  "+name).encode() if url.endswith("sums") else b"fake")):
            with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
                manager.verified_archive(tag, assets)

    def test_archive_rejects_symlinks_and_path_escape(self):
        tag = "v0.1.0-beta.18"
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "Unsafe"):
                manager.unpack_release(archive_for(tag, bad_link=True), tag, Path(temp))
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w:gz") as bundle:
                entry = tarfile.TarInfo("mac-control-mcp-server-" + tag + "/../../escape")
                entry.size = 1
                bundle.addfile(entry, io.BytesIO(b"x"))
            with self.assertRaisesRegex(RuntimeError, "Unsafe"):
                manager.unpack_release(stream.getvalue(), tag, Path(temp))
            self.assertFalse((Path(temp) / "escape").exists())

    def test_update_uses_verified_release_not_a_git_checkout(self):
        tag = "v0.1.0-beta.18"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "MacControlMCP"
            root.mkdir()
            (root / ".mac-control-installer-owned").write_text("owned")
            bundle = archive_for(tag)
            with patch.object(manager, "latest_beta", return_value=(tag, {})), \
                 patch.object(manager, "verified_archive", return_value=bundle), \
                 patch.object(manager.subprocess, "call", return_value=0) as call:
                self.assertEqual(manager.update(root, without_chatbridge=True), 0)
            argv = call.call_args.args[0]
            self.assertIn("--update", argv)
            self.assertIn("--without-chatbridge", argv)
            self.assertEqual(argv[argv.index("--root") + 1], str(root))
            self.assertIn("maccontrol-verified-", argv[1])
            self.assertFalse((root / "source").exists())

    def test_uninstall_all_refuses_nonstandard_root_without_deleting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / ".mac-control-installer-owned"
            marker.write_text("owned")
            with self.assertRaisesRegex(RuntimeError, "only at"):
                install.purge(root)
            self.assertTrue(marker.is_file())

    def test_purge_owned_default_root_preserves_independent_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "MacControlMCP"
            root.mkdir()
            (root / "releases").mkdir()
            (root / "data/workspace").mkdir(parents=True)
            (root / ".mac-control-installer-owned").write_text("owned")
            (root / "data/workspace/private.txt").write_text("temporary fixture")
            external = Path(temp) / "chatbridge"
            external.mkdir()
            (external / "unrelated.txt").write_text("preserve")
            with patch.object(install, "DEFAULT_ROOT", root):
                result = install.purge(root)
            self.assertEqual(result["status"], "purged")
            self.assertFalse(root.exists())
            self.assertEqual((external / "unrelated.txt").read_text(), "preserve")

    def test_cli_installation_from_release_not_chatbridge_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(install, "SOURCE", Path(__file__).resolve().parents[2]):
                install._install_manager_launcher(root)
            launcher = root / "bin/maccontrol"
            self.assertTrue(launcher.is_file())
            self.assertIn('current/.venv/bin/python', launcher.read_text())
            self.assertNotIn('chatbridge/chatbridge', launcher.read_text())


if __name__ == "__main__":
    unittest.main()
