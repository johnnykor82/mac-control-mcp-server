"""Frozen 102-handler compatibility inventory, never dispatched to MCP.

This module statically imports trusted source and invokes register() only to
discover its exact callables. Live production continues using old dispatcher.
There is NO interpreter of user data and NO runtime plugin discovery here.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .legacy_handlers import fs_ops, git_ops, system_ops, command_plugins

_HANDLER_ROOT = (Path(__file__).resolve().parent / "legacy_handlers").resolve()
_EXPECTED = frozenset(('approved_commands', 'chrome_chat_adopt', 'chrome_chat_archive', 'chrome_chat_cleanup', 'chrome_chat_new', 'chrome_chat_read', 'chrome_chat_restore', 'chrome_chat_save', 'chrome_chat_send', 'chrome_chat_switch', 'chrome_chat_ui_status', 'chrome_chat_wait', 'chrome_orchestrator_launch', 'chrome_orchestrator_status', 'execute_approved', 'fs_list', 'fs_mkdir', 'fs_move', 'fs_read', 'fs_replace', 'fs_restore', 'fs_search', 'fs_stat', 'fs_trash', 'fs_write', 'git_branches', 'git_commit', 'git_create_branch', 'git_diff', 'git_fetch', 'git_history', 'git_pull_ff', 'git_push', 'git_stage', 'git_status', 'gui_displays', 'gui_focus', 'gui_mouse', 'gui_open_app', 'gui_press', 'gui_request_permissions', 'gui_screenshot', 'gui_scroll', 'gui_status', 'gui_tree', 'gui_type', 'gui_wait_title', 'gui_windows', 'launchd_restart', 'launchd_status', 'local_http_probe', 'machine_health', 'mcp_bridge_call', 'mcp_bridge_list', 'mcp_bridge_read', 'mcp_targets', 'network_listeners', 'package_capabilities', 'package_install', 'package_installed', 'package_job_status', 'project_roots', 'project_task', 'ssh_auth_diagnostics', 'ssh_diagnostic', 'ssh_exec', 'ssh_identity_inspect', 'ssh_open', 'ssh_profile_approve_alias', 'ssh_profile_inventory', 'ssh_profile_register', 'ssh_pty_open', 'ssh_targets', 'terminal_access_configure', 'terminal_capabilities', 'terminal_close', 'terminal_exec', 'terminal_list', 'terminal_open', 'terminal_read', 'terminal_resize', 'terminal_send', 'watcher_ack_delivery', 'watcher_ack_wakeup', 'watcher_cancel_wakeup', 'watcher_error_status', 'watcher_followup_browser_task', 'watcher_get_wakeup', 'watcher_guide', 'watcher_list_wakeups', 'watcher_pause_project', 'watcher_read_report', 'watcher_read_result', 'watcher_register_file_task', 'watcher_register_project', 'watcher_register_task', 'watcher_resolve_current_chat', 'watcher_resume_project', 'watcher_resume_task', 'watcher_schedule_wakeup', 'watcher_status', 'watcher_submit_report'))


@dataclass(frozen=True)
class FrozenHandler:
    handler: Callable[..., Any]
    read_only: bool


class _Collector:
    def __init__(self):
        self.entries: dict[str, FrozenHandler] = {}

    def tool(self, *args, **kwargs):
        annotations = kwargs.get("annotations") or {}
        if type(annotations.get("readOnlyHint")) is not bool:
            raise RuntimeError("Handler lacks readOnlyHint")

        def register(fn):
            name = fn.__name__
            origin = inspect.getsourcefile(fn)
            if (not origin or Path(origin).is_symlink()
                    or Path(origin).resolve(strict=True).parent != _HANDLER_ROOT
                    or not fn.__module__.startswith("mac_control.legacy_handlers.")):
                raise RuntimeError("Untrusted handler source")
            if name in self.entries:
                raise RuntimeError("Duplicate operation: " + name)
            self.entries[name] = FrozenHandler(fn, annotations["readOnlyHint"])
            return fn

        if args and callable(args[0]) and len(args) == 1:
            return register(args[0])
        return register


def inspect_existing_handlers() -> Mapping[str, FrozenHandler]:
    """Retain existing names without executing a single user operation."""
    collector = _Collector()
    for module in (fs_ops, git_ops, system_ops, command_plugins):
        module.register(collector)
    if set(collector.entries) != _EXPECTED:
        raise RuntimeError("Frozen source registry differs from pinned 102 operations")
    if sum(x.read_only for x in collector.entries.values()) != 45:
        raise RuntimeError("Read-only metadata drift")
    return MappingProxyType(collector.entries)
