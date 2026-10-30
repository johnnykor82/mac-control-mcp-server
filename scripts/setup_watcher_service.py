#!/usr/bin/env python3
"""Owner-scoped login autostart for the local task watcher.

The daemon can run idle without ChatBridge, network access, or browser login.
Only an exact owned LaunchAgent is started, stopped or removed. No live-service
operations happen on import; callers explicitly select a lifecycle operation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

try:
    from .setup_remote_service import (
        _owned, _prepare_logs, _read_owned_plist, _safe_path, _write_new_plist,
    )
except ImportError:
    from setup_remote_service import (
        _owned, _prepare_logs, _read_owned_plist, _safe_path, _write_new_plist,
    )

DEFAULT_ROOT = Path.home() / "MacControlMCP"
LABEL = "org.maccontrol.mcpserver.watcher"
POLL_COUNT = 40
POLL_INTERVAL = 0.25


def _layout(root: Path, launch_agents: Path | None) -> tuple[Path, Path, dict]:
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise RuntimeError("Watcher autostart requires a non-root macOS login user")
    root = _safe_path(root)
    _owned(root, directory=True)
    _owned(root / ".mac-control-installer-owned")
    _owned(root / "data", directory=True, private=True)
    releases = root / "releases"
    _owned(_safe_path(releases), directory=True)
    current = root / "current"
    if not current.is_symlink():
        raise RuntimeError("Installed current release pointer is missing")
    release = current.resolve()
    if release.parent != releases:
        raise RuntimeError("Current release is outside the owned installation")
    _owned(_safe_path(release), directory=True)
    agents = _safe_path(launch_agents or (Path.home() / "Library/LaunchAgents"))
    if agents.exists():
        _owned(agents, directory=True)
    logs = root / "data/logs"
    if logs.exists() or logs.is_symlink():
        _owned(logs, directory=True, private=True)
    config = {
        "Label": LABEL,
        "ProgramArguments": [str(current / ".venv/bin/python"), "-B", "-m",
                             "mac_control.watcher_runtime", "run"],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "Umask": 0o077,
        "EnvironmentVariables": {
            "MAC_CONTROL_DATA_ROOT": str(root / "data"),
            "PYTHONPATH": str(current / "src"),
        },
        "StandardOutPath": str(logs / "watcher.stdout.log"),
        "StandardErrorPath": str(logs / "watcher.stderr.log"),
        "MacControlInstallRoot": str(root),
    }
    for key in ("StandardOutPath", "StandardErrorPath"):
        path = Path(config[key])
        if path.exists() or path.is_symlink():
            _owned(path, private=True)
    return root, agents / (LABEL + ".plist"), config


def _validate_runtime(root: Path) -> None:
    """Require installed code only for operations that start a process.

    Virtualenv Python is normally a symlink to the installer-selected Python.
    Its containing directories and the runtime source must remain owned real
    paths; the resolved interpreter must be a protected executable regular file.
    """
    release = (root / "current").resolve()
    for relative in (".venv", ".venv/bin", "src", "src/mac_control",
                     "src/mac_control/watcher_runtime"):
        _owned(_safe_path(release / relative), directory=True)
    _owned(_safe_path(release / "src/mac_control/watcher_runtime/__main__.py"))
    python = release / ".venv/bin/python"
    if python.is_symlink() and python.lstat().st_uid != os.getuid():
        raise RuntimeError("Installed watcher interpreter has unsafe ownership")
    info = python.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.getuid())
            or info.st_mode & 0o022 or not os.access(python, os.X_OK)):
        raise RuntimeError("Installed watcher interpreter is not a protected executable")


def _launchctl(*arguments: str) -> subprocess.CompletedProcess:
    # Arguments never pass through a shell, and no credentials enter the plist.
    return subprocess.run(["/bin/launchctl", *arguments], text=True,
                          capture_output=True, check=False, timeout=12)


def _target() -> str:
    return "gui/" + str(os.getuid()) + "/" + LABEL


def _job(plist: Path, expected: dict) -> dict | None:
    result = _launchctl("print", _target())
    if result.returncode:
        if "Could not find service" in result.stderr:
            return None
        raise RuntimeError("Unable to inspect user LaunchAgent; no takeover attempted")
    fields = {}
    for name in ("path", "program", "state", "pid"):
        match = re.search(r"^\s*" + name + r" = (.+)$", result.stdout, re.MULTILINE)
        fields[name] = match.group(1).strip() if match else None
    if (fields["path"] != str(plist)
            or fields["program"] != expected["ProgramArguments"][0]):
        raise RuntimeError("Unknown loaded LaunchAgent ownership; foreign job preserved")
    return fields


def _running(job: dict | None) -> bool:
    return bool(job and job["state"] == "running" and job["pid"]
                and job["pid"].isdigit() and int(job["pid"]) > 0)


def _wait_running(plist: Path, expected: dict) -> None:
    for _ in range(POLL_COUNT):
        if _running(_job(plist, expected)):
            return
        time.sleep(POLL_INTERVAL)
    raise RuntimeError("Watcher LaunchAgent did not become running")


def _stop_owned(plist: Path, expected: dict) -> None:
    if _job(plist, expected) is None:
        return
    _launchctl("bootout", _target())
    for _ in range(POLL_COUNT):
        if _job(plist, expected) is None:
            return
        time.sleep(POLL_INTERVAL)
    raise RuntimeError("Could not confirm LaunchAgent deregistration; owned plist preserved")


def _rollback_start(plist: Path, expected: dict, *, created: bool) -> None:
    _stop_owned(plist, expected)
    if created and _read_owned_plist(plist, expected):
        plist.unlink()


def status(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Read status without starting a process or creating/repairing files."""
    _, plist, expected = _layout(root, launch_agents)
    installed = _read_owned_plist(plist, expected)
    job = _job(plist, expected) if installed else None
    return {
        "status": ("running" if _running(job) else "loaded" if job else
                   "installed" if installed else "not_installed"),
        "label": LABEL, "plist": str(plist), "domain": "gui/" + str(os.getuid()),
        "run_at_login": installed, "pid": job["pid"] if job else None,
    }


def _ensure(root: Path, launch_agents: Path | None, *, require_installed: bool) -> dict:
    root, plist, expected = _layout(root, launch_agents)
    _validate_runtime(root)
    installed = _read_owned_plist(plist, expected)
    if require_installed and not installed:
        raise FileNotFoundError("Install the owned watcher LaunchAgent before --start")
    job = _job(plist, expected)
    if job is not None:
        if not installed:
            raise RuntimeError("Loaded LaunchAgent has no owned plist; no changes made")
        if not _running(job):
            _wait_running(plist, expected)
    else:
        _prepare_logs(expected)
        created = not installed
        if created:
            _write_new_plist(plist, expected)
        try:
            result = _launchctl("bootstrap", "gui/" + str(os.getuid()), str(plist))
            if result.returncode:
                raise RuntimeError("Watcher LaunchAgent bootstrap failed")
            _wait_running(plist, expected)
        except BaseException as error:
            # An owner interrupt must not strand a replacement daemon while the
            # installer restores the previous current pointer.
            try:
                _rollback_start(plist, expected, created=created)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                raise RuntimeError("Watcher service start failed; rollback incomplete, owned plist preserved") from None
            if not isinstance(error, (OSError, RuntimeError, subprocess.SubprocessError)):
                raise
            raise RuntimeError("Watcher service start failed; prior LaunchAgent state restored") from error
    return {"status": "running", "label": LABEL, "plist": str(plist),
            "domain": "gui/" + str(os.getuid()), "created_plist": not installed,
            "run_at_login": True}


def ensure(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Idempotently install and start the owned login agent, including idle use."""
    return _ensure(root, launch_agents, require_installed=False)


def start(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Start an existing owned agent after the caller restores a release pointer."""
    return _ensure(root, launch_agents, require_installed=True)


def stop_if_installed(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Stop the owned agent before a release switch; preserve its login plist."""
    _, plist, expected = _layout(root, launch_agents)
    if not _read_owned_plist(plist, expected):
        return {"status": "not_installed", "changed": False, "label": LABEL}
    if _job(plist, expected) is None:
        return {"status": "not_loaded", "changed": False, "label": LABEL}
    _stop_owned(plist, expected)
    return {"status": "stopped", "changed": True, "label": LABEL}


class RestartError(RuntimeError):
    """Replacement failed; service_stopped confirms whether pointer restore is safe."""
    def __init__(self, message: str, *, service_stopped: bool | None):
        super().__init__(message)
        self.service_stopped = service_stopped


def restart_if_installed(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Restart a loaded owned agent; caller owns release-pointer rollback.

    Absent/unloaded agents are unchanged. A failed replacement preserves the
    plist. Restore the old pointer before start(root) only when service_stopped
    is True; an unknown deregistration state requires inspection first.
    """
    root, plist, expected = _layout(root, launch_agents)
    if not _read_owned_plist(plist, expected):
        return {"status": "not_installed", "changed": False, "label": LABEL}
    if _job(plist, expected) is None:
        return {"status": "not_loaded", "changed": False, "label": LABEL}
    _validate_runtime(root)
    _stop_owned(plist, expected)
    try:
        result = start(root, launch_agents=launch_agents)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        try:
            _rollback_start(plist, expected, created=False)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            raise RestartError("Watcher restart failed; deregistration unknown, owned plist preserved",
                               service_stopped=None) from None
        raise RestartError("Watcher restart failed; service stopped and owned plist preserved; "
                           "restore previous release pointer before start(root)",
                           service_stopped=True) from error
    return {**result, "status": "restarted", "changed": True}


def remove_if_installed(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Deregister, then remove only the exact owned plist; preserve all data."""
    _, plist, expected = _layout(root, launch_agents)
    if not _read_owned_plist(plist, expected):
        return {"status": "not_installed", "changed": False, "label": LABEL}
    _stop_owned(plist, expected)
    if not _read_owned_plist(plist, expected):
        raise RuntimeError("Owned LaunchAgent plist disappeared during removal")
    plist.unlink()
    return {"status": "removed", "changed": True, "label": LABEL,
            "run_at_login": False, "data_preserved": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--launch-agents", type=Path)
    actions = parser.add_mutually_exclusive_group(required=True)
    for action in ("ensure", "start", "status", "stop", "remove", "restart"):
        actions.add_argument("--" + action, action="store_true")
    args = parser.parse_args(argv)
    operations = {"ensure": ensure, "start": start, "status": status,
                  "stop": stop_if_installed, "remove": remove_if_installed,
                  "restart": restart_if_installed}
    operation = next(function for name, function in operations.items() if getattr(args, name))
    print(json.dumps(operation(args.root, launch_agents=args.launch_agents), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print("Watcher service setup failed:", type(error).__name__,
              str(error) if isinstance(error, RuntimeError) else "", file=sys.stderr)
        raise SystemExit(1)
