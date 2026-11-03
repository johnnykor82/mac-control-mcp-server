"""BF-16: safe self-update launcher and durable, owner-scoped job status.

Only explicitly triggered calls spawn the independent, pre-update watchdog.
The lock and journal live in installer-owned data, not in a mutable release.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile
import time

TERMINAL = frozenset({"succeeded", "rolled_back", "failed", "rollback_failed", "worker_missing"})
IN_PROGRESS = frozenset({"scheduled", "running"})


def _directory(root: Path, *, create: bool = False) -> Path:
    root = Path(root).expanduser().absolute()
    directory = root / "data/run/self-update"
    for part in (root, root / "data", root / "data/run", directory):
        if part.is_symlink() or (part.exists() and not part.is_dir()):
            raise RuntimeError("Unsafe self-update state directory")
        if not part.exists():
            if part != directory or not create:
                raise FileNotFoundError("Self-update state is not installed")
            part.mkdir(mode=0o700)
        info = part.stat()
        if info.st_uid != os.getuid():
            raise RuntimeError("Self-update state has foreign ownership")
    if create:
        directory.chmod(0o700)
    return directory


def _journal(root: Path, *, create: bool = False) -> Path:
    return _directory(root, create=create) / "status.json"


def _read(root: Path) -> dict:
    try:
        journal = _journal(root)
    except FileNotFoundError:
        return {"state": "not_started"}
    if journal.is_symlink():
        raise RuntimeError("Unsafe self-update journal symlink")
    if not journal.exists():
        return {"state": "not_started"}
    info = journal.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 4096):
        raise RuntimeError("Unsafe self-update journal")
    try:
        record = json.loads(journal.read_text())
    except (OSError, ValueError):
        raise RuntimeError("Unreadable self-update journal") from None
    if not isinstance(record, dict) or record.get("state") not in TERMINAL | IN_PROGRESS:
        raise RuntimeError("Malformed self-update journal")
    return record


def _record(root: Path, record: dict) -> None:
    journal = _journal(root, create=True)
    if journal.is_symlink():
        raise RuntimeError("Unsafe self-update journal symlink")
    data = json.dumps(record, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("ascii")
    if len(data) > 4096:
        raise RuntimeError("Self-update journal too large")
    fd, temporary = tempfile.mkstemp(dir=journal.parent, prefix=".status-", suffix=".json")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, journal)
        directory_fd = os.open(journal.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _pid_alive(pid: int) -> bool:
    if type(pid) is not int or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def status(root: Path) -> dict:
    record = _read(root)
    if record["state"] in IN_PROGRESS:
        if not _pid_alive(record.get("pid")):
            try:
                age = time.time() - float(record.get("started_at", 0))
            except (ValueError, TypeError):
                age = 999
            if age > 8:
                return {**record, "state": "worker_missing",
                        "reason": "WATCHDOG_PROCESS_DISAPPEARED"}
    return record


def _owned_preflight(root: Path, release: Path) -> None:
    from mac_control import maintenance_ops
    source, service = maintenance_ops._owned_service(root)
    if (service.get("status") != "running"
            or source != release / "scripts/setup_remote_service.py"):
        raise RuntimeError("Owned remote Mac Control service is not running")
    if not (root / "current").is_symlink() or (root / "current").resolve() != release:
        raise RuntimeError("Mac Control release changed before self-update")
    if (release.parent != root / "releases"
            or not (release / "scripts/maccontrol_manager.py").is_file()
            or not (release / "scripts/self_update_watchdog.py").is_file()):
        raise RuntimeError("Current Mac Control release is not eligible for self-update")


def _spawn(root: Path, release: Path, job_id: str,
           with_chatbridge: bool, lock_fd: int) -> int:
    executable = release / "scripts/self_update_watchdog.py"
    if executable.is_symlink() or not executable.is_file():
        raise RuntimeError("Installed self-update watchdog unavailable")
    env = {"HOME": str(Path.home()), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "LANG": os.environ.get("LANG", "C.UTF-8"),
           "MAC_CONTROL_DATA_ROOT": str(root / "data"),
           "PYTHONPATH": str(release) + os.pathsep + str(release / "src")}
    for key in ("TMPDIR", "SSL_CERT_FILE", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    child = subprocess.Popen(
        [sys.executable, "-P", "-B", str(executable), "--worker",
         "--root", str(root), "--baseline", str(release),
         "--job-id", job_id, "--lock-fd", str(lock_fd),
         "--with-chatbridge" if with_chatbridge else "--without-chatbridge"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, cwd=release, env=env,
        close_fds=True, pass_fds=(lock_fd,), start_new_session=True)
    return int(child.pid)


def start(root: Path, release: Path, with_chatbridge: bool = False) -> dict:
    if type(with_chatbridge) is not bool:
        raise ValueError("with_chatbridge must be boolean")
    root = Path(root).expanduser().absolute().resolve()
    release = Path(release).resolve()
    _owned_preflight(root, release)
    directory = _directory(root, create=True)
    lock = directory / "update.lock"
    if lock.is_symlink():
        raise RuntimeError("Unsafe self-update lock")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise RuntimeError("Unsafe self-update lock ownership")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Self-update already in progress") from None
        previous = _read(root)
        if previous["state"] in IN_PROGRESS:
            try:
                recent = time.time() - float(previous.get("started_at", 0)) < 10
            except (ValueError, TypeError):
                recent = False
            if _pid_alive(previous.get("pid")) or recent:
                raise RuntimeError("Self-update already in progress")
        job_id = secrets.token_hex(12)
        record = {"job_id": job_id, "state": "scheduled",
                  "stage": "starting", "pid": 0,
                  "started_at": int(time.time()),
                  "with_chatbridge": with_chatbridge}
        _record(root, record)
        try:
            pid = _spawn(root, release, job_id, with_chatbridge, fd)
        except (OSError, RuntimeError):
            _record(root, {**record, "state": "failed", "stage": "spawn",
                           "reason": "WATCHDOG_START_FAILED"})
            raise
        record["pid"] = pid
        _record(root, record)
        return {"job_id": job_id, "state": "scheduled",
                "message": "Independent watchdog started; query self_update_status after reconnect"}
    finally:
        os.close(fd)
