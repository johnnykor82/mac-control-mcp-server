#!/usr/bin/env python3
"""End-to-end smoke test for an installed Mac Control MCP Server local MCP server.

Uses only private disposable files and an ephemeral localhost test website.
Does not touch Stable, DEV, or owner browser profiles.
Optional browser test uses an already running ChatBridge and ephemeral local website.
"""
from __future__ import annotations

import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import uuid

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (b'<html><body><input id="value"><button id="go" '
                b'onclick="document.getElementById(\'out\').innerText='
                b'document.getElementById(\'value\').value">Go</button>'
                b'<div id="out"></div></body></html>')
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


async def call(client: Client, name: str, arguments: dict) -> dict:
    value = await client.call_tool(name, arguments)
    if value.is_error:
        raise RuntimeError(name + " returned MCP error")
    return value.data if isinstance(value.data, dict) else {}


async def check(entrypoint: Path, with_chatbridge: bool) -> None:
    assert entrypoint.is_file(), "MCP local launcher not installed"
    async with Client(StdioTransport(command="/bin/sh", args=[str(entrypoint)])) as client:
        tools = {tool.name for tool in await client.list_tools()}
        for name in ("system_info", "fs_write", "fs_read", "fs_stat", "fs_trash"):
            assert name in tools, name + " missing"
        machine = await call(client, "system_info", {})
        assert machine, "system_info empty"
        # File isolation is the Mac Control MCP Server owner's workspace, never a real project.
        name = "smoke-" + uuid.uuid4().hex + ".txt"
        value = "MacControl-Mac Control MCP Server-Smoke-" + uuid.uuid4().hex
        created = False
        try:
            written = await call(client, "fs_write", {"project": "workspace", "path": name,
                                                      "content": value})
            assert written, "fs_write empty"
            created = True
            read = await call(client, "fs_read", {"project": "workspace", "path": name})
            assert value in str(read), "round-trip file contents mismatch"
            meta = await call(client, "fs_stat", {"project": "workspace", "path": name})
            digest = meta["sha256"]
        finally:
            if created:
                meta = await call(client, "fs_stat", {"project": "workspace", "path": name})
                await call(client, "fs_trash", {"project": "workspace", "path": name,
                                               "expected_sha256": meta["sha256"]})
        print("LOCAL_MCP_READ_WRITE_PASS", len(tools), "tools")

        if not with_chatbridge:
            return
        assert "background_browser_create" in tools, "Browser feature not provisioned"
        site = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        worker = threading.Thread(target=site.serve_forever, daemon=True)
        worker.start()
        token = None
        try:
            created = await call(client, "background_browser_create",
                                 {"url": f"http://127.0.0.1:{site.server_port}"})
            assert created.get("ok"), "ChatBridge did not create background session"
            token = created["result"]["session_token"]
            text = "SMOKE-" + uuid.uuid4().hex
            for action, selector, value in (("fill", "#value", text),
                                            ("click", "#go", "")):
                result = await call(client, "background_browser_action",
                                    {"session_token": token, "action": action,
                                     "selector": selector, "text": value})
                assert result.get("ok"), action + " failed"
            snapshot = await call(client, "background_browser_snapshot",
                                  {"session_token": token})
            assert text in snapshot["result"]["snapshot"], "DOM mismatch"
            jpg = await call(client, "background_browser_capture",
                             {"session_token": token})
            assert jpg["result"]["bytes"] > 1024, "Missing screenshot"
            print("CHATBRIDGE_BACKGROUND_BROWSER_MCP_PASS")
        finally:
            if token:
                await call(client, "background_browser_close", {"session_token": token})
            site.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrypoint", type=Path, required=True)
    parser.add_argument("--with-chatbridge", action="store_true")
    args = parser.parse_args()
    asyncio.run(check(args.entrypoint.expanduser(), args.with_chatbridge))
