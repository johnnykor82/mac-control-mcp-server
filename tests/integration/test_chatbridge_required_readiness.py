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
        check.assert_called_once_with("http://127.0.0.1:18787", verify_idle=True)

    def test_passive_status_distinguishes_idle_from_logout(self):
        body=b'{"ready":false,"chatgpt_authenticated":null,"reason":"browser_idle"}'
        def probe(request, timeout):
            raise urllib.error.HTTPError(request.full_url,503,"idle",{},io.BytesIO(body))
        with patch.object(bridge.urllib.request,"urlopen",side_effect=probe) as send:
            state=bridge.browser_login_status("http://127.0.0.1:8787")
        self.assertEqual(state["status"],"browser_idle")
        self.assertFalse(state["authenticated"])
        send.assert_called_once()

    def test_installer_explicitly_verifies_sleeping_managed_profile(self):
        body=b'{"ready":false,"chatgpt_authenticated":null,"reason":"browser_idle"}'
        requests=[]
        def probe(request, timeout):
            requests.append((request.get_method(),request.full_url,timeout))
            if len(requests)==1:
                raise urllib.error.HTTPError(request.full_url,503,"idle",{},io.BytesIO(body))
            return io.BytesIO(b'{"ready":true,"chatgpt_authenticated":true}')
        with patch.object(bridge.urllib.request,"urlopen",side_effect=probe):
            state=bridge.browser_login_status("http://127.0.0.1:8787",verify_idle=True)
        self.assertTrue(state["authenticated"])
        self.assertEqual(state["status"],"ready")
        self.assertEqual([x[0] for x in requests],["GET","POST"])
        self.assertTrue(requests[1][1].endswith("/v1/browser/verify"))
        self.assertGreaterEqual(requests[1][2],45)

    def test_explicit_verification_rejects_missing_composer(self):
        idle=b'{"ready":false,"chatgpt_authenticated":null,"reason":"browser_idle"}'
        denied=b'{"ready":false,"chatgpt_authenticated":false,"reason":"auth_required_or_browser_unavailable"}'
        count=[0]
        def probe(request, timeout):
            count[0]+=1
            body=idle if count[0]==1 else denied
            raise urllib.error.HTTPError(request.full_url,503,"not ready",{},io.BytesIO(body))
        with patch.object(bridge.urllib.request,"urlopen",side_effect=probe):
            state=bridge.browser_login_status("http://127.0.0.1:8787",verify_idle=True)
        self.assertFalse(state["authenticated"])
        self.assertEqual(state["status"],"unverified")
        self.assertEqual(count[0],2)

    def test_browser_unavailable_is_not_login_required(self):
        body=b'{"ready":false,"chatgpt_authenticated":false,"reason":"browser_unavailable"}'
        with patch.object(bridge.urllib.request,"urlopen",side_effect=urllib.error.HTTPError(
            "http://127.0.0.1:8787/ready",503,"bad",{},io.BytesIO(body))):
            state=bridge.browser_login_status("http://127.0.0.1:8787",verify_idle=True)
        self.assertEqual(state["status"],"unavailable")
        self.assertFalse(state["authenticated"])

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
        self.assertEqual(state["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
