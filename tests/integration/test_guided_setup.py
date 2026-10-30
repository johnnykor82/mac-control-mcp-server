"""Guided onboarding orders permissions, authentication and publication."""
import unittest
import io
import json
import tempfile
import subprocess
import sys
from pathlib import Path
from contextlib import redirect_stdout
from contextlib import contextmanager
from unittest.mock import Mock, patch

from scripts import guided_setup
from scripts import install_mac_control


class GuidedSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "data").mkdir(mode=0o700)
        marker = self.root / ".mac-control-installer-owned"
        marker.write_text("owned")
        marker.chmod(0o600)
        release = self.root / "releases/test-release"
        (release / "bin").mkdir(parents=True)
        (release / "bin/mac-control-stdio-mcp.sh").write_text("#!/bin/sh\n")
        (self.root / "current").symlink_to(release)

    def test_wizard_holds_common_lock_and_releases_it_on_interrupt(self):
        def owner_steps(root, **kwargs):
            with self.assertRaises(RuntimeError):
                with install_mac_control._lifecycle_lock(root, timeout=0):
                    self.fail("Wizard did not hold the common lifecycle lock")
            raise KeyboardInterrupt()
        with patch.object(guided_setup, "_setup_locked", side_effect=owner_steps, create=True):
            with self.assertRaises(KeyboardInterrupt):
                guided_setup.setup(self.root, interactive=True, language="en")
        with install_mac_control._lifecycle_lock(self.root, timeout=0):
            pass

    def test_interactive_setup_rejects_missing_ownership_before_lock(self):
        (self.root / ".mac-control-installer-owned").unlink()
        with patch.object(install_mac_control, "_lifecycle_lock") as lock:
            with self.assertRaises(RuntimeError):
                guided_setup.setup(self.root, interactive=True, language="en")
            lock.assert_not_called()

    def test_noninteractive_uninstalled_root_does_not_create_any_files(self):
        fresh = self.root / "uninstalled"
        result = guided_setup.setup(fresh, interactive=False)
        self.assertEqual(result["status"], "pending_owner_interaction")
        self.assertFalse(fresh.exists())

    def test_setup_revalidates_full_marker_permissions_after_lock_wait(self):
        @contextmanager
        def changed_while_waiting(root):
            (root / ".mac-control-installer-owned").chmod(0o666)
            yield root
        with patch.object(install_mac_control, "_lifecycle_lock", side_effect=changed_while_waiting), \
             patch.object(guided_setup, "_setup_locked") as wizard:
            with self.assertRaisesRegex(RuntimeError, "ownership marker is unsafe"):
                guided_setup.setup(self.root, interactive=True, language="en")
            wizard.assert_not_called()

    def test_setup_cli_runs_as_a_real_noninteractive_subprocess(self):
        source = Path(__file__).resolve().parents[2]
        result = subprocess.run([sys.executable, str(source / "scripts/install_mac_control.py"),
                                 "--setup", "--root", "/tmp/mac-control-test-noninteractive"],
                                cwd=source, text=True, capture_output=True, timeout=15, check=True)
        self.assertEqual(json.loads(result.stdout)["status"], "pending_owner_interaction")

    def test_wizard_error_returns_failure_but_pending_is_not_failure(self):
        for outcome, expected in ((RuntimeError("guard failed"), 1),
                                  ({"status": "pending_network"}, 0)):
            with self.subTest(outcome=outcome), \
                 patch.object(guided_setup.sys, "argv", ["guided_setup", "--root", "/tmp/owned"]), \
                 patch.object(guided_setup, "setup", side_effect=outcome if isinstance(outcome, Exception) else None,
                              return_value=outcome):
                self.assertEqual(guided_setup.main(), expected)

    def test_noninteractive_install_returns_single_json_and_does_not_run_wizard(self):
        output = io.StringIO()
        with patch.object(install_mac_control.sys, "argv", ["installer", "--install"]), \
             patch.object(install_mac_control.sys.stdin, "isatty", return_value=False), \
             patch.object(install_mac_control, "paths", return_value={"root": Path("/tmp/owned")}), \
             patch.object(install_mac_control, "install", return_value={"status": "installed"}), \
             patch.object(install_mac_control, "run") as run, redirect_stdout(output):
            self.assertEqual(install_mac_control.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["guided_setup"]["status"], "pending_owner_interaction")
        run.assert_not_called()

    def test_interactive_install_runs_wizard_after_local_success(self):
        with patch.object(install_mac_control.sys, "argv", ["installer", "--install", "--without-gui", "--language", "en"]), \
             patch.object(install_mac_control.sys.stdin, "isatty", return_value=True), \
             patch.object(install_mac_control, "paths", return_value={"root": Path("/tmp/owned")}), \
             patch.object(install_mac_control, "install", return_value={"status": "installed"}), \
             patch.object(install_mac_control, "run", return_value=Mock(returncode=0)) as run:
            self.assertEqual(install_mac_control.main(), 0)
        self.assertIn("guided_setup.py", run.call_args.args[0][1])
        self.assertIn("--without-gui", run.call_args.args[0])
        self.assertIsNone(run.call_args.kwargs["timeout"])

    def test_gui_requests_missing_grants_sequentially_and_waits_for_owner(self):
        state = {"accessibility_trusted": False, "screen_capture_trusted": False}
        calls = []
        def gui(root, operation):
            calls.append(operation)
            return dict(state)
        def owner(prompt):
            calls.append("owner")
            key = ("accessibility_trusted" if not state["accessibility_trusted"]
                   else "screen_capture_trusted")
            state[key] = True
            return ""
        with patch.object(guided_setup, "_gui_call", side_effect=gui), \
             patch.object(guided_setup, "_restart_gui", side_effect=lambda root: gui(root, "status")) as restart, \
             patch.object(guided_setup.subprocess, "run") as opener:
            self.assertTrue(guided_setup.gui_permissions(self.root, language="en", input_fn=owner))
        restart.assert_called_once_with(self.root)
        self.assertEqual(calls, ["status", "request_accessibility", "status", "owner", "status",
                                 "request_screen_capture", "status", "owner", "status"])
        self.assertIn("Privacy_Accessibility", opener.call_args_list[0].args[0][1])
        self.assertIn("Privacy_ScreenCapture", opener.call_args_list[1].args[0][1])

    def test_gui_requests_only_missing_screen_permission(self):
        state = {"accessibility_trusted": True, "screen_capture_trusted": False}
        calls = []
        def gui(root, operation):
            calls.append(operation)
            if operation == "request_screen_capture":
                state["screen_capture_trusted"] = True
            return dict(state)
        with patch.object(guided_setup, "_gui_call", side_effect=gui), \
             patch.object(guided_setup.subprocess, "run") as opener:
            self.assertTrue(guided_setup.gui_permissions(self.root, language="en", input_fn=lambda _: self.fail("unexpected wait")))
        self.assertEqual(calls, ["status", "request_screen_capture", "status"])
        opener.assert_not_called()

    def test_screen_grant_confirmation_restarts_stale_helper_once(self):
        missing = {"accessibility_trusted": True, "screen_capture_trusted": False}
        ready = {"accessibility_trusted": True, "screen_capture_trusted": True}
        answers = iter(("",))
        with patch.object(guided_setup, "_gui_call", return_value=missing) as gui, \
             patch.object(guided_setup, "_restart_gui", return_value=ready, create=True) as restart, \
             patch.object(guided_setup.subprocess, "run"), \
             patch("builtins.print"):
            self.assertTrue(guided_setup.gui_permissions(self.root, language="en", input_fn=lambda _: next(answers)))
        restart.assert_called_once_with(self.root)
        self.assertEqual([call.args[1] for call in gui.call_args_list],
                         ["status", "request_screen_capture", "status"])

    def test_screen_grant_still_missing_restarts_only_after_each_owner_confirmation(self):
        missing = {"accessibility_trusted": True, "screen_capture_trusted": False}
        answers = iter(("", "", "s"))
        with patch.object(guided_setup, "_gui_call", return_value=missing), \
             patch.object(guided_setup, "_restart_gui", return_value=missing, create=True) as restart, \
             patch.object(guided_setup.subprocess, "run"), \
             patch("builtins.print"):
            self.assertFalse(guided_setup.gui_permissions(self.root, language="en", input_fn=lambda _: next(answers)))
        self.assertEqual(restart.call_count, 2)

    def test_later_owner_confirmation_retries_restart_after_early_confirmation(self):
        missing = {"accessibility_trusted": True, "screen_capture_trusted": False}
        ready = {"accessibility_trusted": True, "screen_capture_trusted": True}
        answers = iter(("", ""))
        with patch.object(guided_setup, "_gui_call", return_value=missing), \
             patch.object(guided_setup, "_restart_gui", side_effect=[missing, ready], create=True) as restart, \
             patch.object(guided_setup.subprocess, "run"), \
             patch("builtins.print"):
            self.assertTrue(guided_setup.gui_permissions(self.root, language="en", input_fn=lambda _: next(answers)))
        self.assertEqual(restart.call_count, 2)

    def test_gui_restart_failure_stops_without_retrying(self):
        missing = {"accessibility_trusted": True, "screen_capture_trusted": False}
        with patch.object(guided_setup, "_gui_call", return_value=missing), \
             patch.object(guided_setup, "_restart_gui", side_effect=RuntimeError("Owned helper did not exit")) as restart, \
             patch.object(guided_setup.subprocess, "run"), \
             patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "did not exit"):
                guided_setup.gui_permissions(self.root, language="en", input_fn=lambda _: "")
        restart.assert_called_once_with(self.root)

    def test_gui_restart_verifies_ownership_then_stops_only_owned_app(self):
        from scripts import setup_gui_dependency as dependency
        ready = {"accessibility_trusted": True, "screen_capture_trusted": True}
        calls = []
        with patch.object(dependency.gui, "verify_owned", side_effect=lambda root: calls.append("verify") or True), \
             patch.object(dependency, "_stop_owned_app", side_effect=lambda app: calls.append(app)) as stop, \
             patch.object(guided_setup, "_gui_call", side_effect=lambda *args: calls.append("status") or ready):
            self.assertEqual(guided_setup._restart_gui(self.root), ready)
        app = Path.home() / "Applications" / dependency.gui.APP_NAME
        stop.assert_called_once_with(app)
        self.assertEqual(calls, ["verify", app, "status"])

    def test_gui_restart_refuses_unowned_helper(self):
        from scripts import setup_gui_dependency as dependency
        with patch.object(dependency.gui, "verify_owned", return_value=False), \
             patch.object(dependency, "_stop_owned_app") as stop, \
             patch.object(guided_setup, "_gui_call") as gui:
            with self.assertRaisesRegex(RuntimeError, "owned GUI helper"):
                guided_setup._restart_gui(self.root)
        stop.assert_not_called()
        gui.assert_not_called()

    def test_gui_skip_does_not_request_later_permission_or_repeat_request(self):
        missing = {"accessibility_trusted": False, "screen_capture_trusted": False}
        output = io.StringIO()
        answers = iter(("", "s"))
        with patch.object(guided_setup, "_gui_call", return_value=missing) as gui, \
             patch.object(guided_setup.subprocess, "run"), redirect_stdout(output):
            self.assertFalse(guided_setup.gui_permissions(self.root, language="en", input_fn=lambda _: next(answers)))
        self.assertEqual([call.args[1] for call in gui.call_args_list],
                         ["status", "request_accessibility", "status", "status"])
        self.assertIn("MacControlMCPServer.app", output.getvalue())
        self.assertIn("+", output.getvalue())

    def test_gui_legacy_unknown_operation_falls_back_only_once(self):
        state = {"accessibility_trusted": False, "screen_capture_trusted": False}
        calls = []
        def gui(root, operation):
            calls.append(operation)
            if operation == "request_accessibility":
                raise RuntimeError("Unknown GUI operation")
            return dict(state)
        def owner(prompt):
            key = ("accessibility_trusted" if not state["accessibility_trusted"]
                   else "screen_capture_trusted")
            state[key] = True
            return ""
        with patch.object(guided_setup, "_gui_call", side_effect=gui), \
             patch.object(guided_setup, "_restart_gui", side_effect=lambda root: gui(root, "status")), \
             patch.object(guided_setup.subprocess, "run"):
            self.assertTrue(guided_setup.gui_permissions(self.root, language="en", input_fn=owner))
        self.assertEqual(calls[:3], ["status", "request_accessibility", "request_permissions"])
        self.assertEqual(calls.count("request_permissions"), 1)
        self.assertNotIn("request_screen_capture", calls)

    def test_gui_permission_request_failure_does_not_use_legacy_fallback(self):
        missing = {"accessibility_trusted": False, "screen_capture_trusted": False}
        with patch.object(guided_setup, "_gui_call", side_effect=[missing, RuntimeError("IPC disconnected")]) as gui:
            with self.assertRaisesRegex(RuntimeError, "IPC disconnected"):
                guided_setup.gui_permissions(self.root, language="en", input_fn=lambda _: self.fail("unexpected wait"))
        self.assertEqual([call.args[1] for call in gui.call_args_list], ["status", "request_accessibility"])

    def test_funnel_public_failure_reports_acme_diagnostic(self):
        origin = "https://owner.example.ts.net"
        network = {"status": "ready_for_oauth", "route": "tailscale_funnel", "public_url": origin}
        diagnostic = {"status": "acme_unreachable_from_setup", "daemon_connectivity_verified": False}
        with patch.object(guided_setup, "gui_permissions", return_value=True), \
             patch.object(guided_setup, "guided_network", return_value=network), \
             patch.object(guided_setup, "oauth_check", return_value={"public_url": origin}), \
             patch.object(guided_setup, "ensure_remote_service"), \
             patch.object(guided_setup, "verify_local_oauth"), \
             patch.object(guided_setup, "enable_funnel"), \
             patch.object(guided_setup, "oauth_probe", return_value={"status": "public_oauth_preflight_failed"}), \
             patch.object(guided_setup, "funnel_tls_diagnostics", return_value=diagnostic) as check:
            result = guided_setup._setup_locked(self.root, input_fn=lambda _: "", language="ru")
        self.assertEqual(result["status"], "pending_public_https")
        self.assertEqual(result["certificate_diagnostics"], diagnostic)
        check.assert_called_once_with(language="ru")

    def test_gui_call_preserves_unknown_operation_from_helper(self):
        current = self.root / "current"
        python = current / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        package = current / "src/mac_control"
        handlers = package / "legacy_handlers"
        handlers.mkdir(parents=True)
        (package / "__init__.py").touch()
        (handlers / "__init__.py").touch()
        (handlers / "gui_ops.py").write_text(
            'def _call(*args, **kwargs):\n    raise RuntimeError("Unknown GUI operation")\n')
        with self.assertRaisesRegex(RuntimeError, "^Unknown GUI operation$"):
            guided_setup._gui_call(self.root, "request_accessibility")

    def test_existing_gui_permissions_do_not_prompt_or_open_settings(self):
        with patch.object(guided_setup, "_gui_call", return_value={"accessibility_trusted": True, "screen_capture_trusted": True}) as gui, \
             patch.object(guided_setup.subprocess, "run") as opener:
            self.assertTrue(guided_setup.gui_permissions(self.root, language="en", input_fn=lambda _: self.fail("unexpected prompt")))
        self.assertEqual(gui.call_count, 1)
        opener.assert_not_called()

    def test_noninteractive_never_starts_external_configuration(self):
        with patch.object(guided_setup, "gui_permissions") as gui, \
             patch.object(guided_setup, "guided_network") as network:
            result = guided_setup.setup(self.root, interactive=False)
        self.assertEqual(result["status"], "pending_owner_interaction")
        gui.assert_not_called()
        network.assert_not_called()

    def test_missing_gui_permissions_do_not_configure_network(self):
        with patch.object(guided_setup, "gui_permissions", return_value=False), \
             patch.object(guided_setup, "guided_network") as network:
            result = guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True, language="en")
        self.assertEqual(result["status"], "pending_gui_permissions")
        network.assert_not_called()

    def test_incomplete_network_does_not_start_remote_or_publish(self):
        with patch.object(guided_setup, "gui_permissions", return_value=True), \
             patch.object(guided_setup, "guided_network", return_value={"status": "manual_setup_required"}), \
             patch.object(guided_setup, "ensure_remote_service") as remote, \
             patch.object(guided_setup, "enable_funnel") as funnel:
            result = guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True, language="en")
        self.assertEqual(result["status"], "pending_network")
        remote.assert_not_called()
        funnel.assert_not_called()

    def test_funnel_is_published_only_after_matching_oauth_and_remote_service(self):
        events = []
        origin = "https://mac.example.ts.net"
        with patch.object(guided_setup, "gui_permissions", return_value=True), \
             patch.object(guided_setup, "guided_network", return_value={"status": "ready_for_oauth", "route": "tailscale_funnel", "public_url": origin}), \
             patch.object(guided_setup, "oauth_check", side_effect=lambda root: {"public_url": origin}), \
             patch.object(guided_setup, "ensure_remote_service", side_effect=lambda root: events.append("remote")), \
             patch.object(guided_setup, "verify_local_oauth", side_effect=lambda root, url, **kw: events.append("guard")), \
             patch.object(guided_setup, "enable_funnel", side_effect=lambda root, **kw: events.append("funnel") or {"status": "ok"}), \
             patch.object(guided_setup, "oauth_probe", side_effect=lambda url: events.append("probe") or {"status": "public_oauth_preflight_pass"}):
            result = guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True, language="en")
        self.assertEqual(events, ["remote", "guard", "funnel", "probe"])
        self.assertEqual(result["status"], "pending_chatgpt_connection")

    def test_existing_oauth_for_other_origin_is_not_overwritten_or_published(self):
        with patch.object(guided_setup, "gui_permissions", return_value=True), \
             patch.object(guided_setup, "guided_network", return_value={"status": "ready_for_oauth", "route": "tailscale_funnel", "public_url": "https://new.example"}), \
             patch.object(guided_setup, "oauth_check", return_value={"public_url": "https://old.example"}), \
             patch.object(guided_setup, "oauth_configure") as configure, \
             patch.object(guided_setup, "ensure_remote_service") as remote, \
             patch.object(guided_setup, "enable_funnel") as funnel:
            result = guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True, language="en")
        self.assertEqual(result["status"], "oauth_origin_mismatch")
        configure.assert_not_called()
        remote.assert_not_called()
        funnel.assert_not_called()

    def test_funnel_not_enabled_when_loopback_guard_fails(self):
        origin = "https://mac.example.ts.net"
        with patch.object(guided_setup, "gui_permissions", return_value=True), \
             patch.object(guided_setup, "guided_network", return_value={"status": "ready_for_oauth", "route": "tailscale_funnel", "public_url": origin}), \
             patch.object(guided_setup, "oauth_check", return_value={"public_url": origin}), \
             patch.object(guided_setup, "ensure_remote_service"), \
             patch.object(guided_setup, "verify_local_oauth", side_effect=RuntimeError("guard failed")), \
             patch.object(guided_setup, "enable_funnel") as funnel:
            with self.assertRaisesRegex(RuntimeError, "guard failed"):
                guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True, language="en")
        funnel.assert_not_called()

    def test_direct_route_does_not_change_tailscale(self):
        origin = "https://mac.example.com"
        with patch.object(guided_setup, "gui_permissions", return_value=True), \
             patch.object(guided_setup, "guided_network", return_value={"status": "ready_for_oauth", "route": "direct_https", "public_url": origin}), \
             patch.object(guided_setup, "oauth_check", return_value={"public_url": origin}), \
             patch.object(guided_setup, "ensure_remote_service"), \
             patch.object(guided_setup, "verify_local_oauth"), \
             patch.object(guided_setup, "enable_funnel") as funnel, \
             patch.object(guided_setup, "oauth_probe", return_value={"status": "public_oauth_preflight_pass"}):
            result = guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True, language="en")
        self.assertEqual(result["status"], "pending_chatgpt_connection")
        funnel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
