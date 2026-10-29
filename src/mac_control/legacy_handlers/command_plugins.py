"""Terminal operations. Disabled until the Mac owner creates terminal_policy.json.

Arbitrary shell commands run as the macOS account running this server.
Working-directory selection is not a sandbox. Do not enable on an untrusted MCP.
"""
from ..runtime_paths import DATA_ROOT
import hashlib
import json
import os
import getpass
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from .fs_ops import roots, WORKSPACE

BASE = DATA_ROOT
POLICY = BASE / "terminal_policy.json"
RUNTIME = BASE / "run"
SOCKET = RUNTIME / "tmux.sock"
MAX_TEXT = 16_000
ENVIRONMENT = {
    "HOME": str(Path.home()),
    "USER": os.environ.get("USER") or getpass.getuser(),
    "PATH": ":".join([
        str(Path.home() / ".local/bin"),
        "/opt/homebrew/bin",
        "/opt/homebrew/Caskroom/miniforge/base/bin",
        "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
    ]),
    "LANG": "en_US.UTF-8",
    "TERM": "xterm-256color",
    "CI": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "PYTHONNOUSERSITE": "1",
    # Prefer the agent workspace rather than /tmp for temporary artifacts.
    "TMPDIR": str(WORKSPACE / "scratch/tmp"),
    "TMP": str(WORKSPACE / "scratch/tmp"),
    "TEMP": str(WORKSPACE / "scratch/tmp"),
    "XDG_CACHE_HOME": str(WORKSPACE / "scratch/cache"),
}
KEYS = {
    "Enter", "C-c", "C-d", "C-z", "Tab", "Escape", "BSpace",
    "Up", "Down", "Left", "Right", "Home", "End", "PageUp", "PageDown",
}
TMUX = next((p for p in ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux") if Path(p).is_file()), shutil.which("tmux"))
SHELL = "/bin/zsh"

def _enabled():
    if POLICY.is_symlink() or not POLICY.is_file():
        return False
    info = POLICY.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError("terminal_policy.json must be owner-only (chmod 600)")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    return policy.get("enabled") is True

def _require():
    if not _enabled():
        raise PermissionError(
            "Terminal disabled. Owner must explicitly create "
            f"{POLICY} with enabled: true"
        )

def _cwd(project):
    if project == "workspace":
        for path in (WORKSPACE / "scratch/tmp", WORKSPACE / "scratch/cache"):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
    available = roots()
    if project not in available:
        raise PermissionError("Project root not approved")
    return str(available[project].resolve())

def _runtime():
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    RUNTIME.chmod(0o700)

def _tmux(args, *, timeout=8, env=None):
    if TMUX is None:
        raise RuntimeError("tmux missing; install with brew install tmux")
    _runtime()
    call = [TMUX, "-S", str(SOCKET), *args]
    return subprocess.run(
        call, capture_output=True, text=True, errors="replace",
        stdin=subprocess.DEVNULL, timeout=timeout,
        env=env or ENVIRONMENT,
    )

def _session(session):
    if not isinstance(session, str) or not session.startswith("mc-"):
        raise ValueError("Invalid session ID")
    tail = session[3:]
    if len(tail) != 16 or any(c not in "0123456789abcdef" for c in tail):
        raise ValueError("Invalid session ID")
    check = _tmux(["has-session", "-t", f"={session}"])
    if check.returncode:
        raise ValueError("Unknown or expired session")
    return session

def _screen(session, lines):
    n = max(10, min(int(lines), 250))
    r = _tmux([
        "capture-pane", "-p", "-J", "-t", f"{session}:0.0",
        "-S", f"-{n}",
    ])
    if r.returncode:
        raise RuntimeError(r.stderr[:1000])
    body = r.stdout[-MAX_TEXT:]
    return {"session": session, "screen": body, "chars": len(body),
            "truncated": len(r.stdout) > MAX_TEXT}

def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def terminal_capabilities() -> dict:
        """Show terminal availability and local opt-in status."""
        try:
            enabled = _enabled()
            error = None
        except Exception as exc:
            enabled, error = False, str(exc)
        return {
            "enabled": enabled, "policy": str(POLICY),
            "policy_error": error,
            "tmux_path": TMUX, "shell": SHELL,
            "user": ENVIRONMENT["USER"],
            "projects": sorted(roots()),
            "interactive": TMUX is not None,
            "security": "Shell executes as service user, not sandboxed",
        }

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def terminal_exec(command: str, project: str = "workspace", timeout_seconds: int = 25) -> dict:
        """Run arbitrary noninteractive zsh command with bounded time and captured output."""
        _require()
        if not command or len(command) > 8000 or "\x00" in command:
            raise ValueError("Invalid command")
        cwd = _cwd(project)
        timeout = max(1, min(int(timeout_seconds), 120))
        _runtime()
        # Avoid accumulating unbounded stdout/stderr in the MCP worker.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            proc = subprocess.Popen(
                [SHELL, "-f", "-c", command], cwd=cwd,
                env=ENVIRONMENT, stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, start_new_session=True,
            )
            expired = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                expired = True
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            def collect(stream):
                size = stream.tell()
                stream.seek(0)
                data = stream.read(min(size, MAX_TEXT))
                return data.decode("utf-8", "replace"), size > MAX_TEXT, size
            out, out_trunc, out_bytes = collect(stdout)
            err, err_trunc, err_bytes = collect(stderr)
        return {
            "exit_code": proc.returncode, "timed_out": expired,
            "stdout": out, "stderr": err,
            "stdout_bytes": out_bytes, "stderr_bytes": err_bytes,
            "stdout_truncated": out_trunc, "stderr_truncated": err_trunc,
            "project": project,
        }

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def terminal_open(project: str = "workspace", width: int = 120, height: int = 36) -> dict:
        """Create persistent tmux PTY session, usable across MCP reconnections/restarts."""
        _require()
        cwd = _cwd(project)
        name = "mc-" + secrets.token_hex(8)
        size = [str(max(60, min(width, 240))), str(max(16, min(height, 90)))]
        r = _tmux(
            ["new-session", "-d", "-s", name, "-c", cwd,
             "-x", size[0], "-y", size[1], SHELL, "-f"],
            env=ENVIRONMENT,
        )
        if r.returncode:
            raise RuntimeError(r.stderr[:2000])
        return {"session": name, "project": project, "cols": int(size[0]),
                "rows": int(size[1]),
                "attach_command": f"tmux -S {SOCKET} attach -t {name}"}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def terminal_read(session: str, lines: int = 100) -> dict:
        """Read current tmux PTY screen and scrollback; no keys are sent."""
        _require()
        return _screen(_session(session), lines)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def terminal_send(session: str, text: str = "", key: str = "") -> dict:
        """Type literal text and/or a terminal key (Enter, C-c, arrows). Avoid secrets in chat."""
        _require()
        session = _session(session)
        if len(text) > 4000 or "\x00" in text:
            raise ValueError("Invalid terminal text")
        if key and key not in KEYS:
            raise ValueError("Unsupported key")
        if not text and not key:
            raise ValueError("Supply text or key")
        if text:
            r = _tmux(["send-keys", "-t", f"{session}:0.0", "-l", "--", text])
            if r.returncode:
                raise RuntimeError(r.stderr[:2000])
        if key:
            r = _tmux(["send-keys", "-t", f"{session}:0.0", key])
            if r.returncode:
                raise RuntimeError(r.stderr[:2000])
        return {"session": session, "characters_typed": len(text),
                "key": key, "status": "sent"}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def terminal_resize(session: str, width: int = 120, height: int = 36) -> dict:
        """Resize interactive terminal pane for menus and editors."""
        _require()
        session = _session(session)
        cols = max(60, min(int(width), 240))
        rows = max(16, min(int(height), 90))
        result = _tmux(["resize-window", "-t", f"{session}:0", "-x", str(cols), "-y", str(rows)])
        if result.returncode:
            raise RuntimeError(result.stderr[:1000])
        return {"session": session, "cols": cols, "rows": rows}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def terminal_list() -> dict:
        """List active persistent terminal sessions."""
        _require()
        result = _tmux(["list-sessions", "-F", "#{session_name}|#{session_created}|#{session_attached}"])
        if result.returncode:
            return {"sessions": []}
        sessions = []
        for row in result.stdout.splitlines():
            cells = row.split("|")
            if len(cells) == 3 and cells[0].startswith("mc-"):
                sessions.append({
                    "session": cells[0],
                    "created_epoch": cells[1],
                    "attached": cells[2] == "1",
                })
        return {"sessions": sessions}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def terminal_close(session: str) -> dict:
        """Terminate one explicitly identified interactive terminal session."""
        _require()
        session = _session(session)
        r = _tmux(["kill-session", "-t", f"={session}"])
        if r.returncode:
            raise RuntimeError(r.stderr[:1000])
        return {"closed": session}


    # Downstream MCP and SSH hosts require separate owner-managed allowlists.
    from .mcp_bridge_ops import register as register_mcp_bridge
    from .ssh_bridge_ops import register as register_ssh_bridge
    register_mcp_bridge(mcp)
    register_ssh_bridge(mcp)

    from .ssh_manage_ops import register as register_ssh_manage
    register_ssh_manage(mcp)

    from .ssh_auth_diag import register as register_ssh_auth_diag
    register_ssh_auth_diag(mcp)

    from .package_ops import register as register_package_ops
    register_package_ops(mcp)

    from .gui_ops import register as register_gui_ops
    register_gui_ops(mcp)

    from .chrome_orchestrator_ops import register as register_chrome_orchestrator
    register_chrome_orchestrator(mcp)

    from .watcher_ops import register as register_watcher_ops
    register_watcher_ops(mcp)
