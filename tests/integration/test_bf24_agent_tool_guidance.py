"""BF24: recoverable MCP tool alternatives and discoverable orchestration."""
import asyncio
import unittest

from mac_control.argument_guidance import guided_handler
from scripts.dev_mcp_server import make_server


class BF24AgentGuidanceTests(unittest.TestCase):
    def test_recoverable_error_authorizes_existing_alternative_without_new_prompt(self):
        def terminal_exec(command):
            raise ValueError("Invalid command")
        with self.assertRaises(ValueError) as caught:
            guided_handler("terminal_exec", terminal_exec)("bad")
        msg = str(caught.exception)
        self.assertIn("without additional user approval", msg)
        self.assertIn("permission/policy", msg)

    def test_watcher_metadata_contains_full_orchestration_handoff(self):
        async def probe():
            tools = await make_server(include_mutations=True).list_tools()
            return {tool.name: tool.description for tool in tools}
        descriptions = asyncio.run(probe())
        for name, description in descriptions.items():
            if name.startswith("watcher_"):
                with self.subTest(tool=name):
                    self.assertIn("watcher_guide", description)
        guide = descriptions["watcher_guide"]
        for token in ("watcher_spawn_subagent", "watcher_status",
                      "watcher_read_report", "watcher_ack_delivery",
                      "watcher_approve_goal", "watcher_return_for_rework",
                      "WC"):
            self.assertIn(token, guide)

    def test_policy_denial_remains_unmodified(self):
        def terminal_exec(command):
            raise PermissionError("Denied by platform")
        with self.assertRaisesRegex(PermissionError, "Denied by platform"):
            guided_handler("terminal_exec", terminal_exec)("command")


if __name__ == "__main__":
    unittest.main()
