"""In-memory FastMCP registration parity; no listener, requests or tool calls."""
import asyncio
import json
from pathlib import Path
import unittest

from fastmcp import FastMCP
from mac_control.legacy_handlers import (
    command_plugins, fs_ops, git_ops, system_ops,
)

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    name: read
    for name, read in json.loads(
        (ROOT / "contracts/stable-parity-20261023.json").read_text()
    )["operations"].items()
}

for _retired in ("approved_commands", "execute_approved", "terminal_access_configure"):
    EXPECTED.pop(_retired, None)

EXPECTED["watcher_followup_browser_task"] = False
EXPECTED["watcher_resolve_current_chat"] = False

for _name in ("ssh_upload","ssh_download","ssh_write_text","ssh_transfer_begin",
              "ssh_transfer_chunk","ssh_transfer_finish","ssh_transfer_cancel"):
    EXPECTED[_name] = False


class FastMCPRegistrationTests(unittest.TestCase):
    def test_frozen_handlers_register_exactly_106_tools(self):
        async def probe():
            server = FastMCP("Mac Control offline metadata test")
            for source in (fs_ops, git_ops, system_ops, command_plugins):
                source.register(server)
            return await server.list_tools()

        tools = asyncio.run(probe())
        self.assertEqual(len(tools), 106)
        self.assertEqual(
            {tool.name: tool.annotations.read_only_hint for tool in tools},
            EXPECTED,
        )
        for tool in tools:
            with self.subTest(tool=tool.name):
                self.assertIsInstance(tool.description, str)
                self.assertTrue(tool.description)
                self.assertIsInstance(tool.parameters, dict)
                self.assertEqual(tool.parameters.get("type"), "object")


if __name__ == "__main__":
    unittest.main()
