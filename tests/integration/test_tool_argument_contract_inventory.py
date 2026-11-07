"""FR-025: all MCP schemas are auditable without invoking tool operations."""
import asyncio
import unittest

from mac_control import background_browser_ops, background_native_ops
from scripts.audit_tool_argument_contracts import audit, _raises, render_markdown
from pathlib import Path


class ArgumentContractInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = asyncio.run(audit())

    def test_whole_shipped_catalog_including_opt_in_tools(self):
        summary = self.report["summary"]
        self.assertEqual(summary["tools"], 142)
        self.assertEqual(summary["frozen"], 112)
        self.assertEqual(summary["additional"], 30)
        self.assertEqual(len({x["name"] for x in self.report["tools"]}), 142)

    def test_missing_arguments_and_types_are_visible(self):
        by_name = {x["name"]: x for x in self.report["tools"]}
        self.assertEqual(by_name["ssh_exec"]["required"], ["audit_context", "command", "host"])
        self.assertIn("timeout_seconds", by_name["ssh_exec"]["parameters"])
        self.assertEqual(by_name["custom_command"]["required"], ["audit_context", "operation"])
        self.assertIn("session_token", by_name["background_browser_action"]["required"])
        self.assertTrue(by_name["audit_search"]["read_only"])
        self.assertTrue(by_name["self_update_status"]["read_only"])
        self.assertFalse(by_name["self_update_start"]["read_only"])
        self.assertIn("with_chatbridge", by_name["self_update_start"]["parameters"])

    def test_shared_helpers_included_in_audit_matrix(self):
        modules = self.report["module_inventory"]
        self.assertGreaterEqual(len(modules), 20)
        lookup = {m["module"]: m for m in modules}
        self.assertIn("maintenance_ops.py", lookup)
        self.assertIn("background_browser_ops.py", lookup)
        self.assertIn("ssh_manage_ops.py", lookup)
        self.assertGreater(lookup["ssh_manage_ops.py"]["exception_sites"]["ValueError"], 0)

    def test_source_report_matches_generated_contract(self):
        root = Path(__file__).resolve().parents[2]
        actual = (root / "docs/TOOL_ARGUMENT_AUDIT_FR025.md").read_text()
        self.assertEqual(actual, render_markdown(self.report))

    def test_registration_does_not_enable_optional_runtime_flags(self):
        browser_before = background_browser_ops.enabled()
        native_before = background_native_ops.enabled()
        asyncio.run(audit())
        self.assertEqual(background_browser_ops.enabled(), browser_before)
        self.assertEqual(background_native_ops.enabled(), native_before)

    def test_dynamic_exception_values_are_never_captured(self):
        def rejects(value):
            raise ValueError(f"Invalid caller value: {value}")
        messages = _raises(rejects)
        self.assertTrue(messages)
        # The inspected source has only a dynamic expression, no input values.
        self.assertEqual(messages, [("ValueError", "")])


if __name__ == "__main__":
    unittest.main()
