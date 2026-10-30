"""Pinned dependency bootstrap, using only disposable archives and mocked services."""
import errno
import hashlib
import io
from pathlib import Path
import socket
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
from scripts import setup_chatbridge_dependency as dependency
from scripts import install_mac_control as installer


def archive_bytes(name=None, kind=tarfile.REGTYPE, size=2):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        member = tarfile.TarInfo(name or dependency.RELEASE_DIRECTORY + "/scripts/installer.py")
        member.type = kind
        member.size = size if kind == tarfile.REGTYPE else 0
        member.linkname = "/tmp/escape"
        archive.addfile(member, io.BytesIO(b"x" * size) if member.isfile() else None)
    return output.getvalue()


class BootstrapTests(unittest.TestCase):
    def test_reuses_compatible_service_without_setup(self):
        with patch.object(dependency, "verify", return_value={"status": "compatible"}), \
             patch.object(dependency, "install_pinned") as install:
            self.assertEqual(dependency.ensure()["status"], "compatible")
        install.assert_not_called()

    def test_only_refused_connection_allows_fresh_install(self):
        refused = urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED, "refused"))
        with patch.object(dependency, "verify", side_effect=refused), \
             patch.object(dependency, "assert_installable"), \
             patch.object(dependency, "install_pinned", return_value={}) as install:
            dependency.ensure("http://127.0.0.1:9999")
        install.assert_called_once_with("http://127.0.0.1:9999", install_root=None)
        for error in (TimeoutError(), urllib.error.URLError(socket.timeout()),
                      urllib.error.HTTPError(dependency.DEFAULT_URL, 401, "Unauthorized", {}, None),
                      RuntimeError("incompatible API"), ValueError("invalid JSON")):
            with patch.object(dependency, "verify", side_effect=error), \
                 patch.object(dependency, "install_pinned") as install:
                with self.assertRaises(RuntimeError):
                    dependency.ensure()
                install.assert_not_called()

    def test_conflicts_stop_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            state = home / ".chatbridge"
            state.mkdir()
            (state / "database.sqlite").touch()
            with patch.object(dependency.Path, "home", return_value=home), \
                 patch.object(dependency.urllib.request, "urlopen") as download:
                with self.assertRaisesRegex(RuntimeError, "state"):
                    dependency.install_pinned()
                download.assert_not_called()
            (state / "database.sqlite").unlink()
            plist = home / "Library/LaunchAgents/net.chatbridge.gateway.plist"
            plist.parent.mkdir(parents=True)
            plist.touch()
            with patch.object(dependency.Path, "home", return_value=home):
                with self.assertRaisesRegex(RuntimeError, "LaunchAgent"):
                    dependency.assert_installable(dependency.DEFAULT_URL)

    def test_occupied_port_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(dependency.Path, "home", return_value=Path(temporary)), \
             patch.object(dependency.subprocess, "run", return_value=SimpleNamespace(returncode=1)), \
             patch.object(dependency.socket, "socket") as probe:
            probe.return_value.__enter__.return_value.bind.side_effect = OSError("busy")
            with self.assertRaisesRegex(RuntimeError, "port"):
                dependency.assert_installable(dependency.DEFAULT_URL)

    def test_digest_checked_before_extract_or_execute(self):
        response = io.BytesIO(b"wrong archive")
        response.geturl = lambda: dependency.RELEASE_URL
        with patch.object(dependency, "assert_installable"), \
             patch.object(dependency.urllib.request, "urlopen", return_value=response), \
             patch.object(dependency, "extract_release") as extract, \
             patch.object(dependency, "install") as install:
            with self.assertRaisesRegex(RuntimeError, "SHA256"):
                dependency.install_pinned()
            extract.assert_not_called()
            install.assert_not_called()

    def test_verified_archive_installs_from_distribution_root(self):
        payload = archive_bytes()
        response = io.BytesIO(payload)
        response.geturl = lambda: dependency.RELEASE_URL
        with patch.object(dependency, "assert_installable"), \
             patch.object(dependency, "RELEASE_SHA256", hashlib.sha256(payload).hexdigest()), \
             patch.object(dependency.urllib.request, "urlopen", return_value=response), \
             patch.object(dependency, "install", side_effect=lambda source, **kwargs: self.assertTrue((source / "scripts/installer.py").is_file()) or {}) as install:
            dependency.install_pinned("http://localhost:9999")
            root = install.call_args.args[0]
            self.assertEqual(root.name, dependency.RELEASE_DIRECTORY)
            self.assertEqual(install.call_args.kwargs["url"], "http://localhost:9999")
        self.assertFalse(root.exists())

    def test_rejects_traversal_links_devices_and_bombs(self):
        for name, kind in (("../escape", tarfile.REGTYPE),
                           ("/absolute", tarfile.REGTYPE),
                           (dependency.RELEASE_DIRECTORY + "/../escape", tarfile.REGTYPE),
                           (None, tarfile.SYMTYPE), (None, tarfile.LNKTYPE), (None, tarfile.CHRTYPE)):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / "archive.gz"
                archive.write_bytes(archive_bytes(name, kind))
                with self.assertRaises(RuntimeError):
                    dependency.extract_release(archive, root / "source")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive.gz"
            archive.write_bytes(archive_bytes(size=4096))
            with patch.object(dependency, "MAX_EXPANDED", 1), self.assertRaises(RuntimeError):
                dependency.extract_release(archive, root / "source")

    def test_installer_keeps_interactive_stdio_and_reports_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("install.sh", "LICENSE", "scripts/installer.py"):
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.touch()
            (root / "pyproject.toml").write_text('name = "chatbridge-gateway"\n')
            with patch.object(dependency, "assert_installable"), \
                 patch.object(dependency.subprocess, "run", side_effect=subprocess.TimeoutExpired("installer", 1800)) as run:
                with self.assertRaisesRegex(RuntimeError, "timed out"):
                    dependency.install(root)
                self.assertNotIn("capture_output", run.call_args.kwargs)
                self.assertNotIn("stdin", run.call_args.kwargs)
                self.assertEqual(run.call_args.kwargs["timeout"], 1800)

    def test_download_size_limit_stops_before_execution(self):
        response = io.BytesIO(b"too much")
        response.geturl = lambda: dependency.RELEASE_URL
        with patch.object(dependency, "assert_installable"), \
             patch.object(dependency, "MAX_ARCHIVE", 1), \
             patch.object(dependency.urllib.request, "urlopen", return_value=response), \
             patch.object(dependency, "install") as install:
            with self.assertRaisesRegex(RuntimeError, "size or time"):
                dependency.install_pinned()
            install.assert_not_called()

    def test_cli_default_and_opt_out_plan_on_python39(self):
        script = Path(installer.__file__)
        for flags, expected in (([], "reuse_or_install_pinned"), (["--without-chatbridge"], "skip_setup_preserve_existing")):
            result = subprocess.run(["/usr/bin/python3", str(script), "--plan", *flags], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)

    def test_bootstrap_runs_before_mac_control_uv_lookup(self):
        with patch.object(installer, "paths", return_value={}), \
             patch.object(installer.sys, "platform", "darwin"), \
             patch.object(dependency, "ensure") as ensure, \
             patch.object(installer, "find_uv", side_effect=lambda: (_ for _ in ()).throw(RuntimeError("stop after bootstrap"))):
            with self.assertRaisesRegex(RuntimeError, "stop after bootstrap"):
                installer.install(Path("unused"))
            ensure.assert_called_once()
