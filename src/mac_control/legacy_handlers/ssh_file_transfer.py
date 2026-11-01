"""SFTP file operations for owner-approved SSH profiles.

Only paths/metadata are included in remote commands; all file bytes use the
OpenSSH SFTP subsystem. Files remain staged until hashes match.
"""
from __future__ import annotations
import base64
import binascii
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import subprocess
import tempfile
import time

from ..runtime_paths import DATA_ROOT
from .ssh_file_remote import REMOTE_HELPER
from . import ssh_manage_ops as ssh
from . import ssh_bridge_ops as legacy_ssh

SFTP = "/usr/bin/sftp"
CHUNK_LIMIT = 64 * 1024
TEXT_LIMIT = 512 * 1024
MAX_TOTAL = 512 * 1024 * 1024
SESSION_TTL = 24 * 3600
STAGING = DATA_ROOT / "transfers" / "ssh"
HEX = re.compile(r"[0-9a-f]{64}\Z")
TOKEN = re.compile(r"[0-9a-f]{32}\Z")
REMOTE_PATTERN = re.compile(r"[^\x00\r\n]+\Z")


def _limits():
    """Optional owner-only policy; defaults work with a 100-MiB transfer."""
    path = DATA_ROOT / "ssh_transfer_policy.json"
    default = {"max_total_bytes": MAX_TOTAL, "max_chunk_bytes": CHUNK_LIMIT,
               "ttl_seconds": SESSION_TTL}
    if not path.exists():
        return default
    if (path.is_symlink() or path.stat().st_uid != os.getuid()
            or path.stat().st_mode & 0o077):
        raise TransferError("unsafe_transfer_policy")
    policy = json.loads(path.read_text("utf-8"))
    allowed = {"max_total_bytes":(1024*1024, 1024*1024*1024),
               "max_chunk_bytes":(1024, 256*1024),
               "ttl_seconds":(300, 7*24*3600)}
    if not isinstance(policy, dict) or set(policy)-set(allowed):
        raise TransferError("invalid_transfer_policy")
    for key, bounds in allowed.items():
        if key not in policy:
            continue
        value = policy[key]
        if type(value) is not int or not bounds[0] <= value <= bounds[1]:
            raise TransferError("invalid_transfer_policy")
        default[key] = value
    return default


class TransferError(RuntimeError):
    def __init__(self, code, message="", *, transfer_id=None, retryable=False,
                 resumable=False, next_offset=None):
        super().__init__(message or code)
        self.code = code
        self.transfer_id = transfer_id
        self.retryable = retryable
        self.resumable = resumable
        self.next_offset = next_offset

    def as_dict(self):
        return {"status":"error", "code":self.code, "message":str(self),
                "transfer_id":self.transfer_id, "retryable":self.retryable,
                "resumable":self.resumable, "next_offset":self.next_offset}


def _sha(path, size=None):
    h = hashlib.sha256()
    with open(path, "rb") as source:
        remaining = size
        while True:
            data = source.read(1048576 if remaining is None else min(1048576, remaining))
            if not data:
                break
            h.update(data)
            if remaining is not None:
                remaining -= len(data)
                if not remaining:
                    break
    return h.hexdigest()


def _remote_path(value):
    if not isinstance(value, str) or not REMOTE_PATTERN.fullmatch(value) or len(value.encode()) > 4096:
        raise TransferError("invalid_remote_path")
    if value in (".", "..") or "/../" in "/" + value + "/":
        raise TransferError("invalid_remote_path")
    return value


def _sftp_quoted(path):
    path = _remote_path(path)
    # OpenSSH sftp batch parser supports double quotes and backslash escapes.
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _validate_mode(mode):
    if mode is None:
        return "-"
    if isinstance(mode, int):
        mode = format(mode, "04o")
    if not isinstance(mode, str) or not re.fullmatch(r"0?[0-7]{3}", mode):
        raise TransferError("invalid_mode")
    return format(int(mode, 8), "04o")


def _expected(value):
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise TransferError("invalid_sha256")
    return value


def _ssh_env():
    return {"HOME":str(Path.home()), "PATH":"/usr/bin:/bin",
            "SSH_ASKPASS":"/usr/bin/false", "SSH_ASKPASS_REQUIRE":"never",
            "LANG":"C.UTF-8"}


def _ssh_command(host, remote_command=None):
    """Resolve either of the two existing owner-approved SSH profile stores."""
    try:
        return ssh._command(host,remote_command)
    except PermissionError as exc:
        if str(exc) != "Host is not approved":
            raise
    # Legacy diagnostic hosts are owner-approved in ssh_targets.json.
    # The existing _argv validates their host, login, port and key.
    args = legacy_ssh._argv(host,"identity")[:-1]
    return [*args,remote_command] if remote_command is not None else args


def _sftp_argv(host):
    original = _ssh_command(host)
    boundary = original.index("--")
    if boundary != len(original)-2:
        raise TransferError("invalid_ssh_profile")
    opts = [x for x in original[1:boundary] if x != "-T"]
    return [SFTP, "-b", "-", *("-P" if x == "-p" else x for x in opts),
            "--", original[-1]]


def _sftp(host, instruction, timeout=240):
    try:
        result = subprocess.run(_sftp_argv(host), input=instruction+"\n",
                                text=True, capture_output=True, timeout=timeout,
                                env=_ssh_env(), check=False)
    except subprocess.TimeoutExpired as exc:
        raise TransferError("ssh_disconnected", "SFTP timed out", retryable=True, resumable=True) from exc
    if result.returncode:
        raise TransferError("ssh_disconnected", "SFTP operation failed", retryable=True, resumable=True)
    return result


def _remote(host, action, path, *args):
    _remote_path(path)
    parts = ["python3", "-c", REMOTE_HELPER, action, path, *map(str, args)]
    try:
        result = subprocess.run(_ssh_command(host, shlex.join(parts)),
                                text=True, capture_output=True,
                                timeout=120, env=_ssh_env())
    except subprocess.TimeoutExpired as exc:
        raise TransferError("ssh_disconnected", "SSH helper timed out", retryable=True, resumable=True) from exc
    try:
        payload = json.loads(result.stdout.strip())
        if not payload["ok"]:
            raise TransferError(payload.get("code","remote_error"), payload.get("message","Remote operation failed"))
        return payload["result"]
    except (ValueError, KeyError, TypeError) as exc:
        raise TransferError("ssh_disconnected", "Remote helper unavailable or invalid response",
                            retryable=True, resumable=True) from exc

def _stage_path(remote):
    if not remote.rstrip("/").split("/")[-1]:
        raise TransferError("invalid_remote_path")
    return remote + ".maccontrol-" + secrets.token_hex(16) + ".part"


def _safe_local(path, require_existing=False):
    if not isinstance(path, str) or not path or "\x00" in path:
        raise TransferError("invalid_local_path")
    from .fs_ops import roots
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = roots()["workspace"] / candidate
    candidate = Path(os.path.abspath(candidate))
    allowed = tuple(x.resolve() for x in roots().values())
    if not any(candidate.is_relative_to(root) and candidate != root for root in allowed):
        raise TransferError("local_path_not_approved")
    for part in [candidate, *candidate.parents]:
        if part.is_symlink():
            raise TransferError("unsafe_symlink")
    if require_existing and (not candidate.is_file() or not stat.S_ISREG(candidate.stat().st_mode)):
        raise TransferError("invalid_local_file")
    return candidate


def _local_commit(temp, dest, overwrite):
    if not overwrite:
        try:
            os.link(temp, dest, follow_symlinks=False)
        except FileExistsError as exc:
            raise TransferError("file_exists") from exc
        os.unlink(temp)
    else:
        if dest.is_symlink() or (dest.exists() and not dest.is_file()):
            raise TransferError("unsafe_symlink")
        os.replace(temp, dest)


def upload(host, local_path, remote_path, overwrite=False, mode=None,
           expected_remote_sha256=None, *, remote_stage=None, internal=False):
    local = (Path(local_path) if internal else _safe_local(local_path, require_existing=True))
    remote = _remote_path(remote_path)
    target_hash = _expected(expected_remote_sha256)
    _validate_mode(mode)
    if not local.is_file() or local.is_symlink():
        raise TransferError("invalid_local_file")
    if local.stat().st_size > _limits()["max_total_bytes"]:
        raise TransferError("size_limit")
    sha = _sha(local)
    stage = remote_stage or _stage_path(remote)
    remote_before = _remote(host, "inspect", remote)
    # If a previous transfer was committed but its SSH reply was lost, the
    # staging path is already gone and the destination has the right hash.
    if remote_stage and remote_before["sha256"] == sha:
        staged = _remote(host, "inspect", stage)
        if not staged["exists"]:
            return {"status":"completed", "host":host, "local_path":str(local),
                    "remote_path":remote, "size_bytes":local.stat().st_size,
                    "transferred_bytes":local.stat().st_size, "sha256":sha,
                    "remote_sha256":sha, "verified":True,
                    "cas_consistency":"pre_rename_sha256_check"}
    if remote_before["exists"] and not overwrite:
        raise TransferError("file_exists")
    if target_hash and remote_before["sha256"] != target_hash:
        raise TransferError("cas_conflict")
    # Reput only when the entire existing remote prefix matches the local source.
    existing = _remote(host, "inspect", stage)
    if existing["exists"]:
        size = existing["size"]
        if size > local.stat().st_size or _sha(local, size) != existing["sha256"]:
            raise TransferError("stage_conflict")
        operation = "reput" if size else "put"
        already_complete = size == local.stat().st_size
    else:
        operation = "put"
        already_complete = False
    try:
        if not already_complete:
            _sftp(host, operation+" "+_sftp_quoted(str(local))+" "+_sftp_quoted(stage))
        result = _remote(host, "commit", remote, stage, target_hash, "true" if overwrite else "false",
                         _validate_mode(mode), sha)
    except TransferError:
        # Keep the remote stage for a transfer_id retry. For a one-shot transfer,
        # best-effort remove it after a non-resumable failure.
        if not remote_stage:
            try:
                _remote(host, "remove_stage", stage)
            except TransferError:
                pass
        raise
    return {"status":"completed", "host":host, "local_path":str(local),
            "remote_path":remote, "size_bytes":local.stat().st_size,
            "transferred_bytes":local.stat().st_size, "sha256":sha,
            "remote_sha256":result["sha256"], "verified":True,
            "cas_consistency":result["cas_consistency"]}


def download(host, remote_path, local_path, overwrite=False, expected_sha256=None,
             *, internal_target=None):
    remote = _remote_path(remote_path)
    local = Path(internal_target) if internal_target else _safe_local(local_path)
    expected_hash = _expected(expected_sha256)
    if not internal_target and not local.parent.is_dir():
        raise TransferError("local_parent_missing")
    before = _remote(host, "inspect", remote)
    if not before["exists"]:
        raise TransferError("remote_not_found")
    if before["size"] > _limits()["max_total_bytes"]:
        raise TransferError("size_limit")
    if expected_hash and expected_hash != before["sha256"]:
        raise TransferError("hash_mismatch")
    if not internal_target and (local.is_symlink() or (local.exists() and not overwrite)):
        raise TransferError("file_exists")
    fd, name = tempfile.mkstemp(prefix=".maccontrol-download-", dir=local.parent)
    temp = Path(name)
    os.close(fd)
    try:
        _sftp(host, "get "+_sftp_quoted(remote)+" "+_sftp_quoted(str(temp)))
        digest = _sha(temp)
        if digest != before["sha256"]:
            raise TransferError("hash_mismatch")
        if internal_target:
            os.replace(temp, local)
        else:
            _local_commit(temp, local, overwrite)
        return {"status":"completed", "host":host, "remote_path":remote,
                "local_path":str(local), "sha256":digest, "remote_sha256":digest,
                "size_bytes":local.stat().st_size, "transferred_bytes":local.stat().st_size,
                "verified":True}
    finally:
        temp.unlink(missing_ok=True)


def write_text(host, remote_path, content, encoding="utf-8", overwrite=False,
               mode=None, expected_remote_sha256=None):
    if encoding.lower().replace("_", "-") != "utf-8":
        raise TransferError("unsupported_encoding")
    if not isinstance(content, str):
        raise TransferError("invalid_content")
    data = content.encode("utf-8")
    if len(data) > TEXT_LIMIT:
        raise TransferError("text_too_large", "Use streaming interface instead")
    _prepare_staging()
    fd, path = tempfile.mkstemp(prefix=".maccontrol-text-", dir=STAGING)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        return upload(host, path, remote_path, overwrite, mode, expected_remote_sha256,
                      internal=True)
    finally:
        Path(path).unlink(missing_ok=True)


def _prepare_staging():
    if STAGING.is_symlink():
        raise TransferError("unsafe_staging_root")
    STAGING.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (STAGING.is_symlink() or STAGING.stat().st_uid != os.getuid()
            or STAGING.stat().st_mode & 0o077):
        raise TransferError("unsafe_staging_root")


def _cleanup_expired():
    """Opportunistic TTL cleanup, bounded to eight expired sessions per call.

    Remote-stage deletion is retried when the host is reachable; never remove
    recoverability metadata while an unreachable remote part may remain.
    """
    now = time.time()
    ttl = _limits()["ttl_seconds"]
    cleaned = 0
    for folder in STAGING.iterdir():
        if cleaned >= 8:
            break
        if folder.is_symlink() or not folder.is_dir() or not TOKEN.fullmatch(folder.name):
            continue
        metadata = folder / "meta.json"
        if metadata.is_symlink() or not metadata.is_file():
            continue
        if now - metadata.stat().st_mtime <= ttl:
            continue
        lock_file = folder / "lock"
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                meta = json.loads(metadata.read_text("utf-8"))
                if meta.get("transfer_id") != folder.name:
                    continue
                if meta.get("remote_started") and meta.get("direction") == "upload":
                    try:
                        _remote(meta["host"], "remove_stage", meta["remote_stage"])
                    except (TransferError, KeyError):
                        continue
                _remove_session(folder)
                cleaned += 1
            finally:
                os.close(fd)
        except (OSError, ValueError):
            continue
    return cleaned


def _meta_file(transfer_id):
    if not isinstance(transfer_id, str) or not TOKEN.fullmatch(transfer_id):
        raise TransferError("invalid_transfer_id")
    _prepare_staging()
    return STAGING / transfer_id / "meta.json"


def _save_meta(path, meta):
    temp = path.with_name("meta.tmp")
    if temp.exists() or temp.is_symlink():
        temp.unlink()
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(meta, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read_meta(transfer_id):
    path = _meta_file(transfer_id)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise TransferError("transfer_not_found", transfer_id=transfer_id)
    if time.time() - path.stat().st_mtime > _limits()["ttl_seconds"]:
        raise TransferError("transfer_expired", transfer_id=transfer_id)
    meta = json.loads(path.read_text("utf-8"))
    if meta.get("transfer_id") != transfer_id:
        raise TransferError("transfer_not_found")
    return path, meta


def _session_lock(transfer_id):
    from contextlib import contextmanager
    @contextmanager
    def locked():
        path = _meta_file(transfer_id).parent
        if path.is_symlink() or not path.is_dir():
            raise TransferError("transfer_not_found")
        lock = path / "lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)
    return locked()


def _remove_session(path):
    # Remove only deterministic files inside a verified private transfer folder.
    for name in ("blob", "meta.json", "meta.tmp", "lock"):
        file = path / name
        if file.is_symlink():
            raise TransferError("unsafe_symlink")
        file.unlink(missing_ok=True)
    path.rmdir()


def begin(direction, host, remote_path, local_path=None, total_size=None,
          expected_sha256=None, overwrite=False, mode=None,
          expected_remote_sha256=None, resume_transfer_id=None):
    _ssh_command(host)
    _remote_path(remote_path)
    if direction not in ("upload", "download"):
        raise TransferError("invalid_direction")
    if resume_transfer_id:
        with _session_lock(resume_transfer_id):
            _, saved = _read_meta(resume_transfer_id)
            if (saved["host"], saved["remote_path"], saved["direction"]) != (
                    host, remote_path, direction):
                raise TransferError("transfer_identity_conflict")
            return {"transfer_id":resume_transfer_id, "direction":direction,
                    "next_offset":saved["next_offset"],
                    "max_chunk_bytes":_limits()["max_chunk_bytes"],
                    "expires_at":time.time()+_limits()["ttl_seconds"],
                    "resumable":True, "total_size":saved["total_size"]}
    _expected(expected_sha256)
    _expected(expected_remote_sha256)
    _validate_mode(mode)
    limits = _limits()
    if total_size is not None and (type(total_size) is not int or
                                  not 0 <= total_size <= limits["max_total_bytes"]):
        raise TransferError("size_limit")
    if local_path:
        if direction == "upload":
            raise TransferError("use_ssh_upload_for_local_files")
        _safe_local(local_path)
    _prepare_staging()
    _cleanup_expired()
    transfer_id = secrets.token_hex(16)
    path = STAGING / transfer_id
    path.mkdir(mode=0o700)
    blob = path / "blob"
    fd = os.open(blob, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    meta = {"transfer_id": transfer_id, "direction":direction, "host":host,
            "remote_path":remote_path, "remote_stage":_stage_path(remote_path),
            "local_path":local_path, "total_size":total_size,
            "expected_sha256":_expected(expected_sha256), "overwrite":bool(overwrite),
            "mode":mode, "expected_remote_sha256":_expected(expected_remote_sha256),
            "next_offset":0, "next_index":0, "last_chunk_sha256":"",
            "last_chunk_size":0, "status":"receiving", "created_at":time.time()}
    _save_meta(path/"meta.json",meta)
    if direction == "download":
        try:
            existing = _remote(host,"inspect",remote_path)
            if total_size is not None and existing["size"] != total_size:
                raise TransferError("size_mismatch")
            result = download(host,remote_path,str(blob),expected_sha256=expected_sha256,
                              internal_target=blob)
            meta["total_size"] = result["size_bytes"]
            meta["expected_sha256"] = result["sha256"]
            meta["status"] = "ready"
            _save_meta(path/"meta.json", meta)
        except BaseException:
            _remove_session(path)
            raise
    return {"transfer_id":transfer_id, "direction":direction, "next_offset":0,
            "max_chunk_bytes":limits["max_chunk_bytes"],
            "expires_at":time.time()+limits["ttl_seconds"],
            "resumable":True, "total_size":meta["total_size"]}


def chunk(transfer_id, offset, chunk_index, data_base64="", chunk_sha256=""):
    with _session_lock(transfer_id):
        path, meta = _read_meta(transfer_id)
        blob = path.parent / "blob"
        if not isinstance(offset, int) or offset < 0 or not isinstance(chunk_index, int):
            raise TransferError("invalid_offset")
        if meta["direction"] == "download":
            if offset != meta["next_offset"] or chunk_index != meta["next_index"]:
                raise TransferError("invalid_offset")
            with blob.open("rb") as f:
                f.seek(offset)
                data = f.read(_limits()["max_chunk_bytes"])
            meta["next_offset"] += len(data)
            meta["next_index"] += 1
            _save_meta(path,meta)
            return {"transfer_id":transfer_id, "offset":offset,
                    "bytes":len(data), "data_base64":base64.b64encode(data).decode("ascii"),
                    "chunk_sha256":hashlib.sha256(data).hexdigest(),
                    "next_offset":meta["next_offset"], "eof":not data}
        if meta["status"] != "receiving":
            raise TransferError("transfer_closed")
        limits = _limits()
        max_chunk = limits["max_chunk_bytes"]
        if not isinstance(data_base64, str) or len(data_base64) > ((max_chunk+2)//3)*4+4:
            raise TransferError("chunk_too_large")
        try:
            data = base64.b64decode(data_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise TransferError("invalid_base64") from exc
        digest = hashlib.sha256(data).hexdigest()
        if not data or len(data) > max_chunk or digest != _expected(chunk_sha256):
            raise TransferError("invalid_chunk_hash_or_size")
        if (offset == meta["next_offset"]-meta["last_chunk_size"] and
                chunk_index == meta["next_index"]-1 and digest == meta["last_chunk_sha256"]):
            with blob.open("rb") as f:
                f.seek(offset)
                if hashlib.sha256(f.read(len(data))).hexdigest() != digest:
                    raise TransferError("stage_conflict")
            return {"transfer_id":transfer_id, "status":"already_accepted",
                    "next_offset":meta["next_offset"]}
        if offset != meta["next_offset"] or chunk_index != meta["next_index"]:
            raise TransferError("invalid_offset")
        if offset+len(data) > limits["max_total_bytes"] or (meta["total_size"] is not None and
                                            offset+len(data)>meta["total_size"]):
            raise TransferError("size_limit")
        with blob.open("r+b") as f:
            f.seek(offset)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        meta["last_chunk_size"] = len(data)
        meta["last_chunk_sha256"] = digest
        meta["next_offset"] += len(data)
        meta["next_index"] += 1
        _save_meta(path,meta)
        return {"transfer_id":transfer_id, "status":"accepted",
                "next_offset":meta["next_offset"]}


def finish(transfer_id, expected_sha256=None):
    with _session_lock(transfer_id):
        path, meta = _read_meta(transfer_id)
        blob = path.parent/"blob"
        if not blob.is_file() or blob.is_symlink():
            raise TransferError("transfer_not_found")
        digest = _sha(blob)
        size = blob.stat().st_size
        expected_hash = _expected(expected_sha256) or meta["expected_sha256"]
        if expected_hash and digest != expected_hash:
            raise TransferError("hash_mismatch", transfer_id=transfer_id)
        if meta["total_size"] is not None and size != meta["total_size"]:
            raise TransferError("size_mismatch", transfer_id=transfer_id)
        if meta["direction"] == "upload":
            if size != meta["next_offset"]:
                raise TransferError("stage_conflict", transfer_id=transfer_id)
            meta["remote_started"] = True
            _save_meta(path,meta)
            try:
                result = upload(meta["host"],blob,meta["remote_path"],
                                meta["overwrite"],meta["mode"],
                                meta["expected_remote_sha256"],
                                remote_stage=meta["remote_stage"],internal=True)
            except TransferError as exc:
                exc.transfer_id = transfer_id
                exc.next_offset = meta["next_offset"]
                exc.resumable = True
                raise
        else:
            local = meta["local_path"]
            if local:
                destination = _safe_local(local)
                if not destination.parent.is_dir():
                    raise TransferError("local_parent_missing")
                if destination.exists() and not meta["overwrite"]:
                    raise TransferError("file_exists")
                fd, staging = tempfile.mkstemp(prefix=".maccontrol-transfer-", dir=destination.parent)
                try:
                    with os.fdopen(fd,"wb") as target, blob.open("rb") as source:
                        while True:
                            data = source.read(1048576)
                            if not data:
                                break
                            target.write(data)
                        target.flush()
                        os.fsync(target.fileno())
                    _local_commit(Path(staging),destination,meta["overwrite"])
                finally:
                    Path(staging).unlink(missing_ok=True)
            result = {"status":"completed","host":meta["host"],
                      "remote_path":meta["remote_path"],"local_path":local,
                      "size_bytes":size,"transferred_bytes":size,
                      "sha256":digest,"remote_sha256":digest,"verified":True}
        meta["status"] = "completed"
        _save_meta(path,meta)
    _remove_session(STAGING/transfer_id)
    return {"transfer_id":transfer_id, **result}


def cancel(transfer_id):
    if not _meta_file(transfer_id).exists():
        return {"status":"already_cancelled","transfer_id":transfer_id}
    with _session_lock(transfer_id):
        path, meta = _read_meta(transfer_id)
        if meta["direction"] == "upload":
            try:
                _remote(meta["host"],"remove_stage",meta["remote_stage"])
            except TransferError as exc:
                if exc.retryable:
                    return {"status":"cancel_pending","transfer_id":transfer_id,
                            "retryable":True}
                raise
    _remove_session(STAGING/transfer_id)
    return {"status":"cancelled","transfer_id":transfer_id}


def _audit(tool, host, remote, local, duration, outcome, size=None, sha256=None):
    directory = DATA_ROOT/"logs"
    if directory.is_symlink():
        return
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.stat().st_mode & 0o077:
        return
    file = directory/"ssh-transfers.jsonl"
    if file.is_symlink():
        return
    payload = {"time":time.time(),"operation":tool,"host":host,
               "remote_path":remote,"local_path":local,
               "duration_ms":round(duration*1000,2),"status":outcome,
               "size_bytes":size,"sha256":sha256}
    try:
        fd = os.open(file, os.O_APPEND|os.O_CREAT|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"a",encoding="utf-8") as f:
            f.write(json.dumps(payload,ensure_ascii=False)+"\n")
    except (OSError,ValueError):
        pass


def _wrap(tool, host, remote, local, fn):
    start = time.monotonic()
    try:
        result = fn()
    except TransferError as error:
        _audit(tool,host,remote,local,time.monotonic()-start,error.code)
        return error.as_dict()
    except (PermissionError, ValueError, FileNotFoundError, OSError) as error:
        code = ("host_not_approved" if isinstance(error, PermissionError)
                else "invalid_argument" if isinstance(error, ValueError)
                else "io_error")
        _audit(tool,host,remote,local,time.monotonic()-start,code)
        return TransferError(code).as_dict()
    _audit(tool,host,remote,local,time.monotonic()-start,"ok",
           result.get("size_bytes"), result.get("sha256"))
    return result


def register(mcp):
    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":True,"openWorldHint":False})
    def ssh_upload(host:str, local_path:str, remote_path:str, overwrite:bool=False,
                   mode:str|None=None, expected_remote_sha256:str|None=None)->dict:
        """SFTP upload Mac file; atomically publish after SHA-256. No heredoc."""
        return _wrap("ssh_upload",host,remote_path,local_path,lambda:
                     upload(host,local_path,remote_path,overwrite,mode,expected_remote_sha256))

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":True,"openWorldHint":False})
    def ssh_download(host:str, remote_path:str, local_path:str, overwrite:bool=False,
                     expected_sha256:str|None=None)->dict:
        """SFTP download to approved Mac project; verify SHA-256 before publish."""
        return _wrap("ssh_download",host,remote_path,local_path,lambda:
                     download(host,remote_path,local_path,overwrite,expected_sha256))

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":True,"openWorldHint":False})
    def ssh_write_text(host:str, remote_path:str, content:str, encoding:str="utf-8",
                       overwrite:bool=False, mode:str|None=None,
                       expected_remote_sha256:str|None=None)->dict:
        """Write up to 512 KiB of MCP-supplied UTF-8 text through SFTP, not shell."""
        return _wrap("ssh_write_text",host,remote_path,None,lambda:
                     write_text(host,remote_path,content,encoding,overwrite,mode,expected_remote_sha256))

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":True,"openWorldHint":False})
    def ssh_transfer_begin(direction:str,host:str,remote_path:str,
                           local_path:str|None=None,total_size:int|None=None,
                           expected_sha256:str|None=None, overwrite:bool=False,
                           mode:str|None=None,expected_remote_sha256:str|None=None,
                           resume_transfer_id:str|None=None)->dict:
        """Begin resumable SFTP transfer. For upload chunks come via MCP, not SSH commands."""
        return _wrap("ssh_transfer_begin",host,remote_path,local_path,lambda:
                     begin(direction,host,remote_path,local_path,total_size,
                           expected_sha256,overwrite,mode,expected_remote_sha256,
                           resume_transfer_id))

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":True,"openWorldHint":False})
    def ssh_transfer_chunk(transfer_id:str,offset:int,chunk_index:int,
                           data_base64:str="",chunk_sha256:str="")->dict:
        """Send/receive up to 64 KiB per chunk; data_base64 encodes MCP JSON only."""
        return _wrap("ssh_transfer_chunk","",transfer_id,None,lambda:
                     chunk(transfer_id,offset,chunk_index,data_base64,chunk_sha256))

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":True,"openWorldHint":False})
    def ssh_transfer_finish(transfer_id:str,expected_sha256:str|None=None)->dict:
        """Verify and publish staged transfer atomically."""
        return _wrap("ssh_transfer_finish","",transfer_id,None,lambda:
                     finish(transfer_id,expected_sha256))

    @mcp.tool(annotations={"readOnlyHint":False,"destructiveHint":True,"openWorldHint":False})
    def ssh_transfer_cancel(transfer_id:str)->dict:
        """Cancel one owned transfer and remove staging files."""
        return _wrap("ssh_transfer_cancel","",transfer_id,None,lambda:
                     cancel(transfer_id))
