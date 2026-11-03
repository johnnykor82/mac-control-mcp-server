"""FR025 C7: reviewed synthetic historical test blob is not an API credential."""
from pathlib import Path
import unittest

from scripts import release_history_audit as history

SHA = "224a650b5198ef223832375d71c2e7d99cae9d11"
PATH = "tests/integration/test_argument_guidance.py"
KIND = "embedded_credential_assignment"


class HistoricalSecurityAuditTests(unittest.TestCase):
    def test_one_exact_content_addressed_historical_fixture(self):
        self.assertTrue(history.is_reviewed_fixture(SHA, PATH, 55, KIND))
        self.assertFalse(history.is_reviewed_fixture("0" * 40, PATH, 55, KIND))
        self.assertFalse(history.is_reviewed_fixture(SHA, "src/mac_control/auth.py", 55, KIND))
        self.assertFalse(history.is_reviewed_fixture(SHA, PATH, 56, KIND))
        self.assertFalse(history.is_reviewed_fixture(SHA, PATH, 55, "openai_like_token"))

    def test_full_history_keeps_fixture_visible_and_other_findings_critical(self):
        result = history.audit_history()
        self.assertEqual(result["critical_findings"], [])
        self.assertEqual(len(result["reviewed_test_fixtures"]), 1)
        reviewed = result["reviewed_test_fixtures"][0]
        self.assertEqual(reviewed["blob"], SHA[:12])
        self.assertEqual(reviewed["line"], 55)
        self.assertEqual(reviewed["kind"], KIND)

    def test_ci_retrieves_real_commit_history_before_security_scan(self):
        source = Path(__file__).resolve().parents[2]
        workflow = (source / ".github/workflows/source-tests.yml").read_text()
        self.assertIn("fetch-depth: 0", workflow)


if __name__ == "__main__":
    unittest.main()
