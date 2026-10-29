"""Reliable, isolated Unix-socket transport for MacControlGUI helpers."""
import datetime
import errno
import fcntl
import os
import signal
import socket
import stat
import subprocess
import threading
import time

_recovery_lock = threading.Lock()
_last_success = {}
_RECOVER = {errno.ENOENT, errno.ECONNREFUSED}

class GUIIPCError(RuntimeError):
    def __init__(self, code, message, error_number=None, endpoint=None):
        super().__init__(message)
        self.code = code
        self.error_number = error_number
        self.endpoint = str(endpoint) if endpoint else None

    def as_dict(self):
        return {"code": self.code, "message": str(self),
                "errno": self.error_number, "endpoint": self.endpoint}

def helper_pid(helper):
    try:
        out = subprocess.run(['/bin/ps', '-axo', 'pid=,command='],
                             capture_output=True, text=True, check=True, timeout=3).stdout
        path = str(helper)
        for line in out.splitlines():
            columns = line.strip().split(None, 1)
            if len(columns) == 2 and (columns[1] == path or columns[1].startswith(path + ' ')):
                return int(columns[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None

def diagnostics(endpoint, helper):
    pid = helper_pid(helper)
    return {"endpoint": str(endpoint), "helper_pid": pid,
            "service_state": "running" if pid else "not_running",
            "last_success_at": _last_success.get(str(endpoint))}

def mark_success(endpoint):
    _last_success[str(endpoint)] = datetime.datetime.now(
        datetime.timezone.utc).isoformat()

def _once(endpoint, timeout):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    try:
        conn.connect(str(endpoint))
        return conn
    except BaseException:
        conn.close()
        raise

def _stop_broken_helper(helper, endpoint):
    pid = helper_pid(helper)
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise GUIIPCError("permission_denied", "Could not stop GUI helper",
                          exc.errno, endpoint) from exc
    for _ in range(25):
        if helper_pid(helper) != pid:
            return
        time.sleep(.1)
    raise GUIIPCError("helper_unresponsive",
                      "GUI helper ignored controlled SIGTERM", endpoint=endpoint)

def _discard_stale_socket(endpoint):
    try:
        info = endpoint.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise GUIIPCError("permission_denied",
                          "Will not replace endpoint with unsafe type or ownership",
                          endpoint=endpoint)
    try:
        connected = _once(endpoint, .3)
    except OSError as exc:
        if exc.errno not in _RECOVER:
            raise GUIIPCError("connection_failed", str(exc), exc.errno, endpoint) from exc
    else:
        connected.close()
        return
    newer = endpoint.lstat()
    if newer.st_ino == info.st_ino and newer.st_dev == info.st_dev:
        endpoint.unlink()

def connect(endpoint, helper, timeout=20):
    """Retry only before request dispatch; never replay an already-sent action."""
    try:
        return _once(endpoint, timeout)
    except OSError as exc:
        if exc.errno not in _RECOVER:
            code = "permission_denied" if exc.errno in (errno.EACCES, errno.EPERM) else "connection_failed"
            raise GUIIPCError(code, str(exc), exc.errno, endpoint) from exc
    with _recovery_lock:
        lock = endpoint.parent / '.gui-recovery.lock'
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        except OSError as exc:
            raise GUIIPCError("permission_denied", str(exc), exc.errno, endpoint) from exc
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
                raise GUIIPCError("permission_denied", "Recovery lock ownership mismatch", endpoint=endpoint)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                try:
                    return _once(endpoint, timeout)
                except OSError as exc:
                    if exc.errno not in _RECOVER:
                        raise GUIIPCError("connection_failed", str(exc), exc.errno, endpoint) from exc
                _stop_broken_helper(helper, endpoint)
                _discard_stale_socket(endpoint)
                if not helper.is_file() or helper.is_symlink():
                    raise GUIIPCError("helper_not_running", "GUI app executable missing", endpoint=endpoint)
                try:
                    result = subprocess.run(
                        ['/usr/bin/open', '-a', str(helper.parents[2]), '--args', '--serve'],
                        capture_output=True, text=True, timeout=10, check=False)
                except (OSError, subprocess.SubprocessError) as exc:
                    raise GUIIPCError("helper_not_running", str(exc), endpoint=endpoint) from exc
                if result.returncode:
                    raise GUIIPCError("helper_not_running", result.stderr[:200], endpoint=endpoint)
                last = None
                for _ in range(40):
                    try:
                        return _once(endpoint, timeout)
                    except OSError as exc:
                        last = exc
                        if exc.errno not in _RECOVER:
                            break
                    time.sleep(.15)
                code = "permission_denied" if last and last.errno in (errno.EACCES, errno.EPERM) else "connection_refused"
                raise GUIIPCError(code, "GUI helper did not open IPC endpoint",
                                  last.errno if last else None, endpoint)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
