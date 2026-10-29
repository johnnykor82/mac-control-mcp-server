"""Release pointers and owned remote service remain consistent across updates."""
import tempfile
import json
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import install_mac_control as installer


class RestartError(RuntimeError):
    def __init__(self, stopped):
        self.service_stopped = stopped


class InstallRemoteLifecycleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.old = self.release("old")
        self.new = self.release("new")
        self.older = self.release("older")
        (self.root / "current").symlink_to(self.old)
        (self.root / "previous").symlink_to(self.older)
        self.service = Mock()
        self.service.RestartError = RestartError
        self.service.status.return_value = {"status": "running"}
        self.exists = patch.object(installer, "_remote_plist_exists", return_value=True)
        self.module = patch.object(installer, "_remote_service_module", return_value=self.service)
        self.exists.start(); self.module.start()
        self.addCleanup(self.exists.stop); self.addCleanup(self.module.stop)

    def release(self, name):
        path = self.root / "releases" / name
        (path / "bin").mkdir(parents=True)
        (path / "bin/mac-control-stdio-mcp.sh").write_text("test")
        return path

    def test_switch_restarts_only_the_verified_loaded_service(self):
        installer._activate_release(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.new)
        self.assertEqual((self.root / "previous").resolve(), self.old)
        self.service.restart_if_installed.assert_called_once_with(self.root)

    def test_failed_restart_restores_pointers_and_previous_service(self):
        self.service.restart_if_installed.side_effect = RestartError(True)
        self.service.start.side_effect = lambda root: self.assertEqual((root / "current").resolve(), self.old)
        with self.assertRaises(RestartError):
            installer._activate_release(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertEqual((self.root / "previous").resolve(), self.older)
        self.service.start.assert_called_once_with(self.root)

    def test_unknown_deregistration_never_starts_another_service(self):
        self.service.restart_if_installed.side_effect = RestartError(None)
        with self.assertRaises(RestartError):
            installer._activate_release(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.service.start.assert_not_called()

    def test_unloaded_owned_service_is_not_started_by_update(self):
        self.service.status.return_value = {"status": "installed"}
        installer._activate_release(self.root, self.new)
        self.service.restart_if_installed.assert_not_called()
        self.service.start.assert_not_called()

    def test_concurrent_activation_cannot_overwrite_successful_second_release(self):
        concurrent = self.release("concurrent")
        restarting, allow_failure, second_done = threading.Event(), threading.Event(), threading.Event()
        errors = []
        count = []
        def restart(root):
            count.append(1)
            if len(count) == 1:
                restarting.set()
                if not allow_failure.wait(5):
                    raise AssertionError("Test did not release the first activation")
                raise RestartError(True)
        self.service.restart_if_installed.side_effect = restart
        def activate(target, done=None):
            try:
                installer._activate_release(self.root, target)
            except Exception as error:
                errors.append(error)
            finally:
                if done:
                    done.set()
        first = threading.Thread(target=activate, args=(self.new,))
        second = threading.Thread(target=activate, args=(concurrent, second_done))
        first.start()
        self.assertTrue(restarting.wait(3))
        second.start()
        try:
            self.assertFalse(second_done.wait(0.1), "Second activation bypassed the lifecycle lock")
        finally:
            allow_failure.set()
            first.join(5)
            second.join(5)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RestartError)
        self.assertEqual((self.root / "current").resolve(), concurrent)
        self.assertEqual((self.root / "previous").resolve(), self.old)

    def test_lifecycle_lock_is_private_and_timeout_is_bounded(self):
        with installer._lifecycle_lock(self.root, timeout=0):
            path = self.root / "data/run/install-lifecycle.lock"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            with self.assertRaisesRegex(RuntimeError, "another|Another|busy"):
                with installer._lifecycle_lock(self.root, timeout=0):
                    self.fail("Concurrent lifecycle operation acquired the lock")
        with installer._lifecycle_lock(self.root, timeout=0):
            self.assertTrue(path.is_file())

    def test_lifecycle_lock_symlink_is_not_followed(self):
        run = self.root / "data/run"
        run.mkdir(parents=True, mode=0o700)
        other = self.root / "unrelated"
        other.write_text("preserve")
        other.chmod(0o644)
        (run / "install-lifecycle.lock").symlink_to(other)
        with self.assertRaises((RuntimeError, OSError)):
            with installer._lifecycle_lock(self.root, timeout=0):
                self.fail("Symlink lock accepted")
        self.assertEqual(other.read_text(), "preserve")
        self.assertEqual(other.stat().st_mode & 0o777, 0o644)

    def test_lifecycle_lock_rejects_hardlinks_and_shared_permissions(self):
        run = self.root / "data/run"
        run.mkdir(parents=True, mode=0o700)
        path = run / "install-lifecycle.lock"
        path.write_text("")
        path.chmod(0o600)
        linked = run / "other-link"
        os.link(path, linked)
        with self.assertRaises((RuntimeError, PermissionError)):
            with installer._lifecycle_lock(self.root, timeout=0):
                self.fail("Hardlinked lock accepted")
        linked.unlink()
        path.chmod(0o644)
        with self.assertRaises((RuntimeError, PermissionError)):
            with installer._lifecycle_lock(self.root, timeout=0):
                self.fail("Shared lock accepted")

    def test_install_holds_common_lock_without_nested_acquisition(self):
        observed = []
        def provision(root, *args):
            with self.assertRaises(RuntimeError):
                with installer._lifecycle_lock(root, timeout=0):
                    self.fail("Install did not hold the lifecycle lock")
            installer._activate_release_locked(root, self.new)
            observed.append(True)
            return {"status": "installed"}
        with patch.object(installer, "_install_locked", side_effect=provision):
            self.assertEqual(installer.install(self.root)["status"], "installed")
        self.assertEqual(observed, [True])
        self.assertEqual((self.root / "current").resolve(), self.new)

    def test_unsupported_os_and_root_do_not_create_install_directories(self):
        fresh = self.root / "fresh"
        for platform, uid in (("linux", 501), ("darwin", 0)):
            with self.subTest(platform=platform, uid=uid), \
                 patch.object(installer.sys, "platform", platform), \
                 patch.object(installer.os, "geteuid", return_value=uid):
                with self.assertRaises(RuntimeError):
                    installer.install(fresh)
                self.assertFalse(fresh.exists())

    def test_keyboard_interrupt_restores_pointers_and_releases_lock(self):
        self.service.restart_if_installed.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            installer._activate_release(self.root, self.new)
        self.assertEqual((self.root / "current").resolve(), self.old)
        self.assertEqual((self.root / "previous").resolve(), self.older)
        self.service.start.assert_not_called()
        with installer._lifecycle_lock(self.root, timeout=0):
            pass

    def test_parallel_installs_serialize_feature_flag_provisioning(self):
        entered, release_first, second_done = threading.Event(), threading.Event(), threading.Event()
        calls, failures = [], []
        flags = self.root / "data/feature_flags.json"
        def provision(root, *args):
            index = len(calls)
            calls.append(index)
            previous = json.loads(flags.read_text()) if flags.exists() else {}
            if index == 0:
                entered.set()
                if not release_first.wait(5):
                    raise AssertionError("Test did not release install provisioning")
                previous["native_gui"] = True
            else:
                previous["background_browser"] = True
            flags.write_text(json.dumps(previous))
            return {"status": "installed"}
        def install(done=None):
            try:
                installer.install(self.root)
            except BaseException as error:
                failures.append(error)
            finally:
                if done:
                    done.set()
        with patch.object(installer, "_install_locked", side_effect=provision):
            first = threading.Thread(target=install)
            second = threading.Thread(target=install, args=(second_done,))
            first.start()
            self.assertTrue(entered.wait(3))
            second.start()
            try:
                self.assertFalse(second_done.wait(0.1))
                self.assertEqual(calls, [0])
            finally:
                release_first.set()
                first.join(5)
                second.join(5)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(json.loads(flags.read_text()),
                         {"native_gui": True, "background_browser": True})

    def test_rollback_and_uninstall_hold_lock_without_nested_acquisition(self):
        def assert_locked(root):
            with self.assertRaises(RuntimeError):
                with installer._lifecycle_lock(root, timeout=0):
                    self.fail("Lifecycle operation did not hold the common lock")
        with patch.object(installer, "smoke", side_effect=lambda target, data: assert_locked(self.root)):
            installer.rollback(self.root)
        (self.root / ".mac-control-installer-owned").write_text("owned")
        with patch.object(installer, "_uninstall_locked",
                          side_effect=lambda root: assert_locked(root) or {"status": "uninstalled"}):
            self.assertEqual(installer.uninstall(self.root)["status"], "uninstalled")


if __name__ == "__main__":
    unittest.main()
