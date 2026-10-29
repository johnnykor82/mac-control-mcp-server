"""Client bridge to locally approved downstream MCP servers (HTTP or stdio)."""
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from mcp.types import TextContent
from ..runtime_paths import DATA_ROOT
from .bridge_media import pack as _media_pack, chunk as _media_chunk

BASE = DATA_ROOT
CONFIG = BASE / "mcp_targets.json"
MAX_OUTPUT = 24000

def _targets():
    if not CONFIG.exists():
        return {}
    if CONFIG.is_symlink() or CONFIG.stat().st_uid != os.getuid() or CONFIG.stat().st_mode & 0o077:
        raise PermissionError("mcp_targets.json must be a regular owner-only file (chmod 600)")
    raw = json.loads(CONFIG.read_text("utf-8"))
    targets = raw.get("targets", {})
    if not isinstance(targets, dict):
        raise ValueError("Invalid MCP target configuration")
    return targets

def _target(name):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", name):
        raise ValueError("Invalid target name")
    settings = _targets().get(name)
    if not isinstance(settings, dict):
        raise ValueError("Unknown MCP target; configure it locally first")
    if settings.get("type") == "http":
        url = settings.get("url", "")
        parsed = urlsplit(url)
        if (parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username or parsed.password or parsed.fragment
            or parsed.query or parsed.port in (None, 3000, 3101)):
            raise ValueError("Only local HTTP MCP endpoints other than Mac Control are allowed")
        return Client(url)
    if settings.get("type") == "stdio":
        command = settings.get("command")
        args = settings.get("args", [])
        cwd = settings.get("cwd")
        if not isinstance(command, str) or not Path(command).is_absolute():
            raise ValueError("STDIO requires an absolute executable")
        if not Path(command).is_file() or not isinstance(args, list):
            raise ValueError("Invalid stdio executable/args")
        if not all(isinstance(v, str) and len(v) < 500 for v in args):
            raise ValueError("Invalid stdio args")
        if not isinstance(cwd, str) or not Path(cwd).is_dir():
            raise ValueError("Invalid stdio working directory")
        return Client(StdioTransport(
            command=command, args=args, cwd=cwd,
            env={"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                 "HOME": str(Path.home())},
        ))
    raise ValueError("Target transport must be http or stdio")

def _read_only(tool):
    annotations = getattr(tool, "annotations", None)
    if annotations is None:
        return False
    if isinstance(annotations, dict):
        return annotations.get("readOnlyHint") is True
    return getattr(annotations, "read_only_hint", False) is True

def _clip(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > MAX_OUTPUT:
        return {"preview": text[:MAX_OUTPUT], "truncated": True, "chars": len(text)}
    return value

async def _inspect(name):
    async with _target(name) as client:
        tools = await asyncio.wait_for(client.list_tools(), timeout=20)
        return {
            "target": name,
            "tools": [
                {"name": t.name,
                 "read_only": _read_only(t),
                 "description": (t.description or "")[:350],
                 "input_schema": _clip(t.input_schema)}
                for t in tools[:200]
            ],
            "total": len(tools),
        }

async def _call(name, tool_name, arguments, read_only, media=None):
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be JSON object")
    if len(json.dumps(arguments, default=str)) > 25000:
        raise ValueError("Arguments too large")
    settings = _targets().get(name)
    if not isinstance(settings, dict):
        raise ValueError("Unknown or revoked MCP target")
    if media is not None:
        return {"target": name, "tool": tool_name, "is_error": False,
                "result": _media_chunk(name, tool_name, media)}
    async with _target(name) as client:
        tools = await asyncio.wait_for(client.list_tools(), timeout=20)
        match = next((t for t in tools if t.name == tool_name), None)
        if match is None:
            raise ValueError("Tool not found on target")
        if read_only and not _read_only(match):
            raise PermissionError("Tool is not marked read-only by downstream MCP")
        result = await asyncio.wait_for(
            client.call_tool(tool_name, arguments), timeout=60
        )
        payload = _media_pack(name, tool_name, result, settings)
        envelope = {"target": name, "tool": tool_name,
                    "is_error": bool(getattr(result, "is_error", False))}
        if isinstance(payload, list):
            return [TextContent(type="text", text=json.dumps(envelope)), *payload]
        if "media" in payload:
            return {**envelope, **payload}
        return {**envelope, "result": _clip(payload["result"])}

def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def mcp_targets() -> dict:
        """List owner-configured downstream MCP names and transports."""
        return {"targets": [
            {"name": k, "type": v.get("type")}
            for k, v in _targets().items() if isinstance(v, dict)
        ], "config": str(CONFIG), "configured_via_chat": False}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def mcp_bridge_list(target: str) -> dict:
        """Discover tool names, input schemas and read-only declarations on approved MCP."""
        return await _inspect(target)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def mcp_bridge_read(target: str, tool: str, arguments: dict | None = None,
                              media: dict | None = None):
        """Call downstream tool explicitly marked read-only."""
        return await _call(target, tool, arguments or {}, True, media=media)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    async def mcp_bridge_call(target: str, tool: str, arguments: dict | None = None,
                              media: dict | None = None):
        """Call an approved downstream MCP tool with explicit write-capable authorization."""
        return await _call(target, tool, arguments or {}, False, media=media)
