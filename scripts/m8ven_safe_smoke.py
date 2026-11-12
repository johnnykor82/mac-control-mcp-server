"""Non-mutating macOS-only MCP protocol smoke: initialization, tools/list, safe read.

Never invokes write, browser, GUI, SSH or Watcher handlers. Never uploads
reports, contacts M8ven, authenticates external services or touches ChatBridge.
Run from a checked-out Mac Control source with pinned Python dependencies.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from mac_control.tool_annotation_policy import TOOL_ANNOTATIONS

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
CTX = {
    "task_id": "M8VEN-A09-SMOKE",
    "action": "Read safe MCP server system_info only; no host state change",
    "authorization_basis": "Owner approved M8ven trust assessment on 2026-11-11",
}


async def smoke() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("This native MCP smoke is macOS-only")
    env = os.environ.copy()
    env["MAC_CONTROL_DATA_ROOT"] = ""
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    transport = StdioTransport(
        command=sys.executable,
        args=["-B", str(ROOT / "scripts/dev_mcp_server.py"), "--stdio"],
        cwd=str(ROOT),
        env=env,
    )
    async with Client(transport) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        # Two optional 7-tool modules are intentionally absent in clean CI.
        # Verify the exact advertised set for EACH valid feature-flag state,
        # without changing flags, credentials or any production browser.
        browser_names = {
            "background_browser_action", "background_browser_capture",
            "background_browser_close", "background_browser_create",
            "background_browser_list", "background_browser_reopen",
            "background_browser_snapshot",
        }
        native_names = {
            "background_app_action", "background_app_capture",
            "background_app_close", "background_app_create",
            "background_app_elements", "background_app_list",
            "background_app_windows",
        }
        full_names = set(TOOL_ANNOTATIONS) - {"get_profile"}
        core_names = full_names - browser_names - native_names
        expected = set(core_names)
        if names & browser_names:
            expected.update(browser_names)
        if names & native_names:
            expected.update(native_names)
        if len(names) != len(tools) or names != expected:
            raise AssertionError(
                "Tool inventory drift: expected " + str(len(expected)) +
                " vs observed " + str(len(tools))
            )
        for tool in tools:
            annotation = tool.annotations
            data = annotation.model_dump(by_alias=True, exclude_none=True)
            if any(type(data.get(field)) is not bool for field in FIELDS):
                raise AssertionError("Incomplete MCP annotations: " + tool.name)
            if (tool.name in ("terminal_exec", "git_push", "watcher_ack_delivery")
                    and data.get("readOnlyHint")):
                raise AssertionError("Mutating operation improperly labeled read-only")
        if "get_profile" in names:
            raise AssertionError("Remote-only profile exposed on local unauthenticated stdio")
        response = await client.call_tool("system_info", {"audit_context": CTX})
        if response.is_error:
            raise AssertionError("Safe system_info call failed")
        print("M8VEN_MACOS_MCP_READONLY_SMOKE_PASS", len(tools), "tools")


def main() -> None:
    asyncio.run(smoke())


if __name__ == "__main__":
    main()
