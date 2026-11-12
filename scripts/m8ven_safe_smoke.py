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
        if len(tools) != 142 or len(names) != 142:
            raise AssertionError("Expected 142 stdio tools; remote-only get_profile excluded")
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
