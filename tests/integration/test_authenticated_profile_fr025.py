"""FR-025.2 ChatGPT stable account profile: no fallbacks or client-chosen IDs."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from scripts.dev_mcp_server import make_server
from mac_control import account_profile


class AuthenticatedProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.remote = make_server(include_mutations=True, auth=object())
        cls.anonymous = make_server(include_mutations=True)

    def test_declared_remote_only_profile_tool(self):
        remote = {t.name: t for t in asyncio.run(self.remote.list_tools())}
        local = {t.name for t in asyncio.run(self.anonymous.list_tools())}
        self.assertNotIn("get_profile", local)
        self.assertIn("get_profile", remote)
        tool = remote["get_profile"]
        self.assertEqual(tool.parameters["properties"], {})
        self.assertEqual(tool.parameters.get("required", []), [])
        self.assertFalse(tool.parameters.get("additionalProperties", True))
        self.assertEqual(tool.meta["openai/profile"], True)
        self.assertTrue(tool.annotations.read_only_hint)
        self.assertFalse(tool.annotations.destructive_hint)
        self.assertFalse(tool.annotations.open_world_hint)
        self.assertEqual(tool.output_schema["required"], ["id"])
        self.assertIs(tool.output_schema["additionalProperties"], False)
        Draft202012Validator.check_schema(tool.output_schema)

    def test_stable_provider_subject_across_client_sessions_and_tokens(self):
        for token_id,client in (("token1", "first"), ("token2", "reconnect"),
                                ("token3", "refreshed")):
            with self.subTest(client=client), patch.object(
                account_profile, "get_access_token",
                return_value=SimpleNamespace(subject="12345678", client_id=client, token=token_id)
            ), patch.object(
                account_profile, "load_config",
                return_value={"github_allowed_ids": ["12345678", "87654321"]}
            ):
                result = asyncio.run(self.remote.call_tool("get_profile", {}))
                self.assertEqual(result.structured_content["id"], "12345678")
                self.assertEqual(set(result.structured_content), {"id"})
                self.assertFalse(result.is_error)

    def test_two_allowed_subjects_have_different_profiles(self):
        for who in ("12345678", "87654321"):
            with patch.object(
                account_profile, "get_access_token",
                return_value=SimpleNamespace(subject=who)
            ), patch.object(
                account_profile, "load_config",
                return_value={"github_allowed_ids": ["12345678", "87654321"]}
            ):
                result = asyncio.run(self.remote.call_tool("get_profile", {}))
                self.assertEqual(result.structured_content["id"], who)

    def test_unauthorized_profiles_fail_closed(self):
        for token in (None, SimpleNamespace(subject=None),
                      SimpleNamespace(subject="name@email.invalid"),
                      SimpleNamespace(subject="99999999")):
            with self.subTest(token=str(getattr(token, "subject", None))), patch.object(
                account_profile, "get_access_token", return_value=token
            ), patch.object(
                account_profile, "load_config",
                return_value={"github_allowed_ids": ["12345678"]}
            ):
                with self.assertRaises(PermissionError):
                    account_profile.authenticated_profile()

    def test_caller_cannot_suggest_identity(self):
        schema = asyncio.run(self.remote.list_tools())
        schema = next(t.parameters for t in schema if t.name == "get_profile")
        errors = list(Draft202012Validator(schema).iter_errors({"user_id": "12345678"}))
        self.assertTrue(any(e.validator == "additionalProperties" for e in errors))


if __name__ == "__main__":
    unittest.main()
