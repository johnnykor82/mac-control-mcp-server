"""Isolated loopback-only developer MCP preview.

Exposes only existing read-only system_info, not legacy privileged handlers.
No OAuth, production data, GUI or installer wiring.
"""
from __future__ import annotations

import argparse

from fastmcp import FastMCP
from mac_control.operations import system_info
from mac_control.dev_enabled_operations import register_preview_operations
from mac_control import background_browser_ops, background_native_ops, workspace_policy, maintenance_ops
from mac_control.audit_middleware import AuditMiddleware
from mac_control.runtime_paths import DATA_ROOT
import os


def make_server(*, include_mutations: bool = False, auth=None) -> FastMCP:
    mcp = FastMCP("Mac Control MCP Server", auth=auth, instructions=workspace_policy.instructions())
    # An installed, owner-scoped server emits a metadata-only audit log.
    # Uninstalled read-only DEV preview creates no public-install files.
    if os.environ.get("MAC_CONTROL_DATA_ROOT"):
        mcp.add_middleware(AuditMiddleware(DATA_ROOT / "logs"))
    mcp.tool(
        annotations={"readOnlyHint": True, "openWorldHint": False}
    )(system_info)
    register_preview_operations(mcp, include_mutations=include_mutations)
    if include_mutations:
        workspace_policy.register(mcp)
        maintenance_ops.register(mcp)
    if include_mutations and background_browser_ops.enabled():
        background_browser_ops.register(mcp)
    if include_mutations and background_native_ops.enabled():
        background_native_ops.register(mcp)
    return mcp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--stdio", action="store_true", help="Local bridge mode with scoped write operations")
    parser.add_argument("--remote", action="store_true", help="Owner-authorized full remote HTTP behind HTTPS proxy")
    opts = parser.parse_args()
    if opts.stdio and opts.remote:
        parser.error("stdio and remote modes are mutually exclusive")
    if opts.stdio:
        make_server(include_mutations=True).run(transport="stdio", show_banner=False)
        return
    port = opts.port or (3201 if opts.remote else 3101)
    if not 1024 <= port <= 65535 or port in (3000, 9334, 9335):
        parser.error("Port must be unreserved and different from production ports")
    http_options = {}
    if opts.remote:
        # Credentials are read only at startup, from the owner-only config file.
        from mac_control.remote_auth import build_auth
        from mac_control.remote_http import remote_http_options
        auth = build_auth()
        server = make_server(include_mutations=True, auth=auth)
        http_options = remote_http_options(str(auth.base_url))
    else:
        server = make_server()
    server.run(
        transport="http",
        host="127.0.0.1",
        port=port,
        path="/mcp",
        show_banner=False,
        host_origin_protection=True,
        **http_options,
    )


if __name__ == "__main__":
    main()
