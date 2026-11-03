#!/usr/bin/env python3
"""Reuse ChatBridge or install its checksum-pinned independent release."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import errno
import hashlib
import gzip
import json
import os
import plistlib
import re
import shutil
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

RELEASE_URL = "https://github.com/johnnykor82/chatbridge/releases/download/v0.2.0-beta.12/chatbridge_gateway-0.2.0b12.tar.gz"
RELEASE_SHA256 = "5fc826b36e87e370a6747d5fa95e133aeb808e8b94bfe8fe69536acc0525ffc2"
RELEASE_DIRECTORY = "chatbridge_gateway-0.2.0b12"
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
DEFAULT_URL = "http://127.0.0.1:8787"
MANAGED_LABEL = "net.chatbridge.gateway.maccontrol"


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



def select_endpoint(preferred: str = DEFAULT_URL, *, reuse_compatible: bool = True) -> str:
    """Reuse a compatible service or select an unused loopback port."""
    requested = local_origin(preferred)
    port = requested.port or 80
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            if reuse_compatible:
                try:
                    verify(preferred)
                    return preferred
                except urllib.error.HTTPError as error:
                    if error.code == 401:
                        raise RuntimeError("Existing ChatBridge requires its API key") from None
                except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError):
                    pass
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as available:
                available.bind(("127.0.0.1", 0))
                return "http://127.0.0.1:" + str(available.getsockname()[1])
    return preferred


def browser_login_status(url: str = DEFAULT_URL, *, verify_idle: bool = False) -> dict:
    """Check real composer. Only owner-triggered install may wake an idle Chrome."""
    local_origin(url)
    headers = ({"Authorization": "Bearer " + os.environ["MACCONTROL_CHATBRIDGE_API_KEY"]}
               if os.environ.get("MACCONTROL_CHATBRIDGE_API_KEY") else {})

    def outcome(payload: dict) -> dict:
        if (isinstance(payload, dict) and payload.get("ready") is True
                and payload.get("chatgpt_authenticated") is True):
            return {"authenticated": True, "status": "ready", "url": url}
        return {"authenticated": False, "status": "unverified", "url": url,
                "next": "Inspect managed Chrome readiness before considering login"}

    def error_body(error):
        try:
            with error:
                data = json.load(error)
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError, TypeError):
            return {}

    def unavailable():
        return {"authenticated": False, "status": "unavailable", "url": url,
                "next": "Check ChatBridge service and retry setup"}

    request = urllib.request.Request(url.rstrip("/") + "/ready", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            if getattr(response, "status", 200) != 200:
                raise RuntimeError("Unexpected ChatBridge readiness response")
            return outcome(json.load(response))
    except urllib.error.HTTPError as error:
        if error.code == 503:
            detail = error_body(error)
            reason = detail.get("reason")
            if reason == "browser_idle":
                if not verify_idle:
                    return {"authenticated": False, "status": "browser_idle",
                            "url": url, "next": "Use explicit browser verification during installer update"}
                probe = urllib.request.Request(url.rstrip("/") + "/v1/browser/verify",
                                               headers=headers, method="POST")
                try:
                    with urllib.request.urlopen(probe, timeout=80) as response:
                        return outcome(json.load(response))
                except urllib.error.HTTPError as failure:
                    if failure.code == 404:
                        # Pre-beta.12 ChatBridge has wake but not atomic verify.
                        # Explicit owner update may wake once; only /ready with
                        # a verified ChatGPT composer can establish login.
                        wake = urllib.request.Request(
                            url.rstrip("/") + "/v1/browser/wake",
                            headers=headers, method="POST")
                        try:
                            with urllib.request.urlopen(wake, timeout=80) as response:
                                if getattr(response, "status", 200) != 200:
                                    return unavailable()
                                json.load(response)
                        except urllib.error.HTTPError as wake_failure:
                            return {"authenticated": False, "status": "unavailable",
                                    "url": url,
                                    "next": "Legacy ChatBridge browser wake failed (HTTP " +
                                            str(wake_failure.code) + ")"}
                        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                            return unavailable()
                        return browser_login_status(url, verify_idle=False)
                    if failure.code == 503:
                        error_body(failure)
                        return {"authenticated": False, "status": "unverified",
                                "url": url, "next": "Browser verification failed; inspect ChatBridge logs"}
                    raise
                except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                    return unavailable()
            if reason in ("browser_unavailable", "browser_start_failed"):
                return unavailable()
            if reason in ("provider_cooldown", "provider_rate_limited"):
                return {"authenticated": False, "status": "cooldown", "url": url,
                        "next": "Wait for provider cooldown and retry"}
            if reason in ("auth_required", "login_required"):
                return {"authenticated": False, "status": "login_required",
                        "url": url, "next": "Sign in to the managed Chrome profile"}
            return {"authenticated": False, "status": "unverified",
                    "url": url, "next": "Inspect ChatBridge readiness response; a 503 is not proof of logout"}
        raise
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return unavailable()


def managed_paths(install_root: Path) -> tuple[Path, Path, Path]:
    root = install_root.expanduser().resolve()
    return (root / "deps/chatbridge-source", root / "deps/chatbridge",
            root / "deps/chatbridge-data")



def managed_service_label(install_root: Path) -> str:
    """Retain a verified original-label service; never create a second owner.

    Historical Mac Control installations provisioned `net.chatbridge.gateway`
    under the consolidated Mac Control dependency root. A running service
    may be upgraded in place with this original label, not relabelled live.
    """
    _, prefix, state = managed_paths(install_root)
    agents = Path.home() / "Library/LaunchAgents"
    managed = agents / (MANAGED_LABEL + ".plist")
    legacy = agents / "net.chatbridge.gateway.plist"
    if managed.exists() or managed.is_symlink():
        return MANAGED_LABEL
    if not legacy.is_file() or legacy.is_symlink():
        raise RuntimeError("ChatBridge endpoint is running without a managed LaunchAgent; stop it before installing Mac Control")
    try:
        info = legacy.stat()
        if info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o022:
            raise RuntimeError("Legacy ChatBridge service has unsafe ownership or permissions")
        with legacy.open('rb') as stream:
            data = plistlib.load(stream)
        env = data['EnvironmentVariables']
        release = Path(data['WorkingDirectory']).expanduser().resolve()
        program = data['ProgramArguments'][0]
        db = Path(env['CHATBRIDGE_DB']).expanduser().resolve()
        chrome = Path(env['CHATBRIDGE_CHROME_PROFILE']).expanduser().resolve()
        port = env['CHATBRIDGE_PORT']
        if (data.get('Label') != 'net.chatbridge.gateway'
                or data.get('ChatBridgeInstaller') != '1'
                or release.parent != (prefix / 'releases').resolve()
                or db != (state / 'state.db').resolve()
                or chrome != (state / 'chrome-profile').resolve()
                or not isinstance(port, str) or not port.isdecimal()
                or not 1 <= int(port) <= 65535
                or Path(program).expanduser().resolve() != (release / '.venv/bin/python').resolve()):
            raise RuntimeError("Legacy ChatBridge service is foreign or outside managed owner state")
        status = subprocess.run(
            ['/bin/launchctl', 'print', f'gui/{os.getuid()}/net.chatbridge.gateway'],
            capture_output=True, text=True, check=False, timeout=5)
        if (status.returncode != 0
                or f'path = {legacy}' not in status.stdout
                or f'program = {program}' not in status.stdout
                or 'state = running' not in status.stdout
                or not re.search(r'^\s*pid = [1-9][0-9]*$', status.stdout, re.MULTILINE)):
            raise RuntimeError("Cannot confirm running owner-managed historical ChatBridge service")
    except (OSError, KeyError, IndexError, ValueError, TypeError, AttributeError,
            plistlib.InvalidFileException, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Cannot verify historical ChatBridge service ownership") from error
    return 'net.chatbridge.gateway'


def verify_managed_install(install_root: Path) -> None:
    """Reject unknown endpoints; accept a provably owned historical label."""
    _, prefix, state = managed_paths(install_root)
    label = managed_service_label(install_root)
    plist = Path.home() / ("Library/LaunchAgents/" + label + ".plist")
    if not plist.is_file() or plist.is_symlink():
        raise RuntimeError("ChatBridge endpoint is running without a managed LaunchAgent; stop it before installing Mac Control")
    try:
        with plist.open("rb") as stream:
            data = plistlib.load(stream)
        workdir = Path(data["WorkingDirectory"]).resolve()
        variables = data["EnvironmentVariables"]
        database = Path(variables["CHATBRIDGE_DB"]).resolve()
    except (OSError, KeyError, ValueError, TypeError):
        raise RuntimeError("Cannot verify existing ChatBridge installation ownership") from None
    if (data.get("Label") != label
            or data.get("ChatBridgeInstaller") != "1"
            or workdir.parent != prefix / "releases"
            or database != state / "state.db"):
        raise RuntimeError("ChatBridge is installed outside ~/MacControlMCP; remove or migrate it first")


def owned_endpoint(install_root: Path) -> str | None:
    """Reuse actual bound port of the verified historical or current label."""
    agents = Path.home() / 'Library/LaunchAgents'
    if not any((agents / (label + '.plist')).exists() or
               (agents / (label + '.plist')).is_symlink()
               for label in (MANAGED_LABEL, 'net.chatbridge.gateway')):
        return None
    verify_managed_install(install_root)
    label = managed_service_label(install_root)
    plist = agents / (label + '.plist')
    with plist.open('rb') as stream:
        env = plistlib.load(stream).get('EnvironmentVariables', {})
    port = env.get('CHATBRIDGE_PORT')
    if not isinstance(port, str) or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise RuntimeError('Owned ChatBridge port missing or invalid; inspect its LaunchAgent')
    return 'http://127.0.0.1:' + port


def _alias_absent(label: str) -> None:
    """An exact launchctl not-found result is required before touching a plist."""
    command = ["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Cannot confirm legacy ChatBridge service is inactive") from None
    if result.returncode == 0:
        raise RuntimeError("Legacy ChatBridge service is loaded; active service preserved")
    expected = (f'Could not find service "{label}" in domain '
                f'for user gui: {os.getuid()}')
    if result.returncode != 113 or expected not in result.stderr:
        raise RuntimeError("Cannot confirm legacy ChatBridge service is inactive")


@contextmanager
def quarantine_stale_alias(install_root: Path):
    """Move only an unloaded, provably same-owner duplicate plist; restore on failure.

    The standalone ChatBridge installer retains its shared-state guard. Never
    stop or replace a service, profile or SQLite database here.
    """
    root = install_root.expanduser().resolve()
    _, prefix, state = managed_paths(root)
    agents = Path.home() / "Library/LaunchAgents"
    legacy = agents / "net.chatbridge.gateway.plist"
    managed = agents / (MANAGED_LABEL + ".plist")
    if not legacy.exists() and not legacy.is_symlink():
        yield
        return
    if legacy.is_symlink() or not legacy.is_file():
        raise RuntimeError("Unsafe legacy ChatBridge LaunchAgent path")
    # Never transfer a foreign service or an unrelated data directory.
    if not managed.is_file() or managed.is_symlink():
        yield
        return
    try:
        with managed.open("rb") as stream:
            ours = plistlib.load(stream)
        with legacy.open("rb") as stream:
            old = plistlib.load(stream)
        variables = ours["EnvironmentVariables"]
        old_variables = old["EnvironmentVariables"]
        release_root = (prefix / "releases").resolve()
        expected_db = (state / "state.db").resolve()
        expected_profile = (state / "chrome-profile").resolve()
        ours_release = Path(ours["WorkingDirectory"]).expanduser().resolve()
        old_release = Path(old["WorkingDirectory"]).expanduser().resolve()
        owns_managed = (
            ours.get("Label") == MANAGED_LABEL
            and ours.get("ChatBridgeInstaller") == "1"
            and ours_release.parent == release_root
            and Path(variables["CHATBRIDGE_DB"]).expanduser().resolve() == expected_db
            and Path(variables["CHATBRIDGE_CHROME_PROFILE"]).expanduser().resolve()
            == expected_profile
        )
        same_state = (
            Path(old_variables["CHATBRIDGE_DB"]).expanduser().resolve() == expected_db
            and Path(old_variables["CHATBRIDGE_CHROME_PROFILE"]).expanduser().resolve()
            == expected_profile
        )
        owns_legacy = (
            old.get("Label") == "net.chatbridge.gateway"
            and old.get("ChatBridgeInstaller") == "1"
            and old_release.parent == release_root
        )
    except (OSError, KeyError, TypeError, ValueError, plistlib.InvalidFileException):
        raise RuntimeError("Cannot verify legacy ChatBridge LaunchAgent ownership") from None
    if not same_state:
        yield
        return
    if not owns_managed or not owns_legacy:
        raise RuntimeError("Shared ChatBridge state belongs to an unknown or foreign owner")
    _alias_absent("net.chatbridge.gateway")
    backup_dir = state / "installer-backups/alias-quarantine"
    for candidate in (state, state / "installer-backups", backup_dir):
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_dir()):
            raise RuntimeError("Unsafe ChatBridge alias backup directory")
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir.chmod(0o700)
    nonce = str(time.time_ns()) + "-" + os.urandom(6).hex()
    backup = backup_dir / ("net.chatbridge.gateway-" + nonce + ".original.plist")
    quarantined = backup_dir / ("net.chatbridge.gateway-" + nonce + ".quarantine.plist")
    original = legacy.read_bytes()
    with backup.open("xb") as stream:
        stream.write(original)
    backup.chmod(0o600)
    if backup.read_bytes() != original:
        raise RuntimeError("ChatBridge duplicate LaunchAgent backup verification failed")
    _alias_absent("net.chatbridge.gateway")
    if legacy.read_bytes() != original:
        raise RuntimeError("Legacy ChatBridge LaunchAgent changed during preparation")
    legacy.rename(quarantined)
    try:
        if quarantined.read_bytes() != original:
            raise RuntimeError("Quarantined ChatBridge LaunchAgent integrity mismatch")
        yield
    except BaseException:
        if legacy.exists() or legacy.is_symlink():
            raise RuntimeError("Legacy ChatBridge LaunchAgent reappeared; backup retained") from None
        quarantined.rename(legacy)
        if legacy.read_bytes() != original:
            raise RuntimeError("Restored legacy ChatBridge LaunchAgent integrity mismatch")
        raise


def install(source: Path, *, url: str = DEFAULT_URL,
            install_root: Path | None = None) -> dict:
    """Owner-selected source checkout, not an implicit download or private API."""
    parsed = local_origin(url)
    source = source.expanduser().resolve()
    if install_root is not None:
        managed_source, _, _ = managed_paths(install_root)
        if source != managed_source:
            raise RuntimeError("For a consolidated installation, --chatbridge-source must be under ~/MacControlMCP/deps/chatbridge-source")
    for name in ("install.sh", "LICENSE", "pyproject.toml", "scripts/installer.py"):
        if not (source / name).is_file():
            raise RuntimeError("Not an independently installable ChatBridge source: " + name)
    manifest = (source / "pyproject.toml").read_text()
    if 'name = "chatbridge-gateway"' not in manifest:
        raise RuntimeError("Source is not the expected ChatBridge distribution")
    # Let ChatBridge own its application and state lifecycle inside Mac Control's deps.
    assert_installable(url, label=MANAGED_LABEL if install_root is not None else "net.chatbridge.gateway")
    environment = dict(os.environ)
    client_key = environment.get("MACCONTROL_CHATBRIDGE_API_KEY", "")
    server_key = environment.get("CHATBRIDGE_API_KEY", "")
    if server_key and server_key != client_key:
        raise RuntimeError("Set matching MACCONTROL_CHATBRIDGE_API_KEY and CHATBRIDGE_API_KEY before setup")
    if client_key:
        environment["CHATBRIDGE_API_KEY"] = client_key
    extra = []
    if install_root is not None:
        _, prefix, state = managed_paths(install_root)
        extra = ["--prefix", str(prefix), "--state-dir", str(state),
                 "--label", MANAGED_LABEL]
    try:
        # Preserve terminal input/output: ChatBridge owns interactive uv consent/login guidance.
        proc = subprocess.run([sys.executable, str(source / "scripts/installer.py"),
                               "install", "--host", "127.0.0.1", "--port", str(parsed.port or 80),
                               *extra],
                              cwd=source, check=False, timeout=1800, env=environment)
    except subprocess.TimeoutExpired:
        raise RuntimeError("ChatBridge setup timed out; inspect ChatBridge status before retrying") from None
    if proc.returncode:
        raise RuntimeError("ChatBridge setup failed; see its terminal diagnostics; no automatic overwrite attempted")
    print("Follow ChatBridge's printed guidance to open its managed profile and sign in.")
    print("Complete login manually; no real ChatGPT login has been verified by this installer.")
    result = verify(url)
    if install_root is not None:
        verify_managed_install(install_root)
    return result


def assert_installable(url: str, *, label: str = "net.chatbridge.gateway") -> None:
    """Refuse existing service ownership or an occupied port before any setup."""
    parsed = local_origin(url)
    plist = Path.home() / ("Library/LaunchAgents/" + label + ".plist")
    if plist.exists() or plist.is_symlink():
        raise RuntimeError("ChatBridge LaunchAgent already exists; inspect or upgrade it independently")
    state = Path.home() / ".chatbridge"
    if label == "net.chatbridge.gateway" and (
            state.is_symlink() or
            (state.exists() and (not state.is_dir() or any(state.iterdir())))):
        raise RuntimeError("Existing ChatBridge state found; recover/start it independently, then rerun Mac Control")
    try:
        loaded = subprocess.run(["/bin/launchctl", "print", "gui/" + str(os.getuid()) + "/" + label],
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


def download_pinned_source(root: Path) -> Path:
    """Extract a SHA256-pinned published ChatBridge source distribution."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
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
    return source


def install_pinned(url: str = DEFAULT_URL, install_root: Path | None = None) -> dict:
    assert_installable(url, label=MANAGED_LABEL if install_root is not None else "net.chatbridge.gateway")
    with tempfile.TemporaryDirectory(prefix="mac-control-chatbridge-") as temporary:
        root = Path(temporary)
        source = download_pinned_source(root)
        if install_root is not None:
            permanent, _, _ = managed_paths(install_root)
            if permanent.is_symlink():
                raise RuntimeError("Unsafe ChatBridge source directory")
            if permanent.exists():
                # A second install never overwrites an unreviewed source checkout.
                if not (permanent / "scripts/installer.py").is_file():
                    raise RuntimeError("Unexpected managed ChatBridge source directory")
            else:
                permanent.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                staging = permanent.with_name(".chatbridge-source-pending-" + os.urandom(6).hex())
                try:
                    shutil.copytree(source, staging, symlinks=False)
                    staging.rename(permanent)
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
            source = permanent
        return install(source, url=url, install_root=install_root)


def assert_managed_idle(url: str) -> None:
    """Do not interrupt a ChatBridge request during an automatic upgrade."""
    local_origin(url)
    key = os.environ.get("MACCONTROL_CHATBRIDGE_API_KEY", "")
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(url.rstrip("/") + "/v1/system/status",
                                     headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = json.load(response)
    except (OSError, urllib.error.URLError, ValueError, TimeoutError):
        raise RuntimeError("Cannot confirm ChatBridge idle; existing service preserved") from None
    browser = status.get("browser") if isinstance(status, dict) else None
    active = status.get("active") if isinstance(status, dict) else None
    browser_active = browser.get("active_requests") if isinstance(browser, dict) else None
    if (not isinstance(active, int) or isinstance(active, bool) or active < 0
            or not isinstance(browser_active, int) or isinstance(browser_active, bool)
            or browser_active < 0):
        raise RuntimeError("ChatBridge active request status is invalid; upgrade refused")
    if active or browser_active:
        raise RuntimeError("ChatBridge has active requests; retry update after they finish")


def upgrade_managed(install_root: Path, *, url: str = DEFAULT_URL) -> dict:
    """Upgrade only the owner's exact managed service from a pinned release.

    The standalone ChatBridge installer controls service rollback and persistent
    Chrome/SQLite; old source is retained if the service upgrade succeeds.
    """
    local_origin(url)
    verify_managed_install(install_root)
    source, prefix, state = managed_paths(install_root)
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError("Owned ChatBridge source is unavailable or symlinked")
    manifest = source / "pyproject.toml"
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError("Managed ChatBridge source version is unavailable")
    match = re.search(r'^version = "0\.2\.0b([0-9]+)"$', manifest.read_text(), re.MULTILINE)
    if not match:
        raise RuntimeError("Cannot identify managed ChatBridge version; upgrade refused")
    previous_version = int(match.group(1))
    if previous_version >= 12:
        return {"status": "current", "version": "0.2.0b" + str(previous_version)}
    assert_managed_idle(url)
    with tempfile.TemporaryDirectory(prefix="mac-control-chatbridge-upgrade-") as temporary:
        new_source = download_pinned_source(Path(temporary))
        staging = source.with_name(".chatbridge-source-pending-" + os.urandom(6).hex())
        if staging.exists() or staging.is_symlink():
            raise RuntimeError("Unsafe ChatBridge source staging path")
        shutil.copytree(new_source, staging, symlinks=False)
        try:
            if 'version = "0.2.0b12"' not in (staging / "pyproject.toml").read_text():
                raise RuntimeError("Pinned ChatBridge source version mismatch")
            command = [sys.executable, str(staging / "scripts/installer.py"),
                       "upgrade", "--prefix", str(prefix), "--state-dir", str(state),
                       "--label", managed_service_label(install_root)]
            try:
                completed = subprocess.run(command, cwd=staging, check=False,
                                           timeout=1800)
            except subprocess.TimeoutExpired:
                raise RuntimeError("ChatBridge upgrade timed out; inspect owned service") from None
            if completed.returncode:
                raise RuntimeError("Owned ChatBridge upgrade failed; old source preserved")
            verify_managed_install(install_root)
            verify(url)
            retained = source.with_name("chatbridge-source.previous-" +
                                        str(time.time_ns()) + "-" + os.urandom(4).hex())
            source.rename(retained)
            try:
                staging.rename(source)
            except OSError:
                retained.rename(source)
                raise
            return {"status": "upgraded", "version": "0.2.0b12",
                    "previous_source": str(retained)}
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def ensure(url: str = DEFAULT_URL, source: Path | None = None, install_root: Path | None = None) -> dict:
    """Reuse a compatible endpoint; only a refused connection permits fresh setup."""
    if install_root is not None:
        url = owned_endpoint(install_root) or select_endpoint(
            url, reuse_compatible=False)
    try:
        result = verify(url)
        if install_root is not None:
            verify_managed_install(install_root)
        return result
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise RuntimeError("ChatBridge requires a matching MACCONTROL_CHATBRIDGE_API_KEY; existing service preserved") from None
        raise RuntimeError(
            "Local port " + str(local_origin(url).port) +
            " serves a different/incompatible HTTP API (HTTP " + str(error.code) +
            "); existing service preserved. For Mac Control updates, "
            "omit ChatBridge provisioning (default), or use "
            "--without-chatbridge with an older installer."
        ) from None
    except urllib.error.URLError as error:
        if not isinstance(error.reason, ConnectionRefusedError) or error.reason.errno != errno.ECONNREFUSED:
            raise RuntimeError("ChatBridge probe failed; inspect the endpoint before installation") from None
    except (TimeoutError, ValueError):
        raise RuntimeError("ChatBridge probe timed out or returned invalid data; existing service preserved") from None
    assert_installable(url, label=MANAGED_LABEL if install_root is not None else "net.chatbridge.gateway")
    if install_root is not None and source is None:
        existing, _, _ = managed_paths(install_root)
        if existing.is_dir() and (existing / "scripts/installer.py").is_file():
            return install(existing, url=url, install_root=install_root)
    return (install(source, url=url, install_root=install_root) if source is not None
            else install_pinned(url, install_root=install_root))

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
