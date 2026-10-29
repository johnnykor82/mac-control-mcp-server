"""Tests standalone remote auth configuration without contacting GitHub."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest

from mac_control.remote_auth import build_auth, load_config
from scripts.dev_mcp_server import make_server


def sample_config():
    return {
        "github_client_id": "public-client-id",
        "github_client_secret": "fake-local-test-secret",
        "github_allowed_ids": ["12345678"],
        "public_url": "https://agent.example.test",
        "jwt_signing_key": "testing-only-signing-key-" + "X" * 48,
    }


class RemoteAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "remote_auth.json"
        self.write(sample_config())

    def write(self, config, mode=0o600):
        self.path.write_text(json.dumps(config))
        self.path.chmod(mode)

    def test_valid_owner_private_config_and_authorized_tool_inventory(self):
        loaded = load_config(self.path)
        self.assertEqual(loaded["github_allowed_ids"], ["12345678"])
        auth = build_auth(self.path)
        tools = asyncio.run(make_server(include_mutations=True, auth=auth).list_tools())
        self.assertGreaterEqual(len(tools), 102)
        self.assertIn("terminal_exec", {tool.name for tool in tools})

    def test_world_readable_config_is_rejected(self):
        self.write(sample_config(), 0o644)
        with self.assertRaises(PermissionError):
            load_config(self.path)

    def test_missing_config_is_rejected(self):
        self.path.unlink()
        with self.assertRaises(RuntimeError):
            build_auth(self.path)

    def test_insecure_public_url_is_rejected(self):
        data = sample_config()
        data["public_url"] = "http://example.test"
        self.write(data)
        with self.assertRaises(ValueError):
            load_config(self.path)

    def test_empty_allowlist_rejected(self):
        data = sample_config()
        data["github_allowed_ids"] = []
        self.write(data)
        with self.assertRaises(ValueError):
            load_config(self.path)

    def test_local_http_remains_read_only(self):
        web = asyncio.run(make_server().list_tools())
        self.assertEqual(len(web), 20)
        self.assertNotIn("terminal_exec", {tool.name for tool in web})


if __name__ == "__main__":
    unittest.main()
