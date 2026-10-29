"""Legacy launch delegates idle browser startup to ChatBridge HTTP."""
from __future__ import annotations

import io
import json
import os
import unittest
from unittest.mock import patch

from mac_control.legacy_handlers import chrome_orchestrator_ops as chrome


class ToolRegistry:
    def __init__(self):
        self.tools = {}

    def tool(self, **_):
        def register(function):
            self.tools[function.__name__] = function
            return function
        return register


class LegacyChromeWakeTests(unittest.TestCase):
    def setUp(self):
        registry = ToolRegistry()
        chrome.register(registry)
        self.launch = registry.tools["chrome_orchestrator_launch"]

    def test_idle_launch_waits_for_gateway_wake_with_auth_and_longer_timeout(self):
        requests = []
        running = {"state": "running", "pid": 123, "cdp_connected": True}

        def transport(request, timeout):
            requests.append((request, timeout))
            value = {"browser": {"state": "idle"}} if len(requests) == 1 else {"browser": running}
            return io.BytesIO(json.dumps(value).encode())

        with patch.dict(os.environ, {"MACCONTROL_CHATBRIDGE_API_KEY": "test-key"}), \
             patch.object(chrome.urllib.request, "urlopen", side_effect=transport):
            result = self.launch()

        self.assertTrue(result["running"])
        self.assertEqual(result["browser"], running)
        self.assertTrue(result["reused"])
        self.assertFalse(result["launched_by_mac_control"])
        self.assertEqual([(request.get_method(), request.full_url) for request, _ in requests], [
            ("GET", chrome.GATEWAY + "/v1/system/status"),
            ("POST", chrome.GATEWAY + "/v1/browser/wake"),
        ])
        self.assertEqual([timeout for _, timeout in requests], [22, 60])
        for request, _ in requests:
            self.assertEqual(request.get_header("Authorization"), "Bearer test-key")

    def test_other_states_preserve_existing_behavior_without_wake(self):
        for state in ("running", "starting", "unavailable", "stopped"):
            with self.subTest(state=state), \
                 patch.object(chrome, "_api", return_value={"browser": {"state": state}}) as api:
                if state == "running":
                    self.assertTrue(self.launch()["running"])
                else:
                    with self.assertRaisesRegex(RuntimeError, "ChatBridge unavailable"):
                        self.launch()
                api.assert_called_once_with("GET", "/v1/system/status")


if __name__ == "__main__":
    unittest.main()
