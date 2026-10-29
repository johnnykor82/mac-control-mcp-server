#!/usr/bin/env python3
"""Owner-guided remote connectivity and Tailscale Funnel setup.

All diagnoses and instructions are read-only. Enabling Funnel is a separate
explicit, interactive command; no public endpoint is enabled by installation.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

try:
    from .release_preflight import inspect
    from .setup_github_oauth import check as check_oauth
except ImportError:  # Allow direct execution: python scripts/setup_network.py
    from release_preflight import inspect
    from setup_github_oauth import check as check_oauth

DEFAULT_ROOT = Path.home() / "Library/Application Support/MacControl/MCPServer"
PORT = 3201


def run(argv: list[str], timeout: int = 12) -> subprocess.CompletedProcess:
    return subprocess.run(argv, text=True, capture_output=True, timeout=timeout,
                          check=False, env={**os.environ, "TAILSCALE_BE_CLI": "1"})


def tailscale_cli() -> str | None:
    """Locate CLI in PATH or inside the official macOS GUI app.

    Both App Store and Standalone variants can expose HTTP ports through
    Funnel. No separate tailscaled daemon or symlink is required.
    """
    executable = shutil.which("tailscale")
    if executable:
        return executable
    for app in (Path("/Applications/Tailscale.app"),
                Path.home() / "Applications/Tailscale.app"):
        embedded = app / "Contents/MacOS/Tailscale"
        if embedded.is_file() and os.access(embedded, os.X_OK):
            return str(embedded)
    return None


def tailscale_state() -> dict:
    executable = tailscale_cli()
    if not executable:
        return {"installed": False, "logged_in": False}
    version = run([executable, "version"])
    status = run([executable, "status", "--json"])
    if status.returncode != 0:
        return {"installed": True, "logged_in": False,
                "version": (version.stdout.splitlines() or ["unknown"])[0]}
    try:
        data = json.loads(status.stdout)
    except ValueError:
        data = {}
    device = data.get("Self") if isinstance(data.get("Self"), dict) else {}
    return {
        "installed": True, "logged_in": data.get("BackendState") == "Running",
        "device_dns_name": str(device.get("DNSName", "")).rstrip("."),
        "backend_state": data.get("BackendState", "unknown"),
        "version": (version.stdout.splitlines() or ["unknown"])[0],
        "cli_path": executable,
    }


def diagnose(*, network: bool = False) -> dict:
    base = inspect(network=network)
    ts = tailscale_state()
    # Local interface addresses alone cannot prove public inbound access.
    eligible = base.get("locally_global_ip_candidates", [])
    outcome = "verification_required"
    if not eligible:
        outcome = "no_globally_routable_local_interface_address"
    return {
        "schema": 1,
        "incoming_reachable": "not_tested",
        "local_ip_signal": outcome,
        "public_ip_verified": False,
        "public_ipv4_echo": base["external_ipv4"],
        "public_ipv6_echo": base["external_ipv6"],
        "tailscale": ts,
        "recommendation": (
            "Mac Control's supported guided remote deployment is Tailscale Funnel. "
            "It provides public HTTPS without a public IP and does not require "
            "changes to default routes, existing VPN connections, or exit-node settings. "
            "CGNAT and inbound reachability cannot be determined from IP echo alone."
        ),
        "funnel_requires": [
            "Authenticated Tailscale client, MagicDNS and HTTPS on tailnet",
            "Owner authorization for funnel node attribute",
            "Existing Mac Control remote OAuth configuration and anonymous 401",
            "Explicit owner approval before opening a public HTTPS endpoint",
            "External-client test of HTTPS and real GitHub OAuth",
        ],
    }


def guide() -> None:
    print("Mac Control remote connection (no verified public inbound IP/port):")
    print("1. Confirm whether public IPv4/IPv6 with incoming HTTPS is actually reachable.")
    print("   Public IP echo alone does not prove inbound access; CGNAT may exist.")
    print("2. Use the existing Tailscale app if installed (App Store or Standalone).")
    print("   If absent, install the official macOS client:")
    print("   https://tailscale.com/docs/install/mac")
    print("3. Log in to Tailscale and approve macOS networking permissions.")
    print("   The installer detects the CLI inside Tailscale.app when not in PATH.")
    print("   Existing VPN connections, routes and Exit Node selections are untouched.")
    print("4. Enable MagicDNS / HTTPS and Funnel for this device in your tailnet.")
    print("   Tailscale prompts for web approval as needed (owner performs login).")
    print("5. Configure your own GitHub OAuth App in Mac Control using the resulting")
    print("   HTTPS origin: https://YOUR-DEVICE.YOUR-TAILNET.ts.net")
    print("   callback: https://YOUR-DEVICE.YOUR-TAILNET.ts.net/auth/callback")
    print("6. Start Mac Control's AUTHENTICATED loopback service on 127.0.0.1:3201.")
    print("7. Confirm unauthenticated /mcp requests return HTTP 401.")
    print("8. Run this guide's --enable-funnel with explicit owner consent.")
    print("   Underlying Tailscale CLI command: tailscale funnel --bg 3201")
    print("9. Check tailscale funnel status, external HTTPS and actual GitHub OAuth.")
    print("   Tailscale Serve is tailnet-only; Funnel is public HTTPS.")
    print("   DO NOT expose the unauthenticated DEV preview port 3101.")
    print("Docs: https://tailscale.com/docs/features/tailscale-funnel")
    print("      https://tailscale.com/docs/reference/tailscale-cli/funnel")


def _oauth_guard(root: Path) -> dict:
    configured = check_oauth(root)
    local = f"http://127.0.0.1:{PORT}/mcp"
    request = urllib.request.Request(
        local, method="POST",
        headers={"Content-Type": "application/json"},
        data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
            challenge = bool(response.headers.get("WWW-Authenticate"))
    except urllib.error.HTTPError as exc:
        status = exc.code
        challenge = bool(exc.headers.get("WWW-Authenticate"))
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError("Authenticated Mac Control loopback server is not running") from exc
    if status != 401 or not challenge:
        raise RuntimeError("Refusing public Funnel: unauthenticated MCP did not return 401")
    return configured


def enable_funnel(root: Path, *, input_fn=input) -> dict:
    executable = tailscale_cli()
    ts = tailscale_state()
    if not executable or not ts.get("logged_in"):
        raise RuntimeError("Install and authenticate Tailscale first")
    hostname = ts.get("device_dns_name", "")
    if not hostname.endswith(".ts.net"):
        raise RuntimeError("Tailscale device FQDN unavailable; configure MagicDNS/HTTPS")
    configured = _oauth_guard(root)
    expected = "https://" + hostname
    if configured["public_url"].rstrip("/") != expected:
        raise RuntimeError("Configured GitHub OAuth HTTPS origin does not match Tailscale device")
    if not sys.stdin.isatty():
        raise RuntimeError("Interactive owner approval in Terminal is required")
    print("WARNING: Funnel will expose your AUTHENTICATED Mac Control HTTP port to the public internet.")
    print("Public HTTPS address:", expected)
    print("Authorized account IDs:", ", ".join(configured["allowed_github_ids"]))
    if input_fn("Type PUBLISH to enable public HTTPS Funnel on this Mac: ") != "PUBLISH":
        raise RuntimeError("Owner did not authorize public exposure")
    # Do not clobber any pre-existing Funnel publication on the same Mac.
    existing = run([executable, "funnel", "status"])
    if existing.returncode != 0:
        raise RuntimeError("Unable to inspect existing Funnel routes; no changes made")
    if "Funnel on" in existing.stdout:
        raise RuntimeError("Funnel routes already exist; review them manually before changing")
    outcome = run([executable, "funnel", "--bg", str(PORT)], timeout=50)
    if outcome.returncode != 0:
        raise RuntimeError("Tailscale Funnel setup failed; inspect tailscale funnel status")
    return {
        "status": "funnel_command_succeeded",
        "public_url": expected,
        "port": PORT,
        "external_connectivity_verified": False,
        "github_oauth_login_verified": False,
        "next": "Check tailscale funnel status; test public OAuth from an external MCP client",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--diagnose", action="store_true")
    choices.add_argument("--guide", action="store_true")
    choices.add_argument("--enable-funnel", action="store_true")
    parser.add_argument("--network", action="store_true",
                        help="Opt in to external IP echo lookups for diagnostics")
    args = parser.parse_args()
    if args.guide:
        guide()
    else:
        report = enable_funnel(args.root) if args.enable_funnel else diagnose(network=args.network)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("Mac Control network setup failed:", type(exc).__name__,
              str(exc) if isinstance(exc, (RuntimeError, ValueError)) else "",
              file=sys.stderr)
        raise SystemExit(1)
