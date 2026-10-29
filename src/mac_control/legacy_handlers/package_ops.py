"""Homebrew package management and terminal-access controls.

Installed formula names are restricted to simple Homebrew/core-style identifiers.
No shell command strings, sudo, casks, taps, or arbitrary installer URLs.
"""
from ..runtime_paths import DATA_ROOT
import json
import os
import getpass
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = DATA_ROOT
STATE = ROOT / "run" / "package-jobs"
POLICY = ROOT / "terminal_policy.json"
FORMULA = re.compile(r"[a-z][a-z0-9+._@-]{0,63}\Z")
JOB_ID = re.compile(r"[a-f0-9]{16}\Z")

def brew():
    for path in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if Path(path).is_file():
            return path
    return None

def _run(argv, timeout=10):
    return subprocess.run(
        argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        errors="replace", timeout=timeout,
        env={
            "HOME": str(Path.home()),
            "USER": os.environ.get("USER") or getpass.getuser(),
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "HOMEBREW_NO_AUTO_UPDATE": "1",
            "HOMEBREW_NO_ANALYTICS": "1",
            "HOMEBREW_NO_ENV_HINTS": "1",
        },
    )

def _status(job_id):
    if not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid job ID")
    folder = STATE / job_id
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Job not found")
    info = json.loads((folder / "status.json").read_text("utf-8"))
    log = folder / "output.log"
    if log.is_file():
        size = log.stat().st_size
        with log.open("rb") as stream:
            stream.seek(max(size - 12000, 0))
            chunk = stream.read().decode("utf-8", "replace")
        info["log_tail"] = chunk
        info["log_bytes"] = size
    return info

def _persist(folder, info):
    dest = folder / "status.json"
    tmp = folder / ".status-tmp"
    tmp.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)

def _worker(job_id, name):
    folder = STATE / job_id
    info = json.loads((folder / "status.json").read_text())
    info.update({"status": "running", "started_epoch": time.time(), "worker_pid": os.getpid()})
    _persist(folder, info)
    executable = brew()
    if not executable:
        info.update({"status": "error", "error": "Homebrew not installed"})
        _persist(folder, info)
        return 127
    with (folder / "output.log").open("ab") as log:
        log.write(f"Installing Homebrew formula: {name}\n".encode())
        log.flush()
        try:
            result = subprocess.run(
                [executable, "install", "--formula", name],
                stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, timeout=900,
                env={
                    "HOME": str(Path.home()),
                    "USER": os.environ.get("USER") or getpass.getuser(),
                    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                    "HOMEBREW_NO_AUTO_UPDATE": "1",
                    "HOMEBREW_NO_ANALYTICS": "1",
                    "HOMEBREW_NO_ENV_HINTS": "1",
                    "NONINTERACTIVE": "1",
                },
            )
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
            log.write(b"\nTimed out after 900 seconds\n")
        except Exception as e:
            code = 1
            log.write(("\nWorker exception: " + type(e).__name__ + "\n").encode())
    info.update({"status": "completed" if code == 0 else "failed",
                 "exit_code": code, "finished_epoch": time.time()})
    _persist(folder, info)
    return code

def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def package_capabilities() -> dict:
        """Check Homebrew and tmux installation without executing shell scripts."""
        binary = brew()
        result = {"brew_path": binary,
                  "tmux_path": shutil.which("tmux"),
                  "formula_installs_supported": binary is not None}
        if binary:
            test = _run([binary, "--version"])
            result["brew_version"] = test.stdout.strip()[:250]
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def package_installed(formula: str) -> dict:
        """Test whether a Homebrew formula is installed."""
        if not isinstance(formula, str) or not FORMULA.fullmatch(formula):
            raise ValueError("Invalid formula")
        executable = brew()
        if not executable:
            return {"formula": formula, "installed": False, "reason": "Homebrew unavailable"}
        response = _run([executable, "list", "--versions", formula], timeout=20)
        return {"formula": formula, "installed": response.returncode == 0,
                "version": response.stdout.strip()[:250]}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def package_install(formula: str) -> dict:
        """Install one validated Homebrew formula asynchronously; poll package_job_status.

        This executes upstream package-install scripts as the Mac user.
        """
        if not isinstance(formula, str) or not FORMULA.fullmatch(formula):
            raise ValueError("Formula must be a simple Homebrew formula name")
        if not brew():
            raise RuntimeError("Homebrew is not installed")
        STATE.mkdir(parents=True, mode=0o700, exist_ok=True)
        STATE.chmod(0o700)
        if len(list(STATE.iterdir())) > 100:
            raise RuntimeError("Too many package jobs; clean old job records locally")
        job_id = secrets.token_hex(8)
        folder = STATE / job_id
        folder.mkdir(mode=0o700)
        status = {
            "job_id": job_id, "formula": formula,
            "status": "queued", "created_epoch": time.time(),
        }
        _persist(folder, status)
        with (folder / "output.log").open("wb") as output:
            p = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()),
                 "--install", job_id, formula],
                stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT,
                close_fds=True, start_new_session=True,
                env={"HOME": str(Path.home()), "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                     "PYTHONNOUSERSITE": "1"},
            )
        return {"job_id": job_id, "formula": formula,
                "worker_pid": p.pid, "status": "queued",
                "poll_operation": "package_job_status"}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def package_job_status(job_id: str) -> dict:
        """Get current or completed Homebrew install log and exit code."""
        return _status(job_id)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def terminal_access_configure(enabled: bool) -> dict:
        """Explicitly enable/disable interactive and noninteractive Mac shell access.

        WARNING: Any command can read or modify files accessible to the
        Mac Control service account. This is not a sandbox.
        """
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        if POLICY.is_symlink():
            raise PermissionError("Refusing symlinked terminal policy")
        if POLICY.exists():
            st = POLICY.stat()
            if st.st_uid != os.getuid() or st.st_mode & 0o077:
                raise PermissionError("Policy must be owned by current user, chmod 600")
        temp = ROOT / (".terminal-policy-" + secrets.token_hex(6))
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"enabled": enabled}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, POLICY)
        finally:
            if temp.exists():
                temp.unlink()
        return {"terminal_enabled": enabled, "policy": str(POLICY),
                "effective_user": os.getuid(),
                "note": "Shell commands run with all privileges of the service user"}

if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--install":
        job, formula = sys.argv[2], sys.argv[3]
        if not JOB_ID.fullmatch(job) or not FORMULA.fullmatch(formula):
            sys.exit(2)
        sys.exit(_worker(job, formula))
    sys.exit(2)
