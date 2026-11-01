"""Acceptance-contract fixture for the owner's full-capability installer scope.

This is a code-level test fixture; the owner's private specification stays
outside the public source checkout.
"""
import json
from pathlib import Path
import unittest


CONTRACT = Path(__file__).parents[1] / "fixtures/installer_acceptance_matrix.json"
APPROVED = set(range(1, 12)) | {14, 16, 17, 18, 19}


class InstallerAcceptanceMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_all_sixteen_approved_requirements_are_accounted_for(self):
        self.assertEqual(set(self.matrix["requirements"]), APPROVED)
        self.assertEqual(len(self.matrix["requirements"]), 16)
        self.assertTrue({12, 13, 15}.isdisjoint(self.matrix["requirements"]))

    def test_required_test_scenarios_cover_untrusted_existing_system_state(self):
        expected = {
            "clean", "foreign_port", "compatible_bridge", "ssh_alias",
            "mcp_dynamic", "tcc_denied", "tcc_granted", "cli_conflict",
        }
        self.assertEqual(set(self.matrix["scenarios"]), expected)
        self.assertEqual(self.matrix["scenarios"]["foreign_port"]["expect"],
                         "preserve_foreign_process")
        self.assertFalse(self.matrix["scenarios"]["ssh_alias"]["registration_required"])
        self.assertFalse(self.matrix["scenarios"]["mcp_dynamic"]["registration_required"])

    def test_contract_requires_readiness_not_just_http_startup(self):
        self.assertEqual(set(self.matrix["states"]), {"READY", "INCOMPLETE"})
        self.assertEqual(self.matrix["scenarios"]["tcc_denied"]["expect"], "INCOMPLETE")
        self.assertEqual(set(self.matrix["removed_commands"]),
                         {"approved_commands", "execute_approved"})


if __name__ == "__main__":
    unittest.main()
