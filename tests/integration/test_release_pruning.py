"""Release retention and shared tmux discovery regression checks."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import install_mac_control as installer
from scripts import maccontrol_manager as manager
from mac_control import tmux_runtime
from mac_control.legacy_handlers import package_ops, command_plugins


class Registry:
    def __init__(self):
        self.tools = {}
    def tool(self, **kwargs):
        def bind(fn):
            self.tools[fn.__name__] = fn
            return fn
        return bind


class PackageCapabilityTests(unittest.TestCase):
    def test_pathless_launchd_finds_homebrew_tmux_and_terminal_agrees(self):
        path = "/opt/homebrew/bin/tmux"
        with patch.object(tmux_runtime.shutil, "which", return_value=None), \
             patch.object(tmux_runtime.Path, "is_file", return_value=True), \
             patch.object(tmux_runtime.os, "access", return_value=True):
            self.assertEqual(tmux_runtime.locate(), path)
        reg = Registry()
        package_ops.register(reg)
        with patch.object(package_ops, "brew", return_value=None), \
             patch.object(package_ops, "locate_tmux", return_value=path), \
             patch.object(command_plugins, "locate_tmux", return_value=path):
            self.assertEqual(reg.tools["package_capabilities"]()["tmux_path"],path)
            self.assertEqual(command_plugins._tmux_available(),path)

    def test_new_binary_detected_without_restart(self):
        reg = Registry()
        package_ops.register(reg)
        with patch.object(package_ops, "brew", return_value=None), \
             patch.object(package_ops, "locate_tmux",
                          side_effect=[None, "/opt/homebrew/bin/tmux"]):
            self.assertIsNone(reg.tools["package_capabilities"]()["tmux_path"])
            self.assertEqual(reg.tools["package_capabilities"]()["tmux_path"],
                             "/opt/homebrew/bin/tmux")

    def test_unexecutable_tmux_is_not_reported(self):
        with patch.object(tmux_runtime.shutil, "which", return_value=None), \
             patch.object(tmux_runtime.Path, "is_file", return_value=True), \
             patch.object(tmux_runtime.os, "access", return_value=False):
            self.assertIsNone(tmux_runtime.locate())


class RetentionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / "MacControlMCP"
        (self.root / "releases").mkdir(parents=True)
        (self.root / "data/run").mkdir(parents=True)
        (self.root / ".mac-control-installer-owned").write_text("owned")
        self.external = self.root.parent / "AgentWorkspace"
        (self.external / "projects").mkdir(parents=True)
        (self.external / "projects/important.txt").write_text("valuable")
        self.current = self.release("source-111111111111")
        self.previous = self.release("source-222222222222")
        self.old = self.release("source-333333333333")
        self.older = self.release("abcdefabcdef-123456789abcd")
        (self.root / "current").symlink_to(self.current)
        (self.root / "previous").symlink_to(self.previous)

    def release(self, name):
        path = self.root / "releases" / name
        (path / "bin").mkdir(parents=True)
        (path / ".venv/bin").mkdir(parents=True)
        (path / "bin/mac-control-stdio-mcp.sh").write_text("mcp")
        (path / ".venv/bin/python").write_text("python")
        (path / ".venv/lib.txt").write_text("fixture" * 50)
        (path / "build/gui_clipboard_paste").mkdir(parents=True)
        return path

    def test_dry_run_does_not_delete(self):
        result = installer._release_cleanup_locked(self.root, dry_run=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(len(result["protected"]), 2)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertGreater(result["reclaimable_bytes"], 0)
        self.assertTrue(self.old.exists() and self.older.exists())

    def test_auto_cleanup_keeps_current_previous_and_projects(self):
        result = installer._release_cleanup_locked(self.root, dry_run=False)
        self.assertEqual(len(result["removed"]), 2)
        self.assertEqual(result["errors"], [])
        self.assertFalse(self.old.exists() or self.older.exists())
        self.assertTrue(self.current.is_dir() and self.previous.is_dir())
        self.assertEqual((self.external / "projects/important.txt").read_text(),
                         "valuable")

    def test_rollback_protection(self):
        (self.root / "current").unlink()
        (self.root / "previous").unlink()
        (self.root / "current").symlink_to(self.old)
        (self.root / "previous").symlink_to(self.current)
        installer._release_cleanup_locked(self.root, dry_run=False)
        self.assertTrue(self.old.is_dir() and self.current.is_dir())
        self.assertFalse(self.previous.exists())

    def test_unrecognized_directory_and_symlink_skipped(self):
        foreign = self.root.parent / "foreign"
        foreign.mkdir()
        (foreign / "important").write_text("keep")
        (self.root / "releases/source-444444444444").symlink_to(foreign)
        unknown = self.root / "releases/my-project"
        unknown.mkdir()
        (unknown / "data").write_text("keep")
        extra = self.release("source-555555555555")
        (extra / "custom-content").mkdir()
        result = installer._release_cleanup_locked(self.root, dry_run=False)
        self.assertGreaterEqual(len(result["skipped"]), 3)
        self.assertTrue(extra.exists() and unknown.exists())
        self.assertEqual((foreign / "important").read_text(), "keep")

    def test_symlinked_virtualenv_is_skipped(self):
        candidate = self.release("source-666666666666")
        external = self.root.parent / "outside-venv"
        external.mkdir()
        (external / "keep").write_text("external")
        import shutil
        shutil.rmtree(candidate / ".venv")
        (candidate / ".venv").symlink_to(external)
        result = installer._release_cleanup_locked(self.root, dry_run=False)
        self.assertIn(str(candidate), {item["path"] for item in result["skipped"]})
        self.assertTrue(candidate.exists())
        self.assertEqual((external / "keep").read_text(), "external")

    def test_dangling_previous_refuses_delete(self):
        (self.root / "previous").unlink()
        (self.root / "previous").symlink_to(self.root.parent / "missing")
        with self.assertRaisesRegex(RuntimeError, "Refusing"):
            installer._release_cleanup_locked(self.root, dry_run=False)
        self.assertTrue(self.old.exists())

    def test_pending_activation_refuses_delete(self):
        (self.root / ".pending-current-unsafe").write_text("pending")
        with self.assertRaisesRegex(RuntimeError, "Activation"):
            installer._release_cleanup_locked(self.root, dry_run=False)
        self.assertTrue(self.old.exists())

    def test_missing_current_pointer_refuses_cleanup(self):
        (self.root / "current").unlink()
        with self.assertRaisesRegex(RuntimeError, "No verified active release"):
            installer._release_cleanup_locked(self.root, dry_run=False)
        self.assertTrue(self.old.exists())

    def test_missing_ownership_marker_refuses_delete(self):
        (self.root / ".mac-control-installer-owned").unlink()
        with self.assertRaisesRegex(RuntimeError, "marker"):
            installer._release_cleanup_locked(self.root, dry_run=False)
        self.assertTrue(self.old.exists())

    def test_cli_explicit_yes_required_for_deletion(self):
        with patch.object(manager, "installed", return_value=0) as runner:
            self.assertEqual(manager.main(["--root", str(self.root),
                                           "releases", "cleanup"]), 0)
            runner.assert_called_with(self.root, "--releases-cleanup")
            self.assertEqual(manager.main(["--root", str(self.root),
                                           "releases", "cleanup", "--yes"]), 0)
            runner.assert_called_with(self.root, "--releases-cleanup", "--yes")
            with self.assertRaisesRegex(ValueError, "Choose"):
                manager.main(["--root", str(self.root), "releases",
                              "cleanup", "--dry-run", "--yes"])


if __name__ == "__main__":
    unittest.main()
