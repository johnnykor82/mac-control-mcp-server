"""Bounded, safety-preserving suggestions for recoverable tool argument errors.

A validation hint is not permission to bypass policy/host/tool authorization.
No user-supplied argument values are copied into guidance.
"""
from __future__ import annotations

from functools import wraps
import inspect
from typing import Callable


# All alternatives are already shipped, read-only introspection or a safer
# matching tool. Never suggest repeating a policy-denied operation elsewhere.
_ALTERNATIVES = {
    "ssh": "Check ssh_profile_inventory; for generated files use ssh_write_text or ssh_upload, then a short ssh_exec.",
    "terminal": "Check terminal_capabilities and terminal_list; retry with a supported project, command and session ID.",
    "gui": "Check gui_status, gui_windows and the tool's supported actions before retrying.",
    "fs": "Use project_roots for an approved root, then use a relative non-traversing path; inspect with fs_stat.",
    "git": "Call project_roots and git_status; choose an approved repository and a concrete Git path.",
    "watcher": "Call watcher_guide and watcher_status; use a valid existing project/task ID and operation.",
    "chrome": "Call chrome_chat_ui_status or chrome_orchestrator_status; verify the task ID and current chat state.",
    "mcp": "Call mcp_targets or mcp_bridge_list; choose an allowed target and valid JSON object.",
    "package": "Call package_capabilities; choose a listed supported formula or job ID.",
    "project": "Call project_roots to see approved project names and supported tasks.",
    "local": "Call system_info and confirm the approved local endpoint and method.",
    "launchd": "Call launchd_status with a current-user LaunchAgent label; own MCP uses restart_server.",
    "network": "Call network_listeners to inspect existing listeners before retrying.",
}
_GENERIC = "Review required argument names and values against the tool signature; retry only with authorized input."
_KNOWN_REASONS = {
    "Unsupported mouse action": "Unsupported mouse action.",
    "Invalid session ID": "Invalid terminal session ID.",
    "Invalid branch name": "Invalid Git branch name.",
    "Invalid command": "Command is invalid.",
    "Invalid terminal text": "Terminal text is invalid.",
    "Invalid Watcher state path": "Watcher state path is invalid.",
    "File too large (512 KiB limit)": "Input file exceeds 512 KiB limit.",
    "Content exceeds 512 KiB": "Input content exceeds 512 KiB limit.",
    "Text length limit 1500": "Text exceeds 1500 characters.",
    "Relative non-traversing path required": "Path must be relative without traversal components.",
    "Path outside approved root": "Path is outside the approved root.",
    "Nonempty prompt required": "Prompt must be non-empty.",
    "Invalid bundle identifier": "Application bundle identifier is invalid.",
    "Invalid host label": "SSH host label is invalid.",
    "Unsupported key": "Terminal key is unsupported.",
    "Search text must be 1–160 characters": "Search text must be 1–160 characters.",
    "Supply 1–20 explicit paths": "Supply between 1 and 20 explicit paths.",
    "Commit message must be 1–300 chars": "Commit message must be 1–300 characters.",
    "Arguments too large": "MCP arguments exceed the tool payload limit.",
    "Arguments exceed 128 KiB": "Arguments exceed the 128 KiB wrapper limit.",
    "Invalid media byte range": "Invalid media byte range.",
    "Media base64 too large; use media_file reference": "Inline media is too large; use media_file reference.",
    "Invalid SSH host parameters": "SSH host registration parameters are invalid.",
    "Task archived; restore it before sending": "Chat task is archived; restore it before sending.",
    "No active branch": "Git repository has no active branch.",
    "Expected JSON payload": "Watcher payload must be valid JSON.",
    "Invalid job ID": "Package job identifier is invalid.",
    "Invalid formula": "Package formula name is invalid.",
    "Task ID must be short": "Task ID must be short.",
}


def _alternative(operation: str) -> str:
    for prefix, remedy in _ALTERNATIVES.items():
        if operation == prefix or operation.startswith(prefix + "_"):
            return remedy
    return _GENERIC


def _parameters(handler: Callable) -> str:
    """Show names only, no default values or annotations with private content."""
    try:
        sig = inspect.signature(handler)
        names = []
        for name, param in sig.parameters.items():
            if name.startswith("_"):
                continue
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                names.append("**options")
            elif param.kind == inspect.Parameter.VAR_POSITIONAL:
                names.append("*args")
            else:
                names.append(name + (" (required)" if param.default is inspect.Parameter.empty else ""))
        return ", ".join(names)[:250] or "(none)"
    except (TypeError, ValueError):
        return "consult the MCP tool schema"


def guided_validation_error(operation: str, handler: Callable,
                            original: Exception, *, signature: bool = False) -> ValueError:
    """Never echo dynamic exception text, tool parameters or secrets."""
    message = str(original)
    # Preserve already actionable, tool-specific machine-readable errors.
    if (
        (operation == "ssh_exec" and message.startswith(("SSH_COMMAND_TOO_LONG:", "SSH_COMMAND_INVALID:")))
        or (operation == "terminal_exec" and message.startswith(
            ("TERMINAL_COMMAND_TOO_LONG:", "TERMINAL_COMMAND_INVALID:")))
        or (operation.startswith("watcher_") and message.startswith("WATCHER_ID_INVALID:"))
        or (operation == "terminal_send" and message.startswith((
            "TERMINAL_TEXT_INVALID:", "TERMINAL_TEXT_TOO_LONG:",
            "TERMINAL_KEY_INVALID:", "TERMINAL_SEND_EMPTY:")))
        or (operation == "gui_mouse" and message.startswith("GUI_MOUSE_ACTION_INVALID:"))
        or (operation == "git_create_branch" and message.startswith("GIT_BRANCH_NAME_INVALID:"))
        or (operation.startswith("terminal_") and message.startswith((
            "TERMINAL_SESSION_INVALID:", "TERMINAL_SESSION_NOT_FOUND:")))
        or (operation.startswith("mcp_bridge_") and message.startswith((
            "MCP_TARGET_NAME_INVALID:", "MCP_TARGET_NOT_FOUND:", "MCP_URL_INVALID:")))
    ):
        return ValueError(message)
    # Signature.bind() happens before invocation, so missing/extra args are
    # always preflight failures. Handler-thrown ValueErrors can occur later.
    classified = signature or message in _KNOWN_REASONS
    reason = ("Missing, unexpected or incompatible parameter names."
              if signature else _KNOWN_REASONS.get(message,
                   "Unclassified ValueError; the operation may have started or changed state."))
    operation = operation[:80] if isinstance(operation, str) else "unknown"
    kind = "VALIDATION_ERROR" if classified else "TOOL_VALUE_ERROR"
    text = (f"{kind}: tool={operation}; reason={reason} "
            f"Expected parameters: {_parameters(handler)}. "
            f"Next: {_alternative(operation)} "
            + ("Inspect the audit and actual state before any retry. "
               if not classified else "")
            + "If a permission/policy check is denied, stop rather than bypass it.")
    return ValueError(text[:760])


def guided_handler(operation: str, handler: Callable) -> Callable:
    """Wrap a shipped handler without modifying schema, async behavior or policy."""
    if inspect.iscoroutinefunction(handler):
        @wraps(handler)
        async def guarded(*args, **kwargs):
            try:
                return await handler(*args, **kwargs)
            except ValueError as error:
                raise guided_validation_error(operation, handler, error) from None
        return guarded

    @wraps(handler)
    def guarded(*args, **kwargs):
        try:
            return handler(*args, **kwargs)
        except ValueError as error:
            raise guided_validation_error(operation, handler, error) from None
    return guarded
