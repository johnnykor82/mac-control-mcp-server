"""E4: detect occupied ports and authenticated ChatBridge readiness."""
import io
import socket
import urllib.error
import unittest
from unittest.mock import patch

from scripts import setup_chatbridge_dependency as bridge
from scripts import install_mac_control as installer
from pathlib import Path


class RequiredReadinessTests(unittest.TestCase):
    def test_compatible_chatbridge_keeps_original_endpoint(self):
        with patch.object(bridge, "verify", return_value={"status": "compatible"}):
            self.assertEqual(bridge.select_endpoint("http://127.0.0.1:8787"),
                             "http://127.0.0.1:8787")

    def test_busy_foreign_port_selects_other_loopback_endpoint(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            target = f"http://127.0.0.1:{busy.getsockname()[1]}"
            with patch.object(bridge, "verify", side_effect=RuntimeError("not ChatBridge")):
                other = bridge.select_endpoint(target)
        self.assertTrue(other.startswith("http://127.0.0.1:"), other)
        self.assertNotEqual(other, target)

    def test_managed_install_does_not_claim_foreign_compatible_endpoint(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            endpoint = f"http://127.0.0.1:{busy.getsockname()[1]}"
            with patch.object(bridge, "verify", return_value={"status": "compatible"}):
                managed = bridge.select_endpoint(endpoint, reuse_compatible=False)
        self.assertNotEqual(managed, endpoint)

    def test_unreachable_browser_reports_incomplete_not_success(self):
        reason = urllib.error.URLError(ConnectionRefusedError(61, "refused"))
        with patch.object(bridge.urllib.request, "urlopen", side_effect=reason):
            state = bridge.browser_login_status("http://127.0.0.1:8787")
        self.assertFalse(state["authenticated"])
        self.assertEqual(state["status"], "unavailable")

    def test_installer_uses_actual_selected_endpoint_and_auth_probe(self):
        with patch.object(installer.sys, "platform", "darwin"), \
             patch.object(bridge, "ensure", return_value={
                 "status": "compatible", "url": "http://127.0.0.1:18787"}), \
             patch.object(bridge, "browser_login_status", return_value={
                 "status": "login_required", "authenticated": False}) as check, \
             patch.object(installer, "find_uv", side_effect=RuntimeError("stop")):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                installer.install(Path("/tmp/test-chatbridge-installer"))
        check.assert_called_once_with("http://127.0.0.1:18787")

    def test_ready_is_stricter_than_browser_capabilities(self):
        with patch.object(bridge.urllib.request, "urlopen",
                          return_value=io.BytesIO(b'{"ready":true,"chatgpt_authenticated":true}')):
            self.assertTrue(bridge.browser_login_status("http://127.0.0.1:8787")["authenticated"])
        with patch.object(bridge.urllib.request, "urlopen",
                          return_value=io.BytesIO(b'{"ready":true,"chatgpt_authenticated":null}')):
            false_ready = bridge.browser_login_status("http://127.0.0.1:8787")
        self.assertFalse(false_ready["authenticated"], "mock transport is NOT ChatGPT login")
        missing = urllib.error.HTTPError("http://127.0.0.1:8787/ready", 503,
                                         "login required", {}, None)
        with patch.object(bridge.urllib.request, "urlopen", side_effect=missing):
            state = bridge.browser_login_status("http://127.0.0.1:8787")
        self.assertFalse(state["authenticated"])
        self.assertEqual(state["status"], "login_required")


if __name__ == "__main__":
    unittest.main()
