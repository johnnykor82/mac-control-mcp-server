"""Owner-owned user workspace, independent of Mac Control release directories.

The configuration stays under the product data root. No filesystem changes
occur on import or while resolving a path. Existing legacy data is never moved.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import tempfile

from .runtime_paths import DATA_ROOT, DEFAULT_DATA_ROOT

SUBDIRS = ("projects", "shared", "artifacts", "downloads", "scratch")
FILENAME = "config/workspace.json"


def _settings(data_root: Path) -> Path:
    return data_root / FILENAME


def _safe_path(value: str | Path, install_root: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path == Path("/") or ".." in path.parts:
        raise ValueError("workspace_root must be an absolute, non-root directory")
    if path.is_symlink():
        raise PermissionError("Workspace symlinks are not accepted")
    # macOS /var and /tmp may be system symlinks. Resolve parents to their
    # canonical location instead of rejecting the entire user home tree.
    path = path.resolve(strict=False)
    if install_root is not None:
        install_root = Path(os.path.abspath(install_root.expanduser())).resolve(strict=False)
        if path == install_root or path.is_relative_to(install_root):
            raise ValueError("User workspace cannot be inside the Mac Control installation")
    return path


def _owned_config(path: Path) -> dict | None:
    if path.is_symlink():
        raise PermissionError("Refusing symlink workspace config")
    if not path.exists():
        return None
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise PermissionError("Workspace config must be owner-only (0600)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or set(doc) != {"workspace_root"} or not isinstance(doc["workspace_root"], str):
        raise ValueError("Invalid workspace configuration")
    return doc


def legacy_has_user_data(data_root: Path) -> bool:
    legacy = Path(data_root) / "workspace"
    if not legacy.exists():
        return False
    if legacy.is_symlink() or not legacy.is_dir():
        raise PermissionError("Unsafe legacy workspace")
    # Ignore only an untouched prior installer directory skeleton.
    known = {"projects", "scratch", "artifacts", "downloads", "logs"}
    for entry in legacy.iterdir():
        if entry.name not in known or entry.is_symlink() or not entry.is_dir():
            return True
        if entry.name == "scratch":
            for sub in entry.iterdir():
                if sub.name not in ("tmp", "cache") or sub.is_symlink() or not sub.is_dir():
                    return True
                if any(sub.iterdir()):
                    return True
        elif any(entry.iterdir()):
            return True
    return False


def default_root(data_root: Path = DATA_ROOT) -> Path:
    # A preview/development session must not share the real user workspace.
    if data_root == DEFAULT_DATA_ROOT:
        return Path.home() / "AgentWorkspace-Dev"
    # Standard ~/MacControlMCP/data => ~/AgentWorkspace; custom installs
    # use a sibling outside their independent installation directory.
    return data_root.parent.parent / "AgentWorkspace"


def resolve(data_root: Path = DATA_ROOT, *, legacy_compat: bool = True) -> dict:
    data_root = Path(data_root).expanduser()
    doc = _owned_config(_settings(data_root))
    if doc is not None:
        path = _safe_path(doc["workspace_root"])
        return {"workspace_root":str(path), "source":"configured", "configured":True,
                "exists":path.is_dir(), "legacy":False}
    legacy = data_root / "workspace"
    if legacy_compat and legacy_has_user_data(data_root):
        return {"workspace_root":str(_safe_path(legacy)), "source":"legacy_preserved",
                "configured":False,"exists":True,"legacy":True}
    path = default_root(data_root)
    return {"workspace_root":str(_safe_path(path)), "source":"default",
            "configured":False,"exists":path.is_dir(),"legacy":False}


def workspace_root(data_root: Path = DATA_ROOT) -> Path:
    return Path(resolve(data_root)["workspace_root"])


def ensure(path: Path, *, create: bool = True) -> Path:
    path = _safe_path(path)
    if path.exists():
        if not path.is_dir():
            raise ValueError("Workspace root is not a directory")
        if path.stat().st_uid != os.getuid():
            raise PermissionError("Workspace root belongs to another user")
    elif create:
        if not path.parent.is_dir():
            raise FileNotFoundError("Workspace parent missing; mount external volume first")
        path.mkdir(mode=0o700)
    else:
        raise FileNotFoundError("Workspace missing or external disk unavailable")
    if create:
        for sub in SUBDIRS:
            folder = path / sub
            if folder.is_symlink():
                raise PermissionError("Workspace directory is symlink")
            folder.mkdir(mode=0o700, exist_ok=True)
    return path


def set_root(data_root: Path, root: Path, install_root: Path | None = None) -> dict:
    data_root = Path(data_root)
    path = _safe_path(root, install_root)
    config = _settings(data_root)
    _owned_config(config)
    ensure(path)
    if config.parent.is_symlink():
        raise PermissionError("Symlink config directory")
    config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if config.parent.stat().st_uid != os.getuid():
        raise PermissionError("Workspace config directory is not owner-owned")
    _owned_config(config)
    fd, name = tempfile.mkstemp(prefix=".workspace-", dir=config.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({"workspace_root":str(path)},out)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name,0o600)
        os.replace(name,config)
    finally:
        Path(name).unlink(missing_ok=True)
    return resolve(data_root)


def provision(data_root: Path, install_root: Path | None = None,
              requested: Path | None = None) -> dict:
    """Install only. Keep legacy workspace in place until a separate migration."""
    data_root = Path(data_root)
    if requested is not None:
        return set_root(data_root, requested, install_root)
    current = resolve(data_root)
    if current["legacy"]:
        return current
    if not current["configured"]:
        return set_root(data_root, default_root(data_root), install_root)
    ensure(Path(current["workspace_root"]),create=False)
    return current
