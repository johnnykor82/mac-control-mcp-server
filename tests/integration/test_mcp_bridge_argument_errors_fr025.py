"""FR025: caller-correctable MCP target failures name required values."""
import unittest
from unittest.mock import patch

from mac_control.argument_guidance import guided_handler
from mac_control.legacy_handlers import mcp_bridge_ops as mcp


class MCPBridgeArgumentTests(unittest.TestCase):
    def test_invalid_name_mentions_syntax_and_discovery(self):
        with patch.object(mcp, "_targets", side_effect=AssertionError("no discovery")):
            with self.assertRaisesRegex(ValueError, "MCP_TARGET_NAME_INVALID") as error:
                mcp._settings("a name with spaces")
        msg = str(error.exception)
        self.assertIn("mcp_targets", msg)
        self.assertIn("130", msg)
        self.assertNotIn("a name with spaces", msg)

    def test_missing_target_suggests_existing_targets(self):
        with patch.object(mcp, "_targets", return_value={}):
            with self.assertRaisesRegex(ValueError, "MCP_TARGET_NOT_FOUND") as error:
                mcp._settings("not-configured")
        self.assertIn("mcp_targets", str(error.exception))
        self.assertIn("target_spec", str(error.exception))

    def test_malformed_url_rejected_before_client_creation(self):
        with patch.object(mcp, "Client", side_effect=AssertionError("Client created")):
            with self.assertRaisesRegex(ValueError, "MCP_URL_INVALID") as error:
                mcp._target("not-relevant", {"type": "http", "url":
                           "https://demo.invalid/mcp?token=private"})
        msg = str(error.exception)
        self.assertIn("http", msg)
        self.assertNotIn("private", msg)

    def test_handler_preserves_precise_mcp_target_code(self):
        def bridge(_target):
            raise ValueError("MCP_TARGET_NOT_FOUND: inspect mcp_targets; no request dispatched.")
        wrapped = guided_handler("mcp_bridge_read", bridge)
        with self.assertRaisesRegex(ValueError, "MCP_TARGET_NOT_FOUND") as error:
            wrapped("absent")
        self.assertIn("mcp_targets", str(error.exception))


if __name__ == "__main__":
    unittest.main()
