"""FR-025: distinguish argument, configuration and provider protocol errors."""
import unittest
from unittest.mock import patch

from mac_control import background_browser_ops as browser
from tests.integration.test_chatbridge_browser_adapter import HTTPResponse, TOKEN


class BrowserArgumentDiagnosticsTests(unittest.TestCase):
    def test_bad_capability_keeps_legacy_code_but_names_field_and_remedy(self):
        with patch.object(browser.urllib.request, "urlopen", side_effect=AssertionError("HTTP called")):
            result = browser._call("action", session_token="not-token", action="click")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        self.assertIn("session_token", result["error"]["message"])
        self.assertIn("background_browser_create", result["error"]["message"])
        self.assertNotIn("not-token", result["error"]["message"])

    def test_bad_idempotency_key_explains_length_without_http(self):
        with patch.object(browser.urllib.request, "urlopen", side_effect=AssertionError("HTTP called")):
            result = browser._call("action", session_token=TOKEN, action="click",
                                   client_request_id="x")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        self.assertIn("client_request_id", result["error"]["message"])
        self.assertIn("180", result["error"]["message"])

    def test_bad_session_list_explains_expected_shape_without_http(self):
        with patch.object(browser.urllib.request, "urlopen", side_effect=AssertionError("HTTP called")):
            result = browser._call("list", session_tokens="not-a-list")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        self.assertIn("session_tokens", result["error"]["message"])
        self.assertIn("list", result["error"]["message"])

    def test_malformed_provider_response_is_not_argument_error(self):
        with patch.object(browser.urllib.request, "urlopen", return_value=HTTPResponse(
                b"<html>server bug</html>", "text/html")):
            result = browser._call("create", url="about:blank")
        self.assertEqual(result["error"]["code"], "INVALID_PROVIDER_RESPONSE")
        self.assertIn("do not", result["error"]["message"].lower())

    def test_malformed_gateway_config_is_not_argument_error(self):
        with patch.dict(browser.os.environ, {"MACCONTROL_CHATBRIDGE_URL": "http://127.0.0.1:9999/extra"}),              patch.object(browser.urllib.request, "urlopen", side_effect=AssertionError("HTTP called")):
            result = browser._call("create", url="about:blank")
        self.assertEqual(result["error"]["code"], "CHATBRIDGE_CONFIGURATION_ERROR")
        self.assertIn("MACCONTROL_CHATBRIDGE_URL", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
