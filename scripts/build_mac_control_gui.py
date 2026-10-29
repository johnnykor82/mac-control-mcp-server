#!/usr/bin/env python3
"""Build and optionally install an independent Mac Control MCP Server native macOS GUI helper.

Never touches MacControlGUI.app (Stable), MacControlGUIDev.app (DEV), or
their TCC permissions. A new macOS permission grant can be required.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/mac_control/assets/gui_agent.swift"
CAPTURE = ROOT / "scripts/dev_gui_window_capture.swift.part"
BUNDLE = "org.maccontrol.mcpserver.gui"
APP_NAME = "MacControlMCPServer.app"
EXEC_NAME = "MacControlMCPServer"
SOURCE_SOCKET = "__MAC_CONTROL_SOCKET__"
SOURCE_CAPTURE = "__MAC_CONTROL_CAPTURES__"
SOURCE_ACTIVATE = "let success=app.activate(options:[])"


def build(install_root: Path) -> Path:
    install_root = install_root.expanduser().resolve()
    data = install_root / "data"
    socket_path = data / "run/maccontrol-gui.sock"
    capture_path = str(data / "run/gui-captures") + "/"
    if len(str(socket_path).encode()) >= 100:
        raise RuntimeError("GUI Unix socket path exceeds 99 UTF-8 bytes; choose shorter --root")
    source = TEMPLATE.read_text()
    for name, expected in ((SOURCE_SOCKET, 1), (SOURCE_CAPTURE, 1),
                           (SOURCE_ACTIVATE, 1), ('case "capture":', 1),
                           ("func postMouse(_ kind: CGEventType", 1)):
        if source.count(name) != expected:
            raise RuntimeError("GUI source template does not match expected original")
    source = source.replace(SOURCE_SOCKET, str(socket_path))
    source = source.replace(SOURCE_CAPTURE, capture_path)
    source = source.replace(SOURCE_ACTIVATE,
                            "let success=app.activate(options:[.activateIgnoringOtherApps])")
    fragment = CAPTURE.read_text()
    fragment, changed = re.subn(r'let allowed="[^"]*gui-captures/"',
                               'let allowed="' + capture_path + '"', fragment)
    if changed == 0 and fragment.count('__MAC_CONTROL_CAPTURES__') == 1:
        fragment = fragment.replace('__MAC_CONTROL_CAPTURES__', capture_path)
        changed = 1
    if changed != 1:
        raise RuntimeError("GUI capture fragment lacks portable capture path anchor")
    source = source.replace(
        "func postMouse(_ kind: CGEventType",
        fragment + "\nfunc postMouse(_ kind: CGEventType")
    source = source.replace('case "capture": return try await capture(req)',
                            'case "capture": return try await capture(req)\n'
                            '    case "capture_window": return try await captureOwnedWindow(req)')
    output = ROOT / "build" / APP_NAME
    if output.exists() or output.is_symlink():
        shutil.rmtree(output) if output.is_dir() and not output.is_symlink() else output.unlink()
    binpath = output / "Contents/MacOS" / EXEC_NAME
    binpath.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    generated = ROOT / "build/gui_mac_control_generated.swift"
    generated.write_text(source)
    metadata = {
        "CFBundleIdentifier": BUNDLE,
        "CFBundleExecutable": EXEC_NAME,
        "CFBundleName": "MacControlMCPServer",
        "CFBundleDisplayName": "Mac Control MCP Server",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "CFBundlePackageType": "APPL",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSScreenCaptureUsageDescription": "Allow Mac Control to capture the screen and owned app windows.",
    }
    (output / "Contents/Info.plist").write_bytes(plistlib.dumps(metadata))
    subprocess.run([
        "/usr/bin/swiftc", "-swift-version", "5", "-parse-as-library",
        "-O", str(generated), "-o", str(binpath),
        "-framework", "AppKit", "-framework", "ApplicationServices",
        "-framework", "CoreGraphics", "-framework", "ImageIO",
        "-framework", "ScreenCaptureKit",
    ], check=True, capture_output=True, text=True, timeout=160)
    binpath.chmod(0o700)
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-",
                    "--timestamp=none", str(output)], check=True,
                   capture_output=True, timeout=20)
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(output)],
                   check=True, capture_output=True, timeout=20)
    return output


def install(root: Path, candidate: Path) -> dict:
    target = Path.home() / "Applications" / APP_NAME
    backups = root.expanduser().resolve() / "data/backups"
    target.parent.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.is_symlink():
        raise RuntimeError("Cannot install GUI over a symlink")
    if target.exists():
        with (target / "Contents/Info.plist").open("rb") as stream:
            old_id = plistlib.load(stream).get("CFBundleIdentifier")
        if old_id != BUNDLE:
            raise RuntimeError("Existing GUI app is not a Mac Control MCP Server installation")
    staging = target.with_name("." + APP_NAME + ".pending-" + str(os.getpid()))
    if staging.exists():
        raise RuntimeError("GUI staging target already exists")
    shutil.copytree(candidate, staging)
    replaced = False
    prior = None
    try:
        if target.exists():
            prior = backups / ("gui-previous-" + os.urandom(6).hex() + ".app")
            target.rename(prior)
            replaced = True
        staging.rename(target)
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(target)],
                       capture_output=True, check=True, timeout=20)
    except BaseException:
        if target.exists() and target != prior:
            shutil.rmtree(target)
        if replaced and prior is not None:
            prior.rename(target)
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {"installed": str(target), "bundle_id": BUNDLE,
            "previous_backup": str(prior) if prior else None,
            "permission_grant": "Owner must approve Accessibility and Screen Recording in macOS Settings",
            "dev_stable_modified": False, "started": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    bundle = build(args.root)
    response = install(args.root, bundle) if args.install else {
        "built": str(bundle), "signed": "ad-hoc", "bundle_id": BUNDLE,
        "started": False, "tcc_permissions_requested": False,
        "binary_sha256": hashlib.sha256(
            (bundle / "Contents/MacOS" / EXEC_NAME).read_bytes()).hexdigest(),
    }
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        print("Mac Control MCP Server GUI build/install failed:", str(exc), file=sys.stderr)
        sys.exit(1)
