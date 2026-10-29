"""Owner-scoped remote LaunchAgent lifecycle; never calls live launchd."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import setup_remote_service as service


class FakeLaunchd:
    def __init__(self):
        self.loaded = False
        self.calls = []
        self.plist = None
        self.bootstrap_fails = False
        self.deregister_checks = 0
        self.stopping = False
        self.foreign = False
        self.bootstrap_count = 0
        self.readiness_history = []

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
                program = "/foreign/service" if self.foreign else config["ProgramArguments"][0]
                stdout = ("path = " + str(self.plist) + "\nprogram = " + program
                          + "\nstate = running\npid = 12345\n")
            else:
                stderr, code = 'Could not find service "missing" in domain for user gui', 113
        elif command == "bootstrap":
            if self.stopping and self.loaded:
                raise AssertionError("Bootstrap before completed deregistration")
            self.plist = Path(argv[3])
            self.loaded = True
            self.stopping = False
            self.bootstrap_count += 1
            if self.bootstrap_fails:
                stderr, code = "Bootstrap failed: 5: Input/output error", 5
        elif command == "bootout":
            self.stopping = True
        else:
            raise AssertionError("Unexpected launchctl operation: " + command)
        return subprocess.CompletedProcess(argv, code, stdout, stderr)


class RemoteServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.root = self.home / "MCP Server"
        self.root.mkdir(mode=0o700)
        self.data = self.root / "data"
        self.data.mkdir(mode=0o700)
        (self.root / ".mac-control-installer-owned").write_text("owned\n")
        release = self.root / "releases/test-release"
        (release / "bin").mkdir(parents=True)
        launcher = release / "bin/mac-control-remote-mcp.sh"
        launcher.write_text("#!/bin/sh\nexit 0\n")
        launcher.chmod(0o700)
        (self.root / "current").symlink_to(release)
        config = self.data / "remote_auth.json"
        config.write_text(json.dumps({
            "github_client_id": "Ov23abc00000test",
            "github_client_secret": "secret-" + "x" * 32,
            "github_allowed_ids": ["12500001"],
            "jwt_signing_key": "y" * 64,
            "public_url": "https://mac.example.test",
        }))
        config.chmod(0o600)
        self.agents = self.home / "Library/LaunchAgents"
        self.plist = self.agents / (service.LABEL + ".plist")
        self.launchd = FakeLaunchd()
        self.addCleanup(patch.stopall)
        patch.object(service.sys, "platform", "darwin").start()
        patch.object(service.os, "geteuid", return_value=501).start()
        patch.object(service.subprocess, "run", side_effect=self.launchd).start()
        patch.object(service, "_endpoint_ready", return_value=True).start()
        patch.object(service, "_assert_port_free", return_value=None).start()
        patch.object(service.time, "sleep").start()

    def ensure(self):
        return service.ensure(self.root, launch_agents=self.agents)

    def test_install_starts_fixed_loopback_service_with_private_files(self):
        result = self.ensure()
        self.assertEqual(result["status"], "running")
        self.assertTrue(result["created_plist"])
        config = plistlib.loads(self.plist.read_bytes())
        self.assertEqual(config["ProgramArguments"],
                         [str(self.root / "current/bin/mac-control-remote-mcp.sh")])
        self.assertEqual(config["EnvironmentVariables"]["MAC_CONTROL_REMOTE_PORT"], "3201")
        self.assertTrue(config["RunAtLoad"])
        self.assertTrue(config["KeepAlive"])
        self.assertEqual(config["Umask"], 0o077)
        self.assertEqual(self.plist.stat().st_mode & 0o777, 0o600)
        for key in ("StandardOutPath", "StandardErrorPath"):
            logfile = Path(config[key])
            self.assertEqual(logfile.stat().st_mode & 0o777, 0o600)
            self.assertEqual(logfile.parent.stat().st_mode & 0o777, 0o700)
        serialized = self.plist.read_text()
        self.assertNotIn("secret-", serialized)
        self.assertNotIn("y" * 32, serialized)
        self.assertIn(["/bin/launchctl", "bootstrap", "gui/" + str(os.getuid()),
                       str(self.plist)], self.launchd.calls)
        self.assertFalse(result["public_endpoint_published"])

    def test_repeated_install_preserves_plist_and_running_process(self):
        self.ensure()
        before = (self.plist.read_bytes(), self.plist.stat().st_mtime_ns)
        self.launchd.calls.clear()
        result = self.ensure()
        self.assertFalse(result["created_plist"])
        self.assertEqual(before, (self.plist.read_bytes(), self.plist.stat().st_mtime_ns))
        self.assertEqual([call[1] for call in self.launchd.calls], ["print"])

    def test_status_is_read_only_even_before_first_install(self):
        result = service.status(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "not_installed")
        self.assertFalse(self.agents.exists())
        self.assertFalse((self.data / "logs").exists())
        self.assertEqual(self.launchd.calls, [])

    def test_status_does_not_create_or_repair_private_files(self):
        self.ensure()
        config = plistlib.loads(self.plist.read_bytes())
        Path(config["StandardOutPath"]).unlink()
        self.launchd.calls.clear()
        result = service.status(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "running")
        self.assertFalse(Path(config["StandardOutPath"]).exists())
        self.assertEqual([call[1] for call in self.launchd.calls], ["print"])

    def test_insecure_log_is_rejected_even_when_service_already_runs(self):
        self.ensure()
        config = plistlib.loads(self.plist.read_bytes())
        logfile = Path(config["StandardOutPath"])
        logfile.chmod(0o644)
        self.launchd.calls.clear()
        with self.assertRaises(PermissionError):
            self.ensure()
        self.assertEqual(logfile.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.launchd.calls, [])

    def test_symlink_launch_agents_directory_is_refused(self):
        elsewhere = self.home / "elsewhere"
        elsewhere.mkdir()
        self.agents.parent.mkdir(parents=True)
        self.agents.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.ensure()
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(self.launchd.calls, [])

    def test_current_release_outside_installation_is_refused(self):
        (self.root / "current").unlink()
        (self.root / "current").symlink_to(self.home)
        with self.assertRaisesRegex(RuntimeError, "outside"):
            self.ensure()
        self.assertEqual(self.launchd.calls, [])

    def test_foreign_file_owner_is_rejected(self):
        self.ensure()
        original_stat = service.Path.lstat
        def changed_owner(path):
            info = original_stat(path)
            if path == self.plist:
                data = list(info)
                data[4] = info.st_uid + 1
                return os.stat_result(data)
            return info
        self.launchd.calls.clear()
        with patch.object(service.Path, "lstat", changed_owner):
            with self.assertRaisesRegex(RuntimeError, "ownership"):
                self.ensure()
        self.assertEqual(self.launchd.calls, [])

    def test_missing_oauth_refuses_before_any_launchd_or_filesystem_mutation(self):
        (self.data / "remote_auth.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.ensure()
        self.assertFalse(self.agents.exists())
        self.assertEqual(self.launchd.calls, [])

    def test_unknown_plist_is_never_replaced(self):
        self.agents.mkdir(parents=True)
        self.plist.write_bytes(plistlib.dumps({"Label": service.LABEL}))
        self.plist.chmod(0o600)
        original = self.plist.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "ownership|unrecognized|Unknown"):
            self.ensure()
        self.assertEqual(self.plist.read_bytes(), original)
        self.assertEqual(self.launchd.calls, [])

    def test_failed_plist_write_leaves_no_partial_agent(self):
        with patch.object(service.plistlib, "dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.ensure()
        self.assertFalse(self.plist.exists())
        self.assertEqual(list(self.agents.iterdir()), [])
        self.assertFalse(self.launchd.loaded)

    def test_world_readable_plist_is_not_repaired(self):
        self.ensure()
        self.plist.chmod(0o644)
        self.launchd.calls.clear()
        with self.assertRaises(PermissionError):
            self.ensure()
        self.assertEqual(self.plist.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.launchd.calls, [])

    def test_symlink_plist_is_never_followed(self):
        self.agents.mkdir(parents=True)
        other = self.home / "unrelated"
        other.write_text("preserve")
        self.plist.symlink_to(other)
        with self.assertRaises((RuntimeError, PermissionError)):
            self.ensure()
        self.assertEqual(other.read_text(), "preserve")
        self.assertEqual(self.launchd.calls, [])

    def test_symlink_log_is_never_chmodded_or_overwritten(self):
        logs = self.data / "logs"
        logs.mkdir(mode=0o700)
        other = self.home / "unrelated"
        other.write_text("preserve")
        other.chmod(0o644)
        (logs / "remote-mcp.stdout.log").symlink_to(other)
        with self.assertRaises((RuntimeError, PermissionError)):
            self.ensure()
        self.assertEqual(other.read_text(), "preserve")
        self.assertEqual(other.stat().st_mode & 0o777, 0o644)
        self.assertFalse(self.plist.exists())
        self.assertFalse(self.launchd.loaded)

    def test_start_reuses_installed_but_unloaded_agent(self):
        self.ensure()
        self.launchd.loaded = False
        self.launchd.calls.clear()
        result = service.start(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "running")
        self.assertFalse(result["created_plist"])
        self.assertEqual(sum(call[1] == "bootstrap" for call in self.launchd.calls), 1)

    def test_start_does_not_install_a_missing_agent(self):
        with self.assertRaises(FileNotFoundError):
            service.start(self.root, launch_agents=self.agents)
        self.assertFalse(self.agents.exists())
        self.assertEqual(self.launchd.calls, [])

    def test_failed_bootstrap_rolls_back_new_plist_after_deregistration(self):
        self.launchd.bootstrap_fails = True
        self.launchd.deregister_checks = 2
        with self.assertRaisesRegex(RuntimeError, "start|bootstrap"):
            self.ensure()
        self.assertFalse(self.launchd.loaded)
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.launchd.deregister_checks, 0)
        self.launchd.bootstrap_fails = False
        self.launchd.stopping = False
        self.assertEqual(self.ensure()["status"], "running")

    def test_failed_start_preserves_existing_plist(self):
        self.ensure()
        original = self.plist.read_bytes()
        self.launchd.loaded = False
        self.launchd.bootstrap_fails = True
        with self.assertRaises(RuntimeError):
            self.ensure()
        self.assertFalse(self.launchd.loaded)
        self.assertEqual(self.plist.read_bytes(), original)

    def test_unhealthy_new_service_is_stopped_and_plist_rolled_back(self):
        with patch.object(service, "_endpoint_ready", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "ready|start"):
                self.ensure()
        self.assertFalse(self.launchd.loaded)
        self.assertFalse(self.plist.exists())

    def test_existing_running_unhealthy_service_is_not_restarted(self):
        self.ensure()
        self.launchd.calls.clear()
        with patch.object(service, "_endpoint_ready", return_value=False):
            with self.assertRaises(RuntimeError):
                self.ensure()
        self.assertTrue(self.launchd.loaded)
        self.assertEqual([call[1] for call in self.launchd.calls], ["print"])

    def test_foreign_loaded_job_is_not_stopped(self):
        self.ensure()
        self.launchd.foreign = True
        self.launchd.calls.clear()
        with self.assertRaisesRegex(RuntimeError, "ownership|foreign|Unknown"):
            self.ensure()
        self.assertTrue(self.launchd.loaded)
        self.assertEqual([call[1] for call in self.launchd.calls], ["print"])

    def test_deregistration_timeout_preserves_owned_plist_for_safe_recovery(self):
        self.launchd.bootstrap_fails = True
        self.launchd.deregister_checks = service.POLL_COUNT + 1
        with self.assertRaisesRegex(RuntimeError, "rollback incomplete"):
            self.ensure()
        self.assertTrue(self.launchd.loaded)
        self.assertTrue(self.plist.is_file())

    def test_unknown_launchctl_error_is_not_treated_as_absent(self):
        denied = subprocess.CompletedProcess([], 1, "", "Operation not permitted")
        with patch.object(service.subprocess, "run", return_value=denied):
            with self.assertRaisesRegex(RuntimeError, "inspect"):
                self.ensure()
        self.assertFalse(self.plist.exists())

    def test_unrecognized_environment_in_owned_label_is_not_replaced(self):
        self.ensure()
        self.launchd.loaded = False
        config = plistlib.loads(self.plist.read_bytes())
        config["EnvironmentVariables"]["MAC_CONTROL_REMOTE_PORT"] = "3101"
        self.plist.write_bytes(plistlib.dumps(config))
        self.launchd.calls.clear()
        with self.assertRaisesRegex(RuntimeError, "ownership"):
            self.ensure()
        self.assertEqual(self.launchd.calls, [])

    def test_occupied_port_is_not_taken_over(self):
        with patch.object(service, "_assert_port_free", side_effect=RuntimeError("occupied")):
            with self.assertRaisesRegex(RuntimeError, "occupied"):
                self.ensure()
        self.assertFalse(self.plist.exists())
        self.assertFalse(self.launchd.loaded)

    def test_cli_status_emits_json_without_starting_service(self):
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            result = service.main(["--root", str(self.root), "--launch-agents", str(self.agents),
                                   "--status"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "not_installed")
        self.assertFalse(self.agents.exists())

    def test_restart_absent_agent_is_noop_without_oauth(self):
        (self.data / "remote_auth.json").unlink()
        result = service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "not_installed")
        self.assertFalse(result["changed"])
        self.assertFalse(self.agents.exists())
        self.assertEqual(self.launchd.calls, [])

    def test_restart_does_not_start_a_previously_unloaded_owned_agent(self):
        self.ensure()
        self.launchd.loaded = False
        self.launchd.calls.clear()
        result = service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "not_loaded")
        self.assertFalse(result["changed"])
        self.assertEqual([call[1] for call in self.launchd.calls], ["print"])

    def test_restart_waits_for_deregistration_and_checks_health(self):
        self.ensure()
        self.launchd.deregister_checks = 2
        self.launchd.calls.clear()
        original = self.plist.read_bytes()
        with patch.object(service, "_endpoint_ready", return_value=True) as health:
            result = service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "restarted")
        self.assertTrue(result["changed"])
        self.assertTrue(result["authenticated_endpoint_verified"])
        self.assertEqual(self.launchd.deregister_checks, 0)
        self.assertEqual(self.launchd.bootstrap_count, 2)
        self.assertTrue(self.launchd.loaded)
        health.assert_called_once_with("https://mac.example.test")
        self.assertEqual(self.plist.read_bytes(), original)
        operations = [call[1] for call in self.launchd.calls]
        self.assertEqual(operations.count("bootout"), 1)
        self.assertEqual(operations.count("bootstrap"), 1)
        self.assertLess(operations.index("bootout"), operations.index("bootstrap"))

    def test_invalid_new_oauth_does_not_stop_running_agent(self):
        self.ensure()
        (self.data / "remote_auth.json").unlink()
        self.launchd.calls.clear()
        with self.assertRaises(FileNotFoundError):
            service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertTrue(self.launchd.loaded)
        self.assertNotIn("bootout", [call[1] for call in self.launchd.calls])

    def test_restart_failure_leaves_owned_plist_for_old_pointer_restore_and_start(self):
        self.ensure()
        original = self.plist.read_bytes()
        self.launchd.bootstrap_fails = True
        with self.assertRaisesRegex(RuntimeError, "restart.*failed") as failure:
            service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertTrue(failure.exception.service_stopped)
        self.assertFalse(self.launchd.loaded)
        self.assertEqual(self.plist.read_bytes(), original)
        self.launchd.bootstrap_fails = False
        self.assertEqual(service.start(self.root, launch_agents=self.agents)["status"], "running")

    def test_restart_auth_health_failure_stops_new_process_and_preserves_plist(self):
        self.ensure()
        with patch.object(service, "_endpoint_ready", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "restart.*failed"):
                service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertFalse(self.launchd.loaded)
        self.assertTrue(self.plist.is_file())

    def test_restart_deregistration_timeout_never_bootstraps_new_process(self):
        self.ensure()
        self.launchd.deregister_checks = service.POLL_COUNT + 1
        self.launchd.calls.clear()
        with self.assertRaisesRegex(RuntimeError, "deregistration"):
            service.restart_if_installed(self.root, launch_agents=self.agents)
        self.assertTrue(self.plist.is_file())
        self.assertNotIn("bootstrap", [call[1] for call in self.launchd.calls])

    def test_remove_absent_agent_is_read_only_noop_without_oauth(self):
        (self.data / "remote_auth.json").unlink()
        result = service.remove_if_installed(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "not_installed")
        self.assertFalse(result["changed"])
        self.assertFalse(self.agents.exists())
        self.assertEqual(self.launchd.calls, [])

    def test_remove_waits_for_deregistration_and_preserves_logs_and_oauth(self):
        self.ensure()
        self.launchd.deregister_checks = 3
        config = self.data / "remote_auth.json"
        original = config.read_bytes()
        result = service.remove_if_installed(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "removed")
        self.assertTrue(result["changed"])
        self.assertFalse(self.launchd.loaded)
        self.assertEqual(self.launchd.deregister_checks, 0)
        self.assertFalse(self.plist.exists())
        self.assertEqual(config.read_bytes(), original)
        self.assertTrue((self.data / "logs/remote-mcp.stdout.log").exists())
        again = service.remove_if_installed(self.root, launch_agents=self.agents)
        self.assertEqual(again["status"], "not_installed")
        self.assertFalse(again["changed"])

    def test_remove_unloaded_owned_plist_needs_no_oauth(self):
        self.ensure()
        self.launchd.loaded = False
        (self.data / "remote_auth.json").unlink()
        self.launchd.calls.clear()
        result = service.remove_if_installed(self.root, launch_agents=self.agents)
        self.assertEqual(result["status"], "removed")
        self.assertFalse(self.plist.exists())
        self.assertNotIn("bootout", [call[1] for call in self.launchd.calls])

    def test_remove_deregistration_timeout_preserves_plist(self):
        self.ensure()
        self.launchd.deregister_checks = service.POLL_COUNT + 1
        with self.assertRaisesRegex(RuntimeError, "deregistration"):
            service.remove_if_installed(self.root, launch_agents=self.agents)
        self.assertTrue(self.plist.is_file())

    def test_lifecycle_helpers_never_stop_foreign_loaded_job(self):
        self.ensure()
        self.launchd.foreign = True
        for operation in (service.restart_if_installed, service.remove_if_installed):
            self.launchd.calls.clear()
            with self.assertRaisesRegex(RuntimeError, "ownership"):
                operation(self.root, launch_agents=self.agents)
            self.assertTrue(self.plist.is_file())
            self.assertNotIn("bootout", [call[1] for call in self.launchd.calls])

    def test_lifecycle_helpers_never_change_unknown_plist(self):
        self.ensure()
        self.plist.write_bytes(plistlib.dumps({"Label": service.LABEL}))
        original = self.plist.read_bytes()
        for operation in (service.restart_if_installed, service.remove_if_installed):
            self.launchd.calls.clear()
            with self.assertRaisesRegex(RuntimeError, "ownership"):
                operation(self.root, launch_agents=self.agents)
            self.assertEqual(self.plist.read_bytes(), original)
            self.assertEqual(self.launchd.calls, [])


class EndpointHealthTests(unittest.TestCase):
    def response(self, data):
        return io.BytesIO(json.dumps(data).encode())

    def test_metadata_401_is_not_healthy_authenticated_mcp(self):
        with patch.object(service.urllib.request, "build_opener") as build:
            build.return_value.open.side_effect = HTTPError(
                "http://127.0.0.1:3201/.well-known/oauth-authorization-server", 401,
                "Unauthorized", {"WWW-Authenticate": "Bearer"}, io.BytesIO())
            self.assertFalse(service._endpoint_ready("https://mac.example.test"))

    def test_valid_issuer_and_anonymous_mcp_challenge_are_required(self):
        with patch.object(service.urllib.request, "build_opener") as build:
            build.return_value.open.side_effect = [
                self.response({"issuer": "https://mac.example.test"}),
                HTTPError("http://127.0.0.1:3201/mcp", 401, "Unauthorized",
                          {"WWW-Authenticate": "Bearer"}, io.BytesIO()),
            ]
            self.assertTrue(service._endpoint_ready("https://mac.example.test"))
            self.assertEqual(build.return_value.open.call_count, 2)

    def test_foreign_issuer_is_rejected_before_mcp_probe(self):
        with patch.object(service.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = self.response({"issuer": "https://other.example.test"})
            self.assertFalse(service._endpoint_ready("https://mac.example.test"))
            self.assertEqual(build.return_value.open.call_count, 1)

    def test_unauthenticated_mcp_200_is_unhealthy(self):
        with patch.object(service.urllib.request, "build_opener") as build:
            build.return_value.open.side_effect = [
                self.response({"issuer": "https://mac.example.test"}), self.response({}),
            ]
            self.assertFalse(service._endpoint_ready("https://mac.example.test"))

    def test_health_opener_disables_proxies_and_external_redirects(self):
        with patch.object(service.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = self.response({"issuer": "wrong"})
            service._endpoint_ready("https://mac.example.test")
        handlers = build.call_args.args
        self.assertTrue(any(isinstance(item, service.urllib.request.ProxyHandler)
                            and item.proxies == {} for item in handlers))
        redirects = [item for item in handlers
                     if isinstance(item, service.urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        self.assertIsNone(redirects[0].redirect_request(None, None, 302, "Found", {},
                                                     "https://external.example.test"))


class LoopbackPortTests(unittest.TestCase):
    """Real loopback sockets only; no launchd, fixed ports or external network."""
    def listener(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
        except PermissionError:
            listener.close()
            self.skipTest("Sandbox does not allow isolated loopback sockets")
        except BaseException:
            listener.close()
            raise
        return listener

    def test_live_other_listener_blocks_probe_even_with_reuseaddr(self):
        with self.listener() as listener:
            with patch.object(service, "PORT", listener.getsockname()[1]):
                with self.assertRaisesRegex(RuntimeError, "occupied"):
                    service._assert_port_free()

    def test_time_wait_after_closed_http_connection_does_not_block_restart(self):
        with self.listener() as listener:
            port = listener.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port)) as client:
                accepted, _ = listener.accept()
                with accepted:
                    accepted.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1), b"")
        with patch.object(service, "PORT", port):
            service._assert_port_free()


if __name__ == "__main__":
    unittest.main()
