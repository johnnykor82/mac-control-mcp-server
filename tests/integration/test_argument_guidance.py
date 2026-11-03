"""FR-023 fail-closed, user-actionable argument errors across MCP tools."""
import asyncio
import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class ArgumentGuidanceTests(unittest.TestCase):
    def test_all_direct_frozen_handlers_have_guidance_in_registration(self):
        from mac_control.legacy_adapter import inspect_existing_handlers
        from mac_control.dev_enabled_operations import guided_handler
        entries = inspect_existing_handlers()
        self.assertEqual(len(entries), 106)
        for name, entry in entries.items():
            with self.subTest(name=name):
                wrapped = guided_handler(name, entry.handler)
                self.assertEqual(inspect.signature(wrapped), inspect.signature(entry.handler))
                self.assertEqual(inspect.iscoroutinefunction(wrapped),
                                 inspect.iscoroutinefunction(entry.handler))
                self.assertIs(wrapped.__wrapped__, entry.handler)

    def test_gui_argument_error_has_bounded_remedy(self):
        from mac_control.argument_guidance import guided_handler
        def gui_mouse(action: str, x: int, y: int):
            raise ValueError("Unsupported mouse action")
        wrapped=guided_handler("gui_mouse", gui_mouse)
        with self.assertRaisesRegex(ValueError, "VALIDATION_ERROR") as x:
            wrapped("new_action", 5, 7)
        m=str(x.exception)
        self.assertIn("gui_mouse",m)
        self.assertIn("gui_status",m)
        self.assertIn("action",m)
        self.assertNotIn("new_action",m)

    def test_ssh_detailed_error_is_preserved(self):
        from mac_control.argument_guidance import guided_handler
        def ssh_exec(host,command):
            raise ValueError("SSH_COMMAND_TOO_LONG: command has 65537 UTF-8 bytes; maximum 65536; use ssh_write_text")
        wrapped=guided_handler("ssh_exec",ssh_exec)
        with self.assertRaisesRegex(ValueError,"SSH_COMMAND_TOO_LONG") as x:
            wrapped("demo","abc")
        self.assertIn("65537",str(x.exception))

    def test_authorization_denial_is_never_reframed_as_retry(self):
        from mac_control.argument_guidance import guided_handler
        def fs_read(path):raise PermissionError("Path outside approved root")
        wrapped=guided_handler("fs_read",fs_read)
        with self.assertRaises(PermissionError) as x:
            wrapped("../etc")
        self.assertNotIn("VALIDATION_ERROR",str(x.exception))

    def test_opaque_secrets_are_not_quoted_in_error(self):
        from mac_control.argument_guidance import guided_handler
        marker="TEST_INPUT_MARKER_DO_NOT_ECHO_20261103"
        def terminal_exec(command:str):raise ValueError("Invalid command "+marker)
        wrapped=guided_handler("terminal_exec",terminal_exec)
        with self.assertRaises(ValueError) as x:wrapped(marker)
        self.assertIn("terminal_capabilities",str(x.exception))
        self.assertNotIn(marker,str(x.exception))

    def test_unknown_value_error_after_side_effect_does_not_claim_preflight(self):
        from mac_control.argument_guidance import guided_handler
        effects=[]
        def fs_write(content):
            effects.append("written")
            raise ValueError("remote write already committed: confidential_value")
        with self.assertRaises(ValueError) as error:
            guided_handler("fs_write",fs_write)("private")
        self.assertEqual(effects,["written"])
        msg=str(error.exception)
        self.assertIn("TOOL_VALUE_ERROR",msg)
        self.assertIn("Inspect the audit and actual state",msg)
        self.assertNotIn("confidential_value",msg)

    def test_parameter_error_recovery_matrix_across_tool_families(self):
        from mac_control.argument_guidance import guided_handler
        cases=[
            ("terminal_send", "Unsupported key", "terminal_capabilities"),
            ("gui_mouse", "Unsupported mouse action", "gui_status"),
            ("fs_search", "Search text must be 1–160 characters", "project_roots"),
            ("git_stage", "Supply 1–20 explicit paths", "git_status"),
            ("ssh_profile_register", "Invalid SSH host parameters", "ssh_profile_inventory"),
            ("watcher_submit_report", "Expected JSON payload", "watcher_guide"),
            ("chrome_chat_send", "Task archived; restore it before sending", "chrome_chat_ui_status"),
            ("mcp_bridge_call", "Arguments too large", "mcp_targets"),
            ("package_install", "Invalid formula", "package_capabilities"),
            ("project_task", "Invalid command", "project_roots"),
            ("launchd_restart", "Invalid command", "launchd_status"),
            ("network_listeners", "Invalid command", "network_listeners"),
            ("local_http_probe", "Invalid command", "system_info"),
        ]
        for tool, cause, expected in cases:
            with self.subTest(tool=tool):
                def reject(arg):
                    raise ValueError(cause)
                with self.assertRaises(ValueError) as error:
                    guided_handler(tool,reject)("private_input_never_display")
                message=str(error.exception)
                self.assertIn("VALIDATION_ERROR",message)
                self.assertIn(expected,message)
                self.assertNotIn("private_input_never_display",message)

    def test_fastmcp_direct_missing_parameter_is_named_by_schema(self):
        from scripts.dev_mcp_server import make_server
        mcp=make_server(include_mutations=True)
        async def exercise():
            with self.assertRaises(Exception) as failure:
                await mcp.call_tool("ssh_exec", {"host":"example"})
            message=str(failure.exception)
            self.assertIn("command",message)
            self.assertIn("Missing required argument",message)
        asyncio.run(exercise())

    def test_nonvalidation_runtime_error_kept_unmodified(self):
        from mac_control.argument_guidance import guided_handler
        def watcher_status():raise RuntimeError("Watcher unavailable")
        with self.assertRaisesRegex(RuntimeError,"Watcher unavailable"):
            guided_handler("watcher_status",watcher_status)()

    def test_nested_custom_command_signature_error(self):
        from scripts.dev_mcp_server import make_server
        mcp=make_server(include_mutations=True)
        async def exercise():
            with self.assertRaises(Exception) as captured:
                await mcp.call_tool("custom_command",{
                    "operation":"ssh_exec","arguments":{"host":"example"}})
            msg=str(captured.exception)
            self.assertIn("VALIDATION_ERROR",msg)
            self.assertIn("ssh_exec",msg)
            self.assertIn("command",msg)
            self.assertIn("ssh_write_text",msg)
        asyncio.run(exercise())

    def test_unknown_nested_operation_suggests_help(self):
        from scripts.dev_mcp_server import make_server
        mcp=make_server(include_mutations=True)
        async def exercise():
            with self.assertRaises(Exception) as x:
                await mcp.call_tool("custom_query", {"operation":"not_a_tool","arguments":{}})
            self.assertIn("custom_query(operation='help')",str(x.exception))
        asyncio.run(exercise())


if __name__=="__main__":
    unittest.main()
