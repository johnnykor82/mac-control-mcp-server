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
SOURCE_ACTIVATE = "let success=app.activate(options:[])"


def require_build_tools() -> None:
    """Only inspect developer tools; downloading them requires owner action."""
    try:
        subprocess.run(["/usr/bin/xcrun", "--find", "swiftc"], check=True,
                       capture_output=True, timeout=20)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("GUI/clipboard compilation requires Apple Command Line Tools. "
                           "Run xcode-select --install in Terminal, confirm Apple's installation "
                           "dialog, wait for completion, then retry. No tools were installed automatically.") from exc


def verify_owned(install_root: Path) -> bool:
    """Validate app ownership and signature without changing or launching it."""
    root = install_root.expanduser().resolve()
    app = root.expanduser().resolve() / "apps" / APP_NAME
    record = root / "data/gui-owned.json"
    if record.parent.is_symlink() or record.is_symlink() or (record.exists() and not record.is_file()):
        raise RuntimeError("Untrusted GUI ownership record")
    if record.exists() and (record.stat().st_uid != os.getuid() or record.stat().st_mode & 0o022):
        raise RuntimeError("GUI ownership record must be owned and writable only by the installer user")
    expected = {"app": str(app), "bundle": BUNDLE, "installed_by": str(root)}
    if record.exists() and json.loads(record.read_text()) != expected:
        raise RuntimeError("GUI ownership record is inconsistent")
    if app.is_symlink() or app.parent.is_symlink():
        raise RuntimeError("GUI app path cannot be a symlink")
    if not app.exists():
        return False
    if not record.is_file() or not app.is_dir():
        raise RuntimeError("Refusing to replace an app without matching owner metadata")
    if any(path.is_symlink() for path in app.rglob("*")):
        raise RuntimeError("GUI app contains a symlink")
    with (app / "Contents/Info.plist").open("rb") as stream:
        metadata = plistlib.load(stream)
    if (not isinstance(metadata, dict) or metadata.get("CFBundleIdentifier") != BUNDLE
            or metadata.get("CFBundleExecutable") != EXEC_NAME
            or not (app / "Contents/MacOS" / EXEC_NAME).is_file()):
        raise RuntimeError("Existing GUI app metadata is inconsistent")
    subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(app)],
                   check=True, capture_output=True, timeout=20)
    return True


def build(install_root: Path) -> Path:
    require_build_tools()
    install_root = install_root.expanduser().resolve()
    data = install_root / "data"
    socket_path = data / "run/maccontrol-gui.sock"
    if len(str(socket_path).encode()) >= 100:
        raise RuntimeError("GUI Unix socket path exceeds 99 UTF-8 bytes; choose shorter --root")
    source = TEMPLATE.read_text()
    for name, expected in (("struct GUIRuntimePaths {", 1),
                           (SOURCE_ACTIVATE, 1), ('case "capture":', 1),
                           ("func postMouse(_ kind: CGEventType", 1)):
        if source.count(name) != expected:
            raise RuntimeError("GUI source template does not match expected original")
    source = source.replace(SOURCE_ACTIVATE,
                            "let success=app.activate(options:[.activateIgnoringOtherApps])")
    fragment = CAPTURE.read_text()
    if fragment.count('let allowed=try GUI_RUNTIME_PATHS.get().capturePrefix') != 1:
        raise RuntimeError("GUI capture fragment lacks runtime capture path anchor")
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
    verify_owned(root)
    target = root.expanduser().resolve() / "apps" / APP_NAME
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
    record = root.expanduser().resolve() / "data/gui-owned.json"
    pending = record.with_name("gui-owned.pending-" + os.urandom(6).hex())
    pending.write_text(json.dumps({"app": str(target), "bundle": BUNDLE,
                                  "installed_by": str(root.expanduser().resolve())}) + "\n")
    pending.chmod(0o600)
    pending.replace(record)
    return {"installed": str(target), "bundle_id": BUNDLE,
            "previous_backup": str(prior) if prior else None,
            "permission_grant": "Owner must approve Accessibility and Screen Recording in macOS Settings",
            "dev_stable_modified": False, "started": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    if args.install:
        verify_owned(args.root)
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
