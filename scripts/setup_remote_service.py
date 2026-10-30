#!/usr/bin/env python3
"""Owner-scoped login autostart for the authenticated, loopback-only remote MCP.

ensure(root) installs and starts the owned LaunchAgent; start(root) requires an
existing owned plist. status(root) is read-only. No sudo, public listener,
Funnel configuration, OAuth credential changes or TCC changes are performed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

try:
    from .setup_github_oauth import check as check_oauth
except ImportError:
    from setup_github_oauth import check as check_oauth

DEFAULT_ROOT = Path.home() / "MacControlMCP"
LABEL = "org.maccontrol.mcpserver.remote"
PORT = 3201
POLL_COUNT = 40
POLL_INTERVAL = 0.25


def _safe_path(path: Path) -> Path:
    path = path.expanduser().absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise RuntimeError("Refusing symlink in service installation path")
    return path


def _owned(path: Path, *, directory: bool = False, private: bool = False) -> None:
    info = path.lstat()
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid or info.st_uid != os.getuid() or (not directory and info.st_nlink != 1):
        raise RuntimeError("Service path has unsafe type or ownership: " + str(path))
    forbidden = 0o077 if private else 0o022
    if info.st_mode & forbidden:
        raise PermissionError("Service path has unsafe permissions: " + str(path))


def _layout(root: Path, launch_agents: Path | None) -> tuple[Path, Path, dict]:
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise RuntimeError("Remote autostart requires a non-root macOS login user")
    root = _safe_path(root)
    _owned(root, directory=True)
    _owned(root / ".mac-control-installer-owned")
    _owned(root / "data", directory=True, private=True)
    releases = root / "releases"
    _owned(releases, directory=True)
    current = root / "current"
    if not current.is_symlink():
        raise RuntimeError("Installed current release pointer is missing")
    release = current.resolve()
    if release.parent != releases or release.is_symlink():
        raise RuntimeError("Current release is outside the owned installation")
    _owned(release, directory=True)
    _owned(release / "bin", directory=True)
    _owned(release / "bin/mac-control-remote-mcp.sh")
    if not os.access(release / "bin/mac-control-remote-mcp.sh", os.X_OK):
        raise RuntimeError("Installed remote launcher is not executable")
    agents = _safe_path(launch_agents or (Path.home() / "Library/LaunchAgents"))
    if agents.exists():
        _owned(agents, directory=True)
    logs = root / "data/logs"
    if logs.exists() or logs.is_symlink():
        _owned(logs, directory=True, private=True)
    config = {
        "Label": LABEL,
        "ProgramArguments": [str(current / "bin/mac-control-remote-mcp.sh")],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "Umask": 0o077,
        "EnvironmentVariables": {"MAC_CONTROL_REMOTE_PORT": str(PORT)},
        "StandardOutPath": str(logs / "remote-mcp.stdout.log"),
        "StandardErrorPath": str(logs / "remote-mcp.stderr.log"),
        "MacControlInstallRoot": str(root),
    }
    for key in ("StandardOutPath", "StandardErrorPath"):
        logfile = Path(config[key])
        if logfile.exists() or logfile.is_symlink():
            _owned(logfile, private=True)
    return root, agents / (LABEL + ".plist"), config


def _read_owned_plist(path: Path, expected: dict) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    _owned(path, private=True)
    # Exact structure binds ownership to this root, launcher, port and log paths.
    # Do not "repair" a label collision or accept injected launchd options.
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise PermissionError("LaunchAgent must be an owner-only regular file")
        actual = plistlib.load(source)
    if actual != expected:
        raise RuntimeError("Unknown LaunchAgent ownership; existing plist preserved")
    return True


def _launchctl(*arguments: str) -> subprocess.CompletedProcess:
    # Dynamic values are argv entries, never shell commands; secrets stay in data.
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _endpoint_ready(public_url: str) -> bool:
    # Bypass HTTP proxy environment settings for this strictly local health check.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    local = "http://127.0.0.1:" + str(PORT)
    try:
        with opener.open(local + "/.well-known/oauth-authorization-server", timeout=1) as response:
            metadata = json.loads(response.read(65536))
        if not isinstance(metadata, dict) or str(metadata.get("issuer", "")).rstrip("/") != public_url.rstrip("/"):
            return False
    except urllib.error.HTTPError as error:
        error.close()
        return False
    except (OSError, ValueError):
        return False
    try:
        request = urllib.request.Request(
            local + "/mcp", method="POST",
            data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
            headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=1):
            return False
    except urllib.error.HTTPError as error:
        try:
            return error.code == 401 and bool(error.headers.get("WWW-Authenticate"))
        finally:
            error.close()
    except (OSError, ValueError):
        return False


def _assert_port_free() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        # Match the HTTP server's reuse policy: closed HTTP connections can
        # remain in TIME_WAIT after launchd deregisters the old process.
        # A live listening socket still rejects this exact-address bind.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", PORT))
        except OSError:
            raise RuntimeError("Loopback port 3201 is occupied; existing process preserved") from None


def _prepare_logs(expected: dict) -> None:
    logs = Path(expected["StandardOutPath"]).parent
    logs.mkdir(mode=0o700, exist_ok=True)
    _owned(logs, directory=True, private=True)
    for key in ("StandardOutPath", "StandardErrorPath"):
        path = Path(expected[key])
        if path.exists() or path.is_symlink():
            _owned(path, private=True)
        flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path), flags, 0o600)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or info.st_mode & 0o077):
                raise PermissionError("Remote service log must be an owner-only regular file")
        finally:
            os.close(fd)


def _write_new_plist(path: Path, expected: dict) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    _owned(path.parent, directory=True)
    fd, pending = tempfile.mkstemp(prefix=".remote-mcp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as destination:
            plistlib.dump(expected, destination)
            destination.flush()
            os.fsync(destination.fileno())
        # Atomic creation without replacing a concurrently created file/symlink.
        os.link(pending, path)
    finally:
        Path(pending).unlink()


def _wait_ready(public_url: str) -> None:
    for _ in range(POLL_COUNT):
        if _endpoint_ready(public_url):
            return
        time.sleep(POLL_INTERVAL)
    raise RuntimeError("Authenticated remote service did not become ready on loopback 3201")


def _stop_owned(plist: Path, expected: dict) -> None:
    """Stop only a verified job and wait until launchd has deregistered it."""
    job = _job(plist, expected)
    if job is not None:
        _launchctl("bootout", _target())
        for _ in range(POLL_COUNT):
            if _job(plist, expected) is None:
                break
            time.sleep(POLL_INTERVAL)
        else:
            raise RuntimeError("Could not confirm LaunchAgent deregistration; owned plist preserved")


def _rollback_start(plist: Path, expected: dict, *, created: bool) -> None:
    _stop_owned(plist, expected)
    if created and _read_owned_plist(plist, expected):
        plist.unlink()


def status(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Read configured/loaded status without starting, repairing or probing HTTP."""
    root, plist, expected = _layout(root, launch_agents)
    installed = _read_owned_plist(plist, expected)
    job = _job(plist, expected) if installed else None
    return {
        "status": ("running" if job and job["state"] == "running" else
                   "loaded" if job else "installed" if installed else "not_installed"),
        "label": LABEL, "plist": str(plist), "domain": "gui/" + str(os.getuid()),
        "listen": "127.0.0.1:3201", "run_at_login": installed,
        "pid": job["pid"] if job else None,
        "authenticated_endpoint_verified": False,
        "public_endpoint_published": False,
    }


def _ensure(root: Path, launch_agents: Path | None, *, require_installed: bool) -> dict:
    root, plist, expected = _layout(root, launch_agents)
    configured = check_oauth(root)
    installed = _read_owned_plist(plist, expected)
    if require_installed and not installed:
        raise FileNotFoundError("Install the owned remote LaunchAgent before --start")
    job = _job(plist, expected)
    if job is not None:
        if not installed:
            raise RuntimeError("Loaded LaunchAgent has no owned plist; no changes made")
        _wait_ready(configured["public_url"])
    else:
        _assert_port_free()
        _prepare_logs(expected)
        created = not installed
        if created:
            _write_new_plist(plist, expected)
        try:
            result = _launchctl("bootstrap", "gui/" + str(os.getuid()), str(plist))
            if result.returncode:
                raise RuntimeError("Remote LaunchAgent bootstrap/start failed")
            if _job(plist, expected) is None:
                raise RuntimeError("Remote LaunchAgent was not registered after start")
            _wait_ready(configured["public_url"])
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            try:
                _rollback_start(plist, expected, created=created)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                raise RuntimeError("Remote service start failed; rollback incomplete, owned plist preserved") from None
            raise RuntimeError("Remote service start failed; prior LaunchAgent state restored") from error
    return {
        "status": "running", "label": LABEL, "plist": str(plist),
        "domain": "gui/" + str(os.getuid()), "listen": "127.0.0.1:3201",
        "created_plist": not installed, "run_at_login": True,
        "authenticated_endpoint_verified": True,
        "github_oauth_login_verified": False,
        "public_endpoint_published": False,
    }


def ensure(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Idempotently install and start the owner-authorized remote LoginAgent."""
    return _ensure(root, launch_agents, require_installed=False)


def start(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Start/reuse an existing owned agent; never replace a running service."""
    return _ensure(root, launch_agents, require_installed=True)


class RestartError(RuntimeError):
    """A replacement start failed after a controlled stop.

    service_stopped=True confirms rollback deregistered the replacement. None
    means deregistration could not be confirmed. The owned plist is preserved.
    The caller owns current-pointer recovery, then may call start(root) only
    when its pre-operation status showed an owned loaded service.
    """
    def __init__(self, message: str, *, service_stopped: bool | None):
        super().__init__(message)
        self.service_stopped = service_stopped


def restart_if_installed(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Restart only a previously loaded owned agent after a release change.

    Absent/unloaded agents are unchanged. Validate OAuth before stopping. This
    function never changes the release pointer and always preserves the plist
    on failure, so the caller can restore the old pointer and call start(root).
    """
    root, plist, expected = _layout(root, launch_agents)
    if not _read_owned_plist(plist, expected):
        return {"status": "not_installed", "changed": False, "label": LABEL}
    if _job(plist, expected) is None:
        return {"status": "not_loaded", "changed": False, "label": LABEL}
    check_oauth(root)
    _stop_owned(plist, expected)
    try:
        result = start(root, launch_agents=launch_agents)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        try:
            _rollback_start(plist, expected, created=False)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            raise RestartError(
                "Remote service restart failed; deregistration unknown, owned plist preserved",
                service_stopped=None) from None
        raise RestartError(
            "Remote service restart failed; service stopped and owned plist preserved; "
            "restore the previous release pointer before start(root)",
            service_stopped=True) from error
    return {**result, "status": "restarted", "changed": True}


def remove_if_installed(root: Path = DEFAULT_ROOT, *, launch_agents: Path | None = None) -> dict:
    """Deregister the owned agent, then remove only its matching plist.

    Call before deleting installed releases. OAuth and log data are preserved;
    missing OAuth does not prevent removal. Any ownership/stop error preserves
    the plist and stops removal rather than touching an unknown service.
    """
    _, plist, expected = _layout(root, launch_agents)
    if not _read_owned_plist(plist, expected):
        return {"status": "not_installed", "changed": False, "label": LABEL}
    _stop_owned(plist, expected)
    if not _read_owned_plist(plist, expected):
        raise RuntimeError("Owned LaunchAgent plist disappeared during removal; inspect state manually")
    plist.unlink()
    return {"status": "removed", "changed": True, "label": LABEL,
            "run_at_login": False, "data_preserved": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--launch-agents", type=Path,
                        help="Owner-selected LaunchAgents directory (normally ~/Library/LaunchAgents)")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--install", action="store_true", help="Install and start owner login autostart")
    actions.add_argument("--start", action="store_true", help="Start an existing owned LaunchAgent")
    actions.add_argument("--status", action="store_true", help="Read-only launchd registration status")
    args = parser.parse_args(argv)
    operation = status if args.status else start if args.start else ensure
    print(json.dumps(operation(args.root, launch_agents=args.launch_agents), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print("Remote service setup failed:", type(error).__name__,
              str(error) if isinstance(error, RuntimeError) else "", file=sys.stderr)
        raise SystemExit(1)
