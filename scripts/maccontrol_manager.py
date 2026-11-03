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
# The current installed release owns its source, not user data.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
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

def update(root, without_chatbridge=False, without_gui=False, install_tmux=False):
    if not (root / ".mac-control-installer-owned").is_file():
        raise RuntimeError("Mac Control installation not found: " + str(root))
    tag, assets = latest_beta()
    print("GitHub release:", tag, flush=True)
    archive = verified_archive(tag, assets)
    with tempfile.TemporaryDirectory(prefix="maccontrol-verified-") as temp:
        source = unpack_release(archive, tag, Path(temp))
        options = (["--without-chatbridge" if without_chatbridge else "--with-chatbridge"]
                   + (["--without-gui"] if without_gui else [])
                   + (["--install-tmux"] if install_tmux else []))
        return subprocess.call([sys.executable, str(source / "scripts/install_mac_control.py"),
                                "--root", str(root), "--update", *options])

def main(argv=None):
    parser = argparse.ArgumentParser(description="Mac Control: update, status, rollback and uninstall")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    upd = commands.add_parser("update", help="Fetch latest verified GitHub beta release")
    browser = upd.add_mutually_exclusive_group()
    browser.add_argument("--without-chatbridge", action="store_true",
                         help="Skip owner-managed ChatBridge refresh for this update")
    browser.add_argument("--with-chatbridge", action="store_true",
                         help="Explicitly provision or refresh managed ChatBridge (default)")
    upd.add_argument("--without-gui", action="store_true")
    upd.add_argument("--install-tmux", action="store_true",
                     help="Explicitly allow Homebrew installation of tmux when missing")
    commands.add_parser("status")
    commands.add_parser("doctor", help="Read-only complete readiness report (JSON)")
    commands.add_parser("setup", help="Resume interactive configuration and privacy permissions")
    commands.add_parser("rollback")
    releases = commands.add_parser("releases", help="Inspect or prune unused installer releases")
    releases_actions = releases.add_subparsers(dest="releases_action", required=True)
    cleanup = releases_actions.add_parser("cleanup", help="Preview cleanup; --yes applies deletions")
    cleanup.add_argument("--dry-run", action="store_true", help="Show only; default")
    cleanup.add_argument("--yes", action="store_true",
                         help="Delete only eligible old release directories")
    un = commands.add_parser("uninstall")
    un.add_argument("--all", action="store_true", help="Erase owned Mac Control data only; never user workspace")
    ws = commands.add_parser("workspace", help="Inspect and set independent user workspace")
    ws_actions = ws.add_subparsers(dest="workspace_action",required=True)
    ws_actions.add_parser("status")
    ws_set = ws_actions.add_parser("set")
    ws_set.add_argument("path",type=Path)
    ws_inventory = ws_actions.add_parser("inventory", help="Read-only inventory of a legacy workspace")
    ws_inventory.add_argument("--from",dest="source",required=True,type=Path)
    ws_migrate = ws_actions.add_parser("migrate", help="Non-destructive copy; dry-run by default")
    ws_migrate.add_argument("--from",dest="source",required=True,type=Path)
    ws_migrate.add_argument("--name",default="legacy-import")
    ws_migrate.add_argument("--execute",action="store_true")
    ws_migrate.add_argument("--yes",action="store_true")
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    if args.command == "releases":
        if args.dry_run and args.yes:
            raise ValueError("Choose --dry-run or --yes, not both")
        return installed(root, "--releases-cleanup", *(["--yes"] if args.yes else []))
    if args.command == "workspace":
        from mac_control.workspace_config import resolve, set_root
        data = root / "data"
        if not (root / ".mac-control-installer-owned").is_file():
            raise RuntimeError("Mac Control installation not found")
        if args.workspace_action == "set":
            result = set_root(data,args.path,root)
        elif args.workspace_action == "status":
            result = resolve(data)
        else:
            from scripts.workspace_migration import inventory, migrate
            destination = Path(resolve(data)["workspace_root"])
            result = (inventory(args.source,destination) if args.workspace_action == "inventory"
                      else migrate(args.source,destination,args.name,execute=args.execute,
                                   confirmed=args.yes))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    if args.command == "doctor":
        from scripts.doctor_mac_control import collect
        print(json.dumps(collect(root), ensure_ascii=False, indent=2))
        return 0
    if args.command == "update":
        return update(root, without_chatbridge=args.without_chatbridge,
                      without_gui=args.without_gui, install_tmux=args.install_tmux)
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
