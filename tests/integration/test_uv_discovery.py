"""Fresh-Mac uv discovery without modifying PATH or installing anything."""
from contextlib import ExitStack
import os
import platform
import subprocess
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import install_mac_control as installer, release_preflight as preflight
from scripts import runtime_tools


class UvDiscoveryTests(unittest.TestCase):
    def setUp(self):
        system = patch.object(platform, "system", return_value="Linux")
        system.start()
        self.addCleanup(system.stop)

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


class NativeUvDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target, name, value in ((platform, "system", "Darwin"),
                                    (platform, "machine", "arm64"),
                                    (runtime_tools.shutil, "which", "/intel/bin/uv"),
                                    (runtime_tools.Path, "home", Path("/home/test")),
                                    (runtime_tools.Path, "is_file", True),
                                    (runtime_tools.os, "access", True)):
            self.stack.enter_context(patch.object(target, name, return_value=value))

    def test_apple_silicon_skips_intel_path_for_working_native_fallback(self):
        def probe(args, **kwargs):
            return SimpleNamespace(returncode=0 if args == ["/usr/bin/arch", "-arm64", "/opt/homebrew/bin/uv", "--version"] else 1)
        with patch.object(subprocess, "run", side_effect=probe):
            self.assertEqual(runtime_tools.find_uv(), "/opt/homebrew/bin/uv")

    def test_apple_silicon_rejects_all_incompatible_or_broken_uv(self):
        with patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            self.assertIsNone(runtime_tools.find_uv())

    def test_rosetta_detects_hardware_before_probing_native_uv(self):
        def probe(args, **kwargs):
            if args == ["/usr/sbin/sysctl", "-n", "hw.optional.arm64"]:
                return SimpleNamespace(returncode=0, stdout="1\n")
            return SimpleNamespace(returncode=0 if args[2] == "/home/test/.local/bin/uv" else 1)
        with patch.object(platform, "machine", return_value="x86_64"), \
             patch.object(subprocess, "run", side_effect=probe):
            self.assertEqual(runtime_tools.find_uv(), "/home/test/.local/bin/uv")

    def test_intel_mac_keeps_path_precedence(self):
        with patch.object(platform, "machine", return_value="x86_64"), \
             patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="0\n")):
            self.assertEqual(runtime_tools.find_uv(), "/intel/bin/uv")

    def test_native_path_precedence_and_read_only_probe(self):
        with patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(runtime_tools.find_uv(), "/intel/bin/uv")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/arch", "-arm64", "/intel/bin/uv", "--version"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertEqual(run.call_args.kwargs["timeout"], 5)

    def test_chatbridge_native_uv_is_found_outside_path(self):
        uv = "/home/test/.local/share/chatbridge/tools/uv/aarch64-apple-darwin/uv"
        with patch.object(subprocess, "run", side_effect=lambda args, **kwargs: SimpleNamespace(returncode=0 if args[2] == uv else 1)):
            self.assertEqual(runtime_tools.find_uv(), uv)

    def test_intel_mac_can_find_chatbridge_uv_outside_path(self):
        uv = "/home/test/.local/share/chatbridge/tools/uv/x86_64-apple-darwin/uv"
        with patch.object(platform, "machine", return_value="x86_64"), \
             patch.object(runtime_tools.shutil, "which", return_value=None), \
             patch.object(runtime_tools.os, "access", side_effect=lambda path, mode: str(path) == uv), \
             patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="0\n")):
            self.assertEqual(runtime_tools.find_uv(), uv)

    def test_native_candidates_must_be_executable_files(self):
        for target, name in ((runtime_tools.Path, "is_file"), (runtime_tools.os, "access")):
            with self.subTest(check=name), \
                 patch.object(target, name, return_value=False), \
                 patch.object(subprocess, "run") as run:
                self.assertIsNone(runtime_tools.find_uv())
                run.assert_not_called()

    def test_native_probe_errors_skip_candidate(self):
        for failure in (OSError("unavailable"), subprocess.TimeoutExpired("uv", 5)):
            with self.subTest(failure=type(failure).__name__), \
                 patch.object(subprocess, "run", side_effect=failure):
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
