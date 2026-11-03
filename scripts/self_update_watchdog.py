#!/usr/bin/env python3
"""BF-16 detached supervisor: update, check authenticated MCP, recover old release.

Executed from an immutable previously active release. No target-supplied code
is imported by the supervisor while the update is in progress.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time


def _installed_pointer(root: Path, name: str) -> Path | None:
    pointer = root / name
    if not pointer.is_symlink():
        return None
    try:
        release = pointer.resolve(strict=True)
    except OSError:
        return None
    return release if (release.parent == root / "releases"
                       and release.is_dir() and not release.is_symlink()) else None


def _current(root: Path) -> Path | None:
    return _installed_pointer(root, "current")


def _previous(root: Path) -> Path | None:
    return _installed_pointer(root, "previous")


def _service_pid(root: Path) -> int | None:
    try:
        from scripts import setup_remote_service as service
        state = service.status(root)
        if state.get("status") != "running":
            return None
        value = state.get("pid")
        pid = int(value)
        return pid if pid > 1 else None
    except (OSError, RuntimeError, ValueError, TypeError, subprocess.SubprocessError):
        return None


def _owned_running(root: Path) -> bool:
    return _service_pid(root) is not None


def _endpoint_responds(root: Path) -> bool:
    try:
        from scripts.setup_github_oauth import check
        from scripts.setup_remote_service import _endpoint_ready
        endpoint = check(root)["public_url"]
        return _endpoint_ready(endpoint)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return False


def _health(root: Path) -> bool:
    """Require owned loaded service and real OAuth challenge on 127.0.0.1."""
    return _owned_running(root) and _endpoint_responds(root)


def _preflight_health(root: Path) -> bool:
    return _health(root)


def _poll_health(root: Path, timeout: float = 45,
                 *, old_pid: int | None = None) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if _health(root):
            pid = _service_pid(root) if old_pid is not None else None
            if old_pid is None or (pid is not None and pid != old_pid):
                return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(1.0, remaining))


def _update(root: Path, baseline: Path, with_chatbridge: bool) -> int:
    command = [sys.executable, str(baseline / "scripts/maccontrol_manager.py"),
               "--root", str(root), "update",
               "--with-chatbridge" if with_chatbridge else "--without-chatbridge"]
    try:
        result = subprocess.run(command, cwd=baseline, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=1800, check=False)
        return result.returncode
    except (OSError, subprocess.TimeoutExpired):
        return -1


def _rollback(root: Path, baseline: Path) -> None:
    """The old immutable installer, not the failed target, performs rollback."""
    command = [sys.executable, str(baseline / "scripts/install_mac_control.py"),
               "--root", str(root), "--rollback"]
    result = subprocess.run(command, cwd=baseline, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=300, check=False)
    if result.returncode:
        raise RuntimeError("ROLLBACK_COMMAND_FAILED")
    from scripts.setup_remote_service import start, status
    if status(root).get("status") != "running":
        start(root)


def run_transaction(root: Path, baseline: Path, with_chatbridge: bool,
                    report, *, health_timeout: float = 45) -> str:
    """Independent transaction: only verified baseline may be restored."""
    try:
        if _current(root) != baseline or not _preflight_health(root):
            raise RuntimeError("PREFLIGHT_NOT_READY")
        initial_pid = _service_pid(root)
        if initial_pid is None:
            raise RuntimeError("PREFLIGHT_PID_UNAVAILABLE")
        report("updating")
        code = _update(root, baseline, with_chatbridge)
        if code != 0:
            raise RuntimeError("UPDATE_COMMAND_FAILED")
        # An update may be an idempotent no-op; otherwise verify its ancestry.
        current = _current(root)
        if current == baseline:
            raise RuntimeError("RELEASE_NOT_ACTIVATED")
        if current is None or _previous(root) != baseline:
            raise RuntimeError("UNVERIFIED_RELEASE_POINTERS")
        report("checking")
        if not _poll_health(root, timeout=health_timeout,
                            old_pid=initial_pid if current != baseline else None):
            raise RuntimeError("NEW_RELEASE_UNHEALTHY")
        report("verified")
        return "succeeded"
    except BaseException:
        try:
            current = _current(root)
            if current == baseline:
                return "failed"
            if current is None or _previous(root) != baseline:
                return "rollback_failed"
            report("rolling_back")
            _rollback(root, baseline)
            if _current(root) != baseline or not _poll_health(root, timeout=health_timeout):
                return "rollback_failed"
            report("restored")
            return "rolled_back"
        except BaseException:
            return "rollback_failed"


def worker(root: Path, baseline: Path, job_id: str,
           with_chatbridge: bool) -> str:
    from mac_control import self_update

    # Parent records our PID immediately after spawning. Bound the handoff.
    for _ in range(50):
        state = self_update._read(root)
        if state.get("job_id") != job_id or state.get("state") != "scheduled":
            raise RuntimeError("Self-update job identity changed")
        if state.get("pid") == os.getpid():
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("Self-update job handoff timed out")

    def report(stage: str) -> None:
        item = self_update._read(root)
        if item.get("job_id") != job_id:
            raise RuntimeError("Self-update journal changed during execution")
        self_update._record(root, {**item, "state": "running", "stage": stage})

    outcome = run_transaction(root, baseline, with_chatbridge, report)
    item = self_update._read(root)
    self_update._record(root, {**item, "state": outcome, "stage": "finished",
                               "finished_at": int(time.time()),
                               "reason": ("SUCCESS" if outcome == "succeeded"
                                          else "ROLLBACK_COMPLETED" if outcome == "rolled_back"
                                          else "UPDATE_OR_RECOVERY_FAILED")})
    return outcome


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True, action="store_true")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--lock-fd", required=True, type=int)
    browser = parser.add_mutually_exclusive_group(required=True)
    browser.add_argument("--with-chatbridge", action="store_true")
    browser.add_argument("--without-chatbridge", action="store_true")
    opts = parser.parse_args(argv)
    if len(opts.job_id) != 24 or any(c not in "0123456789abcdef" for c in opts.job_id):
        raise RuntimeError("Invalid self-update job id")
    root = opts.root.expanduser().absolute().resolve()
    baseline = opts.baseline.expanduser().resolve()
    if baseline.parent != root / "releases" or _current(root) != baseline:
        raise RuntimeError("Self-update initial release pointer mismatch")
    from mac_control import self_update
    lock_path = root / "data/run/self-update/update.lock"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise RuntimeError("Missing self-update lock")
    lock = os.fstat(opts.lock_fd)
    if (lock.st_ino != lock_path.stat().st_ino
            or lock.st_dev != lock_path.stat().st_dev):
        raise RuntimeError("Self-update lock descriptor mismatch")
    try:
        result = worker(root, baseline, opts.job_id, opts.with_chatbridge)
        return 0 if result == "succeeded" else 1
    finally:
        os.close(opts.lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
