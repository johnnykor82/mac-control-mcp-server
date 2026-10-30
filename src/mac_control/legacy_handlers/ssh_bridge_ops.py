"""SSH diagnostics for explicitly owner-approved hosts; no arbitrary remote shell."""
from ..runtime_paths import DATA_ROOT
import json
import os
import re
import subprocess
from pathlib import Path

BASE = DATA_ROOT
CONFIG = BASE / "ssh_targets.json"
SSH = "/usr/bin/ssh"
COMMANDS = {
    "identity": "id -un",
    "kernel": "uname -a",
    "uptime": "uptime",
    "disk": "df -h",
    "memory": "free -m",
    "services_failed": "systemctl --failed --no-pager --plain",
}
SAFE_HOST = re.compile(r"[a-zA-Z0-9.:-]{1,253}")
SAFE_LOGIN = re.compile(r"[a-z_][a-z0-9_-]{0,31}")

def _profiles():
    if not CONFIG.exists():
        return {}
    st = CONFIG.lstat()
    if CONFIG.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise PermissionError("ssh_targets.json must be owned by the service user and chmod 600")
    profiles = json.loads(CONFIG.read_text("utf-8")).get("hosts", {})
    if not isinstance(profiles, dict):
        raise ValueError("Invalid ssh_targets.json")
    return profiles

def _argv(name, command_id):
    data = _profiles().get(name)
    if not isinstance(data, dict):
        raise ValueError("SSH host not in owner-managed allowlist")
    if command_id not in COMMANDS:
        raise ValueError("Unknown diagnostic command")
    host = data.get("host")
    login = data.get("user")
    port = data.get("port", 22)
    if (not isinstance(host, str) or not SAFE_HOST.fullmatch(host)
        or not isinstance(login, str) or not SAFE_LOGIN.fullmatch(login)
        or not isinstance(port, int) or not 1 <= port <= 65535):
        raise ValueError("Invalid host settings")
    argv = [
        SSH, "-F", "/dev/null", "-T", "-p", str(port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=6",
        "-o", "ForwardAgent=no",
        "-o", "ClearAllForwardings=yes",
        "-o", "PermitLocalCommand=no",
        "-o", "RequestTTY=no",
        "-o", "ServerAliveInterval=5",
        "-o", "NumberOfPasswordPrompts=0",
        "-o", "LogLevel=ERROR",
    ]
    key = data.get("identity_file")
    if key:
        path = Path(key).expanduser()
        # Owner-selected key path; not included in output or logs.
        if not path.is_file() or not path.is_absolute():
            raise ValueError("Configured SSH identity not found")
        argv.extend(["-i", str(path), "-o", "IdentitiesOnly=yes"])
    # options terminated before destination; host has a restrictive grammar
    argv.extend(["--", f"{login}@{host}", COMMANDS[command_id]])
    return argv

def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def ssh_targets() -> dict:
        """List SSH servers and diagnostic command names configured locally by owner."""
        return {
            "hosts": [
                {"name": name, "host": data.get("host"),
                 "user": data.get("user"), "port": data.get("port", 22)}
                for name, data in _profiles().items() if isinstance(data, dict)
            ],
            "diagnostics": list(COMMANDS),
            "config": str(CONFIG),
        }

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def ssh_open(host: str) -> dict:
        """Open interactive SSH PTY with strict known-host checking and owner-approved host.

        Uses same tmux socket as terminal_read/terminal_send/terminal_close.
        Local terminal policy must explicitly be enabled.
        """
        import secrets
        from . import command_plugins
        command_plugins._require()
        if command_plugins.TMUX is None:
            raise RuntimeError("tmux is not installed")
        # Validation is shared with the read-only SSH diagnostic.
        ssh_args = _argv(host, "identity")[:-1]
        # Replace non-interactive flags with TTY request for interactive session.
        options = []
        i = 0
        while i < len(ssh_args):
            if ssh_args[i] == "-T":
                i += 1
                continue
            if ssh_args[i] == "-o" and i + 1 < len(ssh_args) and ssh_args[i + 1] == "RequestTTY=no":
                i += 2
                continue
            options.append(ssh_args[i])
            i += 1
        options.insert(1, "-tt")
        session = "mc-" + secrets.token_hex(8)
        command_plugins._runtime()
        result = command_plugins._tmux([
            "new-session", "-d", "-s", session,
            "-c", str(Path.home()),
            "-x", "120", "-y", "36",
            "--", *options
        ])
        if result.returncode:
            raise RuntimeError(result.stderr[:1000])
        return {
            "session": session, "host": host,
            "status": "started",
            "next": "terminal_read / terminal_send / terminal_close",
        }

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def ssh_diagnostic(host: str, command: str = "uptime") -> dict:
        """Run one fixed read-only SSH diagnostic on an owner-approved host.

        Password prompting is disabled; strict known_hosts verification is required.
        """
        argv = _argv(host, command)
        p = subprocess.run(
            argv, capture_output=True, text=True, errors="replace",
            stdin=subprocess.DEVNULL, timeout=25,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(Path.home()),
                "LANG": "C.UTF-8",
                "SSH_ASKPASS": "/usr/bin/false",
            },
        )
        return {
            "host": host,
            "command": command,
            "exit_code": p.returncode,
            "stdout": p.stdout[:16000],
            "stderr": p.stderr[:3000],
        }
