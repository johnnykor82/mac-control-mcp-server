"""Exact deployed Dev tool surface: existing bounded, read-only operations."""
import asyncio
from pathlib import Path
import json
import unittest

from fastmcp import FastMCP
from mac_control.dev_enabled_operations import (
    READ_ONLY_PREVIEW_OPERATIONS, register_preview_operations,
)
from mac_control.legacy_adapter import inspect_existing_handlers

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = {item["name"]: item for item in json.loads(
    (ROOT / "contracts/current-dynamic-operations.json").read_text()
)["operations"]}


class PreviewExposureTests(unittest.TestCase):
    def test_expected_mcp_tool_set_and_metadata(self):
        async def retrieve():
            server = FastMCP("offline preview test")
            register_preview_operations(server)
            return await server.list_tools()
        tools = asyncio.run(retrieve())
        names = {x.name for x in tools}
        self.assertEqual(names, READ_ONLY_PREVIEW_OPERATIONS)
        self.assertEqual(len(tools), len(names))
        for t in tools:
            self.assertTrue(t.annotations.read_only_hint)
            self.assertFalse(t.annotations.open_world_hint)
            self.assertTrue(SNAPSHOT[t.name]["read_only_hint"])
            self.assertTrue(t.description)
            self.assertEqual(t.parameters["type"], "object")

    def test_all_names_unchanged_and_no_write_tools(self):
        frozen = inspect_existing_handlers()
        self.assertEqual(len(READ_ONLY_PREVIEW_OPERATIONS), 19)
        self.assertTrue(READ_ONLY_PREVIEW_OPERATIONS.issubset(set(frozen)))
        for name in READ_ONLY_PREVIEW_OPERATIONS:
            self.assertTrue(frozen[name].read_only)
        self.assertNotIn("terminal_exec", READ_ONLY_PREVIEW_OPERATIONS)
        self.assertNotIn("fs_write", READ_ONLY_PREVIEW_OPERATIONS)
        self.assertNotIn("git_commit", READ_ONLY_PREVIEW_OPERATIONS)
        self.assertNotIn("mcp_bridge_call", READ_ONLY_PREVIEW_OPERATIONS)

    def test_loopback_server_is_preconfigured_not_generic_proxy(self):
        source = (ROOT / "scripts" / "dev_mcp_server.py").read_text()
        self.assertIn('host="127.0.0.1"', source)
        self.assertNotIn("0.0.0.0", source)
        self.assertNotIn("runpy", source)
        self.assertNotIn("importlib", source)


if __name__ == "__main__":
    unittest.main()
