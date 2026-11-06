"""FR025.3: frozen signatures remain distinct; only known values are aliased."""
import asyncio
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from scripts.dev_mcp_server import make_server


class CrossToolArgumentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = {t.name: t for t in asyncio.run(
            make_server(include_mutations=True).list_tools()
        )}

    def test_maintenance_alias_keeps_original_json_schema(self):
        maintenance = self.tools["write_file"].parameters
        self.assertEqual(set(maintenance["properties"]), {
            "path", "content", "expected_sha256", "audit_context"
        })
        self.assertEqual(set(maintenance["required"]), {"path", "content", "audit_context"})
        self.assertFalse(maintenance.get("additionalProperties", True))
        Draft202012Validator.check_schema(maintenance)

    def test_legacy_fs_write_retains_project_path_signature(self):
        legacy = self.tools["fs_write"].parameters
        self.assertEqual(set(legacy["properties"]), {
            "project", "path", "content", "expected_sha256", "audit_context"
        })
        self.assertEqual(set(legacy["required"]), {
            "project", "path", "content", "audit_context"
        })
        self.assertFalse(legacy.get("additionalProperties", True))
        Draft202012Validator.check_schema(legacy)
        invalid = list(Draft202012Validator(legacy).iter_errors({
            "path": "projects/a.txt", "content": "data"
        }))
        self.assertTrue(any(e.validator == "required" for e in invalid))

    def test_compatibility_matrix_and_installer_payload_present(self):
        root = Path(__file__).resolve().parents[2]
        doc = (root / "docs/TOOL_ARGUMENT_COMPATIBILITY_FR025.md").read_text()
        self.assertIn("WORKSPACE_PATH_FORMAT_INVALID", doc)
        self.assertIn("projects/android-license-audit", doc)
        manifest = (root / "scripts/install_manifest.txt").read_text().splitlines()
        self.assertIn("docs/TOOL_ARGUMENT_COMPATIBILITY_FR025.md", manifest)


if __name__ == "__main__":
    unittest.main()
