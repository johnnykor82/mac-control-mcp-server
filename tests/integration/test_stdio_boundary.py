"""No writable operations are reachable on Dev HTTP; local stdio is explicit."""
import asyncio
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.dev_mcp_server import make_server
from mac_control.dev_enabled_operations import (
    LOCAL_MUTATION_OPERATIONS, LOCAL_COMPAT_READ_OPERATIONS, LOCAL_GUI_READ_OPERATIONS,
    LOCAL_TERMINAL_READ_OPERATIONS, LOCAL_BRIDGE_READ_OPERATIONS,
    READ_ONLY_PREVIEW_OPERATIONS,
)
from mac_control.legacy_adapter import inspect_existing_handlers


class StdioBoundaryTests(unittest.TestCase):
    def test_http_is_read_only_and_stdio_has_bounded_local_writes(self):
        async def tools(server):
            return await server.list_tools()
        http = asyncio.run(tools(make_server()))
        with patch("mac_control.background_browser_ops.enabled",return_value=False), patch("mac_control.background_native_ops.enabled",return_value=False):
            stdio = asyncio.run(tools(make_server(include_mutations=True)))
        web = {t.name:t.annotations.read_only_hint for t in http}
        local = {t.name:t.annotations.read_only_hint for t in stdio}
        self.assertEqual(set(web), {"system_info"}|READ_ONLY_PREVIEW_OPERATIONS)
        self.assertTrue(all(web.values()))
        self.assertEqual(set(local)-set(web),
                         LOCAL_MUTATION_OPERATIONS | LOCAL_COMPAT_READ_OPERATIONS | LOCAL_GUI_READ_OPERATIONS | LOCAL_TERMINAL_READ_OPERATIONS | LOCAL_BRIDGE_READ_OPERATIONS | {"workspace_policy"})
        for name in LOCAL_GUI_READ_OPERATIONS:
            self.assertTrue(local[name])
            self.assertNotIn(name,web)
        self.assertFalse(any(local[n] for n in LOCAL_MUTATION_OPERATIONS))
        for name in LOCAL_TERMINAL_READ_OPERATIONS:
            self.assertTrue(local[name])
            self.assertNotIn(name,web)
        for name in LOCAL_BRIDGE_READ_OPERATIONS:
            self.assertTrue(local[name])
            self.assertNotIn(name,web)
        self.assertEqual(len(stdio),103)
        legacy = inspect_existing_handlers()
        for n in LOCAL_MUTATION_OPERATIONS:
            self.assertIn(n,legacy)
            self.assertFalse(legacy[n].read_only)

    def test_stable_mutation_parity_is_local_only(self):
        sources = {n for n in LOCAL_MUTATION_OPERATIONS}
        http = {t.name for t in asyncio.run(make_server().list_tools())}
        for name in ("ssh_exec", "package_install", "git_pull_ff", "git_push",
                     "git_fetch", "terminal_access_configure", "gui_request_permissions"):
            self.assertIn(name, sources)
            self.assertNotIn(name, http)

    def test_privileged_stdio_launch_is_fixed_local_path(self):
        root = Path(__file__).resolve().parents[2]
        contents = (root / "bin" / "dev-stdio-mcp.sh").read_text()
        self.assertIn("--stdio", contents)
        self.assertIn("PYTHONNOUSERSITE=1", contents)
        self.assertIn("-P -B", contents)
        self.assertNotIn("curl", contents)
        self.assertNotIn("0.0.0.0", contents)


if __name__ == "__main__":
    unittest.main()
