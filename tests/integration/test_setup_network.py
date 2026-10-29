"""Tailscale Funnel onboarding never publishes an unauthenticated endpoint."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import io
from scripts import setup_network


class NetworkGuidanceTests(unittest.TestCase):
    def test_diagnostics_do_not_claim_public_inbound_access(self):
        with patch.object(setup_network, "inspect", return_value={
            "locally_global_ip_candidates": [], "external_ipv4": {"status": "not_checked"},
            "external_ipv6": {"status": "not_checked"},
        }), patch.object(setup_network, "tailscale_state",
                         return_value={"installed": False, "logged_in": False}):
            data = setup_network.diagnose(network=False)
        self.assertFalse(data["public_ip_verified"])
        self.assertEqual(data["incoming_reachable"], "not_tested")
        self.assertIn("Tailscale Funnel", data["recommendation"])

    def test_no_installed_tailscale_rejects_public_funnel(self):
        with patch.object(setup_network, "tailscale_cli", return_value=None), \
             patch.object(setup_network, "tailscale_state",
                          return_value={"installed": False, "logged_in": False}):
            with self.assertRaises(RuntimeError):
                setup_network.enable_funnel(Path("/tmp/non-existent"))

    def test_no_authenticated_local_server_rejects_public_funnel(self):
        with patch.object(setup_network.shutil, "which", return_value="/opt/homebrew/bin/tailscale"), \
             patch.object(setup_network, "tailscale_state", return_value={
                 "installed": True, "logged_in": True,
                 "device_dns_name": "laptop.example.ts.net",
             }), patch.object(setup_network, "_oauth_guard",
                               side_effect=RuntimeError("Missing OAuth")):
            with self.assertRaises(RuntimeError):
                setup_network.enable_funnel(Path("/tmp/non-existent"))

    def test_owner_refusal_never_runs_tailscale_funnel(self):
        with patch.object(setup_network.shutil, "which", return_value="/opt/homebrew/bin/tailscale"), \
             patch.object(setup_network, "tailscale_state", return_value={
                 "installed": True, "logged_in": True,
                 "device_dns_name": "laptop.example.ts.net",
             }), patch.object(setup_network, "_oauth_guard",
                               return_value={"public_url": "https://laptop.example.ts.net",
                                             "allowed_github_ids": ["12345"]}), \
             patch.object(setup_network.sys.stdin, "isatty", return_value=True), \
             patch.object(setup_network, "run", side_effect=AssertionError("public exposure")):
            with patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(RuntimeError):
                    setup_network.enable_funnel(Path("/example"), input_fn=lambda _: "NO")

    def test_owner_approved_funnel_executes_expected_single_command(self):
        class Success:
            returncode = 0
            stdout = "No serve config"
        with patch.object(setup_network.shutil, "which", return_value="/opt/homebrew/bin/tailscale"), \
             patch.object(setup_network, "tailscale_state", return_value={
                 "installed": True, "logged_in": True,
                 "device_dns_name": "laptop.example.ts.net",
             }), patch.object(setup_network, "_oauth_guard",
                              return_value={"public_url": "https://laptop.example.ts.net",
                                            "allowed_github_ids": ["12345"]}), \
             patch.object(setup_network.sys.stdin, "isatty", return_value=True), \
             patch.object(setup_network, "run", return_value=Success()) as command:
            with patch("sys.stdout", new_callable=io.StringIO):
                outcome = setup_network.enable_funnel(Path("/example"),
                                                      input_fn=lambda _: "PUBLISH")
        self.assertEqual(command.call_count, 2)
        command.assert_any_call(["/opt/homebrew/bin/tailscale", "funnel", "status"])
        command.assert_any_call(
            ["/opt/homebrew/bin/tailscale", "funnel", "--bg", "3201"], timeout=50)
        self.assertFalse(outcome["external_connectivity_verified"])
        self.assertFalse(outcome["github_oauth_login_verified"])

    def test_detects_gui_embedded_cli_without_path_launcher(self):
        with patch.object(setup_network.shutil, "which", return_value=None), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(setup_network.os, "access", return_value=True):
            self.assertEqual(
                setup_network.tailscale_cli(),
                "/Applications/Tailscale.app/Contents/MacOS/Tailscale")

    def test_funnel_existing_configuration_is_not_overwritten(self):
        class Existing:
            returncode = 0
            stdout = "# Funnel on:\nhttps://existing.ts.net (Funnel on)"
        with patch.object(setup_network, "tailscale_cli", return_value="/Applications/Tailscale.app/Contents/MacOS/Tailscale"), \
             patch.object(setup_network, "tailscale_state", return_value={
                 "installed": True, "logged_in": True,
                 "device_dns_name": "laptop.example.ts.net",
             }), patch.object(setup_network, "_oauth_guard", return_value={
                 "public_url": "https://laptop.example.ts.net",
                 "allowed_github_ids": ["12345"],
             }), patch.object(setup_network.sys.stdin, "isatty", return_value=True), \
             patch.object(setup_network, "run", return_value=Existing()) as run:
            with patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(RuntimeError):
                    setup_network.enable_funnel(Path("/example"), input_fn=lambda _: "PUBLISH")
        run.assert_called_once_with(
            ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "funnel", "status"])

    def test_embedded_cli_has_explicit_cli_mode(self):
        with patch.object(setup_network.subprocess, "run") as runner:
            setup_network.run(["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "version"])
        self.assertEqual(runner.call_args.kwargs["env"]["TAILSCALE_BE_CLI"], "1")

    def test_anonymous_401_required(self):
        class Response:
            status = 200
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(setup_network, "check_oauth",
                          return_value={"public_url": "https://laptop.example.ts.net"}), \
             patch.object(setup_network.urllib.request, "urlopen",
                          return_value=Response()):
            with self.assertRaises(RuntimeError):
                setup_network._oauth_guard(Path("/example"))


if __name__ == "__main__":
    unittest.main()
