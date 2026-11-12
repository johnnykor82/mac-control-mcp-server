"""Owner-authorized fallback from terminal_exec length validation, not a policy bypass."""
import asyncio
import unittest
from unittest.mock import patch

from scripts.dev_mcp_server import make_server
from mac_control.legacy_adapter import inspect_existing_handlers
from mac_control.legacy_handlers import command_plugins
from mac_control.argument_guidance import guided_handler


class TerminalLongFallbackContractTests(unittest.TestCase):
    def test_mcp_tool_description_explicitly_says_use_fs_write_without_new_permission(self):
        async def metadata():
            server = make_server(include_mutations=True)
            tools = await server.list_tools(run_middleware=False)
            return {t.name: t.description for t in tools}
        descriptions = asyncio.run(metadata())
        text = descriptions["terminal_exec"].lower()
        self.assertIn("8000", text)
        self.assertIn("use fs_write", text)
        self.assertIn("no additional permission", text)
        self.assertIn("same authorized task", text)
        self.assertIn("policy denial", text)
        self.assertIn("short terminal_exec", text)

    def test_too_long_is_nonexecuting_validation_with_direct_alternative(self):
        handler = inspect_existing_handlers()["terminal_exec"].handler
        with patch.object(command_plugins, "_require"), patch.object(
            command_plugins, "_cwd"
        ) as cwd, patch.object(command_plugins.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "TERMINAL_COMMAND_TOO_LONG") as cm:
                handler("x" * 8001)
        value = str(cm.exception).lower()
        for required in (
            "8001", "8000", "validation", "not a permission",
            "use fs_write", "no additional permission",
            "same authorized task", "policy denial",
            "no shell command was executed",
        ):
            with self.subTest(required=required):
                self.assertIn(required, value)
        self.assertNotIn("x" * 20, value)
        cwd.assert_not_called()
        popen.assert_not_called()

    def test_guided_wrapper_retains_exact_fallback_and_does_not_dispatch(self):
        handler = inspect_existing_handlers()["terminal_exec"].handler
        wrapped = guided_handler("terminal_exec", handler)
        with patch.object(command_plugins, "_require"), patch.object(
            command_plugins, "_cwd"
        ) as cwd:
            with self.assertRaisesRegex(ValueError, "TERMINAL_COMMAND_TOO_LONG") as cm:
                wrapped("x" * 8001)
        self.assertIn("no additional permission", str(cm.exception).lower())
        self.assertIn("policy denial", str(cm.exception).lower())
        cwd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
