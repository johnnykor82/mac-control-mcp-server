"""Mac diagnostics, loopback probes, approved project tests, launchd inspection."""
from ..runtime_paths import DATA_ROOT
import os
import re
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path
from .fs_ops import roots, target_for, root_for_project

MAX_OUTPUT = 24000
BASE_ENV = {
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": str(Path.home()),
    "LANG": "C.UTF-8",
    "CI": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "PYTHONNOUSERSITE": "1",
}

def execute(argv, cwd, timeout):
    result = subprocess.run(
        argv, cwd=cwd, env=BASE_ENV, shell=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        errors="replace", timeout=max(2, min(int(timeout), 90)),
    )
    return {
        "argv": [Path(argv[0]).name, *argv[1:]],
        "exit_code": result.returncode,
        "stdout": result.stdout[:MAX_OUTPUT],
        "stderr": result.stderr[:8000],
        "stdout_truncated": len(result.stdout) > MAX_OUTPUT,
        "stderr_truncated": len(result.stderr) > 8000,
    }

def _managed_service():
    # The installed release is the single source of truth for the MCP port
    # and LaunchAgent identity. Never import arbitrary scripts from sys.path.
    from ..maintenance_ops import _service_helper
    return _service_helper()





def _launchd_target(label: str, domain: str = "gui", uid: int | None = None) -> str:
    if not isinstance(label,str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,119}",label):
        raise ValueError("Invalid launchd label")
    if domain not in ("gui","user","system"):
        raise ValueError("Invalid launchd domain: gui, user or system")
    if domain == "system":
        if uid is not None:
            raise ValueError("UID cannot be passed for system domain")
        return f"system/{label}"
    if uid is None:
        uid = os.getuid()
    if type(uid) is not int or not 0 <= uid <= 2**31-1:
        raise ValueError("Invalid launchd UID")
    return f"{domain}/{uid}/{label}"

def register(mcp):
    @mcp.tool(annotations={
                              'readOnlyHint': True,
                              'destructiveHint': False,
                              'idempotentHint': True,
                              'openWorldHint': False,
                          })
    def machine_health() -> dict:
        """Read disk capacity, uptime, and memory pressure summary."""
        output = {}
        for name, command in {
            "uptime": ["/usr/bin/uptime"],
            "disk": ["/bin/df", "-h", str(Path.home())],
            "memory": ["/usr/bin/memory_pressure", "-Q"],
        }.items():
            if Path(command[0]).exists():
                try:
                    output[name] = execute(command, str(Path.home()), 8)
                except Exception as exc:
                    output[name] = {"error": type(exc).__name__}
        return output

    @mcp.tool(annotations={
                              'readOnlyHint': True,
                              'destructiveHint': False,
                              'idempotentHint': True,
                              'openWorldHint': False,
                          })
    def network_listeners(limit: int = 100) -> dict:
        """List TCP listening processes and ports, without network requests."""
        limit = max(1, min(int(limit), 200))
        result = execute(
            ["/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
            str(Path.home()), 10,
        )
        return {**result, "stdout": "\n".join(result["stdout"].splitlines()[:limit + 1])}

    @mcp.tool(annotations={
                              'readOnlyHint': True,
                              'destructiveHint': False,
                              'idempotentHint': True,
                              'openWorldHint': False,
                          })
    def local_http_probe(port: int | None = None, path: str = "/", method: str = "GET") -> dict:
        """Probe ANY TCP port on loopback (1..65535), GET/HEAD, no redirects or credentials."""
        active_mcp_port = _managed_service().PORT
        if port is None:
            port = active_mcp_port
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Local TCP port must be an integer 1..65535")
        if (method not in ("GET", "HEAD") or not isinstance(path, str)
                or not path.startswith("/") or len(path) > 2048 or "#" in path
                or any(ord(char) <= 32 or ord(char) == 127 for char in path)
                or urllib.parse.urlsplit(path).netloc):
            raise ValueError("Unsupported method or unsafe HTTP path")
        decoded = path.split("?", 1)[0]
        for _ in range(3):
            if any(part == ".." for part in decoded.split("/")):
                raise ValueError("Unsafe path traversal")
            decoded = urllib.parse.unquote(decoded)
        url = f"http://127.0.0.1:{port}{path}"
        request = urllib.request.Request(url, method=method)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        handler = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPHandler(),
            NoRedirect(),
        )
        try:
            with handler.open(request, timeout=5) as response:
                data = response.read(12000)
                return {"status": response.status, "body_preview": data.decode("utf-8", "replace"),
                        "content_type": response.headers.get("content-type")}
        except urllib.error.HTTPError as exc:
            data = exc.read(2000)
            return {"status": exc.code, "body_preview": data.decode("utf-8", "replace")}

    @mcp.tool(annotations={
                              'readOnlyHint': True,
                              'destructiveHint': False,
                              'idempotentHint': True,
                              'openWorldHint': False,
                          })
    def launchd_status(label: str = "", domain: str = "gui", uid: int | None = None) -> dict:
        """Inspect owner-authorized launchd gui/user/system service by OS rights.

        Default gui/current UID. Other domains or users require explicit
        owner permission for the particular task; no sudo or policy bypass.
        """
        if not label:
            label = _managed_service().LABEL
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,119}", label):
            raise ValueError("Invalid launchd label")
        query = _launchd_target(label, domain, uid)
        result = execute(["/bin/launchctl", "print", query],
                         str(Path.home()), 8)
        original = result["stdout"]
        state = re.search(r"^\s*state = (\S+)", original, re.M)
        pid = re.search(r"^\s*pid = (\d+)", original, re.M)
        result["stdout"] = "\n".join(
            line.strip() for line in original.splitlines()
            if any(key in line for key in
                   ("state =", "pid =", "last exit code =", "runs =",
                    "program =", "path =", "throttle interval ="))
        )[:6000]
        return {**result, "label": label, "state": state.group(1) if state else None,
                "pid": int(pid.group(1)) if pid else None}

    @mcp.tool(annotations={
                              'readOnlyHint': False,
                              'destructiveHint': True,
                              'idempotentHint': False,
                              'openWorldHint': False,
                          })
    def launchd_restart(label: str, domain: str = "gui", uid: int | None = None) -> dict:
        """Restart task-authorized launchd service in GUI/user/system namespace.

        Default current GUI user; nondefault domains need specific owner
        authorization and macOS permissions. Use restart_server for own MCP.
        """
        if label == _managed_service().LABEL:
            raise ValueError("Use restart_server for the MCP agent")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,119}", label):
            raise ValueError("Invalid label")
        target = _launchd_target(label, domain, uid)
        return execute(["/bin/launchctl", "kickstart", "-k",
                        target], str(Path.home()), 20)

    @mcp.tool(annotations={
                              'readOnlyHint': False,
                              'destructiveHint': True,
                              'idempotentHint': False,
                              'openWorldHint': False,
                          })
    def project_task(project: str, task: str, path: str = "") -> dict:
        """Run a named test shortcut OR an arbitrary shell-free argv command in an approved project.

        AgentWorkspace is the default working directory. Operations elsewhere
        require explicit owner permission for the specific task; do not claim
        that an audit field alone grants permission. Use terminal_exec for pipes.
        """
        project_root = root_for_project(project)
        cwd = str(project_root)
        if task == "python_compile":
            _, target = target_for(project, path, require_file=True)
            if target.suffix != ".py":
                raise ValueError("Provide a Python source file")
            data = target.read_bytes()
            if len(data) > 512 * 1024:
                raise ValueError("File too large")
            compile(data, str(target), "exec")
            return {"task": task, "path": path, "result": "syntax_ok"}
        if task == "pytest":
            python = project_root / ".venv/bin/python"
            if not python.is_file() or not os.access(python, os.X_OK):
                raise ValueError("pytest requires the project's .venv/bin/python; "
                                 "use the terminal_exec tool for another environment")
            command = [str(python), "-m", "pytest", "-q", "--disable-warnings"]
        elif task == "npm_test":
            command = [shutil.which("npm") or "/opt/homebrew/bin/npm", "test", "--", "--runInBand"]
        elif task == "npm_build":
            command = [shutil.which("npm") or "/opt/homebrew/bin/npm", "run", "build"]
        else:
            if not isinstance(task, str) or not task or "\x00" in task or len(task) > 8192:
                raise ValueError("Task command must be a nonempty argv string <=8192 characters")
            try:
                command = shlex.split(task)
            except ValueError as exc:
                raise ValueError("Invalid project command quoting") from exc
            if not command or any(not part or "\x00" in part for part in command):
                raise ValueError("Invalid project command arguments")
        return execute(command, cwd, 60)
