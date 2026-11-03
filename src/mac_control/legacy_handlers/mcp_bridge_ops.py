"""Client bridge to discovered or directly supplied downstream MCP servers."""
import asyncio
import json
import os
import re
import shutil
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

def _saved_targets():
    if not CONFIG.exists():
        return {}
    if CONFIG.is_symlink() or CONFIG.stat().st_uid != os.getuid() or CONFIG.stat().st_mode & 0o077:
        raise PermissionError("Saved MCP config must be owner-only")
    data = json.loads(CONFIG.read_text("utf-8")).get("targets", {})
    if not isinstance(data, dict):
        raise ValueError("Invalid saved MCP targets")
    return data


def _discovered_targets():
    home = Path.home()
    sources = {
        "claude": home / "Library/Application Support/Claude/claude_desktop_config.json",
        "claudecli": home / ".claude.json",
        "cursor": home / ".cursor/mcp.json",
        "vscode": home / "Library/Application Support/Code/User/mcp.json",
    }
    found = {}
    for source, path in sources.items():
        try:
            if path.is_symlink() or not path.is_file():
                continue
            info = path.stat()
            if info.st_uid != os.getuid() or info.st_size > 1024 * 1024:
                continue
            config = json.loads(path.read_text("utf-8"))
            entries = config.get("mcpServers", config.get("servers", {}))
            if not isinstance(entries, dict):
                continue
            for name, value in entries.items():
                if (not isinstance(name, str) or
                    not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name) or
                    not isinstance(value, dict) or value.get("disabled") is True):
                    continue
                if isinstance(value.get("url"), str):
                    settings = {"type": "http", "url": value["url"]}
                elif isinstance(value.get("command"), str):
                    settings = {"type": "stdio", "command": value["command"],
                                "args": value.get("args", []),
                                "cwd": value.get("cwd", str(home)),
                                "env": value.get("env", {})}
                else:
                    continue
                found[source + ":" + name] = settings
        except (OSError, ValueError, TypeError):
            continue
    return found


def _targets():
    return {**_discovered_targets(), **_saved_targets()}


def _public_targets():
    return [{"name": name, "type": cfg.get("type")}
            for name, cfg in sorted(_targets().items()) if isinstance(cfg, dict)]


def _settings(name, specification=None):
    if specification is not None:
        if not isinstance(specification, dict):
            raise ValueError("target_spec must be an object")
        return specification
    if isinstance(name, str) and name.startswith(("http://", "https://")):
        return {"type": "http", "url": name}
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,130}", name):
        raise ValueError(
            "MCP_TARGET_NAME_INVALID: target name must be 1–130 characters "
            "using ASCII letters, digits, underscore, dot, colon or hyphen. "
            "Use mcp_targets for saved names or supply an explicit target_spec. "
            "No downstream MCP request was sent."
        )
    settings = _targets().get(name)
    if not isinstance(settings, dict):
        raise ValueError(
            "MCP_TARGET_NOT_FOUND: target is not configured. Inspect mcp_targets "
            "or supply a valid explicit HTTP(S) URL or target_spec. "
            "No downstream MCP request was sent."
        )
    return settings


def _target(name, specification=None):
    settings = _settings(name, specification)
    if settings.get("type") == "http":
        url = settings.get("url", "")
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError(
                "MCP_URL_INVALID: target_spec.url must be an http(s) URL of "
                "at most 2048 characters, without embedded credentials, "
                "query, fragment or spaces. No downstream MCP request was sent."
            )
        parsed = urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.fragment
                or parsed.query or any(c.isspace() for c in url)):
            raise ValueError(
                "MCP_URL_INVALID: target_spec.url must be an http(s) URL "
                "without embedded credentials, query, fragment or spaces. "
                "No downstream MCP request was sent."
            )
        return Client(url)
    if settings.get("type") == "stdio":
        command = settings.get("command")
        args = settings.get("args", [])
        cwd = settings.get("cwd", str(Path.home()))
        extras = settings.get("env", {})
        if (not isinstance(command, str) or not command
                or (not Path(command).is_absolute() and not shutil.which(command))):
            raise ValueError("STDIO executable unavailable")
        if (not isinstance(args, list) or len(args) > 128
                or not all(isinstance(v, str) and len(v) < 4000
                           and "\x00" not in v for v in args)):
            raise ValueError("Invalid stdio arguments")
        if not isinstance(cwd, str) or not Path(cwd).is_dir():
            raise ValueError("Invalid stdio working directory")
        if (not isinstance(extras, dict) or len(extras) > 128
                or not all(isinstance(k, str) and isinstance(v, str)
                           and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k)
                           and "\x00" not in v for k, v in extras.items())):
            raise ValueError("Invalid stdio environment")
        return Client(StdioTransport(command=command, args=args, cwd=cwd,
                                     env={**os.environ, **extras}))
    raise ValueError("MCP transport must be http or stdio")


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

async def _inspect(name, specification=None):
    async with _target(name, specification) as client:
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

async def _call(name, tool_name, arguments, read_only, media=None, specification=None):
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be JSON object")
    if len(json.dumps(arguments, default=str)) > 25000:
        raise ValueError("Arguments too large")
    settings = _settings(name, specification)
    if media is not None:
        return {"target": name, "tool": tool_name, "is_error": False,
                "result": _media_chunk(name, tool_name, media)}
    async with _target(name, specification) as client:
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
        """Discover existing MCP connections without revealing their secrets."""
        return {"targets": _public_targets(),
                "direct_connect": ["http", "https", "stdio"],
                "configured_via_chat": True}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def mcp_bridge_list(target: str = "", target_spec: dict | None = None) -> dict:
        """List tools for a configured name, direct HTTP URL or stdio target_spec."""
        return await _inspect(target, target_spec)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def mcp_bridge_read(target: str, tool: str, arguments: dict | None = None,
                              media: dict | None = None,
                              target_spec: dict | None = None):
        """Call downstream tool explicitly marked read-only."""
        return await _call(target, tool, arguments or {}, True,
                           media=media, specification=target_spec)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    async def mcp_bridge_call(target: str, tool: str, arguments: dict | None = None,
                              media: dict | None = None,
                              target_spec: dict | None = None):
        """Call downstream MCP using a configured name or direct target."""
        return await _call(target, tool, arguments or {}, False,
                           media=media, specification=target_spec)
