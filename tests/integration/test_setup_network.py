"""Tailscale Funnel onboarding never publishes an unauthenticated endpoint."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
import io
from scripts import setup_network


class NetworkGuidanceTests(unittest.TestCase):
    def test_mismatched_path_cli_uses_matching_app_for_the_same_node(self):
        original = {"Version": "1.104.4-daemon", "BackendState": "Running",
                    "Self": {"ID": "same-node", "DNSName": "mac.tailnet.ts.net."}}
        responses = [Mock(returncode=0, stdout="1.94.1\n"),
                     Mock(returncode=0, stdout=json.dumps(original)),
                     Mock(returncode=0, stdout="1.104.4-app\n"),
                     Mock(returncode=0, stdout=json.dumps(original))]
        with patch.object(setup_network, "tailscale_cli", return_value="/opt/homebrew/bin/tailscale"), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(setup_network.os, "access", return_value=True), \
             patch.object(setup_network, "run", side_effect=responses) as runner:
            result = setup_network.tailscale_state()
        self.assertEqual(result["cli_path"], "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
        self.assertEqual(result["version"], "1.104.4-app")
        self.assertFalse(result["version_mismatch"])
        self.assertTrue(all(call.args[0][1:] in (["version"], ["status", "--json"])
                            for call in runner.call_args_list))

    def test_mismatched_cli_keeps_path_when_app_cannot_match_same_daemon(self):
        original = {"Version": "1.104.4-daemon", "BackendState": "Running",
                    "Self": {"ID": "same-node", "DNSName": "mac.tailnet.ts.net."}}
        for candidate in ({**original, "Self": {"ID": "other-node"}},
                          {**original, "Version": "1.102.4-daemon"},
                          {**original, "Self": {}},
                          {**original, "BackendState": "Stopped"}):
            with self.subTest(candidate=candidate), \
                 patch.object(setup_network, "tailscale_cli", return_value="/opt/homebrew/bin/tailscale"), \
                 patch.object(Path, "is_file", side_effect=[True, False]), \
                 patch.object(setup_network.os, "access", return_value=True), \
                 patch.object(setup_network, "run", side_effect=[
                     Mock(returncode=0, stdout="1.94.1\n"),
                     Mock(returncode=0, stdout=json.dumps(original)),
                     Mock(returncode=0, stdout="1.104.4-app\n"),
                     Mock(returncode=0, stdout=json.dumps(candidate))]):
                result = setup_network.tailscale_state()
            self.assertEqual(result["cli_path"], "/opt/homebrew/bin/tailscale")
            self.assertTrue(result["version_mismatch"])

    def test_compatible_path_cli_never_probes_installed_app(self):
        original = {"Version": "1.104.4-daemon", "BackendState": "Running",
                    "Self": {"ID": "same-node"}}
        with patch.object(setup_network, "tailscale_cli", return_value="/custom/tailscale"), \
             patch.object(Path, "is_file", side_effect=AssertionError("app probe")), \
             patch.object(setup_network, "run", side_effect=[
                 Mock(returncode=0, stdout="1.104.4\n"),
                 Mock(returncode=0, stdout=json.dumps(original))]) as runner:
            result = setup_network.tailscale_state()
        self.assertEqual(result["cli_path"], "/custom/tailscale")
        self.assertFalse(result["version_mismatch"])
        self.assertEqual(runner.call_count, 2)

    def test_mismatch_without_node_identity_never_probes_app(self):
        with patch.object(setup_network, "tailscale_cli", return_value="/custom/tailscale"), \
             patch.object(Path, "is_file", side_effect=AssertionError("app probe")), \
             patch.object(setup_network, "run", side_effect=[
                 Mock(returncode=0, stdout="1.94.1\n"),
                 Mock(returncode=0, stdout=json.dumps({"Version": "1.104.4", "Self": {}}))]):
            result = setup_network.tailscale_state()
        self.assertEqual(result["cli_path"], "/custom/tailscale")
        self.assertTrue(result["version_mismatch"])

    def test_funnel_tls_check_only_reads_the_acme_directory(self):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock(open=Mock(return_value=response))
        with patch.object(setup_network.urllib.request, "build_opener", return_value=opener) as build, \
             patch.object(setup_network, "run", side_effect=AssertionError("Tailscale mutation")), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            result = setup_network.funnel_tls_diagnostics(language="en")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://acme-v02.api.letsencrypt.org/directory")
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 8)
        self.assertTrue(any(isinstance(handler, setup_network._NoRedirect)
                            for handler in build.call_args.args))
        self.assertEqual(result["status"], "acme_reachable_from_setup")
        self.assertFalse(result["daemon_connectivity_verified"])
        self.assertIn("different network or proxy", output.getvalue())
        self.assertIn("Tailscale logs", output.getvalue())

    def test_funnel_tls_check_failure_hides_exception_and_proxy_credentials(self):
        secret = "https://owner:secret@proxy.example/?token=hidden"
        with patch.object(setup_network.urllib.request, "build_opener",
                          return_value=Mock(open=Mock(side_effect=URLError(secret)))), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            result = setup_network.funnel_tls_diagnostics(language="en")
        self.assertEqual(result["status"], "acme_unreachable_from_setup")
        self.assertFalse(result["daemon_connectivity_verified"])
        self.assertNotIn(secret, output.getvalue() + json.dumps(result))
        self.assertNotIn("secret", output.getvalue() + json.dumps(result))
        self.assertIn("certificate", output.getvalue())

    def test_funnel_tls_check_rejects_redirect_and_closes_response(self):
        error = HTTPError("https://acme-v02.api.letsencrypt.org/directory", 302,
                          "redirect", {}, io.BytesIO(b"private response"))
        with patch.object(error, "close") as close, \
             patch.object(setup_network.urllib.request, "build_opener",
                          return_value=Mock(open=Mock(side_effect=error))), \
             patch("sys.stdout", new_callable=io.StringIO):
            result = setup_network.funnel_tls_diagnostics(language="en")
        self.assertEqual(result["status"], "acme_unreachable_from_setup")
        close.assert_called_once()

    def test_funnel_tls_check_warning_uses_russian_when_selected(self):
        with patch.object(setup_network.urllib.request, "build_opener",
                          return_value=Mock(open=Mock(side_effect=TimeoutError()))), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            setup_network.funnel_tls_diagnostics(language="ru")
        self.assertIn("не удалось", output.getvalue())
        self.assertIn("другую сеть или прокси", output.getvalue())
        self.assertIn("журнал", output.getvalue())

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
             patch.object(setup_network, "publication_state", return_value={"status": "empty"}), \
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
                 "cli_path": "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
             }), patch.object(setup_network, "_oauth_guard",
                              return_value={"public_url": "https://laptop.example.ts.net",
                                            "allowed_github_ids": ["12345"]}), \
             patch.object(setup_network.sys.stdin, "isatty", return_value=True), \
             patch.object(setup_network, "publication_state", side_effect=[
                 {"status": "empty"}, {"status": "empty"},
                 {"status": "existing_matching"}]), \
             patch.object(setup_network, "run", return_value=Success()) as command:
            with patch("sys.stdout", new_callable=io.StringIO):
                outcome = setup_network.enable_funnel(Path("/example"),
                                                      input_fn=lambda _: "PUBLISH")
        command.assert_called_once_with(
            ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "funnel", "--bg", "3201"], timeout=50)
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
            stdout = json.dumps({"TCP": {"443": {"HTTPS": True}},
                                 "Web": {"existing.ts.net:443": {
                                     "Handlers": {"/": {"Proxy": "http://127.0.0.1:9999"}}}},
                                 "AllowFunnel": {"existing.ts.net:443": True}})
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
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "funnel", "status", "--json"],
            ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "serve", "status", "--json"],
        ])

    def test_embedded_cli_has_explicit_cli_mode(self):
        with patch.object(setup_network.subprocess, "run") as runner:
            setup_network.run(["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "version"])
        self.assertEqual(runner.call_args.kwargs["env"]["TAILSCALE_BE_CLI"], "1")

    def test_anonymous_401_required(self):
        class Response:
            status = 200
            headers = {}
            def read(self, limit):
                return b'{"issuer":"https://laptop.example.ts.net"}'
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(setup_network, "check_oauth",
                          return_value={"public_url": "https://laptop.example.ts.net"}), \
             patch.object(setup_network.urllib.request, "build_opener",
                          return_value=Mock(open=Mock(return_value=Response()))):
            with self.assertRaises(RuntimeError):
                setup_network._oauth_guard(Path("/example"))


if __name__ == "__main__":
    unittest.main()
