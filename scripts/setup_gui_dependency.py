"""Install checksum-pinned universal native helpers without developer tools.

Release archive contract: MacControlMCPServer.app/ plus gui_clipboard_paste.
SHA256 is pinned in reviewed source; ad-hoc codesign verifies bundle integrity,
not publisher identity, and does not imply Apple notarization.
"""
from __future__ import annotations

import gzip
import hashlib
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import signal
import struct
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

try:
    from scripts import build_mac_control_gui as gui
except ModuleNotFoundError:
    import build_mac_control_gui as gui

RELEASE_URL = ('https://github.com/johnnykor82/mac-control-mcp-server/releases/download/'
               'v0.1.0-beta.11/mac-control-native-v0.1.0-beta.11-universal.tar.gz')
# Never download or accept an unpinned native executable.
RELEASE_SHA256 = '7540329d030e5066d49ef9af4c8c2007edc245f8c17b7ef3c93c39114881cfaa'
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 96 * 1024 * 1024


def verify_universal(binary: Path) -> None:
    """Inspect the fat Mach-O directory without requiring CLT's lipo utility."""
    with binary.open('rb') as stream:
        header = stream.read(4096)
    if len(header) < 8:
        raise RuntimeError('Native helper is not a universal Mach-O executable')
    layouts = {b'\xca\xfe\xba\xbe': ('>', 20), b'\xbe\xba\xfe\xca': ('<', 20),
               b'\xca\xfe\xba\xbf': ('>', 32), b'\xbf\xba\xfe\xca': ('<', 32)}
    layout = layouts.get(header[:4])
    if layout is None:
        raise RuntimeError('Native helper must be universal for Apple Silicon and Intel')
    endian, size = layout
    count = struct.unpack_from(endian + 'I', header, 4)[0]
    if count != 2 or len(header) < 8 + count * size:
        raise RuntimeError('Native helper has an invalid universal architecture directory')
    cpus = set()
    ranges = []
    for index in range(count):
        base = 8 + index * size
        cpu = struct.unpack_from(endian + 'I', header, base)[0]
        offset, length = struct.unpack_from(endian + ('II' if size == 20 else 'QQ'), header, base + 8)
        if offset < 8 + count * size or length == 0 or offset + length > binary.stat().st_size:
            raise RuntimeError('Native helper has invalid universal slice bounds')
        cpus.add(cpu)
        ranges.append((offset, offset + length))
    if cpus != {0x01000007, 0x0100000c} or max(r[0] for r in ranges) < min(r[1] for r in ranges):
        raise RuntimeError('Native helper must be universal for Apple Silicon and Intel')


def extract_release(archive: Path, destination: Path) -> Path:
    """Bound decompression and allow only regular files under expected paths."""
    unpacked = destination.parent / 'bounded-native-release.tar'
    expanded = 0
    with gzip.open(archive, 'rb') as source, unpacked.open('xb') as output:
        while True:
            chunk = source.read(65536)
            if not chunk:
                break
            expanded += len(chunk)
            if expanded > MAX_EXPANDED:
                raise RuntimeError('Native archive decompression exceeds size limit')
            output.write(chunk)
    seen = set()
    total = 0
    with tarfile.open(unpacked, 'r|') as bundle:
        for number, member in enumerate(bundle, 1):
            parts = PurePosixPath(member.name).parts
            if (number > 256 or not parts or member.name.startswith('/')
                    or '..' in parts or '\\' in member.name
                    or not (parts[0] == gui.APP_NAME or parts == ('gui_clipboard_paste',))
                    or parts in seen or not (member.isdir() or member.isfile())
                    or member.size < 0 or member.size > MAX_ARCHIVE):
                raise RuntimeError('Unsafe native helper release archive')
            seen.add(parts)
            total += member.size
            if total > MAX_EXPANDED:
                raise RuntimeError('Native archive exceeds size limit')
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source = bundle.extractfile(member)
                if source is None:
                    raise RuntimeError('Incomplete native helper archive')
                with source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 65536)
                target.chmod(0o700 if parts[-1] in (gui.EXEC_NAME, 'gui_clipboard_paste') else 0o600)
    return destination


def _download(target: Path) -> None:
    if len(RELEASE_SHA256) != 64 or any(c not in '0123456789abcdef' for c in RELEASE_SHA256):
        raise RuntimeError('Prebuilt GUI release is not published: reviewed SHA256 pin is missing')
    digest = hashlib.sha256()
    total = 0
    deadline = time.monotonic() + 90
    try:
        with urllib.request.urlopen(RELEASE_URL, timeout=20) as response, target.open('xb') as output:
            if urlsplit(response.geturl()).scheme != 'https':
                raise RuntimeError('Native helper download redirected outside HTTPS')
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE or time.monotonic() > deadline:
                    raise RuntimeError('Native helper download exceeds size or time limit')
                digest.update(chunk)
                output.write(chunk)
    except (OSError, urllib.error.URLError):
        raise RuntimeError('Could not download pinned GUI helpers; retry or use --without-gui') from None
    if digest.hexdigest() != RELEASE_SHA256:
        raise RuntimeError('Native helper SHA256 mismatch; nothing was installed')


def _verify_payload(directory: Path) -> tuple[Path, Path]:
    app = directory / gui.APP_NAME
    with (app / 'Contents/Info.plist').open('rb') as source:
        metadata = plistlib.load(source)
    if (not isinstance(metadata, dict) or metadata.get('CFBundleIdentifier') != gui.BUNDLE
            or metadata.get('CFBundleExecutable') != gui.EXEC_NAME):
        raise RuntimeError('Prebuilt GUI app identity is inconsistent')
    clipboard = directory / 'gui_clipboard_paste'
    for binary in (app / 'Contents/MacOS' / gui.EXEC_NAME, clipboard):
        verify_universal(binary)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(app)],
                   check=True, capture_output=True, timeout=20)
    subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(clipboard)],
                   check=True, capture_output=True, timeout=20)
    return app, clipboard


def _stop_owned_app(app: Path) -> None:
    """Send only SIGTERM to this user's exact owned helper; never force kill."""
    executable = str(app / 'Contents/MacOS' / gui.EXEC_NAME)
    def matching_pids():
        processes = subprocess.run(['/bin/ps', '-axo', 'uid=,pid=,command='], check=True,
                                   capture_output=True, text=True, timeout=5).stdout
        found = set()
        for line in processes.splitlines():
            columns = line.strip().split(None, 2)
            if (len(columns) == 3 and columns[0] == str(os.getuid())
                    and (columns[2] == executable or columns[2].startswith(executable + ' '))):
                found.add(int(columns[1]))
        return found
    pids = matching_pids()
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(25):
        if not pids.intersection(matching_pids()):
            return
        time.sleep(0.1)
    raise RuntimeError('Owned GUI helper did not exit after SIGTERM; inspect it before retrying --with-gui')


def ensure(root: Path, release: Path, *, replace: bool = False) -> dict:
    """Preserve an owned helper by default; refresh release-local clipboard."""
    existing = gui.verify_owned(root)
    if existing:
        app = root.expanduser().resolve() / 'apps' / gui.APP_NAME
        for path in (app.parent, app, *app.rglob('*')):
            info = path.lstat()
            if info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise RuntimeError('GUI app has unsafe ownership or permissions')
        if replace:
            _stop_owned_app(app)
    with tempfile.TemporaryDirectory(prefix='mac-control-native-') as temporary:
        directory = Path(temporary)
        archive = directory / 'release.tar.gz'
        _download(archive)
        try:
            payload = extract_release(archive, directory / 'payload')
            app, clipboard = _verify_payload(payload)
        except (tarfile.TarError, OSError, EOFError, ValueError) as error:
            raise RuntimeError('Invalid native helper release: ' + str(error)) from None
        build = release / 'build'
        if build.is_symlink():
            raise RuntimeError('Clipboard build directory cannot be a symlink')
        build.mkdir(mode=0o700, exist_ok=True)
        target = build / 'gui_clipboard_paste'
        if target.is_symlink():
            raise RuntimeError('Clipboard executable cannot be a symlink')
        staged = build / ('gui-clipboard-pending-' + os.urandom(6).hex())
        try:
            shutil.copy2(clipboard, staged)
            staged.chmod(0o700)
            staged.replace(target)
        finally:
            staged.unlink(missing_ok=True)
        if replace or not existing:
            gui.install(root, app)
    return {'native_gui': 'installed' if replace or not existing else 'reused'}
