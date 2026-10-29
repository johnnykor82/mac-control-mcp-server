#!/usr/bin/env python3
"""Install/verify an independently distributed ChatBridge as an optional dependency.

Never vend ChatBridge source into Mac Control. Run only after the installing
agent has verified the separate ChatBridge GitHub checkout and its tag.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

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
    proc = subprocess.run([sys.executable, str(source / "scripts/installer.py"),
                           "install", "--host", "127.0.0.1", "--port", str(parsed.port or 80)],
                          cwd=source, check=False, capture_output=True,
                          timeout=180, text=True)
    if proc.returncode:
        raise RuntimeError("ChatBridge installer failed; inspect its own diagnostic logs")
    return verify(url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--install", action="store_true")
    opts = parser.parse_args()
    result = install(opts.source, url=opts.url) if opts.install and opts.source else verify(opts.url)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print("ChatBridge dependency setup failed: ", type(exc).__name__,
              str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "", file=sys.stderr)
        raise SystemExit(1)
