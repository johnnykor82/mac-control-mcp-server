#!/usr/bin/env python3
"""Versioned, non-destructive local-stdio installation for Mac Control.

This is NOT an installer for the public remote HTTPS/OAuth service.
Run --plan first. --install provisions Python packages and writes under
~/Library/Application Support/MacControl/MCPServer only (or --root).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    from scripts.runtime_tools import find_uv
except ModuleNotFoundError:
    # Direct invocation: python3 scripts/<name>.py.
    from runtime_tools import find_uv

SOURCE = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "MacControl" / "MCPServer"
COPY_DIRS = ("src", "scripts", "bin", "requirements")
COPY_FILES = ("README.md", "README.ru.md", "AGENT_INSTALL.md",
              "AGENT_WORKSPACE_POLICY.md", "SECURITY.md", "LICENSE",
              "docs/GITHUB_OAUTH_SETUP.md", "docs/REMOTE_ACCESS_GUIDE.md",
              "docs/INSTALL_CONTENTS.md", "docs/MCLOG.md", "docs/PUBLIC_RELEASE_GATES.md",
              "docs/RELEASE_NOTES_BETA.md", "docs/CHATBRIDGE_BROWSER_MIGRATION.md",
              "docs/CHATGPT_SETUP.ru.md")


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("timeout", 600)
    kwargs.setdefault("check", True)
    return subprocess.run(argv, text=True, **kwargs)


def source_id() -> str:
    # A change to any file copied by the installer creates a new release.
    digest = hashlib.sha256()
    for path in install_sources():
        digest.update(path.relative_to(SOURCE).as_posix().encode())
        digest.update(path.read_bytes())
    identity = "source"
    try:
        sha = run(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                  capture_output=True, timeout=10).stdout.strip()
        if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
            identity = sha[:12]
    except (OSError, subprocess.CalledProcessError):
        pass
    return identity + "-" + digest.hexdigest()[:12]


def paths(root: Path) -> dict[str, Path]:
    root = root.expanduser().resolve()
    return {"root": root, "data": root / "data", "releases": root / "releases",
            "current": root / "current", "release": root / "releases" / source_id()}


def install_sources() -> list[Path]:
    """Explicit release payload; never copy arbitrary local files or symlinks."""
    entries = (SOURCE / "scripts/install_manifest.txt").read_text().splitlines()
    paths = []
    for entry in entries:
        relative = Path(entry)
        if (not entry or relative.is_absolute() or ".." in relative.parts
                or not (relative.parts[0] in COPY_DIRS or entry in COPY_FILES)):
            raise RuntimeError("Invalid installation manifest entry")
        path = SOURCE / relative
        if not path.is_file() or any(parent.is_symlink() for parent in
                                     [path, *list(path.parents)[:len(relative.parts) - 1]]):
            raise RuntimeError("Missing or symlink installation source: " + entry)
        paths.append(path)
    return paths


def copy_source(release: Path) -> None:
    for source in install_sources():
        target = release / source.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def smoke(release: Path, data: Path) -> None:
    py = release / ".venv/bin/python"
    env = {**os.environ, "PYTHONPATH": str(release / "src") + os.pathsep + str(release),
           "MAC_CONTROL_DATA_ROOT": str(data), "PYTHONNOUSERSITE": "1"}
    statement = ("from mac_control.legacy_adapter import inspect_existing_handlers; "
                 "x=inspect_existing_handlers(); assert len(x) == 102; "
                 "from scripts.dev_mcp_server import make_server; "
                 "assert make_server(include_mutations=True)")
    run([str(py), "-P", "-B", "-c", statement], cwd=release,
        env=env, capture_output=True, timeout=60)


def require_chatbridge_browser_api() -> dict:
    """Read-only install prerequisite, never starts Chrome or ChatBridge."""
    gateway = os.getenv("MACCONTROL_CHATBRIDGE_URL", "http://127.0.0.1:8787").rstrip("/")
    req = urllib.request.Request(gateway + "/v1/browser/capabilities", headers={
        "Accept": "application/json",
        **({"Authorization": "Bearer " + os.environ["MACCONTROL_CHATBRIDGE_API_KEY"]}
           if os.getenv("MACCONTROL_CHATBRIDGE_API_KEY") else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            info = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, TimeoutError) as exc:
        raise RuntimeError("ChatBridge Browser API v1 unavailable; install/update ChatBridge first") from exc
    if not isinstance(info, dict):
        raise RuntimeError("ChatBridge capabilities are invalid")
    features = info.get("capabilities", info)
    modes = features.get("modes", []) if isinstance(features, dict) else []
    if not isinstance(features, dict) or not (features.get("background") is True or "background" in modes):
        raise RuntimeError("ChatBridge does not advertise background browser support")
    return {"provider": "chatbridge", "background": True}


def _verified_release(root: Path, candidate: Path) -> Path:
    releases = root / "releases"
    if not candidate.is_dir() or candidate.is_symlink() or candidate.parent != releases:
        raise RuntimeError("Refusing non-owned or missing release directory")
    if not (candidate / "bin/mac-control-stdio-mcp.sh").is_file():
        raise RuntimeError("Release is not a Mac Control MCP Server installation")
    return candidate


def _atomic_pointer(root: Path, name: str, target: Path) -> None:
    pointer = root / name
    if pointer.exists() and not pointer.is_symlink():
        raise RuntimeError("Refusing to replace non-symlink " + name)
    tmp = root / (".pending-" + name + "-" + os.urandom(6).hex())
    os.symlink(target, tmp)
    os.replace(tmp, pointer)


def _remote_service_module():
    try:
        from scripts import setup_remote_service
    except ModuleNotFoundError:
        import setup_remote_service
    return setup_remote_service


def _watcher_service_module():
    try:
        from scripts import setup_watcher_service
    except ModuleNotFoundError:
        import setup_watcher_service
    return setup_watcher_service


def _watcher_plist_exists() -> bool:
    path = Path.home() / "Library/LaunchAgents/org.maccontrol.mcpserver.watcher.plist"
    return path.exists() or path.is_symlink()


def _watcher_enabled(root: Path, target: Path) -> bool:
    flags = root / "data/feature_flags.json"
    if flags.is_symlink():
        raise RuntimeError("Refusing symlink feature flags")
    settings = json.loads(flags.read_text()) if flags.is_file() else {}
    return (isinstance(settings, dict) and settings.get("watcher") is True
            and (target / "src/mac_control/watcher_runtime/__main__.py").is_file())


def _remote_plist_exists() -> bool:
    path = Path.home() / "Library/LaunchAgents/org.maccontrol.mcpserver.remote.plist"
    return path.exists() or path.is_symlink()


def _lock_directory(path: Path, *, private: bool = False) -> None:
    if path.is_symlink():
        raise RuntimeError("Lifecycle lock directory cannot be a symlink")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.lstat()
    forbidden = 0o077 if private else 0o022
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & forbidden):
        raise RuntimeError("Lifecycle lock directory has unsafe ownership or permissions")


@contextmanager
def _lifecycle_lock(root: Path, *, timeout: float = 15):
    """Serialize provisioning, pointer recovery and removal for this install.

    The persistent lock is never unlinked: waiters must continue to lock the
    same inode even after uninstall preserves the data directory.
    """
    if sys.platform != "darwin" or os.geteuid() == 0:
        raise RuntimeError("Installation lifecycle requires a non-root macOS user")
    root = root.expanduser().absolute()
    _lock_directory(root)
    root = root.resolve()
    _lock_directory(root / "data")
    _lock_directory(root / "data/run", private=True)
    path = root / "data/run/install-lifecycle.lock"
    if path.is_symlink():
        raise RuntimeError("Lifecycle lock file cannot be a symlink")
    flags = os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise RuntimeError("Lifecycle lock must be an owner-only regular file with one link")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise RuntimeError("Another installation lifecycle operation is busy; retry after it finishes") from None
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        yield root
    finally:
        # Closing this non-inherited descriptor releases flock on every exit,
        # including an interrupt during the protected operation.
        os.close(fd)


def _activate_release(root: Path, target: Path) -> None:
    """Switch release and restart only an existing verified remote service."""
    with _lifecycle_lock(root) as locked_root:
        _activate_release_locked(locked_root, target)


def _activate_release_locked(root: Path, target: Path) -> None:
    # A concurrent uninstall may have removed a previously checked target
    # before this operation acquired the lifecycle lock.
    target = _verified_release(root, target)
    current, previous = root / "current", root / "previous"
    active = _verified_release(root, current.resolve()) if current.is_symlink() else None
    if active == target:
        if _watcher_enabled(root, target):
            _watcher_service_module().ensure(root)
        return
    saved_previous = _verified_release(root, previous.resolve()) if previous.is_symlink() else None
    service = _remote_service_module() if active is not None and _remote_plist_exists() else None
    remote_loaded = bool(service and service.status(root)["status"] in ("running", "loaded"))
    watcher = _watcher_service_module() if active is not None and _watcher_plist_exists() else None
    watcher_loaded = bool(watcher and watcher.status(root)["status"] in ("running", "loaded"))
    target_watcher = _watcher_enabled(root, target)
    if watcher_loaded:
        watcher.stop_if_installed(root)
    remote_restarted = False
    try:
        if active is not None:
            _atomic_pointer(root, "previous", active)
        _atomic_pointer(root, "current", target)
        if remote_loaded:
            service.restart_if_installed(root)
            remote_restarted = True
        if target_watcher:
            _watcher_service_module().ensure(root)
        elif watcher:
            watcher.remove_if_installed(root)
    except BaseException as error:
        if active is not None:
            _atomic_pointer(root, "current", active)
        elif current.is_symlink():
            current.unlink()
        if saved_previous is None:
            if previous.is_symlink():
                previous.unlink()
        else:
            _atomic_pointer(root, "previous", saved_previous)
        restore_errors = []
        try:
            if remote_restarted:
                service.restart_if_installed(root)
            elif (remote_loaded and isinstance(error, service.RestartError)
                  and error.service_stopped is True):
                service.start(root)
        except Exception as restore_error:
            restore_errors.append(restore_error)
        try:
            if watcher and watcher_loaded:
                # A failed/interrupted replacement may still be running.
                watcher.stop_if_installed(root)
                watcher.start(root)
            elif target_watcher and active is not None:
                _watcher_service_module().remove_if_installed(root)
        except Exception as restore_error:
            restore_errors.append(restore_error)
        if restore_errors:
            raise RuntimeError("Previous release restored, but an owned service could not be restarted") from restore_errors[0]
        raise


def rollback(root: Path) -> dict:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError("No previous Mac Control MCP Server release available")
    with _lifecycle_lock(root) as root:
        pointer = root / "previous"
        if not pointer.is_symlink():
            raise RuntimeError("No previous Mac Control MCP Server release available")
        target = _verified_release(root, pointer.resolve())
        data = root / "data"
        smoke(target, data)
        _activate_release_locked(root, target)
        return {"status": "rolled_back", "active": str(target),
                "data_preserved": True, "stable_modified": False}


def uninstall(root: Path) -> dict:
    root = root.expanduser().resolve()
    marker = root / ".mac-control-installer-owned"
    if not marker.is_file() or marker.is_symlink():
        raise RuntimeError("Install ownership marker missing; refuse uninstall")
    with _lifecycle_lock(root) as locked_root:
        return _uninstall_locked(locked_root)


def _uninstall_locked(root: Path) -> dict:
    marker = root / ".mac-control-installer-owned"
    if not marker.is_file() or marker.is_symlink():
        raise RuntimeError("Install ownership marker missing; refuse uninstall")
    current = root / "current"
    previous = root / "previous"
    for link in (current, previous):
        if link.exists() and not link.is_symlink():
            raise RuntimeError("Non-symlink activation pointer; refusing uninstall")
    releases = root / "releases"
    if not releases.is_dir() or releases.is_symlink():
        raise RuntimeError("Mac Control MCP Server release folder not valid")
    targets = list(releases.iterdir())
    for target in targets:
        _verified_release(root, target)
    ownership = root / "data/gui-owned.json"
    app = None
    if ownership.exists() or ownership.is_symlink():
        if ownership.is_symlink():
            raise RuntimeError("Untrusted Mac Control MCP Server GUI ownership record")
        owned = json.loads(ownership.read_text())
        app = Path.home() / "Applications/MacControlMCPServer.app"
        if owned != {"app": str(app), "bundle": "org.maccontrol.mcpserver.gui",
                     "installed_by": str(root)}:
            raise RuntimeError("GUI ownership record is inconsistent")
        if app.exists() or app.is_symlink():
            if app.is_symlink() or not app.is_dir():
                raise RuntimeError("Mac Control MCP Server GUI app path is unsafe")
            with (app / "Contents/Info.plist").open("rb") as fp:
                import plistlib
                if plistlib.load(fp).get("CFBundleIdentifier") != "org.maccontrol.mcpserver.gui":
                    raise RuntimeError("Refusing to remove unrelated GUI app")
    try:
        from scripts.setup_network import assert_public_route_safe_for_uninstall
    except ModuleNotFoundError:
        from setup_network import assert_public_route_safe_for_uninstall
    assert_public_route_safe_for_uninstall(root, known_remote_service=_remote_plist_exists())
    if _watcher_plist_exists():
        _watcher_service_module().remove_if_installed(root)
    if _remote_plist_exists():
        _remote_service_module().remove_if_installed(root)
    if app is not None and app.exists():
        # Keep a recoverable backup in the user's preserved data folder.
        backup = root / "data/backups" / ("gui-uninstalled-" + os.urandom(6).hex() + ".app")
        backup.parent.mkdir(parents=True, exist_ok=True)
        app.rename(backup)
    if ownership.exists():
        ownership.unlink()
    for link in (current, previous):
        link.unlink(missing_ok=True)
    for target in targets:
        shutil.rmtree(target)
    releases.rmdir()
    marker.unlink()
    return {"status": "uninstalled", "removed_releases": len(targets),
            "data_preserved": str(root / "data"), "stable_modified": False}


def _save_chatbridge_key(data: Path) -> None:
    """Persist only an explicitly supplied key for the owned background daemon."""
    key = os.environ.get("MACCONTROL_CHATBRIDGE_API_KEY", "").strip()
    if not key:
        return
    if len(key.encode()) > 4096 or "\n" in key or "\r" in key:
        raise ValueError("Invalid ChatBridge key format")
    path = data / "chatbridge_api_key.txt"
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise PermissionError("Unsafe ChatBridge credential file")
    temporary = data / (".chatbridge-key-" + os.urandom(6).hex())
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w") as destination:
            destination.write(key + "\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install(root: Path, with_chatbridge: bool = True, with_gui: bool | None = None,
            chatbridge_source: Path | None = None,
            chatbridge_url: str | None = None, with_watcher: bool = True) -> dict:
    with _lifecycle_lock(root) as locked_root:
        return _install_locked(locked_root, with_chatbridge, with_gui,
                               chatbridge_source, chatbridge_url, with_watcher)


def _install_locked(root: Path, with_chatbridge: bool = True, with_gui: bool | None = None,
                    chatbridge_source: Path | None = None,
                    chatbridge_url: str | None = None, with_watcher: bool = True) -> dict:
    info = paths(root)
    if sys.platform != "darwin":
        raise RuntimeError("Install is supported on macOS only")
    provider_url = chatbridge_url or os.environ.get("MACCONTROL_CHATBRIDGE_URL", "http://127.0.0.1:8787")
    if with_chatbridge:
        try:
            from scripts.setup_chatbridge_dependency import ensure
        except ModuleNotFoundError:
            from setup_chatbridge_dependency import ensure
        ensure(provider_url, chatbridge_source)
    elif chatbridge_source is not None or chatbridge_url is not None:
        raise RuntimeError("ChatBridge options cannot be used with --without-chatbridge")
    uv = find_uv()
    if not uv:
        raise RuntimeError("uv missing: install uv from https://docs.astral.sh/uv/getting-started/installation/")
    dest = info["release"]
    data = info["data"]
    # Do not modify any Stable or MCP-Dev launchd service.
    info["releases"].mkdir(parents=True, exist_ok=True, mode=0o700)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ("workspace", "run", "backups", "workspace/projects",
                 "workspace/scratch", "workspace/scratch/tmp", "workspace/artifacts",
                 "workspace/downloads", "workspace/logs", "logs"):
        folder = data / name
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.chmod(0o700)
    for path in (info["releases"], data, data / "run"):
        path.chmod(0o700)
    created = False
    if not dest.exists():
        dest.mkdir(mode=0o700)
        created = True
        try:
            copy_source(dest)
            run([uv, "venv", "--python", "3.13", str(dest / ".venv")], timeout=180)
            run([uv, "pip", "install", "--python", str(dest / ".venv/bin/python"),
                 "-r", str(dest / "requirements/dev-frozen.txt")], timeout=600)
            smoke(dest, data)
        except BaseException:
            shutil.rmtree(dest)
            raise
    else:
        smoke(dest, data)
    if with_chatbridge:
        _save_chatbridge_key(data)
        # ChatBridge is an independent prerequisite and the ONLY browser owner.
        # Setup uses ChatBridge's own installer; its lifecycle remains independent.
        flags = data / "feature_flags.json"
        original = json.loads(flags.read_text()) if flags.is_file() else {}
        if not isinstance(original, dict):
            raise ValueError("Invalid feature flags")
        original["background_browser"] = True
        original["watcher"] = with_watcher
        connection = data / "chatbridge_connection.txt"
        if connection.is_symlink():
            raise RuntimeError("Refusing symlink ChatBridge connection file")
        new_connection = connection.with_suffix(".tmp")
        new_connection.write_text(provider_url.rstrip("/") + "\n")
        new_connection.chmod(0o600)
        new_connection.replace(connection)
        temp = flags.with_name("feature_flags.tmp")
        temp.write_text(json.dumps(original, indent=2) + "\n")
        temp.chmod(0o600)
        temp.replace(flags)
    gui_status = "skipped"
    flags = data / "feature_flags.json"
    if flags.is_symlink():
        raise RuntimeError("Refusing symlink feature flags")
    old_flags = json.loads(flags.read_text()) if flags.is_file() else {}
    if not isinstance(old_flags, dict):
        raise ValueError("Invalid feature flags")
    preserve_gui = with_gui is False and old_flags.get("native_gui") is True
    if with_gui is not False or preserve_gui:
        try:
            from scripts.build_mac_control_gui import verify_owned
            from scripts.setup_gui_dependency import ensure as ensure_gui
        except ModuleNotFoundError:
            from build_mac_control_gui import verify_owned
            from setup_gui_dependency import ensure as ensure_gui
        existing_gui = verify_owned(info["root"])
        if preserve_gui and not existing_gui:
            raise RuntimeError("Enabled GUI helper is missing; retry with --with-gui to restore it")
        # Reuse the app by default; pinned clipboard binaries belong to every
        # release, including updates preserving a previously enabled helper.
        gui_status = ensure_gui(info["root"], dest, replace=with_gui is True)["native_gui"]
        old_flags["native_gui"] = True
        temp = flags.with_suffix(".tmp")
        temp.write_text(json.dumps(old_flags, indent=2) + "\n")
        temp.chmod(0o600)
        temp.replace(flags)
        print("GUI helper " + gui_status + ". Owner must grant Accessibility and Screen Recording "
              "in System Settings → Privacy & Security for ~/Applications/MacControlMCPServer.app. "
              "Installation cannot grant TCC permissions; interactive setup starts the helper "
              "and requests owner approval.", file=sys.stderr)
    if not with_watcher:
        old_flags["watcher"] = False
        temp = flags.with_suffix(".tmp")
        temp.write_text(json.dumps(old_flags, indent=2) + "\n")
        temp.chmod(0o600)
        temp.replace(flags)
        if _watcher_plist_exists():
            _watcher_service_module().remove_if_installed(root)
    marker = info["root"] / ".mac-control-installer-owned"
    if marker.is_symlink():
        raise RuntimeError("Unsafe ownership marker")
    if not marker.exists():
        marker.write_text("Mac Control MCP Server installation; data is not removed by uninstall.\n")
        marker.chmod(0o600)
    # Service provisioning is part of activation, so failed Watcher startup
    # restores the previous pointer and any previously running remote service.
    _verified_release(info["root"], dest)
    _activate_release_locked(info["root"], dest)
    watcher_status = (_watcher_service_module().status(root)["status"]
                      if _watcher_enabled(root, dest) else "disabled")
    pointer = info["current"]
    return {"status": "installed", "watcher": watcher_status, "release": str(dest),
            "current": str(pointer), "data": str(data),
            "created_new_release": created, "browser_provider": "chatbridge" if with_chatbridge else "existing_configuration_preserved",
            "entrypoint": str(pointer / "bin/mac-control-stdio-mcp.sh"),
            "native_gui": gui_status,
            "remote_https_oauth": "EXPERIMENTAL_UNVERIFIED"}


def status(root: Path) -> dict:
    info = paths(root)
    pointer = info["current"]
    active = pointer.resolve() if pointer.is_symlink() else None
    return {"status": "installed" if active and active.is_dir() else "not_installed",
            "active": str(active) if active else None,
            "expected_release": str(info["release"]),
            "data": str(info["data"]), "remote_https_oauth": "EXPERIMENTAL_UNVERIFIED"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="Install root; defaults to owner-only MCP Server data directory")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true")
    action.add_argument("--status", action="store_true")
    action.add_argument("--install", action="store_true")
    action.add_argument("--setup", action="store_true", help="Resume interactive permissions and ChatGPT connection setup")
    action.add_argument("--update", action="store_true", help="Install new version, preserve previous for rollback")
    action.add_argument("--rollback", action="store_true", help="Restore previous verified release")
    action.add_argument("--uninstall", action="store_true", help="Remove installed binaries only; retain data")
    action.add_argument("--github-oauth-guide", action="store_true", help="Show GitHub OAuth App registration steps")
    action.add_argument("--setup-github-oauth", action="store_true", help="Owner-guided GitHub OAuth registration and credential setup")
    action.add_argument("--github-oauth-check", action="store_true", help="Validate configured GitHub OAuth without showing credentials")
    action.add_argument("--github-oauth-probe", action="store_true", help="Check public HTTPS OAuth discovery and authentication challenge")
    action.add_argument("--github-oauth-login-test", action="store_true", help="Open GitHub OAuth consent and test real authenticated MCP via browser")
    action.add_argument("--network-diagnose", action="store_true", help="Read-only check of IP and Tailscale status")
    action.add_argument("--network-guide", action="store_true", help="Tailscale Funnel instructions for no public IP")
    action.add_argument("--enable-funnel", action="store_true", help="After owner confirmation, expose authenticated 127.0.0.1:3201 via Funnel")
    parser.add_argument("--public-url", help="Public HTTPS origin, e.g. https://your-mac.example.com")
    parser.add_argument("--network", action="store_true", help="Allow external public IP echo lookups for --network-diagnose")
    parser.add_argument("--github-login", help="GitHub username to authorize (or auto-detect logged-in gh CLI)")
    gui = parser.add_mutually_exclusive_group()
    gui.add_argument("--with-gui", dest="with_gui", action="store_true",
                     help="Explicitly install or replace the owner-managed GUI helper from the pinned release")
    gui.add_argument("--without-gui", dest="with_gui", action="store_false",
                     help="Skip GUI provisioning; preserve any existing helper")
    parser.set_defaults(with_gui=None)
    browser = parser.add_mutually_exclusive_group()
    browser.add_argument("--with-chatbridge", dest="with_chatbridge", action="store_true",
                         help="Use ChatBridge (default); reuse or install pinned release")
    browser.add_argument("--without-chatbridge", dest="with_chatbridge", action="store_false",
                         help="Skip ChatBridge setup; preserve any existing browser configuration")
    parser.set_defaults(with_chatbridge=True)
    parser.add_argument("--chatbridge-source", type=Path,
                        help="Reviewed standalone ChatBridge checkout; enables installing dependency when absent")
    parser.add_argument("--chatbridge-url",
                        help="Existing local ChatBridge HTTP origin (default http://127.0.0.1:8787)")
    parser.add_argument("--without-watcher", dest="with_watcher", action="store_false",
                        help="Skip Watcher provisioning and stop its owned service if present")
    parser.set_defaults(with_watcher=True)
    parser.add_argument("--language", choices=("ru", "en"), help="Choose setup language")
    args = parser.parse_args()
    selected_language = args.language
    if args.install and sys.stdin.isatty() and selected_language is None:
        try:
            from scripts.setup_language import choose_language
        except ModuleNotFoundError:
            from setup_language import choose_language
        selected_language = choose_language()
    info = paths(args.root)
    if args.setup:
        command = [sys.executable, str(SOURCE / "scripts/guided_setup.py"), "--root", str(info["root"])]
        if args.with_gui is False:
            command.append("--without-gui")
        if selected_language:
            command += ["--language", selected_language]
        return run(command, timeout=None, check=False).returncode
    if args.network_guide or args.network_diagnose or args.enable_funnel:
        choice = ("--guide" if args.network_guide
                  else "--enable-funnel" if args.enable_funnel else "--diagnose")
        command = [sys.executable, str(SOURCE / "scripts/setup_network.py"),
                   "--root", str(info["root"]), choice]
        if args.network and args.network_diagnose:
            command.append("--network")
        if selected_language:
            command += ["--language", selected_language]
        return run(command, timeout=None if args.enable_funnel else 110).returncode
    if args.github_oauth_login_test:
        launcher = info["current"] / ".venv/bin/python"
        if not launcher.is_file():
            raise RuntimeError("Install Mac Control MCP Server before running OAuth login test")
        return run([str(launcher), str(SOURCE / "scripts/test_github_oauth_login.py"),
                    "--root", str(info["root"])], timeout=None).returncode
    if args.github_oauth_guide or args.setup_github_oauth or args.github_oauth_check or args.github_oauth_probe:
        subcommand = "--guide" if args.github_oauth_guide else (
            "--configure" if args.setup_github_oauth else (
                "--probe" if args.github_oauth_probe else "--check"))
        command = [sys.executable, str(SOURCE / "scripts/setup_github_oauth.py"),
                   "--root", str(info["root"]), subcommand]
        if args.public_url:
            command += ["--public-url", args.public_url]
        if args.github_login:
            command += ["--github-login", args.github_login]
        if selected_language:
            command += ["--language", selected_language]
        return run(command, timeout=None if args.setup_github_oauth else 120).returncode
    if args.plan:
        result = {"status": "plan_only", "root": str(info["root"]),
                  "release": str(info["release"]),
                  "entrypoint": str(info["current"] / "bin/mac-control-stdio-mcp.sh"),
                  "installs_packages": True, "network_required": True,
                  "watcher": "install_with_chatbridge" if args.with_watcher and args.with_chatbridge else "skip",
                  "chatbridge": "reuse_or_install_pinned" if args.with_chatbridge else "skip_setup_preserve_existing",
                  "existing_stable_modified": False,
                  "native_background_gui": ("skip_preserve_existing" if args.with_gui is False else
                                            "explicit_prebuilt_install" if args.with_gui is True else
                                            "install_if_missing_reuse_owned"),
                  "gui_tcc": "interactive setup requests Accessibility and Screen Recording; owner grants them",
                  "guided_setup": "interactive_after_install; noninteractive installation reports pending steps",
                  "remote_https_oauth": "EXPERIMENTAL_UNVERIFIED"}
    elif args.status:
        result = status(args.root)
    elif args.rollback:
        result = rollback(args.root)
    elif args.uninstall:
        result = uninstall(args.root)
    else:
        result = install(args.root, args.with_chatbridge, args.with_gui,
                         args.chatbridge_source, args.chatbridge_url, with_watcher=args.with_watcher)
    if args.install and result.get("status") == "installed":
        if not sys.stdin.isatty():
            result["guided_setup"] = {"status": "pending_owner_interaction",
                                      "next": ("Run --setup --without-gui in an interactive Terminal"
                                               if args.with_gui is False else
                                               "Run --setup in an interactive Terminal")}
        else:
            print(json.dumps(result, indent=2), flush=True)
            command = [sys.executable, str(SOURCE / "scripts/guided_setup.py"), "--root", str(info["root"])]
            if args.with_gui is False:
                command.append("--without-gui")
            if selected_language:
                command += ["--language", selected_language]
            return run(command, timeout=None, check=False).returncode
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as error:
        print("Mac Control MCP Server local installation failed:", str(error), file=sys.stderr)
        sys.exit(1)
