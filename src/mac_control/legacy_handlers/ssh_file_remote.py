"""Fixed, source-controlled remote commit helper. No file bytes in SSH commands.

Executed as python3 -c SCRIPT <action> <path> [args] under the SSH account.
Overwrites verify the previous SHA-256 immediately before atomic rename.
"""
REMOTE_HELPER = r'''
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

def commit(stage, dest, expected, overwrite, mode, content_sha):
    if os.path.dirname(stage) != os.path.dirname(dest) or stage == dest:
        raise ValueError("stage_not_sibling")
    # Validate the fully transferred data before checking the destination.
    staged = info(stage)
    if not staged["exists"] or staged["sha256"] != content_sha:
        raise ValueError("hash_mismatch")
    if mode != "-":
        os.chmod(stage, int(mode, 8))
    # Recheck the current SHA-256 immediately before publish: no remote
    # lock service, no inter-process coordination, and no strict CAS claim.
    original = info(dest)
    if not overwrite and original["exists"]:
        raise ValueError("file_exists")
    if expected and (not original["exists"] or original["sha256"] != expected):
        raise ValueError("cas_conflict")
    if overwrite:
        os.replace(stage, dest)
    else:
        # Atomic no-clobber on the same filesystem; a concurrent create
        # cannot be silently overwritten.
        os.link(stage, dest, follow_symlinks=False)
        os.unlink(stage)
    return {"status":"published", "sha256":content_sha,
            "bytes":staged["size"], "cas_consistency":"pre_rename_sha256_check"}

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
