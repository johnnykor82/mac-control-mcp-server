"""Minimal, credential-safe audit trail for the separately installed MCP Server.

Only bounded, value-redacted argument descriptions are retained.
Never log raw arguments, messages, response content, tokens or exception text.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import math
import re
from logging.handlers import TimedRotatingFileHandler
import os
from pathlib import Path
import time
import uuid

from fastmcp.server.middleware import Middleware


# An intentionally narrow, non-reversible summary. Never persist raw values.
_SAFE_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}\Z")
_SECRET_FIELD = re.compile(
    r"token|secret|password|passwd|api.?key|authorization|cookie|credential|bearer|private.?key",
    re.IGNORECASE,
)
# Do not accept arbitrary strings merely because they resemble enum identifiers.
_SAFE_ENUM_VALUES = {
    "mode": frozenset(("auto", "foreground", "background")),
    "action": frozenset((
        "read", "write", "list", "open", "close", "start", "stop",
        "click", "move", "drag", "scroll", "left_click", "double_click",
        "right_click", "set_value", "AXPress", "AXIncrement", "AXDecrement",
        "AXShowMenu", "AXConfirm", "AXCancel", "AXScrollToVisible",
    )),
    "operation": frozenset((
        "terminal_exec", "terminal_capabilities", "terminal_open", "terminal_read",
        "terminal_send", "terminal_close", "status", "list", "read", "write",
        "scan", "query", "inspect", "run", "start", "stop", "open", "close",
        "gui_status", "gui_windows", "ssh_exec", "custom_command",
        "custom_query", "watcher_status", "mcp_targets", "mcp_diagnostics",
    )),
}


_SAFE_NUMERIC_FIELDS = frozenset((
    "timeout", "timeout_seconds", "max_depth", "max_nodes",
    "limit", "lines", "offset", "width", "height",
    "count", "row", "column", "size", "duration_ms",
))


def safe_argument_info(arguments: object) -> dict:
    """Bounded structure-only audit metadata; never save user-provided text."""
    if not isinstance(arguments, dict):
        return {}
    result = {}
    priority = ("operation", "action", "mode", "project", "command", "cmd")
    keys = sorted(arguments, key=lambda k: (
        str(k) not in priority, priority.index(str(k)) if str(k) in priority else 99, str(k)))
    for key in keys:
        if len(result) >= 10:
            break
        if not isinstance(key, str) or not _SAFE_FIELD.fullmatch(key):
            continue
        val = arguments[key]
        if _SECRET_FIELD.search(key):
            label = "[скрыто]"
        elif val is None:
            label = "[не передано]"
        elif isinstance(val, bool):
            label = val
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            label = (val if key in _SAFE_NUMERIC_FIELDS and
                     abs(val) <= 1000000000 and math.isfinite(val) else "[число]")
        elif isinstance(val, str):
            if key == "project" and val == "workspace":
                label = "workspace"
            elif val in _SAFE_ENUM_VALUES.get(key, ()):
                label = val
            elif key in ("command", "cmd", "script"):
                label = f"[команда: {min(len(val), 99999)} симв.]"
            elif key.endswith(("path", "dir", "file")):
                label = "[путь]"
            else:
                label = f"[строка: {min(len(val), 99999)} симв.]"
        elif isinstance(val, (list, tuple)):
            label = f"[список: {min(len(val), 999)}]"
        elif isinstance(val, dict):
            label = f"[объект: {min(len(val), 999)} полей]"
        else:
            label = "[тип скрыт]"
        result[key] = label
    if len(arguments) > len(result):
        result["other_fields"] = "[пропущены]"
    return result


class AuditMiddleware(Middleware):
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self._logger = None

    def _ensure_logger(self) -> logging.Logger:
        if self._logger is not None:
            return self._logger
        path = self.log_dir
        if path.is_symlink():
            raise RuntimeError("Refusing symlink audit directory")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.stat().st_mode & 0o077:
            raise PermissionError("Audit directory must be owner-only (0700)")
        if hasattr(os, "getuid") and path.stat().st_uid != os.getuid():
            raise PermissionError("Audit directory not owned by current user")
        output = path / "audit.jsonl"
        if output.is_symlink():
            raise RuntimeError("Refusing symlink audit log")
        logger = logging.getLogger(f"mac_control.mcp_audit.{id(self)}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = TimedRotatingFileHandler(
            output, when="midnight", interval=1, backupCount=7,
            utc=True, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        output.chmod(0o600)
        self._logger = logger
        return logger

    def _record(self, event: dict) -> None:
        # Logging failures should not break an already authorized MCP tool.
        try:
            self._ensure_logger().info(json.dumps({
                "time_utc": datetime.now(timezone.utc).isoformat(),
                **event,
            }, ensure_ascii=False))
        except (OSError, RuntimeError, ValueError):
            pass

    async def on_call_tool(self, context, call_next):
        started = time.monotonic()
        request_id = uuid.uuid4().hex
        # Tool name is registered; only a bounded summary of argument shapes is retained.
        name = str(context.message.name)[:100]
        self._record({
            "event": "tool_start", "id": request_id, "tool": name,
            "argument_info": safe_argument_info(getattr(context.message, "arguments", None)),
        })
        try:
            result = await call_next(context)
        except BaseException:
            self._record({
                "event": "tool_end", "id": request_id, "tool": name,
                "status": "exception",
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            })
            raise
        self._record({
            "event": "tool_end", "id": request_id, "tool": name,
            "status": "error" if getattr(result, "is_error", False) else "ok",
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        })
        return result
