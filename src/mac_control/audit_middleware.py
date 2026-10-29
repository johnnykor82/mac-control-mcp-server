"""Minimal, credential-safe audit trail for the separately installed MCP Server.

Only invocation metadata is retained. Never log call arguments, messages,
response content, OAuth tokens or exception text. Compatible with mclog.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from pathlib import Path
import time
import uuid

from fastmcp.server.middleware import Middleware


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
        # Tool names come from our registry, not from user-supplied argument data.
        name = str(context.message.name)[:100]
        self._record({"event": "tool_start", "id": request_id, "tool": name})
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
