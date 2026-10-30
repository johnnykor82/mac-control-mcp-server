"""Installer/watcher cutover and rollback use fake services, never launchd."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import install_mac_control as installer


class RestartError(RuntimeError):
    def __init__(self, stopped):
        super().__init__("remote restart failed")
        self.service_stopped = stopped


class WatcherInstallLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "MCP Server"
        self.root.mkdir(mode=0o700)
        self.data = self.root / "data"
        self.data.mkdir(mode=0o700)
        self.old = self.release("old", watcher=True)
        self.new = self.release("new", watcher=True)
        self.older = self.release("older", watcher=False)
        (self.root / "current").symlink_to(self.old)
        (self.root / "previous").symlink_to(self.older)
        (self.root / ".mac-control-installer-owned").write_text("owned\n")
        (self.data / "feature_flags.json").write_text(json.dumps({
            "watcher": True, "background_browser": True,
        }))
        self.database = self.data / "watcher/tasks.sqlite3"
        self.database.parent.mkdir(mode=0o700)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, state TEXT)")
            connection.execute("INSERT INTO tasks VALUES ('retained-task', 'scheduled')")
            connection.commit()
        self.events = []
        self.watcher = Mock()
        self.watcher.status.return_value = {"status": "running"}
        self.watcher.ensure.side_effect = lambda root: self.record("watcher.ensure", root)
        self.watcher.start.side_effect = lambda root: self.record("watcher.start", root)
        self.watcher.stop_if_installed.side_effect = lambda root: self.record("watcher.stop", root)
        self.watcher.remove_if_installed.side_effect = lambda root: self.record("watcher.remove", root)
        self.remote = Mock()
        self.remote.RestartError = RestartError
        self.remote.status.return_value = {"status": "running"}
        self.remote.restart_if_installed.side_effect = lambda root: self.record("remote.restart", root)
        self.remote.start.side_effect = lambda root: self.record("remote.start", root)
        self.addCleanup(patch.stopall)
        patch.object(installer, "_watcher_plist_exists", return_value=True).start()
        patch.object(installer, "_watcher_service_module", return_value=self.watcher).start()
        patch.object(installer, "_remote_plist_exists", return_value=True).start()
        patch.object(installer, "_remote_service_module", return_value=self.remote).start()
        patch.object(installer.sys, "platform", "darwin").start()
        patch.object(installer.os, "geteuid", return_value=501).start()
        patch.object(installer.Path, "home", return_value=self.root.parent / "fake-home").start()

    def release(self, name, *, watcher):
        release = self.root / "releases" / name
        (release / "bin").mkdir(parents=True)
        (release / "bin/mac-control-stdio-mcp.sh").write_text("test\n")
        if watcher:
            runtime = release / "src/mac_control/watcher_runtime"
            runtime.mkdir(parents=True)
            (runtime / "__main__.py").write_text("pass\n")
        return release

    def record(self, operation, root):
        self.events.append((operation, (root / "current").resolve()))
        return {"status": "running", "changed": True}

    def assert_database_preserved(self):
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT id, state FROM tasks").fetchall(),
                             [("retained-task", "scheduled")])

    def assert_target_started(self, target):
        starts = [event for event in self.events if event[0] in ("watcher.start", "watcher.ensure")]
        self.assertTrue(starts, "Enabled watcher was not started")
        self.assertEqual(starts[-1][1], target)

    def install(self, *, with_chatbridge=True, with_watcher=True):
        paths = {"root": self.root, "data": self.data, "releases": self.root / "releases",
                 "release": self.new, "current": self.root / "current"}
        with patch.object(installer, "paths", return_value=paths), \
             patch.object(installer, "find_uv", return_value="/fake/uv"), \
             patch.object(installer, "smoke"), \
             patch("scripts.setup_chatbridge_dependency.ensure", return_value={"status": "ready"}):
            return installer.install(self.root, with_chatbridge=with_chatbridge,
                                     with_gui=False, with_watcher=with_watcher)

    def test_update_stops_watcher_before_pointer_then_starts_target(self):
        installer._activate_release(self.root, self.new)
        self.assertEqual(self.events[0], ("watcher.stop", self.old))
        self.assert_target_started(self.new)
        self.assertEqual((self.root / "current").resolve(), self.new)
        self.assertEqual((self.root / "previous").resolve(), self.old)
        self.assert_database_preserved()

    def test_update_ensures_enabled_watcher_even_without_previous_agent(self):
        with patch.object(installer, "_watcher_plist_exists", return_value=False):
            installer._activate_release(self.root, self.new)
        self.watcher.stop_if_installed.assert_not_called()
        self.watcher.ensure.assert_called_once_with(self.root)
        self.assert_target_started(self.new)
        self.assert_database_preserved()

    def test_rollback_to_release_without_watcher_removes_autostart_and_preserves_tasks(self):
        with patch.object(installer, "smoke"):
            result = installer.rollback(self.root)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual((self.root / "current").resolve(), self.older)
        self.watcher.remove_if_installed.assert_called_once_with(self.root)
        self.watcher.start.assert_not_called()
        self.watcher.ensure.assert_not_called()
        self.assert_database_preserved()

    def test_watcher_failure_restores_pointers_and_remote_running_release(self):
        def watcher_start(root):
            current = (root / "current").resolve()
            self.events.append(("watcher.start", current))
            if current == self.new:
                raise RuntimeError("watcher start failed")
            return {"status": "running"}
        self.watcher.start.side_effect = watcher_start
        self.watcher.ensure.side_effect = watcher_start
        with self.assertRaisesRegex(RuntimeError, "watcher"):
            installer._activate_release(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertEqual((self.root / "previous").resolve(), self.older)
        self.assertIn(("remote.restart", self.new), self.events)
        self.assertIn(("remote.restart", self.old), self.events)
        self.assert_target_started(self.old)
        self.assert_database_preserved()

    def test_remote_recovery_still_runs_when_old_watcher_cannot_restart(self):
        self.watcher.ensure.side_effect = RuntimeError("replacement watcher failed")
        self.watcher.start.side_effect = RuntimeError("old watcher failed")
        with self.assertRaises(RuntimeError):
            installer._activate_release(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertIn(("remote.restart", self.old), self.events)
        self.assert_database_preserved()

    def test_interrupted_watcher_replacement_is_stopped_before_old_restart(self):
        loaded = {"release": self.old}
        def stop(root):
            loaded["release"] = None
            return self.record("watcher.stop", root)
        def ensure(root):
            loaded["release"] = (root / "current").resolve()
            raise KeyboardInterrupt()
        def start(root):
            # Real ensure/start preserves an already running owned daemon.
            if loaded["release"] is None:
                loaded["release"] = (root / "current").resolve()
            return self.record("watcher.start", root)
        self.watcher.stop_if_installed.side_effect = stop
        self.watcher.ensure.side_effect = ensure
        self.watcher.start.side_effect = start
        with self.assertRaises(KeyboardInterrupt):
            installer._activate_release(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertEqual(loaded["release"], self.old)
        self.assertIn(("remote.restart", self.old), self.events)
        self.assert_database_preserved()

    def test_install_new_watcher_failure_restores_previous_release(self):
        self.watcher.ensure.side_effect = RuntimeError("watcher ensure failed")
        with patch.object(installer, "_watcher_plist_exists", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "watcher"):
                self.install()
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertEqual((self.root / "previous").resolve(), self.older)
        self.assert_database_preserved()

    def test_first_install_starts_only_after_marker_and_pointer_exist(self):
        (self.root / "current").unlink()
        (self.root / "previous").unlink()
        (self.root / ".mac-control-installer-owned").unlink()
        def ensure(root):
            self.assertTrue((root / ".mac-control-installer-owned").is_file())
            self.assertEqual((root / "current").resolve(), self.new)
            return self.record("watcher.ensure", root)
        self.watcher.ensure.side_effect = ensure
        with patch.object(installer, "_watcher_plist_exists", return_value=False):
            result = self.install()
        self.assertEqual(result["status"], "installed")
        self.assert_target_started(self.new)
        self.assert_database_preserved()

    def test_without_watcher_removes_login_agent_even_without_chatbridge_setup(self):
        result = self.install(with_chatbridge=False, with_watcher=False)
        self.assertEqual(result["status"], "installed")
        self.watcher.remove_if_installed.assert_called()
        self.watcher.ensure.assert_not_called()
        self.watcher.start.assert_not_called()
        flags = json.loads((self.data / "feature_flags.json").read_text())
        self.assertIs(flags["watcher"], False)
        self.assert_database_preserved()

    def test_uninstall_removes_services_before_releases_but_preserves_tasks(self):
        def remove(root):
            self.assertTrue((root / "current").is_symlink())
            self.assertTrue(self.new.is_dir())
            self.assert_database_preserved()
            return self.record("watcher.remove", root)
        self.watcher.remove_if_installed.side_effect = remove
        with patch("scripts.setup_network.assert_public_route_safe_for_uninstall"):
            result = installer.uninstall(self.root)
        self.assertEqual(result["status"], "uninstalled")
        self.watcher.remove_if_installed.assert_called_once_with(self.root)
        self.remote.remove_if_installed.assert_called_once_with(self.root)
        self.assertFalse((self.root / "current").exists())
        self.assertFalse((self.root / "releases").exists())
        self.assert_database_preserved()


if __name__ == "__main__":
    unittest.main()
