"""Offline tests for the real ChatBridge Browser API v1 wire contract."""
from __future__ import annotations

import base64
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from mac_control import background_browser_ops as browser

SID = "a" * 32
TOKEN = SID + "." + "b" * 64
FILE = "c" * 32


class HTTPResponse:
    def __init__(self, value, mime="application/json"):
        self.body = json.dumps(value).encode() if isinstance(value, dict) else value
        self.headers = {"Content-Type": mime}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit):
        return self.body[:limit]


class BrowserViaChatBridgeTests(unittest.TestCase):
    def test_create_is_chatbridge_http_not_chrome(self):
        requests = []

        def transport(req, timeout):
            requests.append(req)
            return HTTPResponse({"session_id": SID, "session_token": TOKEN})
        with patch.object(browser.urllib.request, "urlopen", side_effect=transport):
            value = browser._call("create", url="about:blank", mode="background")
        self.assertTrue(value["ok"])
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:8787/v1/browser/sessions")
        self.assertEqual(requests[0].get_method(), "POST")
        self.assertEqual(json.loads(requests[0].data)["mode"], "background")

    def test_action_uses_real_capability_header_and_idempotency_key(self):
        observed = []
        def transport(request, timeout):
            observed.append(request)
            return HTTPResponse({"state": "completed", "result": {"clicked": True},
                                 "operation_id": "op-1"})
        with patch.object(browser.urllib.request, "urlopen", side_effect=transport):
            value = browser._call("action", session_token=TOKEN, action="click", selector="#ok")
        self.assertTrue(value["ok"])
        req = observed[0]
        self.assertEqual(req.full_url, f"http://127.0.0.1:8787/v1/browser/sessions/{SID}/actions")
        self.assertNotIn(TOKEN, req.full_url)
        self.assertEqual(req.get_header("X-browser-session-token"), TOKEN)
        body = json.loads(req.data)
        self.assertRegex(body["client_request_id"], r"^[a-f0-9]{32}$")
        self.assertEqual(value["result"]["client_request_id"], body["client_request_id"])
        self.assertTrue(value["result"]["clicked"])

    def test_action_uncertain_network_failure_includes_reconciliation_id(self):
        with patch.object(browser.urllib.request, "urlopen", side_effect=URLError("down")):
            value = browser._call("action", session_token=TOKEN, action="click")
        self.assertEqual(value["error"]["code"], "UNKNOWN_RESULT")
        self.assertRegex(value["error"]["client_request_id"], r"^[a-f0-9]{32}$")

    def test_missing_route(self):
        with patch.object(browser.urllib.request, "urlopen",
                          side_effect=HTTPError("https://example.invalid", 404, "missing",
                                                {}, io.BytesIO(b"{}"))):
            value = browser._call("create", url="about:blank")
        self.assertEqual(value["error"]["code"], "CHATBRIDGE_API_MISSING")

    def test_bare_screenshot_metadata_causes_second_authorized_file_get(self):
        requests = []
        data = b"\xff\xd8" + b"testjpeg" * 10 + b"\xff\xd9"
        def transport(req, timeout):
            requests.append(req)
            if len(requests) == 1:
                return HTTPResponse({"file_id": FILE, "size_bytes": len(data),
                                     "url": f"/v1/browser/sessions/{SID}/files/{FILE}",
                                     "mime_type": "image/jpeg"})
            return HTTPResponse(data, "image/jpeg")
        with patch.object(browser.urllib.request, "urlopen", side_effect=transport):
            value = browser._call("capture", session_token=TOKEN, quality=70)
        self.assertTrue(value["ok"])
        self.assertEqual(base64.b64decode(value["result"]["image_data"]), data)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[-1].get_header("X-browser-session-token"), TOKEN)

    def test_list_uses_json_post_and_filters_server_side(self):
        requests = []
        def transport(req, timeout):
            requests.append(req)
            return HTTPResponse({"data": [{"session_id": SID}]})
        with patch.object(browser.urllib.request, "urlopen", side_effect=transport):
            value = browser._call("list", session_tokens=[TOKEN])
        self.assertTrue(value["ok"])
        self.assertEqual(value["result"]["sessions"], [{"session_id": SID}])
        self.assertEqual(requests[0].get_method(), "POST")
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:8787/v1/browser/sessions/list")
        self.assertEqual(json.loads(requests[0].data), {"session_tokens": [TOKEN]})

    def test_invalid_capability_never_reaches_chatbridge(self):
        with patch.object(browser.urllib.request, "urlopen", side_effect=AssertionError("called")):
            value = browser._call("action", session_token="../other", action="click")
        self.assertEqual(value["error"]["code"], "INVALID_ARGUMENT")

    def test_provider_failure_preserves_idempotency(self):
        with patch.object(browser.urllib.request, "urlopen",
                          return_value=HTTPResponse({"state": "unknown", "error_code": "OUTCOME_UNCERTAIN",
                                                    "operation_id": "op-5"})):
            value = browser._call("action", session_token=TOKEN, action="click",
                                  client_request_id="known-request-123")
        self.assertEqual(value["error"]["code"], "ACTION_UNKNOWN")
        self.assertEqual(value["error"]["client_request_id"], "known-request-123")


if __name__ == "__main__":
    unittest.main()
