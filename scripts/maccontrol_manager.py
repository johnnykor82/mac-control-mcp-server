#!/usr/bin/env python3
"""Manage a single ~/MacControlMCP installation from GitHub verified releases."""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit

DEFAULT_ROOT = Path.home() / "MacControlMCP"
API = "https://api.github.com/repos/johnnykor82/mac-control-mcp-server/releases?per_page=50"
TAG_RE = re.compile(r"v0\.1\.0-beta\.(\d+)\Z")
MAX_DOWNLOAD = 16 * 1024 * 1024
MAX_FILES = 300
MAX_EXPANDED = 80 * 1024 * 1024
ASSET_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}

def _read_url(url: str, limit: int, *, api: bool = False) -> bytes:
    parsed = urlsplit(url)
    allowed = {"api.github.com"} if api else ASSET_HOSTS
    if parsed.scheme != "https" or parsed.hostname not in allowed:
        raise RuntimeError("Untrusted GitHub release URL")
    request = urllib.request.Request(url, headers={"User-Agent": "MacControlMCP/1.0"})
    try:
        with closing(urllib.request.urlopen(request, timeout=30)) as response:
            final = urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname not in allowed:
                raise RuntimeError("GitHub asset redirected outside trusted HTTPS hosts")
            blocks = []
            size = 0
            while True:
                chunk = response.read(65536)
                if not chunk: break
                size += len(chunk)
                if size > limit: raise RuntimeError("Release download exceeds size limit")
                blocks.append(chunk)
            return b"".join(blocks)
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError("Cannot retrieve GitHub release: " + str(exc)) from None

def latest_beta():
    releases = json.loads(_read_url(API, 512 * 1024, api=True))
    if not isinstance(releases, list):
        raise RuntimeError("Invalid GitHub release metadata")
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or not release.get("prerelease"): continue
        tag = release.get("tag_name", "")
        match = TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
        if not match: continue
        assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])
                  if isinstance(a, dict) and isinstance(a.get("name"), str)
                  and isinstance(a.get("browser_download_url"), str)}
        name = "mac-control-mcp-server-" + tag + ".tar.gz"
        if name in assets and "SHA256SUMS.txt" in assets:
            candidates.append((int(match.group(1)), tag, assets))
    if not candidates: raise RuntimeError("No complete published beta release")
    _, tag, assets = max(candidates, key=lambda c: c[0])
    return tag, assets

def verified_archive(tag, assets):
    name = "mac-control-mcp-server-" + tag + ".tar.gz"
    sums = _read_url(assets["SHA256SUMS.txt"], 65536).decode("ascii")
    hashes = []
    for line in sums.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            hashes.append(parts[0])
    if len(hashes) != 1: raise RuntimeError("Missing or ambiguous archive checksum")
    archive = _read_url(assets[name], MAX_DOWNLOAD)
    if hashlib.sha256(archive).hexdigest() != hashes[0]:
        raise RuntimeError("Release SHA256 mismatch; install cancelled")
    return archive

def unpack_release(archive, tag, destination):
    prefix = "mac-control-mcp-server-" + tag
    total = 0
    count = 0
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        for member in bundle:
            parts = PurePosixPath(member.name).parts
            if (not parts or parts[0] != prefix or member.name.startswith("/")
                    or ".." in parts or "\\" in member.name
                    or not (member.isfile() or member.isdir())
                    or member.size < 0 or member.size > MAX_EXPANDED):
                raise RuntimeError("Unsafe GitHub release archive entry")
            count += 1
            total += member.size
            if count > MAX_FILES or total > MAX_EXPANDED:
                raise RuntimeError("Release archive too large")
            if len(parts) == 1:
                if not member.isdir(): raise RuntimeError("Invalid release root")
                continue
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                reader = bundle.extractfile(member)
                if reader is None: raise RuntimeError("Incomplete release archive")
                with closing(reader), target.open("xb") as output:
                    shutil.copyfileobj(reader, output, 65536)
                target.chmod(0o700 if member.mode & 0o111 else 0o600)
    source = destination / prefix
    if not (source / "scripts/install_mac_control.py").is_file():
        raise RuntimeError("Archive lacks Mac Control installer")
    return source

def installed(root, action, *extra):
    script = root / "current/scripts/install_mac_control.py"
    if not script.is_file(): raise RuntimeError("Mac Control is not installed")
    return subprocess.call([sys.executable, str(script), "--root", str(root), action, *extra])

def update(root, without_chatbridge=False, without_gui=False):
    if not (root / ".mac-control-installer-owned").is_file():
        raise RuntimeError("Mac Control installation not found: " + str(root))
    tag, assets = latest_beta()
    print("GitHub release:", tag, flush=True)
    archive = verified_archive(tag, assets)
    with tempfile.TemporaryDirectory(prefix="maccontrol-verified-") as temp:
        source = unpack_release(archive, tag, Path(temp))
        options = (["--without-chatbridge"] if without_chatbridge else []) + (["--without-gui"] if without_gui else [])
        return subprocess.call([sys.executable, str(source / "scripts/install_mac_control.py"),
                                "--root", str(root), "--update", *options])

def main(argv=None):
    parser = argparse.ArgumentParser(description="Mac Control: update, status, rollback and uninstall")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    upd = commands.add_parser("update", help="Fetch latest verified GitHub beta release")
    upd.add_argument("--without-chatbridge", action="store_true")
    upd.add_argument("--without-gui", action="store_true")
    commands.add_parser("status")
    commands.add_parser("rollback")
    un = commands.add_parser("uninstall")
    un.add_argument("--all", action="store_true", help="Also erase all Mac Control data and workspace")
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    if args.command == "update":
        return update(root, without_chatbridge=args.without_chatbridge, without_gui=args.without_gui)
    if args.command == "uninstall" and args.all:
        if root != DEFAULT_ROOT.resolve():
            raise RuntimeError("Full removal requires the standard installation root")
        if not sys.stdin.isatty() or input("Type DELETE to remove all Mac Control data: ") != "DELETE":
            raise RuntimeError("Full removal cancelled")
        return installed(root, "--purge", "--yes")
    return installed(root, "--" + args.command)

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, tarfile.TarError) as error:
        print("Mac Control: " + str(error), file=sys.stderr)
        raise SystemExit(1)
