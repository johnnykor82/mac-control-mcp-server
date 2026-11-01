"""Pure analysis of a shared Tailscale Funnel 443 and additive route changes.

Never call reset or overwrite the root handler. Both Tailscale CLI status
views must agree before considering any mutation.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

TARGET = "http://127.0.0.1:3201"
PORT = "443"


def backend_for(path: str) -> str:
    """Tailscale strips --set-path before proxying; restore the exact path.

    With --set-path=/maccontrol and target http://127.../maccontrol,
    /maccontrol/mcp arrives at the backend unchanged as /maccontrol/mcp.
    """
    if not path.startswith("/") or "//" in path:
        raise ValueError("Invalid backend route path")
    return TARGET + path



def route_paths(prefix: str) -> tuple[str, ...]:
    if prefix != "/maccontrol" and not (
        prefix.startswith("/maccontrol-") and
        prefix[len("/maccontrol-"):].isdigit() and
        2 <= int(prefix[len("/maccontrol-"):]) <= 99
    ):
        raise ValueError("Unsupported Mac Control path prefix")
    return (prefix,
            "/.well-known/oauth-authorization-server" + prefix,
            "/.well-known/oauth-protected-resource" + prefix + "/mcp")


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def analyze(config: dict, hostname: str, prefix: str) -> dict:
    """Validate unrelated routes and provide a stable coexistence fingerprint."""
    expected = route_paths(prefix)
    host = hostname + ":" + PORT
    if not isinstance(config, dict) or any(
        key not in ("TCP", "Web", "AllowFunnel") for key in config
    ):
        return {"status": "conflict", "reason": "unknown_config_sections"}
    for key in ("TCP", "Web", "AllowFunnel"):
        if not isinstance(config.get(key, {}), dict):
            return {"status": "conflict", "reason": "malformed_config"}
    tcp = config.get("TCP", {})
    web = config.get("Web", {})
    enabled = config.get("AllowFunnel", {})
    if any(key != PORT for key in tcp) or _canonical(tcp.get(PORT)) != _canonical({"HTTPS": True}):
        return {"status": "conflict", "reason": "incompatible_https_listener"}
    if any(key != host for key in web) or _canonical(enabled) != _canonical({host: True}):
        return {"status": "conflict", "reason": "unexpected_https_hostname_or_visibility"}
    section = web.get(host)
    if not isinstance(section, dict) or set(section) != {"Handlers"}:
        return {"status": "conflict", "reason": "invalid_web_handler"}
    handlers = section["Handlers"]
    if not isinstance(handlers, dict) or not handlers:
        return {"status": "conflict", "reason": "missing_handlers"}
    owned = {}
    for path, rule in handlers.items():
        if not isinstance(path, str) or not path.startswith("/"):
            return {"status": "conflict", "reason": "invalid_handler_path"}
        if path in expected:
            if rule != {"Proxy": backend_for(path)}:
                return {"status": "conflict", "reason": "reserved_path_owned_by_other",
                        "path": path}
            owned[path] = rule
        else:
            for expected_path in expected:
                if expected_path == prefix:
                    # The existing root / is shared, and unrelated siblings
                    # (e.g. /aidom) do not conflict with /maccontrol.
                    if path != "/" and (path.startswith(prefix + "/")
                                        or prefix.startswith(path.rstrip("/") + "/")):
                        return {"status": "conflict", "reason": "overlapping_path",
                                "path": path}
                elif path != "/" and (
                    path.startswith(expected_path + "/")
                    or expected_path.startswith(path.rstrip("/") + "/")
                ):
                    # Existing generic discovery routes may intentionally be
                    # narrower than root; exact new path overrides them.
                    if path not in ("/.well-known/oauth-authorization-server",
                                    "/.well-known/oauth-protected-resource"):
                        return {"status": "conflict", "reason": "overlapping_discovery",
                                "path": path}
    remaining = deepcopy(config)
    for path in owned:
        remaining["Web"][host]["Handlers"].pop(path)
    fingerprint = hashlib.sha256(_canonical(remaining).encode()).hexdigest()
    missing = [path for path in expected if path not in owned]
    return {"status": "shared_matching" if not missing else
            "shared_partial" if owned else "shared_available",
            "public_url": "https://" + hostname + prefix,
            "prefix": prefix, "missing": missing,
            "already_present": sorted(owned),
            "unrelated_routes_sha256": fingerprint}


def choose(config: dict, hostname: str) -> dict:
    for prefix in ["/maccontrol", *[f"/maccontrol-{n}" for n in range(2, 10)]]:
        result = analyze(config, hostname, prefix)
        if result["status"] != "conflict":
            return result
    return {"status": "conflict", "reason": "no_free_maccontrol_prefix"}


def compare_preserved(before: dict, after: dict) -> bool:
    return before.get("unrelated_routes_sha256") == after.get("unrelated_routes_sha256")
