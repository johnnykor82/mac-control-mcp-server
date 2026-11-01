"""Mac diagnostics, loopback probes, approved project tests, launchd inspection."""
from ..runtime_paths import DATA_ROOT
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from .fs_ops import roots, target_for

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


def _launchd_labels():
    # Keep historic labels opt-in only (through allowed_services.txt).
    return {_managed_service().LABEL, "org.maccontrol.mcpserver.watcher"}


def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
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

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def network_listeners(limit: int = 100) -> dict:
        """List TCP listening processes and ports, without network requests."""
        limit = max(1, min(int(limit), 200))
        result = execute(
            ["/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
            str(Path.home()), 10,
        )
        return {**result, "stdout": "\n".join(result["stdout"].splitlines()[:limit + 1])}

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def local_http_probe(port: int | None = None, path: str = "/", method: str = "GET") -> dict:
        """Probe approved localhost HTTP ports without credentials or redirects."""
        active_mcp_port = _managed_service().PORT
        if port is None:
            port = active_mcp_port
        if type(port) is not int or port not in (3000, 4000, 8000, 8080, 11434, 9333, active_mcp_port):
            raise PermissionError("Local port not on approved list")
        if (method not in ("GET", "HEAD")
                or not re.fullmatch(r"/[a-zA-Z0-9_./?=&%-]{0,180}", path)
                or any(segment == ".." for segment in path.split("?")[0].split("/"))):
            raise ValueError("Unsupported method or path")
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

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def launchd_status(label: str = "") -> dict:
        """Inspect own LaunchAgent or another locally approved label."""
        if not label:
            label = _managed_service().LABEL
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", label):
            raise ValueError("Invalid launchd label")
        allowlist = _launchd_labels()
        cfg = Path(__file__).resolve().parent.parent / "allowed_services.txt"
        if cfg.is_file() and not cfg.is_symlink():
            allowlist.update(
                x.strip() for x in cfg.read_text().splitlines()
                if re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", x.strip())
            )
        if label not in allowlist:
            raise PermissionError("Service is not locally approved")
        query = f"gui/{os.getuid()}/{label}"
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

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def launchd_restart(label: str) -> dict:
        """Restart ONLY a locally allowlisted LaunchAgent. Mac Control uses restart_server instead."""
        if label == _managed_service().LABEL:
            raise ValueError("Use restart_server for the MCP agent")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", label):
            raise ValueError("Invalid label")
        cfg = Path(__file__).resolve().parent.parent / "allowed_services.txt"
        allowed = (
            set(x.strip() for x in cfg.read_text().splitlines()
                if re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", x.strip()))
            if cfg.is_file() and not cfg.is_symlink() else set()
        )
        if label not in allowed:
            raise PermissionError("Label must be explicitly enabled locally")
        return execute(["/bin/launchctl", "kickstart", "-k",
                        f"gui/{os.getuid()}/{label}"], str(Path.home()), 20)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def project_task(project: str, task: str, path: str = "") -> dict:
        """Run one approved project test or build; test/build scripts can execute project code."""
        allowed = roots()
        if project not in allowed:
            raise PermissionError("Project not allowed")
        cwd = str(allowed[project])
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
            python = allowed[project] / ".venv/bin/python"
            if not python.is_file() or not os.access(python, os.X_OK):
                raise ValueError("pytest requires the project's .venv/bin/python; "
                                 "use the terminal_exec tool for another environment")
            command = [str(python), "-m", "pytest", "-q", "--disable-warnings"]
        elif task == "npm_test":
            command = [shutil.which("npm") or "/opt/homebrew/bin/npm", "test", "--", "--runInBand"]
        elif task == "npm_build":
            command = [shutil.which("npm") or "/opt/homebrew/bin/npm", "run", "build"]
        else:
            raise ValueError("Tasks: python_compile, pytest, npm_test, npm_build")
        return execute(command, cwd, 60)
