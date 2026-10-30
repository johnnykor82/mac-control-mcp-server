"""Read-only SSH authentication diagnostics; never read private key contents."""
import os
import subprocess
from pathlib import Path

def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def ssh_auth_diagnostics() -> dict:
        """Inspect identities and SSH agent availability without exposing private keys."""
        folder = Path.home() / ".ssh"
        identities = []
        public_keys = []
        if folder.is_dir():
            for name in ("id_ed25519", "id_rsa", "id_ecdsa", "id_dsa", "id_ed25519_sk", "id_ecdsa_sk"):
                key = folder / name
                if key.is_file() and not key.is_symlink():
                    identities.append(name)
                pub = folder / (name + ".pub")
                if pub.is_file() and not pub.is_symlink():
                    public_keys.append(pub.name)
        sock = os.environ.get("SSH_AUTH_SOCK")
        out = {"home_ssh_dir_exists": folder.is_dir(),
               "default_private_key_files": identities,
               "default_public_key_files": public_keys,
               "ssh_auth_sock_set": bool(sock)}
        if sock:
            try:
                p = subprocess.run(
                    ["/usr/bin/ssh-add", "-l"],
                    capture_output=True, text=True, timeout=6,
                )
                out["agent_key_count"] = sum(
                    1 for line in p.stdout.splitlines()
                    if line.strip() and not line.startswith("The agent"))
                out["agent_has_identities"] = p.returncode == 0
                out["agent_status"] = p.returncode
            except Exception as exc:
                out["agent_error_type"] = type(exc).__name__
        return out


    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def ssh_identity_inspect(host: str = "") -> dict:
        """Inspect local key metadata; optionally resolve an owner-approved SSH profile."""
        import pwd
        import stat
        import socket
        home = Path.home()
        folder = home / ".ssh"
        files = []
        if folder.is_dir():
            for item in sorted(folder.iterdir(), key=lambda x: x.name)[:80]:
                try:
                    st = item.lstat()
                    files.append({
                        "name": item.name,
                        "kind": "symlink" if item.is_symlink() else "file" if item.is_file() else "dir",
                        "permissions": oct(stat.S_IMODE(st.st_mode)),
                        "bytes": st.st_size if item.is_file() else None,
                    })
                except OSError:
                    pass
        config = {}
        effective_exit = None
        if host:
            from .ssh_bridge_ops import _argv
            # Reuse approved profile validation, omit the remote diagnostic,
            # and disable user SSH config (including Match exec) through -F.
            argv = _argv(host, "identity")[:-1]
            argv.insert(1, "-G")
            effective = subprocess.run(
                argv, capture_output=True, text=True, timeout=8,
                stdin=subprocess.DEVNULL,
            )
            effective_exit = effective.returncode
            allowed_fields = {
                "user", "hostname", "port", "identityfile", "identityagent",
                "identitiesonly", "addkeystoagent", "usekeychain",
                "proxyjump", "pubkeyauthentication", "preferredauthentications",
            }
            for line in effective.stdout.splitlines():
                key, _, val = line.partition(" ")
                if key in allowed_fields:
                    config.setdefault(key, []).append(val[:200])
        agent = os.environ.get("SSH_AUTH_SOCK", "")
        return {
            "username": pwd.getpwuid(os.getuid()).pw_name,
            "home": str(home),
            "hostname": socket.gethostname(),
            "ssh_entries": files,
            "effective_ssh": config,
            "effective_ssh_exit": effective_exit,
            "ssh_auth_sock_present": bool(agent),
            "ssh_auth_sock_is_socket": bool(agent) and Path(agent).exists(),
        }
