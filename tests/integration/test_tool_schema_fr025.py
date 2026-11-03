"""All 135 MCP inputs have machine-readable schemas; never execute operations."""
import asyncio
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from mac_control import background_browser_ops, background_native_ops
from scripts.dev_mcp_server import make_server


class AllToolSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        async def collect():
            with patch.object(background_browser_ops, "enabled", return_value=True),                  patch.object(background_native_ops, "enabled", return_value=True):
                return await make_server(include_mutations=True).list_tools()
        cls.tools = asyncio.run(collect())

    def test_all_135_schemas_are_well_formed_and_named(self):
        self.assertEqual(len(self.tools), 135)
        for tool in self.tools:
            with self.subTest(tool=tool.name):
                Draft202012Validator.check_schema(tool.parameters)
                self.assertEqual(tool.parameters["type"], "object")
                self.assertIsInstance(tool.parameters.get("properties", {}), dict)

    def test_required_fields_have_specific_validation_errors(self):
        for tool in self.tools:
            required = tool.parameters.get("required") or []
            if not required:
                continue
            with self.subTest(tool=tool.name):
                errors = list(Draft202012Validator(tool.parameters).iter_errors({}))
                required_errors = [e for e in errors if e.validator == "required"]
                self.assertTrue(required_errors)
                for field in required:
                    self.assertTrue(any(field in e.message for e in required_errors))

    def test_unexpected_top_level_fields_rejected_before_execution(self):
        for tool in self.tools:
            schema = tool.parameters
            if schema.get("additionalProperties") is not False:
                continue
            with self.subTest(tool=tool.name):
                errors = list(Draft202012Validator(schema).iter_errors(
                    {"__unexpected_fr025_field__": 1}))
                self.assertTrue(any(e.validator == "additionalProperties" for e in errors))


if __name__ == "__main__":
    unittest.main()
