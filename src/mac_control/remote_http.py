"""Exact owner origin checks supplement FastMCP's hostname-only HTTP guard."""
from __future__ import annotations

from ipaddress import ip_address
import re
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.responses import Response


LOOPBACK_HOSTS = frozenset(("localhost", "127.0.0.1", "::1"))


def _origin(value: str) -> tuple[str, str, int]:
    if not isinstance(value, str) or any(ord(char) <= 32 or ord(char) >= 127 for char in value):
        raise ValueError("Invalid HTTP origin")
    parsed = urlsplit(value)
    port = parsed.port  # Reject malformed/out-of-range ports instead of ignoring them.
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.netloc.endswith(":")):
        raise ValueError("Invalid HTTP origin")
    host = parsed.hostname
    try:
        ip_address(host)
    except ValueError:
        if len(host) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                     for label in host.rstrip(".").split(".")):
            raise ValueError("Invalid origin hostname") from None
    if "%" in host or port == 0:
        raise ValueError("Invalid HTTP origin")
    return parsed.scheme, host, port or (443 if parsed.scheme == "https" else 80)


def public_origin(value: str) -> tuple[str, str, int]:
    origin = _origin(value)
    if origin[0] != "https":
        raise ValueError("Public URL must be an HTTPS origin")
    return origin


class RemoteOriginGuard:
    def __init__(self, app, public_url: str):
        self.app = app
        self.public = public_origin(public_url)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        hosts = headers.getlist("host")
        try:
            if len(hosts) != 1 or any(char in hosts[0] for char in "/?#@"):
                raise ValueError("Invalid Host")
            _, host, port = _origin("https://" + hosts[0])
            if host not in LOOPBACK_HOSTS and (host, port) != self.public[1:]:
                raise ValueError("Untrusted Host")
        except ValueError:
            await Response("Misdirected Request", status_code=421)(scope, receive, send)
            return
        origins = headers.getlist("origin")
        if origins:
            try:
                if len(origins) != 1:
                    raise ValueError("Invalid Origin")
                origin = _origin(origins[0])
                if origin != self.public and not (host in LOOPBACK_HOSTS and origin[1] in LOOPBACK_HOSTS):
                    raise ValueError("Untrusted Origin")
            except ValueError:
                await Response("Forbidden Origin", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def remote_http_options(public_url: str) -> dict:
    # FastMCP 4.1.1 ignores Host ports and keeps same-origin HTTP fallback even
    # with allowed_origins. The additional guard enforces the owner HTTPS origin.
    _, host, _ = public_origin(public_url)
    return {
        "allowed_hosts": [host],
        "allowed_origins": [public_url.rstrip("/")],
        "middleware": [Middleware(RemoteOriginGuard, public_url=public_url)],
    }
