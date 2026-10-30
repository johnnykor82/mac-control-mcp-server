#!/usr/bin/env python3
"""Explicit owner-invoked browser OAuth smoke test for public Mac Control MCP.

Must be run in the INSTALLED Mac Control MCP Server virtual environment, after the owner
has configured public HTTPS and started the authenticated remote MCP endpoint.
Runs the standard FastMCP OAuth flow in the user's browser, not a fake login.
Never prints credentials or provider tokens.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

DEFAULT_ROOT = Path.home() / "MacControlMCP"


async def verify_login(endpoint: str) -> dict:
    from fastmcp import Client
    from fastmcp.client.auth import OAuth

    # OAuth performs standard MCP discovery, GitHub consent redirect and local
    # callback. A client-specific token is kept by the provider's token store.
    auth = OAuth(mcp_url=endpoint, scopes=["read:user"],
                 client_name="Mac Control MCP Server Setup Verification",
                 callback_timeout=180)
    async with Client(endpoint, auth=auth, init_timeout=35, timeout=30) as client:
        result = await client.call_tool("system_info", {})
        if result.is_error:
            raise RuntimeError("Authenticated MCP system_info returned an error")
        return {"status": "authenticated_mcp_success",
                "endpoint": endpoint,
                "github_oauth_login_verified": True,
                "mcp_operation": "system_info",
                "mac_command_executed": False,
                "credentials_displayed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import setup_github_oauth
    config = setup_github_oauth.check(args.root)
    endpoint = config["public_url"].rstrip("/") + "/mcp"
    preflight = setup_github_oauth.probe(config["public_url"])
    if preflight["status"] != "public_oauth_preflight_pass":
        raise RuntimeError("Public OAuth discovery/authentication preflight failed")
    print("A web browser will open for an explicit GitHub OAuth login.")
    print("Log in as the allowed GitHub owner and approve the requested read:user scope.")
    report = asyncio.run(verify_login(endpoint))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Print only an exception type to avoid exposing untrusted OAuth pages,
        # callback codes, tokens, or credentials in terminal logs.
        print("OAuth login test failed:", type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
