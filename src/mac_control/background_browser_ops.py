"""All browser operations are delegated to ChatBridge's HTTP Browser API.

Mac Control never launches Chrome, connects to CDP, or changes macOS focus.
Legacy MCP tool signatures are preserved for backwards compatibility.
"""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit
import urllib.error
import urllib.request

from .runtime_paths import DATA_ROOT

FLAGS = DATA_ROOT / "feature_flags.json"
DEFAULT_GATEWAY = "http://127.0.0.1:8787"
_SESSION_ID = re.compile(r"[a-f0-9]{32}\Z")
_MAX_JSON_BYTES = 2_000_000
_MAX_IMAGE_BYTES = 12_000_000


def enabled() -> bool:
    if not FLAGS.is_file() or FLAGS.is_symlink():
        return False
    try:
        return json.loads(FLAGS.read_text()).get("background_browser") is True
    except (OSError, ValueError, TypeError):
        return False


def _gateway() -> str:
    origin = os.getenv("MACCONTROL_CHATBRIDGE_URL", DEFAULT_GATEWAY).rstrip("/")
    parsed = urlsplit(origin)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("Invalid ChatBridge URL origin")
    return origin


def _identity(token: str) -> tuple[str, str]:
    if not isinstance(token, str) or len(token) > 256 or "." not in token:
        raise ValueError("Invalid browser session capability")
    sid, _ = token.split(".", 1)
    if not _SESSION_ID.fullmatch(sid):
        raise ValueError("Invalid browser session ID")
    return sid, token


def _error(code: str, message: str, **details) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, **details}}


def _headers(token: str | None = None, *, json_body: bool = False) -> dict:
    headers = {"Accept": "application/json"}
    key = os.environ.get("MACCONTROL_CHATBRIDGE_API_KEY", "")
    if key:
        headers["Authorization"] = "Bearer " + key
    if token:
        headers["X-Browser-Session-Token"] = token
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _http(method: str, route: str, body: dict | None = None,
          token: str | None = None, *, media: bool = False) -> tuple[str, bytes]:
    raw = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    if raw is not None and len(raw) > 100_000:
        raise ValueError("Browser request too large")
    req = urllib.request.Request(
        _gateway() + route, method=method, data=raw,
        headers=_headers(token, json_body=raw is not None))
    with urllib.request.urlopen(req, timeout=50) as response:
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        limit = _MAX_IMAGE_BYTES if media else _MAX_JSON_BYTES
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError("ChatBridge response exceeds size limit")
    return mime, content


def _json(method: str, route: str, body: dict | None = None,
          token: str | None = None) -> dict:
    mime, content = _http(method, route, body, token)
    if mime != "application/json":
        raise ValueError("ChatBridge returned unexpected content type")
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("ChatBridge returned non-object JSON")
    return value


def _call(operation: str, **arguments) -> dict:
    """Translate original DEV tools to ChatBridge Browser API v1.

    A client_request_id is generated for each new action and returned so an
    ambiguous HTTP outcome can be reconciled using the upstream operations API.
    The gateway NEVER retries an uncertain modifying request implicitly.
    """
    specs = {
        "create": ("POST", "/v1/browser/sessions"),
        "action": ("POST", "/v1/browser/sessions/{id}/actions"),
        "snapshot": ("GET", "/v1/browser/sessions/{id}/snapshot"),
        "capture": ("GET", "/v1/browser/sessions/{id}/screenshot"),
        "list": ("POST", "/v1/browser/sessions/list"),
        "close": ("DELETE", "/v1/browser/sessions/{id}"),
        "reopen": ("POST", "/v1/browser/sessions/{id}/reopen"),
    }
    if operation not in specs:
        return _error("INVALID_ARGUMENT", "Unknown browser operation")
    method, path = specs[operation]
    request_id = None
    try:
        params = dict(arguments)
        token = None
        if "{id}" in path:
            sid, token = _identity(params.pop("session_token", ""))
            path = path.replace("{id}", sid)
        if operation == "action":
            request_id = params.pop("client_request_id", None) or uuid.uuid4().hex
            if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,180}", request_id):
                raise ValueError("Invalid client_request_id")
            params["client_request_id"] = request_id
            # The legacy caller supplies these fields for all operations.
            # Never modify argument values; ChatBridge interprets the action.
        if operation == "list":
            tokens = params.get("session_tokens", [])
            if not isinstance(tokens, list):
                raise ValueError("session_tokens must be a list")
            for token_value in tokens:
                _identity(token_value)
        if operation in ("snapshot", "capture"):
            params = {key: val for key, val in params.items() if val != ""}
            if params:
                path += "?" + urlencode(params)
        response = _json(method, path,
                         params if method == "POST" else None, token)
        if operation == "capture":
            relative = response.get("url")
            if not isinstance(relative, str) or not relative.startswith(
                    path.split("?", 1)[0].rsplit("/", 1)[0] + "/files/"):
                # Exact same session path and trusted file locator only.
                sid, _ = _identity(arguments["session_token"])
                prefix = f"/v1/browser/sessions/{sid}/files/"
                if not isinstance(relative, str) or not relative.startswith(prefix):
                    return _error("INVALID_PROVIDER_RESPONSE", "Screenshot file URL invalid")
            if "?" in relative or "#" in relative or not re.fullmatch(
                    r"/v1/browser/sessions/[a-f0-9]{32}/files/[A-Za-z0-9_-]+", relative):
                return _error("INVALID_PROVIDER_RESPONSE", "Screenshot file path invalid")
            mime, data = _http("GET", relative, token=token, media=True)
            if mime not in ("image/jpeg", "image/png"):
                return _error("INVALID_PROVIDER_RESPONSE", "Screenshot MIME mismatch")
            response["image_data"] = base64.b64encode(data).decode("ascii")
            response["mime_type"] = mime
            response["bytes"] = len(data)
        if operation == "action":
            state = response.get("state")
            if state not in ("completed", "failed", "unknown", "running"):
                return _error("INVALID_PROVIDER_RESPONSE", "Action state missing", client_request_id=request_id)
            response["client_request_id"] = request_id
            if state != "completed":
                return _error("ACTION_" + state.upper(), "Browser action not confirmed",
                              client_request_id=request_id, operation_id=response.get("operation_id"),
                              state=state, provider_error=response.get("error_code"))
            # Historical MCP consumers expect action details directly.
            response = {**(response.get("result") or {}), "operation_id": response.get("operation_id"),
                        "client_request_id": request_id, "state": state}
        if operation == "list":
            sessions = response.get("data", response.get("sessions"))
            if not isinstance(sessions, list):
                return _error("INVALID_PROVIDER_RESPONSE", "Session list missing")
            response = {"sessions": sessions}
        return {"ok": True, "result": response}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read(10000))
            code = (payload.get("error") or {}).get("code") if isinstance(payload, dict) else None
        except (ValueError, OSError):
            code = None
        return _error(code or ("CHATBRIDGE_UNAUTHORIZED" if exc.code in (401, 403) else
                              "CHATBRIDGE_API_MISSING" if exc.code in (404, 405, 501) else
                              "CHATBRIDGE_RATE_LIMITED" if exc.code == 429 else
                              "CHATBRIDGE_HTTP_ERROR"), "ChatBridge rejected browser request",
                      http_status=exc.code, **({"client_request_id": request_id} if request_id else {}))
    except (urllib.error.URLError, OSError, TimeoutError):
        return _error("UNKNOWN_RESULT" if method in ("POST", "DELETE") else "CHATBRIDGE_UNAVAILABLE",
                      "Browser operation not confirmed; do not automatically retry",
                      **({"client_request_id": request_id} if request_id else {}))
    except (ValueError, TypeError, KeyError):
        return _error("INVALID_ARGUMENT", "Invalid request or ChatBridge response",
                      **({"client_request_id": request_id} if request_id else {}))


def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
    def background_browser_create(persist_profile: bool = False, url: str = "about:blank") -> dict:
        """Create a ChatBridge-owned background browser session."""
        return _call("create", persist_profile=persist_profile, url=url, mode="background")

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
    def background_browser_action(session_token: str, action: str, tab_id: str = "",
                                  url: str = "", selector: str = "", text: str = "",
                                  dx: int = 0, dy: int = 0, mode: str = "background",
                                  client_request_id: str = "") -> dict:
        """Run a browser action in ChatBridge, never changing macOS focus.

        client_request_id can be reused ONLY for the exact same operation.
        """
        if mode not in ("background", "auto", "foreground"):
            return _error("INVALID_MODE", "Unsupported browser mode")
        if mode == "foreground":
            return _error("REQUIRES_FOREGROUND", "Use explicitly requested foreground GUI tools")
        return _call("action", session_token=session_token, action=action, tab_id=tab_id,
                     url=url, selector=selector, text=text, dx=dx, dy=dy, mode=mode,
                     client_request_id=client_request_id)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    def background_browser_snapshot(session_token: str, tab_id: str = "", max_chars: int = 12000) -> dict:
        """Read ChatBridge DOM/Accessibility snapshot."""
        return _call("snapshot", session_token=session_token, tab_id=tab_id, max_chars=max_chars)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    def background_browser_capture(session_token: str, tab_id: str = "", quality: int = 65) -> dict:
        """Fetch screenshot binary via authenticated ChatBridge file endpoint."""
        return _call("capture", session_token=session_token, tab_id=tab_id, quality=quality)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def background_browser_list(session_tokens: list[str]) -> dict:
        """List precisely the ChatBridge sessions for supplied capabilities."""
        return _call("list", session_tokens=session_tokens)

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def background_browser_close(session_token: str) -> dict:
        """Close a ChatBridge-owned session."""
        return _call("close", session_token=session_token)

    @mcp.tool(annotations={"readOnlyHint": False, "openWorldHint": False})
    def background_browser_reopen(session_token: str) -> dict:
        """Reopen a persistent ChatBridge-owned session."""
        return _call("reopen", session_token=session_token)
