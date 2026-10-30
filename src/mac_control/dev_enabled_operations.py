"""Incremental preview of *existing* Mac Control operations.

Only audited, read-only filesystem/Git operations are enabled until the
untrusted-input and write-path integration gates are complete. This is a
static deployment feature set, not a second approval policy/command catalog.
"""
from __future__ import annotations

from .legacy_adapter import inspect_existing_handlers
from .runtime_paths import DATA_ROOT
from .workspace_policy import short_instruction as workspace_short_instruction
import os
import json
from pathlib import Path

READ_ONLY_PREVIEW_OPERATIONS = frozenset({
    "project_roots",
    "fs_list",
    "fs_stat",
    "fs_read",
    "fs_search",
    "git_status",
    "git_diff",
    "git_history",
    "git_branches",
    "approved_commands",
    "machine_health",
    "network_listeners",
    "package_capabilities",
    "package_installed",
    "mcp_targets",
    "ssh_targets",
    "terminal_capabilities",
    "gui_status",
    "gui_displays",
})


# Sensitive GUI introspection and screenshots are stdio-only, not served
# from the unauthenticated loopback HTTP preview.
LOCAL_GUI_READ_OPERATIONS = frozenset({
    "gui_windows", "gui_tree", "gui_screenshot", "gui_wait_title",
})

# PTY session inspection is not available over the unattended HTTP preview.
LOCAL_TERMINAL_READ_OPERATIONS = frozenset({
    "terminal_read", "terminal_list",
})

LOCAL_BRIDGE_READ_OPERATIONS = frozenset({
    "mcp_bridge_list", "mcp_bridge_read",
})

# All current Stable operations are available over LOCAL, explicitly configured Dev stdio.
# The 19 read-only HTTP preview operations are unchanged and not widened.
LOCAL_MUTATION_OPERATIONS = frozenset({
    'chrome_chat_adopt',
    'chrome_chat_archive',
    'chrome_chat_cleanup',
    'chrome_chat_new',
    'chrome_chat_restore',
    'chrome_chat_save',
    'chrome_chat_send',
    'chrome_chat_switch',
    'chrome_orchestrator_launch',
    'execute_approved',
    'fs_mkdir',
    'fs_move',
    'fs_replace',
    'fs_restore',
    'fs_trash',
    'fs_write',
    'git_commit',
    'git_create_branch',
    'git_fetch',
    'git_pull_ff',
    'git_push',
    'git_stage',
    'gui_focus',
    'gui_mouse',
    'gui_open_app',
    'gui_press',
    'gui_request_permissions',
    'gui_scroll',
    'gui_type',
    'launchd_restart',
    'mcp_bridge_call',
    'package_install',
    'project_task',
    'ssh_exec',
    'ssh_open',
    'ssh_profile_approve_alias',
    'ssh_profile_register',
    'ssh_pty_open',
    'terminal_access_configure',
    'terminal_close',
    'terminal_exec',
    'terminal_open',
    'terminal_resize',
    'terminal_send',
    'watcher_followup_browser_task',
    'watcher_resolve_current_chat',
    'watcher_ack_delivery',
    'watcher_ack_wakeup',
    'watcher_cancel_wakeup',
    'watcher_pause_project',
    'watcher_register_file_task',
    'watcher_register_project',
    'watcher_register_task',
    'watcher_resume_project',
    'watcher_resume_task',
    'watcher_schedule_wakeup',
    'watcher_submit_report',
})

LOCAL_COMPAT_READ_OPERATIONS = frozenset({
    'chrome_chat_read',
    'chrome_chat_ui_status',
    'chrome_chat_wait',
    'chrome_orchestrator_status',
    'launchd_status',
    'local_http_probe',
    'package_job_status',
    'ssh_auth_diagnostics',
    'ssh_diagnostic',
    'ssh_identity_inspect',
    'ssh_profile_inventory',
    'watcher_error_status',
    'watcher_get_wakeup',
    'watcher_guide',
    'watcher_list_wakeups',
    'watcher_read_report',
    'watcher_read_result',
    'watcher_status',
})

def operation_enabled(name: str) -> bool:
    """Shared installed-feature gate for direct tools and compatibility wrappers."""
    if not os.environ.get("MAC_CONTROL_DATA_ROOT"):
        return True
    flags = {}
    feature_file = DATA_ROOT / "feature_flags.json"
    if feature_file.is_file() and not feature_file.is_symlink():
        try:
            flags = json.loads(feature_file.read_text())
            if not isinstance(flags, dict):
                return False
        except (OSError, ValueError):
            return False
    if name.startswith("watcher_"):
        return (flags.get("watcher") is True
                and (Path(__file__).parent / "watcher_runtime/__main__.py").is_file())
    if name.startswith("gui_"):
        return (flags.get("native_gui") is True and
                (DATA_ROOT.parent / "apps/MacControlMCPServer.app/Contents/MacOS/MacControlMCPServer").is_file())
    if name.startswith(("chrome_chat_", "chrome_orchestrator_")):
        return flags.get("background_browser") is True
    return True


def register_preview_operations(mcp, *, include_mutations: bool = False) -> None:
    registry = inspect_existing_handlers()
    for name in sorted(READ_ONLY_PREVIEW_OPERATIONS):
        if not operation_enabled(name):
            continue
        found = registry[name]
        if not found.read_only:
            raise RuntimeError("Write operation in HTTP preview: " + name)
        mcp.tool(name=name, annotations={"readOnlyHint": True, "openWorldHint": False})(found.handler)
    if not include_mutations:
        return
    exposed = set(READ_ONLY_PREVIEW_OPERATIONS)
    for name in sorted(set(registry) - exposed):
        if not operation_enabled(name):
            continue
        found = registry[name]
        desc = (found.handler.__doc__ or name).strip()
        if not found.read_only:
            desc += "\n\n" + workspace_short_instruction()
        mcp.tool(name=name, description=desc, annotations={"readOnlyHint": found.read_only,
                   "destructiveHint": not found.read_only, "openWorldHint": False})(found.handler)
    if set(registry) != (READ_ONLY_PREVIEW_OPERATIONS | LOCAL_MUTATION_OPERATIONS |
                         LOCAL_COMPAT_READ_OPERATIONS | LOCAL_GUI_READ_OPERATIONS |
                         LOCAL_TERMINAL_READ_OPERATIONS | LOCAL_BRIDGE_READ_OPERATIONS):
        raise RuntimeError("Dev parity inventory drift")
