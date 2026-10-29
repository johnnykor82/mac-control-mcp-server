"""Controlled filesystem tools for explicitly approved project roots."""
from ..runtime_paths import DATA_ROOT
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import stat
import tempfile
import time
from pathlib import Path

ROOT = DATA_ROOT
WORKSPACE = ROOT / "workspace"
TRUSTED_CONFIG = ROOT / "allowed_projects.json"
RECOVERY = ROOT / "backups" / "fs_recovery"
DENY = {".git", ".ssh", ".aws", ".gnupg", ".venv", "__pycache__", "node_modules", ".DS_Store"}
DENY_PREFIX = (".env", "id_rsa", "id_ed25519", ".npmrc", ".netrc", ".pypirc")
MAX_FILE = 512 * 1024

def roots():
    result = {"workspace": WORKSPACE}
    if TRUSTED_CONFIG.is_file() and not TRUSTED_CONFIG.is_symlink():
        settings = json.loads(TRUSTED_CONFIG.read_text())
        projects = settings.get("projects", {})
        if not isinstance(projects, dict):
            raise ValueError("Invalid trusted projects config")
        for name, value in projects.items():
            if (not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,31}", name)
                or name == "workspace" or not isinstance(value, str)):
                continue
            root = Path(value).expanduser()
            if root.is_dir() and not root.is_symlink():
                result[name] = root.resolve()
    return result

def target_for(project: str, path: str, require_file=False):
    allowed = roots()
    if project not in allowed:
        raise ValueError("Project is not enabled; available: " + ", ".join(sorted(allowed)))
    base = allowed[project].resolve()
    p = Path(path)
    if p.is_absolute() or ".." in p.parts or not path or "\x00" in path:
        raise ValueError("Relative non-traversing path required")
    for part in p.parts:
        if part in DENY or any(part.startswith(x) for x in DENY_PREFIX):
            raise PermissionError("Blocked sensitive or generated path")
        if part.startswith(".") and part != ".github" and part != ".":
            raise PermissionError("Hidden paths are not exposed")
    current = base
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise PermissionError("Symlinks are not supported")
    full = current.resolve()
    if full != base and not full.is_relative_to(base):
        raise PermissionError("Path outside approved root")
    if require_file and (full == base or not full.is_file()):
        raise FileNotFoundError(path)
    return base, full

def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()

def read_bytes(path):
    if path.stat().st_size > MAX_FILE:
        raise ValueError("File too large (512 KiB limit)")
    return path.read_bytes()

def backup_original(path, data):
    RECOVERY.mkdir(mode=0o700, parents=True, exist_ok=True)
    RECOVERY.chmod(0o700)
    backup = RECOVERY / (f"{time.time_ns()}-{secrets.token_hex(5)}.bak")
    backup.write_bytes(data)
    backup.chmod(0o600)
    return backup.name

def atomic_write(path, data, original=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    prior_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    saved = backup_original(path, original) if original is not None else None
    fd, temp = tempfile.mkstemp(prefix=".mcptmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, prior_mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return saved

def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def project_roots() -> dict:
        """List directory roots approved by the Mac owner. New roots require local configuration."""
        return {"projects": {name: str(path) for name, path in roots().items()},
                "default_write_project": "workspace", "workspace": str(WORKSPACE),
                "agent_write_policy": "Default all agent-created work to workspace; external writes only by specific owner request or necessary system integration.",
                "config": str(TRUSTED_CONFIG), "config_writable_via_mcp": False}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def fs_list(project: str = "workspace", path: str = ".", limit: int = 100) -> dict:
        """List non-sensitive directory entries in one approved project."""
        base, directory = target_for(project, path)
        if not directory.is_dir():
            raise NotADirectoryError(path)
        limit = max(1, min(limit, 300))
        items = []
        for entry in sorted(directory.iterdir(), key=lambda f: f.name):
            if len(items) >= limit:
                break
            try:
                target_for(project, str(entry.relative_to(base)))
            except (ValueError, PermissionError):
                continue
            if entry.is_symlink():
                continue
            items.append({"name": entry.name, "directory": entry.is_dir(),
                          "bytes": entry.stat().st_size if entry.is_file() else None})
        return {"project": project, "path": path, "entries": items}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def fs_stat(project: str, path: str, include_media: bool = False) -> dict:
        """File metadata; include_media opt-in returns a scoped binary media reference.

        Large files are never placed directly into the tool's JSON response.
        The existing MCP bridge validates target media_root before reading.
        """
        _, file = target_for(project, path)
        st = file.stat()
        result = {"path": path, "directory": file.is_dir(), "bytes": st.st_size,
                  "modified_epoch": st.st_mtime, "mode": oct(stat.S_IMODE(st.st_mode))}
        if file.is_file() and st.st_size <= MAX_FILE:
            result["sha256"] = hash_bytes(file.read_bytes())
        if include_media:
            if type(include_media) is not bool or not file.is_file() or file.is_symlink():
                raise ValueError("include_media requires a regular approved file")
            kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            result["media_file"] = {"path":str(file), "mime_type":kind,
                                    "name":file.name}
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def fs_read(project: str, path: str, start_line: int = 1, max_lines: int = 250) -> dict:
        """Read numbered lines from a small UTF-8 file in an approved project."""
        _, file = target_for(project, path, require_file=True)
        data = read_bytes(file)
        text = data.decode("utf-8")
        lines = text.splitlines()
        start = max(1, start_line)
        count = max(1, min(max_lines, 500))
        selected = [{"line": n + 1, "text": lines[n]}
                    for n in range(start - 1, min(start - 1 + count, len(lines)))]
        return {"path": path, "project": project, "sha256": hash_bytes(data),
                "total_lines": len(lines), "lines": selected}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def fs_write(project: str, path: str, content: str,
                 expected_sha256: str | None = None) -> dict:
        """Atomically write UTF-8 text; existing files REQUIRE current SHA256 and are backed up."""
        base, file = target_for(project, path)
        if file == base or file.is_dir():
            raise ValueError("Expected a file, not directory")
        data = content.encode("utf-8")
        if len(data) > MAX_FILE:
            raise ValueError("Content exceeds 512 KiB")
        if file.suffix == ".py":
            compile(content, str(file), "exec")
        original = read_bytes(file) if file.exists() else None
        if original is not None and hash_bytes(original) != expected_sha256:
            raise ValueError("SHA256 required or mismatched")
        if original is None and expected_sha256 is not None:
            raise ValueError("Target does not exist")
        saved = atomic_write(file, data, original)
        return {"written": path, "project": project,
                "sha256": hash_bytes(data), "backup_id": saved}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def fs_replace(project: str, path: str, old: str, new: str,
                   expected_sha256: str) -> dict:
        """Replace exactly one matching text span in a file with CAS SHA256 protection."""
        _, file = target_for(project, path, require_file=True)
        original = read_bytes(file)
        actual_sha256 = hash_bytes(original)
        if actual_sha256 != expected_sha256:
            # Expected concurrent edit; not a server exception and no overwrite.
            return {
                "ok": False, "error_code": "SHA256_CONFLICT",
                "project": project, "path": path,
                "expected_sha256": expected_sha256,
                "current_sha256": actual_sha256,
                "retry_policy": "READ_RECONCILE_RETRY",
                "message": "File changed. Read the current version and reconcile the intended edit before retrying.",
            }
        text = original.decode("utf-8")
        matches = text.count(old) if old else 0
        if matches != 1:
            return {
                "ok": False, "error_code": "MATCH_CONFLICT",
                "project": project, "path": path,
                "current_sha256": actual_sha256,
                "matches": matches,
                "message": "Expected exactly one occurrence. Re-read and inspect the intended replacement.",
            }
        updated = text.replace(old, new, 1)
        if file.suffix == ".py":
            compile(updated, str(file), "exec")
        result = updated.encode("utf-8")
        if len(result) > MAX_FILE:
            raise ValueError("Content exceeds 512 KiB")
        saved = atomic_write(file, result, original)
        return {"ok": True, "path": path, "sha256": hash_bytes(result), "backup_id": saved}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def fs_mkdir(project: str, path: str) -> dict:
        """Create one directory within an explicitly approved project root."""
        base, folder = target_for(project, path)
        if base == folder:
            raise ValueError("Cannot modify project root")
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        return {"created": path, "project": project}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def fs_move(project: str, source: str, destination: str) -> dict:
        """Move a file inside one approved project without overwriting its destination."""
        base, old = target_for(project, source, require_file=True)
        _, new = target_for(project, destination)
        if new.exists() or old == new or new == base:
            raise FileExistsError(destination)
        new.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        old.rename(new)
        return {"moved": source, "to": destination}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def fs_trash(project: str, path: str, expected_sha256: str) -> dict:
        """Move a file to private recoverable backups; never recursively delete directories."""
        _, file = target_for(project, path, require_file=True)
        data = read_bytes(file)
        if hash_bytes(data) != expected_sha256:
            raise ValueError("SHA256 mismatch")
        backup = backup_original(file, data)
        file.unlink()
        return {"trashed": path, "backup_id": backup, "recovery_dir": str(RECOVERY)}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def fs_search(project: str, pattern: str, path: str = ".",
                  max_matches: int = 80) -> dict:
        """Search UTF-8 files by literal substring; bounded directory scan and output."""
        base, folder = target_for(project, path)
        if not pattern or len(pattern) > 160:
            raise ValueError("Search text must be 1–160 characters")
        max_matches = max(1, min(int(max_matches), 150))
        hits, scanned = [], 0
        stack = [folder]
        while stack and scanned < 1200 and len(hits) < max_matches:
            current = stack.pop()
            if current.is_dir():
                for child in sorted(current.iterdir(), reverse=True):
                    try:
                        target_for(project, str(child.relative_to(base)))
                    except (ValueError, PermissionError):
                        continue
                    if not child.is_symlink():
                        stack.append(child)
                continue
            if not current.is_file() or current.stat().st_size > MAX_FILE:
                continue
            scanned += 1
            try:
                lines = current.read_text("utf-8").splitlines()
            except UnicodeError:
                continue
            for index, line in enumerate(lines, 1):
                if pattern in line:
                    hits.append({"file": str(current.relative_to(base)),
                                 "line": index, "snippet": line[:450]})
                    if len(hits) >= max_matches:
                        break
        return {"matches": hits, "files_scanned": scanned, "truncated": bool(stack)}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def fs_restore(project: str, path: str, backup_id: str,
                   expected_sha256: str | None = None) -> dict:
        """Restore saved backup to an approved file, with SHA256 CAS protection."""
        base, target = target_for(project, path)
        if target == base or target.is_dir():
            raise ValueError("Destination must be a file")
        if not re.fullmatch(r"[0-9]{12,24}-[0-9a-f]{10}\.bak", backup_id):
            raise ValueError("Invalid backup ID")
        saved = RECOVERY / backup_id
        if saved.is_symlink() or not saved.is_file():
            raise FileNotFoundError("Backup not found")
        data = read_bytes(saved)
        original = read_bytes(target) if target.exists() else None
        if original is None and expected_sha256 is not None:
            raise ValueError("Target does not exist")
        if original is not None and hash_bytes(original) != expected_sha256:
            raise ValueError("SHA256 required or mismatched")
        if target.suffix == ".py":
            compile(data, str(target), "exec")
        previous = atomic_write(target, data, original)
        return {"restored": path, "sha256": hash_bytes(data),
                "previous_backup_id": previous}
