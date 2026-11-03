"""Owner-scoped command registration for maccontrol and mclog without sudo."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import stat

START = "# >>> Mac Control MCP Server PATH >>>"
END = "# <<< Mac Control MCP Server PATH <<<"
PROFILE_BLOCK = (
    START + "\n"
    'case ":$PATH:" in *":$HOME/.local/bin:"*) ;; '
    '*) export PATH="$HOME/.local/bin:$PATH";; esac\n'
    + END + "\n"
)


def wrapper(root: Path, command: str) -> str:
    if command not in ("mclog", "maccontrol"):
        raise ValueError("Unknown CLI command")
    target = root / ("current/bin/mclog" if command == "mclog" else "bin/maccontrol")
    return (
        "#!/bin/sh\n"
        "# Managed by Mac Control MCP Server (CLI registration)\n"
        "exec " + shlex.quote(str(target)) + ' "$@"\n'
    )


def _regular_owner_file(path: Path) -> bool:
    metadata = path.lstat()
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and metadata.st_nlink == 1
        and not bool(metadata.st_mode & 0o022)
    )


def _ensure_wrapper(path: Path, expected: str) -> str:
    if path.exists() or path.is_symlink():
        if not _regular_owner_file(path):
            return "conflict"
        if path.read_text(encoding="utf-8") != expected:
            return "conflict"
        path.chmod(0o700)
        return "already_registered"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.parent.stat().st_uid != os.getuid():
        return "conflict"
    # Exclusive creation: never overwrite another tool's command.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o700)
    except FileExistsError:
        return "conflict"
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(expected)
    return "registered"


def _ensure_profile(user_home: Path, user_bin: Path, environ: dict) -> str:
    if str(user_bin) in environ.get("PATH", "").split(os.pathsep):
        return "already_in_path"
    profile = user_home / ".zprofile"
    if profile.exists() or profile.is_symlink():
        if not _regular_owner_file(profile):
            return "profile_conflict"
        existing = profile.read_text(encoding="utf-8")
        if START in existing or END in existing:
            return "already_configured" if PROFILE_BLOCK in existing else "profile_conflict"
    else:
        existing = ""
    suffix = "" if not existing or existing.endswith("\n") else "\n"
    # A normal user's .zprofile is their owned startup script. Never follow a symlink.
    flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    with os.fdopen(os.open(profile, flags, 0o600), "w", encoding="utf-8") as stream:
        stream.write(suffix + PROFILE_BLOCK)
    return "added_to_zprofile"


def register(root: Path, *, home: Path | None = None,
             environ: dict | None = None) -> dict:
    root = root.expanduser().resolve()
    home = (home or Path.home()).expanduser().resolve()
    user_bin = home / ".local/bin"
    status = {}
    # root/bin/mclog is the explicit fallback even when ~/.local/bin conflicts.
    status["root_mclog"] = _ensure_wrapper(root / "bin/mclog", wrapper(root, "mclog"))
    if user_bin.is_symlink() or (user_bin.exists() and (not user_bin.is_dir()
            or user_bin.stat().st_uid != os.getuid())):
        return {**status, "mclog": "conflict", "maccontrol": "conflict",
                "path": "user_bin_conflict"}
    for name in ("mclog", "maccontrol"):
        status[name] = _ensure_wrapper(user_bin / name, wrapper(root, name))
    status["path"] = _ensure_profile(home, user_bin, environ or os.environ)
    if status["mclog"] == "conflict":
        status["mclog_resolution"] = resolve_mclog_conflict(root, home=home)
    return status



def resolve_mclog_conflict(root: Path, *, home: Path | None = None,
                           approved: bool = False) -> dict:
    """Move a legacy launcher only after explicit owner approval."""
    root = root.expanduser().resolve()
    home = (home or Path.home()).expanduser().resolve()
    current = home / ".local/bin/mclog"
    legacy = home / ".local/bin/mclog-legacy"
    expected = wrapper(root, "mclog")
    if not (current.exists() or current.is_symlink()):
        return {"status": "no_conflict", "new": str(current)}
    if current.is_file() and not current.is_symlink():
        if _regular_owner_file(current) and current.read_text(encoding="utf-8") == expected:
            return {"status": "already_registered", "new": str(current)}
    if not approved:
        return {"status": "approval_required", "old": str(current),
                "preserve_as": str(legacy), "new": str(current)}
    if (legacy.exists() or legacy.is_symlink()
            or current.lstat().st_uid != os.getuid()
            or not (current.is_symlink() or _regular_owner_file(current))):
        return {"status": "conflict", "reason": "unsafe_existing_launcher_or_backup"}
    current.rename(legacy)
    try:
        if _ensure_wrapper(current, expected) != "registered":
            raise RuntimeError("Could not register new mclog")
    except BaseException:
        if not current.exists() and not current.is_symlink():
            legacy.rename(current)
        raise
    return {"status": "migrated", "old": str(legacy), "new": str(current)}


def unregister(root: Path, *, home: Path | None = None) -> dict:
    root = root.expanduser().resolve()
    home = (home or Path.home()).expanduser().resolve()
    status = {}
    for name, path in (
        ("mclog", home / ".local/bin/mclog"),
        ("maccontrol", home / ".local/bin/maccontrol"),
        ("root_mclog", root / "bin/mclog"),
    ):
        expected = wrapper(root, "mclog" if name == "root_mclog" else name)
        if path.is_file() and not path.is_symlink() and _regular_owner_file(path) and (
                path.read_text(encoding="utf-8") == expected):
            path.unlink()
            status[name] = "removed"
        else:
            status[name] = "preserved"
    profile = home / ".zprofile"
    if profile.is_file() and not profile.is_symlink() and _regular_owner_file(profile):
        content = profile.read_text(encoding="utf-8")
        if PROFILE_BLOCK in content:
            profile.write_text(content.replace(PROFILE_BLOCK, "", 1), encoding="utf-8")
            status["path"] = "removed_from_zprofile"
        else:
            status["path"] = "preserved"
    return status
