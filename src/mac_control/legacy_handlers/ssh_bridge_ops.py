"""Owner-approved SSH commands, direct hosts and legacy diagnostic shortcuts."""
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
    """Resolve diagnostics through the same OpenSSH profile as SSH and SFTP."""
    if not isinstance(command_id,str) or not command_id or len(command_id.encode("utf-8"))>65536 or "\x00" in command_id:
        raise ValueError("SSH command must be nonempty and at most 65536 bytes")
    from .ssh_manage_ops import _command
    return _command(name, COMMANDS.get(command_id, command_id))


def register(mcp):
    @mcp.tool(annotations={
                              'readOnlyHint': True,
                              'destructiveHint': False,
                              'idempotentHint': True,
                              'openWorldHint': False,
                          })
    def ssh_targets() -> dict:
        """List SSH servers and diagnostic command names configured locally by owner."""
        from .ssh_manage_ops import _inventory
        saved = _profiles()
        return {
            "hosts": [{"name": name} for name in sorted(set(_inventory()) | set(saved))],
            "diagnostics": list(COMMANDS),
            "source": "OpenSSH config; saved profiles optional",
        }


    @mcp.tool(annotations={
                              'readOnlyHint': False,
                              'destructiveHint': True,
                              'idempotentHint': False,
                              'openWorldHint': False,
                          })
    def ssh_open(host: str) -> dict:
        """Open interactive owner-approved SSH PTY with accept-new first contact and changed-host rejection.

        Uses same tmux socket as terminal_read/terminal_send/terminal_close.
        Uses the owner's existing OpenSSH settings without host registration.
        """
        import secrets
        from . import command_plugins
        if command_plugins._tmux_available() is None:
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

    @mcp.tool(annotations={
                              'readOnlyHint': False,
                              'destructiveHint': True,
                              'idempotentHint': False,
                              'openWorldHint': False,
                          })
    def ssh_diagnostic(host: str, command: str = "uptime") -> dict:
        """Run any task-authorized remote command (legacy shortcuts still supported).

        This may mutate the remote system: explicit owner authorization for the
        particular task is required. New SSH host keys are accepted on first
        contact; changed known_hosts identities are rejected by OpenSSH.
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
