#!/usr/bin/env python3
"""Read-only preflight for a standalone Mac Control installation.

Network probes are opt-in. A reported public IP does not prove incoming access.
No configuration is changed and no credential values are read.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import urllib.request

try:
    from scripts.runtime_tools import find_uv
except ModuleNotFoundError:
    # Direct invocation: python3 scripts/<name>.py.
    from runtime_tools import find_uv


def command(name: str) -> str | None:
    return find_uv() if name == "uv" else shutil.which(name)


def output(argv: list[str], timeout: float = 3) -> str:
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
        return (result.stdout or "").strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def addresses() -> dict[str, list[str]]:
    # Local interface inventory, not proof of inbound reachability.
    interface_text = output(["/sbin/ifconfig"], 4)
    v4: set[str] = set()
    v6: set[str] = set()
    for raw in interface_text.splitlines():
        fields = raw.strip().split()
        if len(fields) < 2 or fields[0] not in ("inet", "inet6"):
            continue
        value = fields[1].split("%", 1)[0]
        try:
            addr = ipaddress.ip_address(value)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local:
            continue
        (v4 if addr.version == 4 else v6).add(str(addr))
    return {"ipv4": sorted(v4), "ipv6": sorted(v6)}


def public_address(url: str) -> dict[str, str]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "MacControl-Preflight/1.0"})
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read(100).decode("ascii", errors="replace").strip()
        ip = ipaddress.ip_address(body)
        return {"address": str(ip), "type": "ipv4" if ip.version == 4 else "ipv6"}
    except (OSError, ValueError, UnicodeError) as error:
        return {"error": type(error).__name__}


def inspect(network: bool = False) -> dict:
    system = platform.system()
    local = addresses() if system == "Darwin" else {"ipv4": [], "ipv6": []}
    public = [str(ip) for family in ("ipv4", "ipv6") for value in local[family]
              if (ip := ipaddress.ip_address(value)).is_global]
    data = {
        "schema": 1,
        "macos": system == "Darwin",
        "os_version": platform.mac_ver()[0] if system == "Darwin" else platform.platform(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "user_is_root": os.geteuid() == 0 if hasattr(os, "geteuid") else False,
        "tools": {key: bool(command(key)) for key in
                  ("git", "uv", "brew", "python3", "xcode-select", "swift", "codesign",
                   "curl", "tailscale", "cloudflared")},
        "developer_directory": output(["/usr/bin/xcode-select", "-p"]) if system == "Darwin" else "",
        "local_addresses": local,
        "locally_global_ip_candidates": public,
        "external_ipv4": {"status": "not_checked"},
        "external_ipv6": {"status": "not_checked"},
        "incoming_reachable": "not_tested",
        "notes": [
            "A public address, including globally routable IPv6, does not prove incoming HTTPS reachability.",
            "CGNAT cannot be ruled out from external-IP lookup alone.",
            "For cloud-hosted MCP clients, a separately validated public HTTPS endpoint is required.",
            "Tailscale Serve only serves the tailnet; Tailscale Funnel can expose a publicly reachable HTTPS endpoint.",
            "Keep all authentication and approval decisions under the owner's control.",
        ],
    }
    if network:
        data["external_ipv4"] = public_address("https://api.ipify.org")
        data["external_ipv6"] = public_address("https://api64.ipify.org")  # May return IPv4.
    data["ready_for_guided_install"] = (data["macos"] and not data["user_is_root"] and
                                         data["tools"]["git"] and data["tools"]["python3"] and
                                         data["tools"]["uv"])
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", action="store_true", help="Contact public IP echo endpoints")
    parser.add_argument("--json", action="store_true", help="Print machine-readable report")
    args = parser.parse_args()
    report = inspect(args.network)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("Mac Control preflight")
        for key in ("macos", "os_version", "architecture", "python",
                    "ready_for_guided_install", "incoming_reachable"):
            print(f"{key}: {report[key]}")
        print("tools:", ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in report["tools"].items()))
        print("local addresses:", report["local_addresses"])
        print("external IPv4:", report["external_ipv4"])
        print("external IPv6:", report["external_ipv6"])
        for note in report["notes"]:
            print("note:", note)
    return 0 if report["ready_for_guided_install"] else 2


if __name__ == "__main__":
    sys.exit(main())
