"""Fixed, source-controlled remote commit helper. No file bytes in SSH commands.

Executed as python3 -c SCRIPT <action> <path> [args] under the SSH account.
Locking coordinates Mac Control operations, not arbitrary third-party writers.
"""
REMOTE_HELPER = r'''
import errno
import fcntl
import hashlib
import json
import os
import stat
import sys

def digest(path):
    h = hashlib.sha256()
    with open(path, "rb", buffering=0) as f:
        while True:
            chunk = f.read(1048576)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def safe_path(value):
    if not value or "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("invalid_path")
    value = os.path.abspath(value)
    cursor = os.path.sep
    parts = value.split(os.sep)
    for part in parts[1:-1]:
        if not part:
            continue
        cursor = os.path.join(cursor, part)
        if stat.S_ISLNK(os.lstat(cursor).st_mode):
            raise ValueError("unsafe_symlink")
    return value

def info(path):
    if not os.path.lexists(path):
        return {"exists":False, "size":0, "sha256":None}
    mode = os.lstat(path).st_mode
    if not stat.S_ISREG(mode):
        raise ValueError("unsafe_symlink_or_nonregular")
    return {"exists":True, "size":os.stat(path).st_size, "sha256":digest(path)}

def lock(path):
    base = os.path.join(os.path.expanduser("~"), ".cache", "mac-control-mcp", "ssh-locks")
    os.makedirs(base, mode=0o700, exist_ok=True)
    if not stat.S_ISDIR(os.lstat(base).st_mode):
        raise ValueError("invalid_lock_directory")
    lockfile = os.path.join(base, hashlib.sha256(path.encode()).hexdigest() + ".lock")
    fd = os.open(lockfile, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd

def commit(stage, dest, expected, overwrite, mode, content_sha):
    if os.path.dirname(stage) != os.path.dirname(dest) or stage == dest:
        raise ValueError("stage_not_sibling")
    locked = lock(dest)
    try:
        original = info(dest)
        if not overwrite and original["exists"]:
            raise ValueError("file_exists")
        if expected and (not original["exists"] or original["sha256"] != expected):
            raise ValueError("cas_conflict")
        staged = info(stage)
        if not staged["exists"] or staged["sha256"] != content_sha:
            raise ValueError("hash_mismatch")
        if mode != "-":
            os.chmod(stage, int(mode, 8))
        if overwrite:
            os.replace(stage, dest)
        else:
            os.link(stage, dest, follow_symlinks=False)
            os.unlink(stage)
        return {"status":"published", "sha256":content_sha,
                "bytes":staged["size"], "cas_consistency":"cooperative_lock"}
    finally:
        os.close(locked)

def main():
    action = sys.argv[1]
    path = safe_path(sys.argv[2])
    if action == "inspect":
        return info(path)
    if action == "remove_stage":
        name = os.path.basename(path)
        if ".maccontrol-" not in name or not name.endswith(".part"):
            raise ValueError("not_owned_stage")
        if os.path.lexists(path):
            if not stat.S_ISREG(os.lstat(path).st_mode):
                raise ValueError("unsafe_symlink")
            os.unlink(path)
        return {"status":"stage_removed"}
    if action == "commit":
        stage = safe_path(sys.argv[3])
        expected = sys.argv[4]
        overwrite = sys.argv[5] == "true"
        mode = sys.argv[6]
        content_sha = sys.argv[7]
        return commit(stage, path, expected, overwrite, mode, content_sha)
    raise ValueError("unknown_operation")

try:
    print(json.dumps({"ok":True,"result":main()}))
except (OSError, ValueError, IndexError) as exc:
    code = str(exc) if isinstance(exc, ValueError) else ("permission_denied" if isinstance(exc, PermissionError) else "remote_io_error")
    print(json.dumps({"ok":False,"code":code[:100],"message":type(exc).__name__}))
    sys.exit(1)
'''
