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

EXPECTED["watcher_followup_browser_task"] = False
EXPECTED["watcher_resolve_current_chat"] = False


class FastMCPRegistrationTests(unittest.TestCase):
    def test_frozen_handlers_register_exactly_same_102_tools(self):
        async def probe():
            server = FastMCP("Mac Control offline metadata test")
            for source in (fs_ops, git_ops, system_ops, command_plugins):
                source.register(server)
            return await server.list_tools()

        tools = asyncio.run(probe())
        self.assertEqual(len(tools), 102)
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
