"""BF-16: isolated supervisor tests; never update an actual Mac/LaunchAgent."""
from __future__ import annotations
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from mac_control import self_update
from scripts import self_update_watchdog as watchdog


class SelfUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="bf16-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = (Path(temporary.name) / "MacControlMCP").resolve()
        self.data = self.root / "data/run"
        self.data.mkdir(parents=True)
        self.release_a = self.root / "releases/aaa"
        self.release_b = self.root / "releases/bbb"
        self.release_a.mkdir(parents=True)
        self.release_b.mkdir(parents=True)
        (self.release_a / "scripts").mkdir()
        (self.release_b / "scripts").mkdir()
        (self.release_a / "scripts/install_mac_control.py").write_text('print("old")')
        (self.release_a / "scripts/maccontrol_manager.py").write_text('print("manager")')
        (self.release_a / "scripts/self_update_watchdog.py").write_text('print("watchdog")')
        (self.root / 'current').symlink_to(self.release_a)
        self.report = []
        pid_patch = patch.object(watchdog, "_service_pid", return_value=12345)
        pid_patch.start()
        self.addCleanup(pid_patch.stop)

    def switch(self):
        (self.root / "current").unlink()
        (self.root / "current").symlink_to(self.release_b)
        (self.root / "previous").symlink_to(self.release_a)

    def test_success_after_mcp_restart_returns_verified_result(self):
        def update(*args, **kwargs):
            self.switch()
            return 0
        with patch.object(watchdog, "_preflight_health", return_value=True), \
             patch.object(watchdog, "_service_pid", side_effect=[12345, 23456]), \
             patch.object(watchdog, "_health", return_value=True), \
             patch.object(watchdog, "_update", side_effect=update) as cmd, \
             patch.object(watchdog, "_rollback") as rollback:
            result = watchdog.run_transaction(self.root, self.release_a, False, self.report.append)
        self.assertEqual(result, "succeeded")
        self.assertIn("verified", self.report)
        cmd.assert_called_once()
        rollback.assert_not_called()

    def test_new_release_fails_health_rolls_back_via_old_installer(self):
        def update(*args, **kwargs):
            self.switch()
            return 0
        def rollback(root, baseline):
            self.assertEqual(baseline, self.release_a)
            (root / "current").unlink()
            (root / "current").symlink_to(self.release_a)
        with patch.object(watchdog, "_preflight_health", return_value=True), \
             patch.object(watchdog, "_poll_health", side_effect=[False, True]), \
             patch.object(watchdog, "_update", side_effect=update), \
             patch.object(watchdog, "_rollback", side_effect=rollback) as did_rollback:
            outcome = watchdog.run_transaction(self.root, self.release_a, False, self.report.append)
        self.assertEqual(outcome, "rolled_back")
        self.assertIn("rolling_back", self.report)
        did_rollback.assert_called_once_with(self.root, self.release_a)

    def test_update_zero_without_release_switch_never_reports_success(self):
        with patch.object(watchdog, "_preflight_health", return_value=True), \
             patch.object(watchdog, "_update", return_value=0), \
             patch.object(watchdog, "_rollback") as rollback:
            outcome = watchdog.run_transaction(self.root, self.release_a, False,
                                               self.report.append)
        self.assertEqual(outcome, "failed")
        rollback.assert_not_called()

    def test_update_failure_before_switch_never_rolls_back(self):
        with patch.object(watchdog, "_preflight_health", return_value=True), \
             patch.object(watchdog, "_update", return_value=1), \
             patch.object(watchdog, "_rollback") as rollback:
            outcome = watchdog.run_transaction(self.root, self.release_a, False, self.report.append)
        self.assertEqual(outcome, "failed")
        rollback.assert_not_called()
        self.assertEqual((self.root / 'current').resolve(), self.release_a)

    def test_unknown_previous_pointer_refuses_destructive_rollback(self):
        def update(*args, **kwargs):
            (self.root / "current").unlink()
            (self.root / "current").symlink_to(self.release_b)
            (self.root / "previous").symlink_to(self.release_b)
            return 1
        with patch.object(watchdog, "_preflight_health", return_value=True), \
             patch.object(watchdog, "_update", side_effect=update), \
             patch.object(watchdog, "_rollback") as rollback:
            outcome = watchdog.run_transaction(self.root, self.release_a, False, self.report.append)
        self.assertEqual(outcome, "rollback_failed")
        rollback.assert_not_called()

    def test_preflight_failure_never_calls_update(self):
        with patch.object(watchdog, "_preflight_health", return_value=False), \
             patch.object(watchdog, "_update") as update:
            outcome = watchdog.run_transaction(self.root, self.release_a, False, self.report.append)
        self.assertEqual(outcome, "failed")
        update.assert_not_called()

    def test_new_release_reuses_old_pid_and_is_rejected(self):
        def update(*args, **kwargs):
            self.switch()
            return 0
        with patch.object(watchdog, "_preflight_health", return_value=True), \
             patch.object(watchdog, "_health", return_value=True), \
             patch.object(watchdog, "_update", side_effect=update), \
             patch.object(watchdog, "_rollback") as rollback:
            outcome = watchdog.run_transaction(self.root, self.release_a, False,
                                              self.report.append, health_timeout=0)
        self.assertEqual(outcome, "rollback_failed")
        rollback.assert_called_once()

    def test_health_checks_owned_status_and_authenticated_challenge(self):
        with patch.object(watchdog, "_owned_running", return_value=True) as ownership, \
             patch.object(watchdog, "_endpoint_responds", return_value=True) as endpoint:
            self.assertTrue(watchdog._health(self.root))
        ownership.assert_called_once_with(self.root)
        endpoint.assert_called_once_with(self.root)

    def test_status_reports_lost_worker_not_success(self):
        self_update._record(self.root, {"job_id": "abc", "state": "running", "pid": 99999999})
        with patch.object(self_update, "_pid_alive", return_value=False):
            result = self_update.status(self.root)
        self.assertEqual(result["state"], "worker_missing")

    def test_status_rejects_symlinked_journal(self):
        directory = self.root / 'data/run/self-update'
        directory.mkdir()
        (directory / 'status.json').symlink_to(self.root / 'current')
        with self.assertRaisesRegex(RuntimeError, "journal|symlink"):
            self_update.status(self.root)

    def test_concurrent_start_refuses_without_launching_second_worker(self):
        with patch.object(self_update, '_owned_preflight'), \
             patch.object(self_update, '_spawn', return_value=43221) as spawn:
            first = self_update.start(self.root, self.release_a, False)
            with self.assertRaisesRegex(RuntimeError, 'already|progress|busy'):
                self_update.start(self.root, self.release_a, False)
        self.assertEqual(first['state'], 'scheduled')
        spawn.assert_called_once()

    def test_spawn_is_independent_and_inherits_lock_fd(self):
        with patch.object(self_update, '_owned_preflight'), \
             patch.object(self_update.subprocess, 'Popen', return_value=SimpleNamespace(pid=55)) as popen:
            result = self_update.start(self.root, self.release_a, False)
        self.assertEqual(result['state'], 'scheduled')
        args, kwargs = popen.call_args
        self.assertTrue(kwargs['start_new_session'])
        self.assertTrue(kwargs['pass_fds'])
        self.assertIn('--worker', args[0])


    def test_with_chatbridge_never_reports_success_when_owned_version_unverified(self):
        """Regression: watchdog used to report SUCCESS while ChatBridge stayed b12."""
        def update(*_):
            self.switch()
            return 0

        def rollback(root, _baseline):
            (root / "current").unlink()
            (root / "current").symlink_to(self.release_a)

        with patch.object(watchdog, "_preflight_health", return_value=True), \
             patch.object(watchdog, "_update", side_effect=update), \
             patch.object(watchdog, "_poll_health", return_value=True), \
             patch.object(watchdog, "_rollback", side_effect=rollback) as restored:
            outcome = watchdog.run_transaction(
                self.root, self.release_a, True, self.report.append)
        self.assertEqual(outcome, "rolled_back")
        self.assertNotIn("verified", self.report)
        restored.assert_called_once_with(self.root, self.release_a)

    def test_with_chatbridge_success_requires_verified_latest_owned_service(self):
        def update(*_):
            self.switch()
            return 0

        with patch.object(watchdog, "_preflight_health", return_value=True), \
             patch.object(watchdog, "_update", side_effect=update), \
             patch.object(watchdog, "_poll_health", return_value=True), \
             patch.object(watchdog, "_verify_latest_owned_chatbridge", return_value=True) as verify:
            outcome = watchdog.run_transaction(
                self.root, self.release_a, True, self.report.append)
        self.assertEqual(outcome, "succeeded")
        verify.assert_called_once_with(self.root)

    def test_chatbridge_opt_out_never_triggers_latest_version_lookup(self):
        def update(*_):
            self.switch()
            return 0

        with patch.object(watchdog, "_preflight_health", return_value=True), \
             patch.object(watchdog, "_update", side_effect=update), \
             patch.object(watchdog, "_poll_health", return_value=True), \
             patch.object(watchdog, "_verify_latest_owned_chatbridge") as verify:
            outcome = watchdog.run_transaction(
                self.root, self.release_a, False, self.report.append)
        self.assertEqual(outcome, "succeeded")
        verify.assert_not_called()


    def test_latest_owned_chatbridge_checks_exact_source_and_runtime_versions(self):
        from scripts import setup_chatbridge_dependency as bridge

        source = self.root / "deps/chatbridge-source"
        source.mkdir(parents=True)
        (source / "pyproject.toml").write_text('version = "0.2.0b12"\n')
        with patch.object(bridge, "verify_managed_install") as owner, \
             patch.object(bridge, "managed_paths",
                          return_value=(source, self.root, self.root)), \
             patch.object(bridge, "managed_installed_runtime_version",
                          return_value="0.2.0b12") as runtime, \
             patch.object(bridge, "latest_published_release",
                          return_value={"version": "0.2.0b20"}) as official:
            self.assertFalse(watchdog._verify_latest_owned_chatbridge(self.root))
            (source / "pyproject.toml").write_text('version = "0.2.0b20"\n')
            runtime.return_value = "0.2.0b20"
            self.assertTrue(watchdog._verify_latest_owned_chatbridge(self.root))
            owner.assert_called()
            official.assert_called()
            runtime.assert_called()

    def test_source_runtime_version_mismatch_fails_closed(self):
        from scripts import setup_chatbridge_dependency as bridge

        source = self.root / "deps/chatbridge-source"
        source.mkdir(parents=True)
        (source / "pyproject.toml").write_text('version = "0.2.0b12"\n')
        with patch.object(bridge, "verify_managed_install"), \
             patch.object(bridge, "managed_paths",
                          return_value=(source, self.root, self.root)), \
             patch.object(bridge, "managed_installed_runtime_version",
                          return_value="0.2.0b20"), \
             patch.object(bridge, "latest_published_release") as official:
            self.assertFalse(watchdog._verify_latest_owned_chatbridge(self.root))
            official.assert_not_called()


if __name__ == '__main__':
    unittest.main()
