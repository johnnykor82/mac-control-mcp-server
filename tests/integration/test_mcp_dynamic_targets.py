"""E3: MCP targets are available directly or via existing client configs."""
import json
import asyncio
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, sentinel

from mac_control.legacy_handlers import mcp_bridge_ops as mcp


class DynamicMCPTests(unittest.TestCase):
    def test_http_url_does_not_need_registered_target(self):
        with patch.object(mcp, "CONFIG", Path("/dev/null/absent.json")), \
             patch.object(mcp, "Client", return_value=sentinel.client) as client:
            result = mcp._target("https://example.test/mcp")
        self.assertIs(result, sentinel.client)
        client.assert_called_once_with("https://example.test/mcp")

    def test_stdio_spec_does_not_need_registered_target(self):
        with patch.object(mcp, "StdioTransport", return_value=sentinel.transport) as transport, \
             patch.object(mcp, "Client", return_value=sentinel.client) as client:
            result = mcp._target("one-off", {
                "type": "stdio", "command": "/bin/echo", "args": ["hello"],
                "cwd": "/tmp",
            })
        self.assertIs(result, sentinel.client)
        self.assertEqual(transport.call_args.kwargs["command"], "/bin/echo")
        self.assertEqual(transport.call_args.kwargs["args"], ["hello"])
        client.assert_called_once_with(sentinel.transport)

    def test_direct_url_read_and_write_dispatch_no_registration(self):
        class StubClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def list_tools(self):
                return [
                    SimpleNamespace(name="inspect", annotations={"readOnlyHint": True}),
                    SimpleNamespace(name="change", annotations={"readOnlyHint": False}),
                ]
            async def call_tool(self, name, args):
                return SimpleNamespace(is_error=False, data={"name": name, "args": args})

        url = "https://mcp.example.test/mcp"
        with patch.object(mcp, "Client", return_value=StubClient()), \
             patch.object(mcp, "_media_pack",
                          side_effect=lambda target, tool, value, settings:
                              {"result": value.data}), \
             patch.object(mcp, "CONFIG", Path("/dev/null/none.json")):
            read = asyncio.run(mcp._call(url, "inspect", {}, True))
            write = asyncio.run(mcp._call(url, "change", {"test": True}, False))
            self.assertEqual(read["result"]["name"], "inspect")
            self.assertEqual(write["result"]["args"], {"test": True})
            with self.assertRaises(PermissionError):
                asyncio.run(mcp._call(url, "change", {}, True))

    def test_claude_desktop_config_discovered_without_exposing_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cfg = home / "Library/Application Support/Claude/claude_desktop_config.json"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(json.dumps({"mcpServers": {"demo": {
                "command": "/bin/echo", "args": ["ok"],
                "env": {"API_KEY": "test-secret-not-for-output"},
            }}}))
            with patch.object(Path, "home", return_value=home), \
                 patch.object(mcp, "CONFIG", home / "missing.json"):
                found = mcp._targets()
                self.assertIn("claude:demo", found)
                inventory = mcp._public_targets()
        self.assertIn("claude:demo", [x["name"] for x in inventory])
        self.assertNotIn("test-secret-not-for-output", repr(inventory))


if __name__ == "__main__":
    unittest.main()
