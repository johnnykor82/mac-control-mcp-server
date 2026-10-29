"""Mac Control MCP Server workspace-first MCP contract tests."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mac_control import workspace_policy
from mac_control import dev_enabled_operations as operations
from mac_control.legacy_handlers import command_plugins, fs_ops
from scripts.dev_mcp_server import make_server


class WorkspaceAgentPolicyTests(unittest.TestCase):
    def test_mcp_server_instructions_and_discoverable_policy_tool(self):
        server = make_server(include_mutations=True)
        names = {tool.name: tool for tool in asyncio.run(server.list_tools())}
        self.assertIn("workspace_policy", names)
        self.assertTrue(names["workspace_policy"].annotations.read_only_hint)
        self.assertIn("workspace", names["terminal_exec"].description)
        self.assertIn("owner", names["fs_write"].description)
        result = workspace_policy.details()
        self.assertEqual(result["default_write_project"], "workspace")
        self.assertIn("projects", result["project_directory"])
        self.assertIn("direct, specific instruction", result["instructions"])

    def test_terminal_workspace_stays_default_and_tmpdir_is_inside(self):
        self.assertEqual(command_plugins.ENVIRONMENT["TMPDIR"],
                         str(fs_ops.WORKSPACE / "scratch/tmp"))
        self.assertEqual(command_plugins.ENVIRONMENT["XDG_CACHE_HOME"],
                         str(fs_ops.WORKSPACE / "scratch/cache"))
        self.assertTrue(command_plugins.ENVIRONMENT["TMPDIR"].startswith(
            str(fs_ops.WORKSPACE)))
        self.assertIn('project: str = "workspace"',
                      __import__("inspect").getsource(command_plugins.register))

    def test_preexisting_outside_files_not_moved(self):
        with tempfile.TemporaryDirectory() as base:
            outside = Path(base) / "existing-project"
            outside.mkdir()
            existing = outside / "README.md"
            existing.write_text("preserve")
            _ = workspace_policy.details()
            self.assertEqual(existing.read_text(), "preserve")

    def test_workspace_project_roots_reports_policy(self):
        class Collector:
            def __init__(self): self.methods = {}
            def tool(self, **kwargs):
                def decorator(fn):
                    self.methods[fn.__name__] = fn
                    return fn
                return decorator
        collector = Collector()
        fs_ops.register(collector)
        result = collector.methods["project_roots"]()
        self.assertEqual(result["default_write_project"], "workspace")
        self.assertIn("workspace", result["projects"])


if __name__ == "__main__":
    unittest.main()
