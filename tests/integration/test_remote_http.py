"""Exercise the remote CLI's real HTTP stack without sockets or GitHub calls."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastmcp import FastMCP
from fastmcp.server.http import HostOriginGuardMiddleware
from starlette.responses import Response
from starlette.testclient import TestClient

from mac_control.remote_auth import build_auth, load_config
from scripts.dev_mcp_server import main
from tests.integration.test_remote_auth import sample_config


PUBLIC_URL = "https://mac.owner-tailnet.ts.net"


class RemoteHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "remote_auth.json"

    def make_client(self, public_url=PUBLIC_URL):
        config = sample_config()
        config["public_url"] = public_url
        self.path.write_text(json.dumps(config))
        self.path.chmod(0o600)
        auth = build_auth(self.path)
        with patch("sys.argv", ["dev_mcp_server.py", "--remote"]), patch(
            "mac_control.remote_auth.build_auth", return_value=auth
        ), patch.object(FastMCP, "run", autospec=True) as run:
            main()
        server = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertIs(kwargs["host_origin_protection"], True)
        app_options = {key: value for key, value in kwargs.items()
                       if key not in ("host", "port", "show_banner")}
        app = server.http_app(**app_options)

        async def loopback_backend(scope, receive, send):
            # TestClient normally derives scope.server from the public URL. A real
            # reverse proxy reaches a loopback listener while preserving Host.
            await app(dict(scope, server=("127.0.0.1", 3201)), receive, send)

        return TestClient(loopback_backend, base_url=public_url)

    def test_public_discovery_and_unauthenticated_mcp_challenge(self):
        client = self.make_client()
        response = client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["issuer"].rstrip("/"), PUBLIC_URL)
        authorization_metadata = response.text
        resource = client.get("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(resource.status_code, 200)
        self.assertEqual(resource.json()["authorization_servers"], [PUBLIC_URL + "/"])
        response = client.get("/mcp")
        self.assertEqual(response.status_code, 401)
        self.assertIn(PUBLIC_URL, response.headers["www-authenticate"])
        for body in (authorization_metadata, resource.text, response.text, response.headers["www-authenticate"]):
            self.assertNotIn(sample_config()["github_client_secret"], body)
            self.assertNotIn(sample_config()["jwt_signing_key"], body)

    def test_other_hosts_cannot_be_authorized_by_proxy_headers(self):
        client = self.make_client()
        for host in ("attacker.test", "other.owner-tailnet.ts.net", "mac.owner-tailnet.ts.net.attacker.test"):
            with self.subTest(host=host):
                response = client.get("/.well-known/oauth-authorization-server", headers={
                    "host": host, "x-forwarded-host": "mac.owner-tailnet.ts.net",
                    "x-forwarded-proto": "https", "forwarded": 'host="mac.owner-tailnet.ts.net";proto=https',
                })
                self.assertEqual(response.status_code, 421)

    def test_public_host_requires_configured_port(self):
        client = self.make_client()
        for host in ("mac.owner-tailnet.ts.net", "mac.owner-tailnet.ts.net:443"):
            with self.subTest(host=host):
                self.assertEqual(client.get("/mcp", headers={"host": host}).status_code, 401)
        for host in ("mac.owner-tailnet.ts.net:444", "mac.owner-tailnet.ts.net:3201", "mac.owner-tailnet.ts.net:bad"):
            with self.subTest(host=host):
                self.assertEqual(client.get("/mcp", headers={"host": host}).status_code, 421)

    def test_public_origin_requires_https_and_configured_port_even_behind_http_proxy(self):
        client = self.make_client()
        for origin in (PUBLIC_URL, PUBLIC_URL + ":443"):
            with self.subTest(origin=origin):
                self.assertEqual(client.get("http://mac.owner-tailnet.ts.net/mcp", headers={"origin": origin}).status_code, 401)
        for origin in (PUBLIC_URL.replace("https:", "http:"), PUBLIC_URL + ":444",
                       "https://attacker.test", "null", PUBLIC_URL + "/path", "https://@mac.owner-tailnet.ts.net"):
            with self.subTest(origin=origin):
                self.assertEqual(client.get("http://mac.owner-tailnet.ts.net/mcp", headers={"origin": origin}).status_code, 403)

    def test_loopback_probe_hosts_and_origins_remain_allowed(self):
        client = self.make_client()
        for host in ("localhost:3201", "127.0.0.1:3201", "[::1]:3201"):
            with self.subTest(host=host):
                self.assertEqual(client.get("/mcp", headers={"host": host}).status_code, 401)
                self.assertEqual(client.get("/mcp", headers={"host": host, "origin": "http://localhost:3201"}).status_code, 401)
                self.assertEqual(client.get("/mcp", headers={"host": host, "origin": "http://[::1]:3201"}).status_code, 401)
                self.assertEqual(client.get("/mcp", headers={"host": host, "origin": "https://attacker.test"}).status_code, 403)

    def test_missing_duplicate_or_malformed_host_is_rejected(self):
        client = self.make_client()
        for host in ("", "mac.owner-tailnet.ts.net/", "user@mac.owner-tailnet.ts.net", "[::1]:bad", "[::1]attacker.test"):
            with self.subTest(host=host):
                self.assertEqual(client.get("/mcp", headers={"host": host}).status_code, 421)
        self.assertEqual(client.get("/mcp", headers=[("host", "mac.owner-tailnet.ts.net"), ("host", "attacker.test")]).status_code, 421)
        # TestClient fills in a missing Host from its URL, so send bare ASGI.
        messages = []

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            messages.append(message)

        asyncio.run(client.app({"type": "http", "headers": [], "method": "GET",
                                "path": "/mcp", "scheme": "http", "query_string": b""}, receive, send))
        self.assertEqual(messages[0]["status"], 421)

    def test_duplicate_origin_is_rejected(self):
        client = self.make_client()
        response = client.get("/mcp", headers=[("origin", PUBLIC_URL), ("origin", "https://attacker.test")])
        self.assertEqual(response.status_code, 403)

    def test_explicit_public_port_and_ipv6(self):
        for public_url, host in ((PUBLIC_URL + ":8443", "mac.owner-tailnet.ts.net"),
                                 ("https://[2001:db8::1]:8443", "[2001:db8::1]")):
            with self.subTest(public_url=public_url):
                client = self.make_client(public_url)
                self.assertEqual(client.get("/mcp", headers={"origin": public_url}).status_code, 401)
                self.assertEqual(client.get("/mcp", headers={"host": host}).status_code, 421)
                self.assertEqual(client.get("/mcp", headers={"origin": "https://" + host}).status_code, 403)

    def test_config_cannot_turn_hostname_into_fastmcp_glob(self):
        for public_url in ("https://*.ts.net", "https://mac.example:bad", "https://mac.example:70000", "https://mac.example:", "https://mac.exa\nmple", "https://@mac.example"):
            with self.subTest(public_url=public_url):
                config = sample_config()
                config["public_url"] = public_url
                self.path.write_text(json.dumps(config))
                self.path.chmod(0o600)
                with self.assertRaises(ValueError):
                    load_config(self.path)

    def test_stock_guard_has_same_origin_http_fallback(self):
        # Documents why allowed_origins alone cannot enforce the HTTPS boundary.
        app = HostOriginGuardMiddleware(Response("ok"), mode="strict",
            allowed_hosts=["mac.owner-tailnet.ts.net"], allowed_origins=[PUBLIC_URL])
        response = TestClient(app).get("http://mac.owner-tailnet.ts.net/mcp",
                                     headers={"origin": "http://mac.owner-tailnet.ts.net"})
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
