#!/usr/bin/env python3
"""Build the portable GUI and clipboard release archive on a developer Mac."""
import argparse
from pathlib import Path
import subprocess
import tarfile
import tempfile

try:
    from scripts import build_mac_control_gui as gui
except ModuleNotFoundError:
    import build_mac_control_gui as gui

SOURCE = Path(__file__).resolve().parents[1]


def command(args):
    subprocess.run(args, check=True, timeout=180)


def package(output: Path):
    output = output.expanduser().absolute()
    if output.exists():
        raise RuntimeError("Refusing to overwrite an existing release archive")
    with tempfile.TemporaryDirectory(prefix="mcr-", dir="/tmp") as temporary:
        work = Path(temporary)
        gui.ROOT = work
        app = gui.build(work / 'install')
        generated = work / 'build/gui_mac_control_generated.swift'
        executable = app / 'Contents/MacOS' / gui.EXEC_NAME
        sdk = subprocess.check_output(['/usr/bin/xcrun', '--show-sdk-path'], text=True).strip()
        for name, source, frameworks in (
            ('gui', generated, ['AppKit', 'ApplicationServices', 'CoreGraphics', 'ImageIO', 'ScreenCaptureKit']),
            ('clipboard', SOURCE / 'scripts/gui_clipboard_paste.swift', []),
        ):
            parts = []
            for arch in ('arm64', 'x86_64'):
                part = work / (name + '-' + arch)
                args = ['/usr/bin/swiftc', '-swift-version', '5', '-O', '-target',
                        arch + '-apple-macosx14.0', '-sdk', sdk]
                if name == 'gui':
                    args.append('-parse-as-library')
                args += [str(source), '-o', str(part)]
                for framework in frameworks:
                    args += ['-framework', framework]
                command(args)
                parts.append(part)
            dest = executable if name == 'gui' else work / 'gui_clipboard_paste'
            command(['/usr/bin/lipo', '-create', *(str(p) for p in parts), '-output', str(dest)])
            dest.chmod(0o700)
        command(['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none',
                 str(work / 'gui_clipboard_paste')])
        command(['/usr/bin/codesign', '--verify', '--strict', str(work / 'gui_clipboard_paste')])
        command(['/usr/bin/codesign', '--force', '--sign', '-', '--timestamp=none', str(app)])
        command(['/usr/bin/codesign', '--verify', '--strict', str(app)])
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, 'x:gz') as archive:
            archive.add(app, arcname=gui.APP_NAME, recursive=True)
            archive.add(work / 'gui_clipboard_paste', arcname='gui_clipboard_paste')
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    package(parser.parse_args().output)
