"""SSH management for explicitly registered hosts, without exposing credentials."""
from ..runtime_paths import DATA_ROOT
import json
import os
import re
import secrets
import subprocess
from pathlib import Path

BASE = DATA_ROOT
CONFIG = BASE / "ssh_managed_hosts.json"
SSH_CONFIG = Path.home() / ".ssh" / "config"
SSH = "/usr/bin/ssh"
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}")
USER = re.compile(r"[a-zA-Z_][a-zA-Z0-9_-]{0,63}")
MAX_OUT = 24000

def _read_config():
    if CONFIG.is_symlink():
        raise PermissionError("Symlinked host configuration is not allowed")
    if not CONFIG.exists():
        return {}
    st = CONFIG.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise PermissionError("SSH host config must be chmod 600 and owned by service user")
    raw = json.loads(CONFIG.read_text("utf-8"))
    hosts = raw.get("hosts", {})
    if not isinstance(hosts, dict):
        raise ValueError("Invalid SSH configuration")
    return hosts

def _write_config(hosts):
    if CONFIG.exists():
        _read_config() # verify ownership and permissions first
    temp = CONFIG.with_name(".ssh-managed-" + secrets.token_hex(6))
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump({"hosts": hosts}, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, CONFIG)
    finally:
        if temp.exists():
            temp.unlink()

def _inventory():
    if not SSH_CONFIG.exists() or SSH_CONFIG.is_symlink():
        return []
    if SSH_CONFIG.stat().st_size > 256 * 1024:
        raise ValueError("SSH config file too large")
    result = set()
    for line in SSH_CONFIG.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) > 1 and parts[0].lower() == "host":
            for host in parts[1:]:
                if NAME.fullmatch(host) and not any(c in host for c in ("*", "?", "!")):
                    result.add(host)
    return sorted(result)

def _spec(name):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("Invalid host label")
    cfg = _read_config().get(name)
    if not isinstance(cfg, dict):
        raise PermissionError("Host is not approved")
    return cfg

def _command(name, remote_cmd=None, interactive=False):
    cfg = _spec(name)
    argv = [
        SSH, "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=8",
        "-o", "ConnectionAttempts=1",
        "-o", "ForwardAgent=no",
        "-o", "ClearAllForwardings=yes",
        "-o", "PermitLocalCommand=no",
        "-o", "NumberOfPasswordPrompts=0",
        "-o", "ControlMaster=no",
        "-o", "LogLevel=ERROR",
    ]
    if cfg["kind"] == "alias":
        # Owner's ~/.ssh/config can supply ProxyJump and identity configuration.
        if not SSH_CONFIG.exists():
            raise FileNotFoundError("SSH config is not present")
        argv += ["-F", str(SSH_CONFIG)]
        dest = cfg["alias"]
    elif cfg["kind"] == "direct":
        argv += ["-F", "/dev/null"]
        argv += ["-p", str(cfg["port"])]
        identity = cfg.get("identity_file")
        if identity:
            key = Path(identity).expanduser()
            if not key.is_file() or key.is_symlink():
                raise FileNotFoundError("SSH identity key is not a regular file")
            argv += ["-i", str(key), "-o", "IdentitiesOnly=yes"]
        dest = cfg["user"] + "@" + cfg["host"]
    else:
        raise ValueError("Unknown profile type")
    argv += ["-tt" if interactive else "-T", "--", dest]
    if remote_cmd is not None:
        argv.append(remote_cmd)
    return argv

def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def ssh_profile_inventory() -> dict:
        """List SSH aliases from ~/.ssh/config (not credentials) and approved profiles."""
        profiles = _read_config()
        return {"existing_ssh_aliases": _inventory(),
                "approved": [{"name": name, "kind": cfg.get("kind")}
                             for name, cfg in sorted(profiles.items())],
                "configuration": str(CONFIG)}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def ssh_profile_approve_alias(name: str) -> dict:
        """Approve one existing ~/.ssh/config Host alias for later SSH commands."""
        if name not in _inventory():
            raise ValueError("Alias not found in ~/.ssh/config")
        hosts = _read_config()
        if name in hosts and hosts[name] != {"kind": "alias", "alias": name}:
            raise ValueError("Name already used for a different host")
        hosts[name] = {"kind": "alias", "alias": name}
        _write_config(hosts)
        return {"approved": name, "kind": "alias", "ready_to_connect": True}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def ssh_profile_register(
        name: str, host: str, user: str, port: int = 22,
        identity_file: str = "",
    ) -> dict:
        """Register one SSH host. Existing known_hosts trust and SSH key are still required."""
        if (not NAME.fullmatch(name) or not HOST.fullmatch(host)
            or not USER.fullmatch(user) or not 1 <= port <= 65535):
            raise ValueError("Invalid SSH host parameters")
        if identity_file:
            key = Path(identity_file).expanduser()
            if (not key.is_absolute() or not key.is_file() or key.is_symlink()
                or not key.is_relative_to(Path.home() / ".ssh")):
                raise ValueError("Identity file must exist under ~/.ssh")
        cfg = {"kind": "direct", "host": host, "user": user,
               "port": port, "identity_file": identity_file}
        hosts = _read_config()
        if name in hosts and hosts[name] != cfg:
            raise ValueError("Duplicate host label; refusing overwrite")
        hosts[name] = cfg
        _write_config(hosts)
        return {"approved": name, "host": host, "user": user, "port": port}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def ssh_exec(host: str, command: str, timeout_seconds: int = 30) -> dict:
        """Execute one remote shell command on a registered SSH host and return stdout/stderr/status.

        Commands run with the remote login user's permissions. Do not send passwords.
        """
        if not isinstance(command, str) or not command or len(command) > 5000:
            raise ValueError("Invalid remote command")
        argv = _command(host, command)
        timeout = max(2, min(int(timeout_seconds), 120))
        try:
            r = subprocess.run(
                argv, capture_output=True, text=True, errors="replace",
                timeout=timeout, stdin=subprocess.DEVNULL,
                env={
                    "HOME": str(Path.home()), "PATH": "/usr/bin:/bin",
                    "SSH_ASKPASS": "/usr/bin/false",
                    "SSH_ASKPASS_REQUIRE": "never",
                    "LANG": "C.UTF-8",
                },
            )
            return {"host": host, "exit_code": r.returncode,
                    "stdout": r.stdout[:MAX_OUT], "stderr": r.stderr[:8000],
                    "stdout_truncated": len(r.stdout) > MAX_OUT,
                    "stderr_truncated": len(r.stderr) > 8000}
        except subprocess.TimeoutExpired:
            return {"host": host, "timed_out": True, "timeout_seconds": timeout}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def ssh_pty_open(host: str) -> dict:
        """Open interactive SSH session in a persistent tmux PTY using approved profile."""
        from . import command_plugins
        command_plugins._require()
        if command_plugins.TMUX is None:
            raise RuntimeError("tmux required for interactive SSH")
        argv = _command(host, interactive=True)
        name = "mc-" + secrets.token_hex(8)
        command_plugins._runtime()
        r = command_plugins._tmux([
            "new-session", "-d", "-s", name, "-c", str(Path.home()),
            "-x", "120", "-y", "36", "--", *argv,
        ])
        if r.returncode:
            raise RuntimeError(r.stderr[:1200])
        return {"session": name, "host": host,
                "read": "terminal_read", "send": "terminal_send",
                "close": "terminal_close"}
