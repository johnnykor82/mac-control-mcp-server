"""GitHub OAuth onboarding tests: offline, no real credentials or app creation."""
from __future__ import annotations

import io
import asyncio
from types import SimpleNamespace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import setup_github_oauth as oauth
from scripts import test_github_oauth_login as login_test


class GitHubOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "Mac Control MCP Server"
        self.root.mkdir(mode=0o700)
        (self.root / ".mac-control-installer-owned").write_text("owned")
        (self.root / "data").mkdir(mode=0o700)
        self.path = self.root / "data/remote_auth.json"

    def _configure(self, confirmation="YES"):
        answers = iter([confirmation, "Ov23abc00000test"])
        with patch.object(oauth, "github_account",
                          return_value=("fakeowner", "12500001", "authenticated_github_cli")):
            return oauth.configure(self.root, "https://mac.example.test", None,
                                   input_fn=lambda prompt: next(answers),
                                   secret_fn=lambda prompt: "test-" + "F" * 50)

    def test_guide_builds_exact_callback_without_changing_disk(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            oauth.guide("https://mac.example.test", "fakeowner")
        text = stdout.getvalue()
        self.assertIn("https://mac.example.test/auth/callback", text)
        self.assertIn("https://github.com/settings/applications/new", text)
        self.assertFalse(self.path.exists())

    def test_owner_onboarding_config_uses_0600_and_validates_through_prod(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = self._configure()
        self.assertEqual(result["status"], "configured")
        self.assertEqual(result["oauth_login_verified"], False)
        self.assertNotIn("F" * 20, json.dumps(result) + stdout.getvalue())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        on_disk = json.loads(self.path.read_text())
        self.assertEqual(on_disk["github_allowed_ids"], ["12500001"])
        self.assertEqual(on_disk["github_client_id"], "Ov23abc00000test")
        self.assertGreaterEqual(len(on_disk["jwt_signing_key"]), 64)
        check = oauth.check(self.root)
        self.assertEqual(check["callback_url"], "https://mac.example.test/auth/callback")
        self.assertNotIn(on_disk["github_client_secret"], str(check))

    def test_existing_credentials_are_never_overwritten(self):
        with patch("sys.stdout", new_callable=io.StringIO):
            self._configure()
        original = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            self._configure()
        self.assertEqual(original, self.path.read_bytes())

    def test_no_owner_consent_writes_nothing(self):
        with patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaises(RuntimeError):
                self._configure("no")
        self.assertFalse(self.path.exists())

    def test_install_ownership_required(self):
        (self.root / ".mac-control-installer-owned").unlink()
        with self.assertRaises(RuntimeError):
            oauth.destination(self.root)

    def test_reject_insecure_url_and_credentials(self):
        for value in ("http://example.com", "https://example.com/path",
                      "https://localhost", "https://user:pass@example.com",
                      "https://example.com?token=secret", "https://192.168.1.1", "https://10.0.0.1"):
            with self.assertRaises(ValueError, msg=value):
                oauth.public_origin(value)

    def test_session_check_refuses_world_readable_file(self):
        with patch("sys.stdout", new_callable=io.StringIO):
            self._configure()
        self.path.chmod(0o644)
        with self.assertRaises(PermissionError):
            oauth.check(self.root)

    def test_token_is_not_placed_in_process_args(self):
        with patch.object(oauth.shutil, "which", return_value="/opt/homebrew/bin/gh"), \
             patch.object(oauth.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps({"login": "fakeowner", "id": 12500001})
            login, user_id, confidence = oauth.github_account(None)
        self.assertEqual((login, user_id), ("fakeowner", "12500001"))
        self.assertEqual(confidence, "authenticated_github_cli")
        self.assertEqual(run.call_args.args[0], ["gh", "api", "user",
                                                "--jq", "{login: .login, id: .id}"])

    def test_gh_login_mismatch_is_not_silently_accepted(self):
        with patch.object(oauth.shutil, "which", return_value="/opt/homebrew/bin/gh"), \
             patch.object(oauth.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps({"login": "another", "id": 12500002})
            with self.assertRaises(ValueError):
                oauth.github_account("fakeowner")

    def test_unauthenticated_probe_checks_challenge(self):
        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, *_): return b""
        with patch.object(oauth.urllib.request, "urlopen") as opened:
            opened.side_effect = [
                io.BytesIO(json.dumps({
                    "issuer": "https://mac.example.test",
                    "authorization_endpoint": "https://mac.example.test/authorize",
                    "token_endpoint": "https://mac.example.test/token",
                }).encode()),
                HTTPError("https://mac.example.test/mcp", 401, "Unauthorized",
                          {"WWW-Authenticate": 'Bearer realm="MacControl"'}, io.BytesIO()),
            ]
            result = oauth.probe("https://mac.example.test")
        self.assertEqual(result["status"], "public_oauth_preflight_pass")
        self.assertFalse(result["oauth_login_verified"])


class OAuthLoginTestTests(unittest.TestCase):
    def test_real_login_client_flow_is_compatible_with_fastmcp(self):
        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
            async def call_tool(self, name, args):
                self_name.append(name)
                return SimpleNamespace(is_error=False)
        self_name = []
        with patch("fastmcp.Client", return_value=FakeClient()) as client, \
             patch("fastmcp.client.auth.OAuth") as auth:
            result = asyncio.run(login_test.verify_login("https://mac.example.test/mcp"))
        self.assertEqual(result["status"], "authenticated_mcp_success")
        self.assertEqual(self_name, ["system_info"])
        self.assertEqual(auth.call_args.kwargs["scopes"], ["read:user"])
        self.assertEqual(client.call_args.args, ("https://mac.example.test/mcp",))

    def test_configure_requires_local_tty(self):
        with patch.object(oauth.sys.stdin, "isatty", return_value=False), \
             patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaises(RuntimeError):
                oauth.main(["--configure", "--public-url", "https://mac.example.test"])


if __name__ == "__main__":
    unittest.main()
