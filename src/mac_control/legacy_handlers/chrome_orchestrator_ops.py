"""Legacy Chrome MCP tools routed to ChatBridge's HTTP API.

Mac Control must never launch, terminate or control ChatBridge's Chrome.
The HTTP gateway owns the browser, profile and tabs. This module retains
legacy MCP tool names for callers that have not yet migrated.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
import urllib.error
import urllib.request
from pathlib import Path
from ..runtime_paths import DATA_ROOT

ROOT = DATA_ROOT
GATEWAY = os.getenv("MACCONTROL_CHATBRIDGE_URL", "http://127.0.0.1:8787").rstrip("/")
DB = ROOT / "run" / "chatbridge-maccontrol-compat.sqlite3"
PROMPTS = ROOT / "workspace" / "agent-prompts"
RESULTS = ROOT / "workspace" / "agent-results"
VALID_TASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
VALID_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")


def _api(method: str, path: str, data: dict | None = None, *, timeout: float = 22) -> dict:
    if not path.startswith("/") or path.startswith("//") or ".." in path:
        raise ValueError("Invalid ChatBridge endpoint")
    headers = {"Accept": "application/json"}
    key = os.getenv("MACCONTROL_CHATBRIDGE_API_KEY", "")
    if key:
        headers["Authorization"] = "Bearer " + key
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(GATEWAY + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            value = json.load(response)
        if not isinstance(value, dict):
            raise RuntimeError("Unexpected ChatBridge response")
        return value
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"ChatBridge returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ConnectionError("ChatBridge HTTP 8787 is not reachable") from exc


@contextmanager
def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            request_id TEXT,
            archived INTEGER NOT NULL DEFAULT 0
        )"""
    )
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _task(value: str) -> str:
    if not isinstance(value, str) or not VALID_TASK.fullmatch(value):
        raise ValueError("task_id is required and must be alphanumeric with - or _")
    return value


def _mapped(task_id: str) -> dict:
    with _conn() as db:
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (_task(task_id),)).fetchone()
    if row is None:
        raise LookupError("Unknown compatibility task. Use chrome_chat_new first")
    return dict(row)


def _session(task_id: str, reuse: bool = True) -> dict:
    task_id = _task(task_id)
    with _conn() as db:
        existing = db.execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        if existing and reuse:
            sid = existing["session_id"]
            _api("GET", f"/v1/sessions/{sid}")
            db.execute("UPDATE tasks SET archived=0 WHERE task_id=?", (task_id,))
            return {"task_id": task_id, "session_id": sid, "reused": True,
                    "browser_owner": "ChatBridge"}
        data = _api("POST", "/v1/sessions", {"title": "maccontrol:" + task_id})
        sid = data["session_id"]
        db.execute(
            """INSERT INTO tasks(task_id,session_id,request_id,archived)
               VALUES(?,?,NULL,0) ON CONFLICT(task_id)
               DO UPDATE SET session_id=excluded.session_id, request_id=NULL,archived=0""",
            (task_id, sid),
        )
        return {"task_id": task_id, "session_id": sid, "reused": False,
                "browser_owner": "ChatBridge"}


def _prompt_file(name: str) -> str:
    if not isinstance(name, str) or not VALID_FILE.fullmatch(name) or ".." in name:
        raise ValueError("prompt_file must be a simple file name under agent-prompts")
    p = PROMPTS / name
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 100_000:
        raise ValueError("Prompt file absent or too large")
    return p.read_text(encoding="utf-8")


def _submit(task_id: str, prompt: str, prompt_file: str) -> dict:
    row = _mapped(task_id)
    if row["archived"]:
        raise ValueError("Task archived; restore it before sending")
    value = _prompt_file(prompt_file) if prompt_file else prompt
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Nonempty prompt required")
    response = _api("POST", f"/v1/sessions/{row['session_id']}/messages",
                    {"content": value})
    rid = response["request_id"]
    with _conn() as db:
        db.execute("UPDATE tasks SET request_id=? WHERE task_id=?", (rid, task_id))
    return {"task_id": task_id, "session_id": row["session_id"],
            "request_id": rid, "status": response.get("status"),
            "browser_owner": "ChatBridge"}


def _result(task_id: str, limit: int = 16_000) -> dict:
    row = _mapped(task_id)
    rid = row["request_id"]
    if not rid:
        return {"task_id": task_id, "status": "not_sent", "content": ""}
    info = _api("GET", f"/v1/requests/{rid}")
    return {"task_id": task_id, "session_id": row["session_id"], "request_id": rid,
            "status": info.get("status"), "content": (info.get("answer") or "")[:limit],
            "attachments": info.get("attachments", [])}


def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def chrome_orchestrator_status() -> dict:
        """Compatibility status: query ChatBridge HTTP. Chrome is owned by ChatBridge."""
        d = _api("GET", "/v1/system/status")
        return {"running": d.get("browser", {}).get("state") == "running",
                "browser": d.get("browser"), "transport": "ChatBridge HTTP"}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def chrome_chat_ui_status() -> dict:
        """Read ChatBridge browser health without CDP or direct tab access."""
        d = _api("GET", "/v1/system/status")
        return {"browser": d.get("browser"), "transport": "ChatBridge HTTP"}

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def chrome_orchestrator_launch() -> dict:
        """Check or wake Chrome through its owning ChatBridge gateway."""
        status = _api("GET", "/v1/system/status")
        browser = status.get("browser", {})
        if browser.get("state") == "idle":
            browser = _api("POST", "/v1/browser/wake", timeout=60).get("browser", {})
        d = {"running": browser.get("state") == "running", "browser": browser,
             "transport": "ChatBridge HTTP"}
        if not d["running"]:
            raise RuntimeError("ChatBridge unavailable; check net.chatbridge.gateway LaunchAgent")
        return {**d, "reused": True, "launched_by_mac_control": False}

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def chrome_chat_new(reuse: bool = True, task_id: str = "") -> dict:
        """Create/reuse an HTTP ChatBridge session for a named task; no browser tab."""
        return _session(task_id, reuse)

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def chrome_chat_adopt(task_id: str) -> dict:
        """Look up a previously created HTTP session; no tab ownership transfer."""
        row = _mapped(task_id)
        return {"task_id": task_id, "session_id": row["session_id"],
                "browser_owner": "ChatBridge"}

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def chrome_chat_switch(task_id: str) -> dict:
        """Choose existing HTTP session; does not manipulate physical Chrome tabs."""
        row = _mapped(task_id)
        return {"task_id": task_id, "session_id": row["session_id"],
                "browser_owner": "ChatBridge"}

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def chrome_chat_send(prompt: str = "", prompt_file: str = "", task_id: str = "") -> dict:
        """Queue prompt via ChatBridge HTTP; optional file is scoped to agent-prompts."""
        return _submit(_task(task_id), prompt, prompt_file)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def chrome_chat_read(max_chars: int = 16_000, task_id: str = "") -> dict:
        """Read ChatBridge request answer and attachments by task ID."""
        return _result(_task(task_id), max(1, min(max_chars, 50_000)))

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def chrome_chat_save(
        result_filename: str = "latest-chatgpt-answer.md", task_id: str = ""
    ) -> dict:
        """Save completed HTTP response to agent-results, never directly from DOM."""
        if not VALID_FILE.fullmatch(result_filename) or ".." in result_filename:
            raise ValueError("Invalid result filename")
        result = _result(_task(task_id), 200_000)
        if result["status"] != "completed":
            raise RuntimeError("Only completed responses can be saved")
        RESULTS.mkdir(parents=True, exist_ok=True)
        path = RESULTS / result_filename
        if path.is_symlink() or path.exists():
            raise FileExistsError("Refusing to overwrite existing result file")
        with path.open("x", encoding="utf-8") as output:
            output.write(result["content"])
        return {"task_id": task_id, "result_filename": result_filename,
                "bytes": path.stat().st_size, "status": result["status"]}

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def chrome_chat_archive(task_id: str) -> dict:
        """Archive logical task mapping only; ChatBridge exclusively owns Chrome tabs."""
        task_id = _task(task_id)
        _mapped(task_id)
        with _conn() as db:
            db.execute("UPDATE tasks SET archived=1 WHERE task_id=?", (task_id,))
        return {"task_id": task_id, "archived": True, "closed_tabs": 0}

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def chrome_chat_cleanup() -> dict:
        """No browser cleanup from Mac Control. ChatBridge owns all tab lifecycle."""
        return {"managed_by": "ChatBridge", "closed_tabs": 0, "legacy_tabs": "not_managed"}

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def chrome_chat_restore(task_id: str) -> dict:
        """Unarchive the logical HTTP task mapping; do not navigate browser."""
        task_id = _task(task_id)
        row = _mapped(task_id)
        with _conn() as db:
            db.execute("UPDATE tasks SET archived=0 WHERE task_id=?", (task_id,))
        return {"task_id": task_id, "session_id": row["session_id"],
                "restored": True, "browser_owner": "ChatBridge"}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def chrome_chat_wait(wait_seconds: int = 15, task_id: str = "") -> dict:
        """Wait for a queued ChatBridge HTTP request, without browser/CDP access."""
        task_id = _task(task_id)
        deadline = time.monotonic() + max(1, min(wait_seconds, 35))
        while time.monotonic() < deadline:
            result = _result(task_id)
            if result["status"] in ("completed", "failed", "interrupted", "unknown"):
                return result
            time.sleep(min(1, max(deadline - time.monotonic(), 0)))
        return _result(task_id)
