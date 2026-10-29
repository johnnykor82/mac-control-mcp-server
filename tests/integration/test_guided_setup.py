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
                guided_setup.setup(self.root, interactive=True)
        with install_mac_control._lifecycle_lock(self.root, timeout=0):
            pass

    def test_interactive_setup_rejects_missing_ownership_before_lock(self):
        (self.root / ".mac-control-installer-owned").unlink()
        with patch.object(install_mac_control, "_lifecycle_lock") as lock:
            with self.assertRaises(RuntimeError):
                guided_setup.setup(self.root, interactive=True)
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
                guided_setup.setup(self.root, interactive=True)
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
        with patch.object(install_mac_control.sys, "argv", ["installer", "--install", "--without-gui"]), \
             patch.object(install_mac_control.sys.stdin, "isatty", return_value=True), \
             patch.object(install_mac_control, "paths", return_value={"root": Path("/tmp/owned")}), \
             patch.object(install_mac_control, "install", return_value={"status": "installed"}), \
             patch.object(install_mac_control, "run", return_value=Mock(returncode=0)) as run:
            self.assertEqual(install_mac_control.main(), 0)
        self.assertIn("guided_setup.py", run.call_args.args[0][1])
        self.assertIn("--without-gui", run.call_args.args[0])
        self.assertIsNone(run.call_args.kwargs["timeout"])

    def test_gui_prompts_only_when_needed_and_checks_both_grants(self):
        missing = {"accessibility_trusted": False, "screen_capture_trusted": False}
        both = {"accessibility_trusted": True, "screen_capture_trusted": True}
        calls = []
        def gui(root, operation):
            calls.append(operation)
            return both if calls.count("status") >= 3 else missing
        with patch.object(guided_setup, "_gui_call", side_effect=gui), \
             patch.object(guided_setup.subprocess, "run") as opener:
            self.assertTrue(guided_setup.gui_permissions(self.root, input_fn=lambda _: ""))
        self.assertEqual(calls, ["status", "request_permissions", "status", "status"])
        self.assertIn("Privacy_Accessibility", opener.call_args.args[0][1])

    def test_existing_gui_permissions_do_not_prompt_or_open_settings(self):
        with patch.object(guided_setup, "_gui_call", return_value={"accessibility_trusted": True, "screen_capture_trusted": True}) as gui, \
             patch.object(guided_setup.subprocess, "run") as opener:
            self.assertTrue(guided_setup.gui_permissions(self.root, input_fn=lambda _: self.fail("unexpected prompt")))
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
            result = guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True)
        self.assertEqual(result["status"], "pending_gui_permissions")
        network.assert_not_called()

    def test_incomplete_network_does_not_start_remote_or_publish(self):
        with patch.object(guided_setup, "gui_permissions", return_value=True), \
             patch.object(guided_setup, "guided_network", return_value={"status": "manual_setup_required"}), \
             patch.object(guided_setup, "ensure_remote_service") as remote, \
             patch.object(guided_setup, "enable_funnel") as funnel:
            result = guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True)
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
             patch.object(guided_setup, "verify_local_oauth", side_effect=lambda root, url: events.append("guard")), \
             patch.object(guided_setup, "enable_funnel", side_effect=lambda root, **kw: events.append("funnel") or {"status": "ok"}), \
             patch.object(guided_setup, "oauth_probe", side_effect=lambda url: events.append("probe") or {"status": "public_oauth_preflight_pass"}):
            result = guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True)
        self.assertEqual(events, ["remote", "guard", "funnel", "probe"])
        self.assertEqual(result["status"], "pending_chatgpt_connection")

    def test_existing_oauth_for_other_origin_is_not_overwritten_or_published(self):
        with patch.object(guided_setup, "gui_permissions", return_value=True), \
             patch.object(guided_setup, "guided_network", return_value={"status": "ready_for_oauth", "route": "tailscale_funnel", "public_url": "https://new.example"}), \
             patch.object(guided_setup, "oauth_check", return_value={"public_url": "https://old.example"}), \
             patch.object(guided_setup, "oauth_configure") as configure, \
             patch.object(guided_setup, "ensure_remote_service") as remote, \
             patch.object(guided_setup, "enable_funnel") as funnel:
            result = guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True)
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
                guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True)
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
            result = guided_setup.setup(self.root, input_fn=lambda _: "", interactive=True)
        self.assertEqual(result["status"], "pending_chatgpt_connection")
        funnel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
