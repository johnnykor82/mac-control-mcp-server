"""FR-025: MCP clients see recoverable errors without running operations."""
import asyncio
import unittest
from unittest.mock import patch

from scripts.dev_mcp_server import make_server
from mac_control import background_browser_ops, background_native_ops
from mac_control.legacy_handlers import command_plugins, watcher_ops, gui_ops, git_ops


class ActualMCPErrorResponseTests(unittest.TestCase):
    def test_invalid_inputs_do_not_dispatch_or_contact_external_services(self):
        async def verify():
            with patch.object(background_browser_ops, "enabled", return_value=True),                  patch.object(background_native_ops, "enabled", return_value=True):
                server = make_server(include_mutations=True)
            cases = [
                ("terminal_exec", {"command": "x" * 8001}, "TERMINAL_COMMAND_TOO_LONG"),
                ("custom_command", {"operation": "terminal_exec",
                                    "arguments": {"command": "x" * 8001}},
                 "TERMINAL_COMMAND_TOO_LONG"),
                ("watcher_status", {"project_id": "BAD ID"}, "WATCHER_ID_INVALID"),
                ("gui_mouse", {"action": "wrong", "x": 0, "y": 0},
                 "GUI_MOUSE_ACTION_INVALID"),
                ("git_create_branch", {"project": "workspace", "name": "bad name"},
                 "GIT_BRANCH_NAME_INVALID"),
            ]
            with patch.object(command_plugins, "_cwd",
                              side_effect=AssertionError("shell invoked")),                  patch.object(watcher_ops, "_cli",
                              side_effect=AssertionError("watcher invoked")),                  patch.object(gui_ops, "_call",
                              side_effect=AssertionError("GUI invoked")),                  patch.object(git_ops, "git",
                              side_effect=AssertionError("git invoked")),                  patch.object(background_browser_ops.urllib.request, "urlopen",
                              side_effect=AssertionError("network invoked")):
                for tool, arguments, code in cases:
                    with self.subTest(tool=tool):
                        with self.assertRaises(Exception) as error:
                            await server.call_tool(tool, {**arguments, 'audit_context':{"task_id":"BF26-REGRESSION", "action":"Run isolated validation and inspect expected error without changing external state", "authorization_basis":"User approved development testing on 2026-11-06"}})
                        self.assertIn(code, str(error.exception))
                response = await server.call_tool("background_browser_action", {
                    "session_token": "bad", "action": "click", "audit_context":{"task_id":"BF26-REGRESSION", "action":"Run isolated validation and inspect expected error without changing external state", "authorization_basis":"User approved development testing on 2026-11-06"}})
                self.assertEqual(response.structured_content["error"]["code"],
                                 "INVALID_ARGUMENT")
                self.assertIn("session_token",
                              response.structured_content["error"]["message"])
        asyncio.run(verify())


if __name__ == "__main__":
    unittest.main()
