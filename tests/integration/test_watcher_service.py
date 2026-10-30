"""Owned watcher LaunchAgent lifecycle; all launchd calls are fake."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import setup_watcher_service as service


class FakeLaunchd:
    def __init__(self):
        self.calls = []
        self.loaded = False
        self.plist = None
        self.bootstrap_fails = False
        self.running = True
        self.foreign = False
        self.stopping = False
        self.deregister_checks = 0

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        command = argv[1]
        stdout, stderr, code = "", "", 0
        if command == "print":
            if self.stopping and self.deregister_checks:
                self.deregister_checks -= 1
            elif self.stopping:
                self.loaded = False
            if self.loaded:
                config = plistlib.loads(self.plist.read_bytes())
                program = "/foreign/python" if self.foreign else config["ProgramArguments"][0]
                stdout = ("path = " + str(self.plist) + "\nprogram = " + program
                          + "\nstate = " + ("running" if self.running else "waiting")
                          + ("\npid = 12345\n" if self.running else "\n"))
            else:
                stderr, code = 'Could not find service "missing" in domain for user gui', 113
        elif command == "bootstrap":
            if self.stopping and self.loaded:
                raise AssertionError("Bootstrap before deregistration")
            self.plist = Path(argv[3])
            self.loaded = True
            self.stopping = False
            if self.bootstrap_fails:
                stderr, code = "Bootstrap failed", 5
        elif command == "bootout":
            self.stopping = True
        else:
            raise AssertionError("Unexpected operation: " + command)
        return subprocess.CompletedProcess(argv, code, stdout, stderr)


class WatcherServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.root = self.home / "MCP Server"
        self.root.mkdir(mode=0o700)
        self.data = self.root / "data"
        self.data.mkdir(mode=0o700)
        (self.root / ".mac-control-installer-owned").write_text("owned\n")
        self.release = self.root / "releases/test-release"
        (self.release / ".venv/bin").mkdir(parents=True)
        python = self.release / ".venv/bin/python"
        python.write_text("#!/bin/sh\nexit 0\n")
        python.chmod(0o700)
        runtime = self.release / "src/mac_control/watcher_runtime"
        runtime.mkdir(parents=True)
        (runtime / "__main__.py").write_text("pass\n")
        (self.root / "current").symlink_to(self.release)
        self.agents = self.home / "Library/LaunchAgents"
        self.plist = self.agents / (service.LABEL + ".plist")
        self.launchd = FakeLaunchd()
        self.addCleanup(patch.stopall)
        patch.object(service.sys, "platform", "darwin").start()
        patch.object(service.os, "geteuid", return_value=501).start()
        patch.object(service.subprocess, "run", side_effect=self.launchd).start()
        patch.object(service.time, "sleep").start()
        patch.dict(os.environ, {"HOME": str(self.home)}).start()

    def ensure(self):
        return service.ensure(self.root, launch_agents=self.agents)

    def test_ensure_installs_idle_capable_login_agent_without_credentials(self):
        result = self.ensure()
        self.assertEqual(result["status"], "running")
        self.assertTrue(result["created_plist"])
        config = plistlib.loads(self.plist.read_bytes())
        self.assertEqual(config["ProgramArguments"], [str(self.root / "current/.venv/bin/python"),
                         "-B", "-m", "mac_control.watcher_runtime", "run"])
        self.assertEqual(config["EnvironmentVariables"], {
            "MAC_CONTROL_DATA_ROOT": str(self.data), "PYTHONPATH": str(self.root / "current/src")})
        self.assertEqual(config["WorkingDirectory"], str(self.root))
        self.assertTrue(config["RunAtLoad"])
        self.assertTrue(config["KeepAlive"])
        self.assertEqual(config["Umask"], 0o077)
        self.assertEqual(self.plist.stat().st_mode & 0o777, 0o600)
        for key, filename in (("StandardOutPath", "watcher.stdout.log"),
                              ("StandardErrorPath", "watcher.stderr.log")):
            logfile = Path(config[key])
            self.assertEqual(logfile.name, filename)
            self.assertEqual(logfile.stat().st_mode & 0o777, 0o600)
            self.assertEqual(logfile.parent.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(argv[0] == "/bin/launchctl" for argv in self.launchd.calls))

    def test_repeated_ensure_preserves_running_job_and_plist(self):
        self.ensure()
        before = (self.plist.read_bytes(), self.plist.stat().st_mtime_ns)
        self.launchd.calls.clear()
        result = self.ensure()
        self.assertFalse(result["created_plist"])
        self.assertEqual(before, (self.plist.read_bytes(), self.plist.stat().st_mtime_ns))
        self.assertEqual([argv[1] for argv in self.launchd.calls], ["print"])

    def test_status_is_read_only_and_cli_emits_json(self):
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(service.main(["--root", str(self.root), "--launch-agents",
                                          str(self.agents), "--status"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "not_installed")
        self.assertFalse(self.agents.exists())
        self.assertFalse((self.data / "logs").exists())
        self.assertEqual(self.launchd.calls, [])

    def test_unknown_plist_and_foreign_job_are_preserved(self):
        self.agents.mkdir(parents=True)
        self.plist.write_bytes(plistlib.dumps({"Label": service.LABEL}))
        self.plist.chmod(0o600)
        before = self.plist.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "ownership"):
            self.ensure()
        self.assertEqual(self.plist.read_bytes(), before)
        self.assertEqual(self.launchd.calls, [])
        self.plist.unlink()
        self.ensure()
        self.launchd.foreign = True
        self.launchd.calls.clear()
        for operation in (self.ensure, lambda: service.remove_if_installed(self.root, launch_agents=self.agents)):
            with self.assertRaisesRegex(RuntimeError, "ownership"):
                operation()
        self.assertNotIn("bootout", [argv[1] for argv in self.launchd.calls])
        self.assertTrue(self.plist.exists())

    def test_symlink_and_insecure_logs_are_not_repaired(self):
        logs = self.data / "logs"
        logs.mkdir(mode=0o700)
        other = self.home / "unrelated"
        other.write_text("preserve")
        other.chmod(0o644)
        logfile = logs / "watcher.stdout.log"
        logfile.symlink_to(other)
        with self.assertRaises((RuntimeError, PermissionError)):
            self.ensure()
        logfile.unlink()
        logfile.write_text("preserve log")
        logfile.chmod(0o644)
        with self.assertRaises(PermissionError):
            self.ensure()
        self.assertEqual(other.read_text(), "preserve")
        self.assertEqual(logfile.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.launchd.calls, [])

    def test_unsafe_install_paths_rejected_before_launchd(self):
        (self.root / "current").unlink()
        (self.root / "current").symlink_to(self.home)
        with self.assertRaisesRegex(RuntimeError, "outside"):
            self.ensure()
        self.assertEqual(self.launchd.calls, [])

    def test_symlink_launch_agents_and_source_rejected(self):
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        self.agents.parent.mkdir()
        self.agents.symlink_to(elsewhere)
        with self.assertRaises(RuntimeError):
            self.ensure()
        self.agents.unlink()
        runtime = self.release / "src/mac_control/watcher_runtime"
        (runtime / "__main__.py").unlink()
        (runtime / "__main__.py").symlink_to(elsewhere / "main.py")
        with self.assertRaises(RuntimeError):
            self.ensure()
        self.assertEqual(self.launchd.calls, [])

    def test_missing_runtime_refuses_start_but_permits_status_stop_remove(self):
        self.ensure()
        (self.release / "src/mac_control/watcher_runtime/__main__.py").unlink()
        with self.assertRaises((OSError, RuntimeError)):
            self.ensure()
        self.assertEqual(service.status(self.root, launch_agents=self.agents)["status"], "running")
        self.assertEqual(service.stop_if_installed(self.root, launch_agents=self.agents)["status"], "stopped")
        self.assertTrue(self.plist.exists())
        self.assertEqual(service.remove_if_installed(self.root, launch_agents=self.agents)["status"], "removed")

    def test_standard_virtualenv_interpreter_symlink_is_supported(self):
        interpreter = self.home / "managed-python"
        interpreter.write_text("#!/bin/sh\nexit 0\n")
        interpreter.chmod(0o700)
        python = self.release / ".venv/bin/python"
        python.unlink()
        python.symlink_to(interpreter)
        self.assertEqual(self.ensure()["status"], "running")

    def test_unsafe_interpreter_is_rejected_before_launchd(self):
        (self.release / ".venv/bin/python").chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, "protected executable"):
            self.ensure()
        self.assertEqual(self.launchd.calls, [])
        self.assertFalse(self.plist.exists())

    def test_status_preserves_missing_log_and_missing_marker_refuses_mutation(self):
        self.ensure()
        logfile = self.data / "logs/watcher.stdout.log"
        logfile.unlink()
        self.assertEqual(service.status(self.root, launch_agents=self.agents)["status"], "running")
        self.assertFalse(logfile.exists())
        (self.root / ".mac-control-installer-owned").unlink()
        self.launchd.calls.clear()
        with self.assertRaises(FileNotFoundError):
            service.remove_if_installed(self.root, launch_agents=self.agents)
        self.assertEqual(self.launchd.calls, [])
        self.assertTrue(self.plist.exists())

    def test_failed_plist_write_does_not_leave_partial_agent(self):
        with patch("scripts.setup_remote_service.plistlib.dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.ensure()
        self.assertFalse(self.plist.exists())
        self.assertEqual(list(self.agents.iterdir()), [])
        self.assertFalse(self.launchd.loaded)

    def test_unrecognized_plist_environment_is_not_replaced(self):
        self.ensure()
        config = plistlib.loads(self.plist.read_bytes())
        config["EnvironmentVariables"]["PYTHONPATH"] = "/foreign/src"
        self.plist.write_bytes(plistlib.dumps(config))
        self.launchd.calls.clear()
        with self.assertRaisesRegex(RuntimeError, "ownership"):
            self.ensure()
        self.assertEqual(self.launchd.calls, [])

    def test_start_requires_existing_agent(self):
        with self.assertRaises(FileNotFoundError):
            service.start(self.root, launch_agents=self.agents)
        self.assertFalse(self.agents.exists())
        self.assertEqual(self.launchd.calls, [])

    def test_restart_waits_for_deregistration_and_preserves_plist(self):
        self.ensure()
        before = self.plist.read_bytes()
        self.launchd.deregister_checks = 3
        self.launchd.calls.clear()
        result = service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "restarted")
        self.assertTrue(result["changed"])
        self.assertEqual(self.launchd.deregister_checks, 0)
        self.assertEqual(self.plist.read_bytes(), before)
        operations = [argv[1] for argv in self.launchd.calls]
        self.assertEqual(operations.count("bootstrap"), 1)
        self.assertEqual(operations.count("bootout"), 1)
        self.assertLess(operations.index("bootout"), operations.index("bootstrap"))

    def test_absent_and_unloaded_restart_are_noops(self):
        self.assertFalse(service.restart_if_installed(self.root, launch_agents=self.agents)["changed"])
        self.ensure()
        self.launchd.loaded = False
        self.launchd.calls.clear()
        result = service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertFalse(result["changed"])
        self.assertEqual([argv[1] for argv in self.launchd.calls], ["print"])

    def test_failed_new_bootstrap_rolls_back_and_preserves_existing_on_restart(self):
        self.launchd.bootstrap_fails = True
        with self.assertRaisesRegex(RuntimeError, "start failed"):
            self.ensure()
        self.assertFalse(self.plist.exists())
        self.assertFalse(self.launchd.loaded)
        self.launchd.bootstrap_fails = False
        self.ensure()
        self.launchd.bootstrap_fails = True
        with self.assertRaises(service.RestartError) as failure:
            service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertTrue(failure.exception.service_stopped)
        self.assertTrue(self.plist.exists())
        self.assertFalse(self.launchd.loaded)
        self.launchd.bootstrap_fails = False
        self.assertEqual(service.start(self.root, launch_agents=self.agents)["status"], "running")

    def test_interrupted_new_start_deregisters_and_removes_created_plist(self):
        with patch.object(service, "_wait_running", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.ensure()
        self.assertFalse(self.launchd.loaded)
        self.assertFalse(self.plist.exists())

    def test_interrupted_existing_start_deregisters_and_preserves_plist(self):
        self.ensure()
        original = self.plist.read_bytes()
        self.launchd.loaded = False
        with patch.object(service, "_wait_running", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                service.start(self.root, launch_agents=self.agents)
        self.assertFalse(self.launchd.loaded)
        self.assertEqual(self.plist.read_bytes(), original)

    def test_registered_but_not_running_fails_readiness(self):
        self.launchd.running = False
        with self.assertRaisesRegex(RuntimeError, "start failed"):
            self.ensure()
        self.assertFalse(self.launchd.loaded)
        self.assertFalse(self.plist.exists())

    def test_deregistration_timeout_preserves_plist_and_never_bootstraps(self):
        self.ensure()
        self.launchd.deregister_checks = service.POLL_COUNT + 1
        self.launchd.calls.clear()
        with self.assertRaisesRegex(RuntimeError, "deregistration"):
            service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertTrue(self.plist.exists())
        self.assertNotIn("bootstrap", [argv[1] for argv in self.launchd.calls])

    def test_remove_preserves_data_and_waits_for_stop(self):
        self.ensure()
        self.launchd.deregister_checks = 2
        result = service.remove_if_installed(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "removed")
        self.assertFalse(self.plist.exists())
        self.assertFalse(self.launchd.loaded)
        self.assertTrue((self.data / "logs/watcher.stdout.log").exists())
        self.assertFalse(service.remove_if_installed(self.root, launch_agents=self.agents)["changed"])

    def test_launchctl_denied_is_not_treated_as_missing(self):
        denied = subprocess.CompletedProcess([], 1, "", "Operation not permitted")
        with patch.object(service.subprocess, "run", return_value=denied):
            with self.assertRaisesRegex(RuntimeError, "inspect"):
                self.ensure()
        self.assertFalse(self.plist.exists())


if __name__ == "__main__":
    unittest.main()
