"""Mac Control graphical UI tools.

The signed GUI helper performs all AppKit/Quartz/Accessibility operations.
The MCP server never records screenshot base64 in its audit log.
"""
from ..runtime_paths import DATA_ROOT
import base64
import json
import os
import re
import secrets
import select
import subprocess
import time
from pathlib import Path
import functools
import socket
from . import gui_ipc_recovery as _gui_ipc

BASE = DATA_ROOT
GUI_APP = (Path(os.environ["MAC_CONTROL_GUI_APP"]).expanduser() if os.environ.get("MAC_CONTROL_GUI_APP")
           else (BASE.parent / "apps/MacControlMCPServer.app" if os.environ.get("MAC_CONTROL_DATA_ROOT")
                 else Path.home() / "Applications/MacControlGUIDev.app"))
GUI_EXECUTABLE = "MacControlMCPServer" if GUI_APP.name == "MacControlMCPServer.app" else "MacControlGUIDev"
HELPER = GUI_APP / "Contents" / "MacOS" / GUI_EXECUTABLE
CAPTURES = BASE / "run" / "gui-captures"
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_ARGS = 3000
GUI_CLIPBOARD_HELPER = Path(__file__).resolve().parents[3] / "build" / "gui_clipboard_paste"
BUNDLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,180}\Z")

def _call(op, timeout=20, **options):
    if not HELPER.is_file() or HELPER.is_symlink():
        raise _gui_ipc.GUIIPCError(
            "helper_not_running", "GUI helper not installed", endpoint=BASE / "run" / "maccontrol-gui.sock")
    req = {"op": op, **options}
    if len(json.dumps(req, ensure_ascii=False)) > MAX_ARGS:
        raise ValueError("GUI arguments too long")
    endpoint = BASE / "run" / "maccontrol-gui.sock"
    # Auto-reconnect only BEFORE dispatch. Never replay writes after sendall().
    connection = _gui_ipc.connect(endpoint, HELPER, timeout)
    with connection:
        try:
            connection.sendall(json.dumps(req, ensure_ascii=False).encode("utf-8"))
            connection.shutdown(socket.SHUT_WR)
            chunks = []
            size = 0
            while True:
                chunk = connection.recv(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise ValueError("GUI response too large")
                chunks.append(chunk)
        except OSError as exc:
            raise _gui_ipc.GUIIPCError(
                "connection_lost", "Helper disconnected after dispatch; request not retried",
                exc.errno, endpoint) from exc
    try:
        data = json.loads(b"".join(chunks).decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise _gui_ipc.GUIIPCError(
            "invalid_helper_response", "GUI helper returned non-JSON response", endpoint=endpoint) from exc
    if data.get("ok") is not True:
        raise RuntimeError(str(data.get("error", "GUI helper rejected request")))
    _gui_ipc.mark_success(endpoint)
    return data["data"]

def _status():
    return _call("status")

def register(mcp):
    # Protect every GUI command from misleading MCP INVALID_ARGUMENT on IPC failure.
    def gui_tool(*args, **kwargs):
        decorator = mcp.tool(*args, **kwargs)
        def attach(fn):
            @functools.wraps(fn)
            def safe(*a, **kw):
                try:
                    return fn(*a, **kw)
                except _gui_ipc.GUIIPCError as exc:
                    return {
                        "available": False,
                        "error": exc.as_dict(),
                        "ipc": _gui_ipc.diagnostics(BASE / "run" / "maccontrol-gui.sock", HELPER)}
            return decorator(safe)
        return attach

    @gui_tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def gui_status() -> dict:
        """Check Screen Recording / Accessibility permissions, active app and displays."""
        status = _status()
        info = _gui_ipc.diagnostics(BASE / "run" / "maccontrol-gui.sock", HELPER)
        info["accessibility_state"] = (
            "available" if status.get("accessibility_trusted") else "accessibility_unavailable")
        info["screen_recording_state"] = (
            "available" if status.get("screen_capture_trusted") else "screen_recording_unavailable")
        return {"helper": str(HELPER), **status, "ipc": info}

    @gui_tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def gui_displays() -> dict:
        """Enumerate Mac display IDs, global mouse coordinates and pixel dimensions."""
        return _call("displays")

    @gui_tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def gui_windows() -> dict:
        """List open onscreen windows, app names and window coordinates."""
        return _call("windows")

    @gui_tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def gui_tree(pid: int = 0, max_depth: int = 4, max_nodes: int = 120) -> dict:
        """Read Accessibility roles, titles and frames of active app (or explicit PID).

        pid=0 means select foreground app. Missing foreground app returns
        a normal structured result rather than an MCP exception.
        """
        selected_pid = int(pid)
        if selected_pid <= 0:
            selected_pid = int((_status().get("frontmost") or {}).get("pid") or 0)
        if selected_pid <= 0:
            return {"available": False, "pid": None, "nodes": [],
                    "reason": "No active application PID available"}
        try:
            result = _call("ui_tree", pid=selected_pid,
                           max_depth=max_depth, max_nodes=max_nodes)
        except RuntimeError as exc:
            if "No application PID available" in str(exc):
                return {"available": False, "pid": selected_pid, "nodes": [],
                        "reason": "Active application changed during inspection"}
            raise
        return {"available": True, **result}

    @gui_tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def gui_screenshot(max_width: int = 1200, display_id: int = 0) -> dict:
        """Capture Mac screen to small JPEG and return base64. Image bytes are not audited.

        Use a client capable of rendering image_data; never share screenshots
        containing credentials or other private content without approval.
        """
        CAPTURES.mkdir(mode=0o700, parents=True, exist_ok=True)
        CAPTURES.chmod(0o700)
        filename = "capture-" + secrets.token_hex(12) + ".jpg"
        path = CAPTURES / filename
        try:
            data = _call("capture", destination=str(path),
                         max_width=max(300, min(int(max_width), 1800)),
                         display_id=int(display_id), timeout=30)
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("Screenshot was not created")
            size = path.stat().st_size
            if size > MAX_IMAGE_BYTES:
                raise ValueError("Screenshot too large")
            return {
                **{k:v for k,v in data.items() if k != "file"},
                "mime_type": "image/jpeg",
                "image_data": base64.b64encode(path.read_bytes()).decode("ascii"),
                "image_bytes":size,
                "note":"Image scaled for preview; click coordinates use display coordinate points.",
            }
        finally:
            path.unlink(missing_ok=True)

    @gui_tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def gui_request_permissions() -> dict:
        """Ask macOS to show Screen Recording and Accessibility permission prompts.

        The Mac owner must approve the helper in System Settings.
        """
        result = _call("request_permissions", timeout=35)
        return {**result, "application":str(HELPER.parent.parent.parent)}

    @gui_tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def gui_mouse(action: str, x: float, y: float,
                  end_x: float = 0, end_y: float = 0) -> dict:
        """Mouse move, left/right/double click, or drag in global display coordinates."""
        if action not in ("move","left_click","double_click","right_click","drag"):
            raise ValueError("Unsupported mouse action")
        return _call("mouse",action=action,x=float(x),y=float(y),
                     end_x=float(end_x),end_y=float(end_y))

    @gui_tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def gui_scroll(dx: int = 0, dy: int = 0) -> dict:
        """Scroll at current pointer position, in lines."""
        return _call("scroll",dx=max(-30,min(30,int(dx))),dy=max(-30,min(30,int(dy))))

    @gui_tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def gui_press(key: str, modifiers: list[str] | None = None) -> dict:
        """Press a key or keyboard shortcut (cmd/shift/ctrl/option modifiers)."""
        return _call("key",key=key,modifiers=modifiers or [])

    @gui_tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def gui_type(text: str) -> dict:
        """Paste Unicode into the focused control without changing user clipboard.

        Dev helper retains ALL clipboard types in memory and restores them
        after the normal macOS Cmd+V action. No MCP operation is added.
        """
        if not isinstance(text, str):
            raise ValueError("Text must be a string")
        if len(text) > 1500:
            raise ValueError("Text length limit 1500")
        if not text:
            return {"characters": 0, "sent": True}
        helper = GUI_CLIPBOARD_HELPER
        if not helper.is_file() or helper.is_symlink():
            raise RuntimeError("Dev clipboard helper not installed")
        proc = subprocess.Popen(
            [str(helper)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        delivered = False
        restored = False
        try:
            proc.stdin.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            if not select.select([proc.stdout], [], [], 6)[0]:
                raise TimeoutError("GUI paste helper not ready")
            if proc.stdout.readline().strip() != "READY":
                raise RuntimeError("Clipboard snapshot or staging unavailable")
            _call("key", key="v", modifiers=["cmd"])
            delivered = True
            time.sleep(0.35)
        finally:
            if proc.poll() is None:
                try:
                    proc.stdin.write("DONE\n")
                    proc.stdin.flush()
                    if select.select([proc.stdout], [], [], 6)[0]:
                        restored = proc.stdout.readline().strip() == "RESTORED"
                finally:
                    proc.stdin.close()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.terminate()
                        proc.wait(timeout=5)
            else:
                proc.wait(timeout=5)
        if not restored:
            raise RuntimeError("GUI paste clipboard restoration not confirmed")
        return {"characters": len(text), "sent": delivered, "clipboard_restored": True}

    @gui_tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def gui_focus(bundle_id: str) -> dict:
        """Activate a running macOS app by exact bundle ID."""
        if not isinstance(bundle_id,str) or not BUNDLE_ID.fullmatch(bundle_id):
            raise ValueError("Invalid bundle identifier")
        return _call("activate",bundle_id=bundle_id)

    @gui_tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def gui_open_app(name: str) -> dict:
        """Launch a locally installed app by exact name, without shell command evaluation."""
        if not isinstance(name,str) or not re.fullmatch(r"[\w .()+-]{1,100}",name):
            raise ValueError("Invalid application name")
        result = subprocess.run(
            ["/usr/bin/open","-a",name],
            stdin=subprocess.DEVNULL,
            capture_output=True,text=True,timeout=12,
        )
        return {"application":name,"exit_code":result.returncode,
                "stderr":result.stderr[:300]}

    @gui_tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def gui_wait_title(title: str, pid: int = 0, timeout_seconds: int = 8) -> dict:
        """Wait until an Accessibility element with given title becomes visible."""
        if not title or len(title) > 150:
            raise ValueError("Title is required and must be short")
        deadline = time.monotonic() + max(1,min(int(timeout_seconds),20))
        while True:
            info = _call("ui_tree",pid=int(pid),max_depth=6,max_nodes=180)
            hits = [n for n in info["nodes"] if title.lower() in n.get("title","").lower()]
            if hits:
                return {"found":True,"matching_nodes":hits[:10]}
            if time.monotonic() >= deadline:
                return {"found":False,"title":title}
            time.sleep(0.4)
