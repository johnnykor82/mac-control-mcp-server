#!/usr/bin/env python3
"""Read-only component diagnostics for an owned Mac Control installation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Callable

REQUIRED_COMPONENTS = (
    "installation", "workspace", "terminal", "pty", "ssh_sftp",
    "mcp_bridge", "gui", "chatbridge", "watcher", "cli", "oauth",
)


def _incomplete(reason: str, remedy: str) -> dict:
    return {"status": "incomplete", "reason": reason, "remedy": remedy}


def combine(components: dict) -> dict:
    """Aggregate a fixed inventory; never silently omit an unknown state."""
    results = {}
    for name in REQUIRED_COMPONENTS:
        item = components.get(name)
        if not isinstance(item, dict) or item.get("status") not in ("ready", "incomplete", "error"):
            item = _incomplete("not_checked", "Run maccontrol doctor after setup")
        results[name] = item
    return {"status": ("READY" if all(x["status"] == "ready" for x in results.values())
                       else "INCOMPLETE"),
            "components": results, "next": "maccontrol setup"}


def _probe(action: Callable, remedy: str) -> dict:
    """No exception messages: they may contain OAuth, SSH or browser secrets."""
    try:
        value = action()
        return {"status": "ready"} if value else _incomplete("not_ready", remedy)
    except (OSError, ValueError, RuntimeError, PermissionError):
        return _incomplete("probe_failed", remedy)


def _oauth_acceptance(root: Path) -> bool:
    """True only for a successful browser OAuth test of this exact release."""
    marker = root / "data/oauth-acceptance.json"
    if not marker.is_file() or marker.is_symlink():
        return False
    metadata = marker.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        return False
    try:
        data = json.loads(marker.read_text())
        from scripts.setup_github_oauth import check
        config = check(root)
        return (data.get("authenticated_mcp_success") is True
                and data.get("endpoint") == config["public_url"].rstrip("/") + "/mcp"
                and data.get("release") == str((root / "current").resolve()))
    except (OSError, ValueError, RuntimeError, KeyError):
        return False


def collect(root: Path) -> dict:
    """Gather only safe facts; never mutate remote services, system TCC or OAuth."""
    root = Path(root).expanduser().resolve()
    data = root / "data"
    release = root / "current"
    results = {}
    results["installation"] = _probe(
        lambda: (root / ".mac-control-installer-owned").is_file()
        and release.is_symlink() and release.resolve().is_dir(),
        "Install or repair the owned Mac Control release")
    results["workspace"] = _probe(
        lambda: (root.parent / "AgentWorkspace").is_dir()
        or (data / "workspace.json").is_file(),
        "Configure the agent workspace")
    results["terminal"] = _probe(lambda: shutil.which("zsh") is not None,
                                 "Install the macOS zsh shell")
    results["pty"] = _probe(lambda: shutil.which("tmux") is not None,
                            "Run brew install tmux")
    results["ssh_sftp"] = _probe(lambda: Path("/usr/bin/ssh").is_file()
                                and Path("/usr/bin/sftp").is_file(),
                                "Restore OpenSSH system binaries")
    results["mcp_bridge"] = _probe(
        lambda: (release / "src/mac_control/legacy_handlers/mcp_bridge_ops.py").is_file(),
        "Repair MCP Bridge module (external MCP servers are optional)")
    from scripts import setup_chatbridge_dependency as bridge
    url_file = data / "chatbridge_connection.txt"
    if url_file.is_file() and not url_file.is_symlink():
        try:
            auth = bridge.browser_login_status(url_file.read_text().strip())
            results["chatbridge"] = ({"status": "ready"} if auth.get("authenticated") is True
                                     else _incomplete("chatgpt_login_required",
                                                     "Sign into ChatGPT in ChatBridge Chrome"))
        except (OSError, RuntimeError, ValueError):
            results["chatbridge"] = _incomplete("browser_probe_failed",
                                               "Inspect ChatBridge, then resume setup")
    else:
        results["chatbridge"] = _incomplete("chatbridge_missing",
                                           "Install and authorize ChatBridge")
    from scripts import setup_watcher_service as watcher
    results["watcher"] = _probe(
        lambda: watcher.status(root).get("status") == "running",
        "Start the owned Watcher after ChatBridge becomes ready")
    try:
        from scripts import guided_setup
        gui = guided_setup._gui_call(root, "status")
        results["gui"] = ({"status": "ready"} if gui.get("accessibility_trusted")
                          and gui.get("screen_capture_trusted")
                          else _incomplete("macos_tcc_missing",
                                           "Grant Accessibility and Screen Recording in System Settings"))
    except (OSError, RuntimeError, ValueError):
        results["gui"] = _incomplete("gui_helper_unavailable",
                                     "Run maccontrol setup to install and authorize the GUI")
    from scripts.setup_cli_commands import wrapper
    cli = Path.home() / ".local/bin/mclog"
    results["cli"] = _probe(
        lambda: cli.is_file() and not cli.is_symlink()
        and cli.read_text() == wrapper(root, "mclog"),
        "Resolve mclog conflict or run ~/MacControlMCP/current/bin/mclog")
    # Metadata alone does not prove an authenticated OAuth browser login.
    # E9 acceptance explicitly verifies OAuth and records the result.
    results["oauth"] = ({"status": "ready"} if _oauth_acceptance(root)
                        else _incomplete("interactive_oauth_test_pending",
                                         "Run --github-oauth-login-test on the installed release"))
    return combine(results)
