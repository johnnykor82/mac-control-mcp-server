#!/usr/bin/env python3
"""Owner-guided ChatGPT setup after local installation; never grants macOS permissions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import urllib.request

try:
    from scripts.setup_network import guided_network, enable_funnel
    from scripts.setup_github_oauth import check as oauth_check, configure as oauth_configure
    from scripts.setup_github_oauth import guide as oauth_guide, probe as oauth_probe
except ImportError:
    from setup_network import guided_network, enable_funnel
    from setup_github_oauth import check as oauth_check, configure as oauth_configure
    from setup_github_oauth import guide as oauth_guide, probe as oauth_probe


def ensure_remote_service(root):
    try:
        from scripts.setup_remote_service import ensure
    except ImportError:
        from setup_remote_service import ensure
    return ensure(root)


def verify_local_oauth(root, origin):
    """Check the loopback challenge and issuer before offering publication."""
    try:
        from scripts.setup_network import _oauth_guard
    except ImportError:
        from setup_network import _oauth_guard
    _oauth_guard(root)
    request = urllib.request.Request(
        "http://127.0.0.1:3201/.well-known/oauth-authorization-server",
        headers={"Accept": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=5) as response:
        payload = response.read(65537)
    if len(payload) > 65536:
        raise RuntimeError("Local OAuth metadata exceeds size limit")
    metadata = json.loads(payload)
    if not isinstance(metadata, dict) or str(metadata.get("issuer", "")).rstrip("/") != origin:
        raise RuntimeError("Local OAuth issuer does not match the configured HTTPS origin")
    return True


def _gui_call(root, operation):
    current = root / "current"
    python = current / ".venv/bin/python"
    data = root / "data"
    env = {**os.environ, "MAC_CONTROL_DATA_ROOT": str(data),
           "PYTHONPATH": str(current / "src"), "PYTHONNOUSERSITE": "1"}
    code = ("import json; from mac_control.legacy_handlers.gui_ops import _call; "
            "v=_call(" + repr(operation) + ", timeout=90); "
            "print(json.dumps({k:bool(v.get(k)) for k in "
            "('accessibility_trusted','screen_capture_trusted')}))")
    result = subprocess.run([str(python), "-c", code], env=env, text=True,
                            capture_output=True, check=True, timeout=100)
    return json.loads(result.stdout)


def gui_permissions(root, *, input_fn=input):
    """Ask macOS to present prompts; only the owner can grant TCC access."""
    state = _gui_call(root, "status")
    if state.get("accessibility_trusted") and state.get("screen_capture_trusted"):
        return True
    print("Mac Control запросит разрешения macOS для своего GUI helper.")
    print("Подтвердите Accessibility и Screen Recording в настройках macOS.")
    _gui_call(root, "request_permissions")
    while True:
        state = _gui_call(root, "status")
        if state.get("accessibility_trusted") and state.get("screen_capture_trusted"):
            return True
        pane = ("Privacy_Accessibility" if not state.get("accessibility_trusted")
                else "Privacy_ScreenCapture")
        try:
            opened = subprocess.run(["/usr/bin/open", "x-apple.systempreferences:com.apple.preference.security?" + pane],
                                    check=False, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if opened.returncode:
                print("Откройте вручную System Settings → Privacy & Security → " + pane)
        except (OSError, subprocess.SubprocessError):
            print("Откройте вручную System Settings → Privacy & Security → " + pane)
        answer = input_fn("После выдачи прав нажмите Enter для проверки; S — отложить: ").strip().lower()
        if answer in ("s", "skip", "q"):
            return False


def _validate_setup_install(root):
    root = Path(root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("Install the owned Mac Control release before interactive setup")
    root = root.resolve()
    directory = root.stat()
    if directory.st_uid != os.getuid() or directory.st_mode & 0o022:
        raise RuntimeError("Install root has unsafe ownership or permissions")
    marker = root / ".mac-control-installer-owned"
    if not marker.exists() or marker.is_symlink():
        raise RuntimeError("Install ownership marker missing; interactive setup stopped")
    info = marker.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_mode & 0o022):
        raise RuntimeError("Install ownership marker is unsafe; interactive setup stopped")
    current = root / "current"
    try:
        from scripts.install_mac_control import _verified_release
    except ImportError:
        from install_mac_control import _verified_release
    if not current.is_symlink():
        raise RuntimeError("Installed current release is missing; interactive setup stopped")
    _verified_release(root, current.resolve())
    return root


def setup(root, *, input_fn=input, interactive=None, with_gui=True):
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        return {"status": "pending_owner_interaction", "next": "Run --setup in an interactive Terminal"}
    root = _validate_setup_install(root)
    try:
        from scripts.install_mac_control import _lifecycle_lock
    except ImportError:
        from install_mac_control import _lifecycle_lock
    with _lifecycle_lock(root) as locked_root:
        # Recheck ownership/release after waiting for another lifecycle action.
        _validate_setup_install(locked_root)
        return _setup_locked(locked_root, input_fn=input_fn, with_gui=with_gui)


def _setup_locked(root, *, input_fn=input, with_gui=True):
    if with_gui and not gui_permissions(root, input_fn=input_fn):
        return {"status": "pending_gui_permissions", "next": "Grant macOS permissions and run --setup"}
    network = guided_network(root, network=True, input_fn=input_fn)
    if network.get("status") != "ready_for_oauth":
        return {"status": "pending_network", "network": network, "next": "Run --setup to continue"}
    origin = network.get("public_url", "").rstrip("/")
    if not origin:
        return {"status": "pending_network", "reason": "public_https_origin_missing"}
    try:
        configured = oauth_check(root)
    except FileNotFoundError:
        oauth_guide(origin, None)
        answer = input_fn("Создайте GitHub OAuth App по инструкции. Enter — продолжить, S — отложить: ").strip().lower()
        if answer in ("s", "skip", "q"):
            return {"status": "pending_github_oauth", "public_url": origin, "next": "Run --setup to continue"}
        login = input_fn("GitHub username (Enter, если уже выполнен gh auth login): ").strip() or None
        configured = oauth_configure(root, origin, login, input_fn=input_fn)
    if configured.get("public_url", "").rstrip("/") != origin:
        return {"status": "oauth_origin_mismatch", "next": "Review existing OAuth configuration; no overwrite"}
    ensure_remote_service(root)
    verify_local_oauth(root, origin)
    if network.get("route") == "tailscale_funnel":
        enable_funnel(root, input_fn=input_fn)
    elif network.get("route") == "direct_https":
        answer = input_fn("Настройте HTTPS proxy и TCP 443 по инструкции. Enter — проверить, S — отложить: ").strip().lower()
        if answer in ("s", "skip", "q"):
            return {"status": "pending_https_proxy", "public_url": origin, "next": "Run --setup to continue"}
    else:
        return {"status": "pending_network", "reason": "unknown_route"}
    verified = oauth_probe(origin)
    if verified.get("status") != "public_oauth_preflight_pass":
        return {"status": "pending_public_https", "public_url": origin, "probe": verified,
                "next": "Run --setup to continue"}
    print("В ChatGPT на сайте откройте Plugins → + → Add custom MCP server.")
    print("Укажите OAuth и Server URL: " + origin + "/mcp")
    print("Войдите через GitHub и проверьте system_info. Секреты в чат не отправляйте.")
    return {"status": "pending_chatgpt_connection", "public_url": origin,
            "public_oauth_preflight": "passed", "chatgpt_oauth_verified": False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--without-gui", action="store_true")
    args = parser.parse_args()
    try:
        result = setup(args.root, with_gui=not args.without_gui)
    except (EOFError, KeyboardInterrupt):
        result = {"status": "pending_owner_interaction", "next": "Run --setup to continue"}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("Guided setup stopped: " + str(error), file=sys.stderr)
        result = {"status": "setup_incomplete", "next": "Resolve the error and run --setup"}
    if args.without_gui and isinstance(result.get("next"), str):
        result["next"] = result["next"].replace("--setup", "--setup --without-gui")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result["status"] == "setup_incomplete" else 0


if __name__ == "__main__":
    sys.exit(main())
