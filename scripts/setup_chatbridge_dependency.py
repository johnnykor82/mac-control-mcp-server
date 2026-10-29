#!/usr/bin/env python3
"""Reuse ChatBridge or install its checksum-pinned independent release."""
from __future__ import annotations
import argparse
import errno
import hashlib
import gzip
import json
import os
from pathlib import Path, PurePosixPath
import socket
import subprocess
import tarfile
import tempfile
import time
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

RELEASE_URL = "https://github.com/johnnykor82/chatbridge/releases/download/v0.2.0-beta.9/chatbridge_gateway-0.2.0b9.tar.gz"
RELEASE_SHA256 = "1248da4818998290d40f6491548a2a527d09a99d1612c39cc649ef7b2dadcf1e"
RELEASE_DIRECTORY = "chatbridge_gateway-0.2.0b9"
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
DEFAULT_URL = "http://127.0.0.1:8787"


def local_origin(url: str):
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost")
            or parsed.username or parsed.password or parsed.path or parsed.query
            or parsed.fragment or parsed.port == 0):
        raise ValueError("ChatBridge dependency must be a local loopback HTTP origin")
    return parsed


def verify(url: str = DEFAULT_URL) -> dict:
    local_origin(url)
    key = os.environ.get("MACCONTROL_CHATBRIDGE_API_KEY", "")
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/browser/capabilities",
        headers={"Accept": "application/json",
                 **({"Authorization": "Bearer " + key} if key else {})},
    )
    with urllib.request.urlopen(request, timeout=4) as response:
        capabilities = json.load(response)
    if not isinstance(capabilities, dict):
        raise RuntimeError("ChatBridge returned invalid capabilities")
    features = capabilities.get("capabilities", capabilities)
    modes = features.get("modes", []) if isinstance(features, dict) else []
    if not isinstance(features, dict) or not (
        features.get("background") is True or "background" in modes
    ):
        raise RuntimeError("ChatBridge does not implement Browser API v1 background mode")
    return {"status": "compatible", "url": url, "installed_by": "chatbridge",
            "mac_control_browser_provider": "chatbridge", "versioned_api": "v1"}


def install(source: Path, *, url: str = DEFAULT_URL) -> dict:
    """Owner-selected source checkout, not an implicit download or private API."""
    parsed = local_origin(url)
    source = source.expanduser().resolve()
    for name in ("install.sh", "LICENSE", "pyproject.toml", "scripts/installer.py"):
        if not (source / name).is_file():
            raise RuntimeError("Not an independently installable ChatBridge source: " + name)
    manifest = (source / "pyproject.toml").read_text()
    if 'name = "chatbridge-gateway"' not in manifest:
        raise RuntimeError("Source is not the expected ChatBridge distribution")
    # Explicit setup runs ChatBridge's own installer; its source remains
    # independent and its own app/state/LaunchAgent are not managed by Mac Control.
    assert_installable(url)
    environment = dict(os.environ)
    client_key = environment.get("MACCONTROL_CHATBRIDGE_API_KEY", "")
    server_key = environment.get("CHATBRIDGE_API_KEY", "")
    if server_key and server_key != client_key:
        raise RuntimeError("Set matching MACCONTROL_CHATBRIDGE_API_KEY and CHATBRIDGE_API_KEY before setup")
    if client_key:
        environment["CHATBRIDGE_API_KEY"] = client_key
    try:
        # Preserve terminal input/output: ChatBridge owns interactive uv consent/login guidance.
        proc = subprocess.run([sys.executable, str(source / "scripts/installer.py"),
                               "install", "--host", "127.0.0.1", "--port", str(parsed.port or 80)],
                              cwd=source, check=False, timeout=1800, env=environment)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ChatBridge setup timed out; inspect ChatBridge status before retrying") from None
    if proc.returncode:
        raise RuntimeError("ChatBridge setup failed; see its terminal diagnostics; no automatic overwrite attempted")
    print("Follow ChatBridge's printed guidance to open its managed profile and sign in.")
    print("Complete login manually; no real ChatGPT login has been verified by this installer.")
    return verify(url)


def assert_installable(url: str) -> None:
    """Refuse existing service ownership or an occupied port before any setup."""
    parsed = local_origin(url)
    plist = Path.home() / "Library/LaunchAgents/net.chatbridge.gateway.plist"
    if plist.exists() or plist.is_symlink():
        raise RuntimeError("ChatBridge LaunchAgent already exists; inspect or upgrade it independently")
    state = Path.home() / ".chatbridge"
    if state.is_symlink() or (state.exists() and (not state.is_dir() or any(state.iterdir()))):
        raise RuntimeError("Existing ChatBridge state found; recover/start it independently, then rerun Mac Control")
    try:
        loaded = subprocess.run(["/bin/launchctl", "print", "gui/" + str(os.getuid()) + "/net.chatbridge.gateway"],
                                capture_output=True, timeout=5, check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Could not confirm ChatBridge service ownership; setup stopped") from None
    if loaded.returncode == 0:
        raise RuntimeError("ChatBridge service is already loaded; recover it independently")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", parsed.port or 80))
        except OSError:
            raise RuntimeError("ChatBridge port is unavailable; inspect the existing service") from None


def extract_release(archive: Path, destination: Path) -> Path:
    """Extract only bounded regular files/directories from the pinned source distribution."""
    total = 0
    seen = set()
    # Bound decompression before tarfile processes extended/PAX metadata.
    unpacked = destination.parent / "bounded-release.tar"
    expanded = 0
    with gzip.open(archive, "rb") as compressed, unpacked.open("xb") as output:
        while True:
            chunk = compressed.read(65536)
            if not chunk:
                break
            expanded += len(chunk)
            if expanded > MAX_EXPANDED + 2 * 1024 * 1024:
                raise RuntimeError("ChatBridge archive decompression exceeds size limit")
            output.write(chunk)
    with tarfile.open(unpacked, "r|") as bundle:
        for number, member in enumerate(bundle, 1):
            parts = PurePosixPath(member.name).parts
            if (number > 2048 or not parts or parts[0] != RELEASE_DIRECTORY
                    or member.name.startswith("/") or ".." in parts
                    or "\\" in member.name or member.name in seen
                    or not (member.isdir() or member.isfile())
                    or member.size < 0 or member.size > 8 * 1024 * 1024):
                raise RuntimeError("Unsafe ChatBridge release archive")
            seen.add(member.name)
            total += member.size
            if total > MAX_EXPANDED:
                raise RuntimeError("ChatBridge release archive exceeds size limit")
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise RuntimeError("Incomplete ChatBridge archive")
                with source, target.open("xb") as output:
                    while True:
                        chunk = source.read(65536)
                        if not chunk:
                            break
                        output.write(chunk)
                target.chmod(0o700 if member.mode & 0o111 else 0o600)
    return destination / RELEASE_DIRECTORY


def install_pinned(url: str = DEFAULT_URL) -> dict:
    assert_installable(url)
    with tempfile.TemporaryDirectory(prefix="mac-control-chatbridge-") as temporary:
        root = Path(temporary)
        archive = root / "release.tar.gz"
        digest = hashlib.sha256()
        downloaded = 0
        deadline = time.monotonic() + 90
        try:
            with urllib.request.urlopen(RELEASE_URL, timeout=20) as response, archive.open("wb") as output:
                if urlsplit(response.geturl()).scheme != "https":
                    raise RuntimeError("ChatBridge download redirected outside HTTPS")
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_ARCHIVE or time.monotonic() > deadline:
                        raise RuntimeError("ChatBridge download exceeds size or time limit")
                    digest.update(chunk)
                    output.write(chunk)
        except (OSError, urllib.error.URLError):
            raise RuntimeError("Could not download pinned ChatBridge release; retry or use --without-chatbridge") from None
        if digest.hexdigest() != RELEASE_SHA256:
            raise RuntimeError("ChatBridge release SHA256 mismatch; installer was not executed")
        try:
            source = extract_release(archive, root / "source")
        except (tarfile.TarError, OSError, EOFError):
            raise RuntimeError("Invalid ChatBridge release archive; installer was not executed") from None
        return install(source, url=url)


def ensure(url: str = DEFAULT_URL, source: Path | None = None) -> dict:
    """Reuse a compatible endpoint; only a refused connection permits fresh setup."""
    try:
        return verify(url)
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise RuntimeError("ChatBridge requires a matching MACCONTROL_CHATBRIDGE_API_KEY; existing service preserved") from None
        raise RuntimeError("Existing HTTP service rejected ChatBridge API probe; preserved") from None
    except urllib.error.URLError as error:
        if not isinstance(error.reason, ConnectionRefusedError) or error.reason.errno != errno.ECONNREFUSED:
            raise RuntimeError("ChatBridge probe failed; inspect the endpoint before installation") from None
    except (TimeoutError, ValueError):
        raise RuntimeError("ChatBridge probe timed out or returned invalid data; existing service preserved") from None
    assert_installable(url)
    return install(source, url=url) if source is not None else install_pinned(url)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--install", action="store_true")
    opts = parser.parse_args()
    result = ensure(opts.url, opts.source) if opts.install else verify(opts.url)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print("ChatBridge dependency setup failed: ", type(exc).__name__,
              str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "", file=sys.stderr)
        raise SystemExit(1)
