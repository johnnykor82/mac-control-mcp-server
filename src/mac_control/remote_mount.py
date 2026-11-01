"""Mount an OAuth-protected FastMCP instance without claiming the root site."""
from __future__ import annotations

from urllib.parse import urlsplit
from starlette.applications import Starlette
from starlette.routing import Mount, Route


def service_prefix(public_url: str) -> str:
    """No accidental nested/doubled mount points or untrusted URL paths."""
    from .remote_http import public_service_url
    public_service_url(public_url)
    return urlsplit(public_url).path.rstrip("/")


def create_remote_app(server, public_url: str, *, middleware=None,
                      allowed_hosts=None, allowed_origins=None):
    prefix = service_prefix(public_url)
    app = server.http_app(
        path="/mcp", middleware=middleware,
        host_origin_protection=True,
        allowed_hosts=allowed_hosts, allowed_origins=allowed_origins)
    if not prefix:
        return app

    discovery = []
    for route in app.routes:
        if not isinstance(route, Route) or not route.path.startswith("/.well-known/"):
            continue
        public_path = route.path
        if route.path in ("/.well-known/oauth-authorization-server",
                          "/.well-known/openid-configuration"):
            public_path += prefix
        # These public metadata routes need to be reached on the site root.
        # The caller never registers generic /.well-known/* catch-all.
        discovery.append(Route(public_path, route.endpoint,
                               methods=sorted(route.methods) if route.methods else None,
                               name=route.name))
    return Starlette(routes=[*discovery, Mount(prefix, app=app)],
                     lifespan=app.lifespan)
