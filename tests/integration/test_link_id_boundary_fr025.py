"""FR-025: external ChatGPT connector link routing != Mac Control MCP args.

These tests intentionally do not attempt OAuth, SSH or platform eligibility.
They check only source-owned FastMCP schemas and framework preflight.
"""
import asyncio
import unittest

from jsonschema import Draft202012Validator
from scripts.dev_mcp_server import make_server


class LinkIdBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        async def collect():
            server = make_server(include_mutations=True)
            return server, {tool.name: tool for tool in await server.list_tools()}
        cls.server, cls.tools = asyncio.run(collect())

    def test_link_id_not_server_side_argument(self):
        expected = {
            "ssh_exec": {"host", "command", "timeout_seconds"},
            "terminal_exec": {"command", "project", "timeout_seconds"},
            "custom_command": {"operation", "arguments"},
        }
        for operation, keys in expected.items():
            with self.subTest(operation=operation):
                schema = self.tools[operation].parameters
                self.assertEqual(set(schema["properties"]), keys | {"audit_context"})
                self.assertEqual(schema.get("additionalProperties"), False)
                self.assertNotIn("link_id", schema["properties"])
                # This is an external routing key; the handler must not
                # learn how to accept it just to appease the connector.
                errors = list(Draft202012Validator(schema).iter_errors(
                    {"link_id": "example-outer-connection-id"}))
                self.assertTrue(any(e.validator == "additionalProperties"
                                    for e in errors))

    def test_framework_names_misplaced_link_id_without_ssh(self):
        async def run():
            with self.assertRaises(Exception) as error:
                # Required host/command missing: this cannot dispatch SSH.
                await self.server.call_tool(
                    "ssh_exec", {"link_id": "wrong-layer-example"})
            msg = str(error.exception)
            self.assertIn("link_id", msg)
            self.assertIn("host", msg)
            self.assertIn("command", msg)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
