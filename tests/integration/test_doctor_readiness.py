"""E8: no READY unless every required installer component passes."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts import doctor_mac_control as doctor


class DoctorReadinessTests(unittest.TestCase):
    def test_all_components_ready_means_ready(self):
        states = {name: {"status": "ready"} for name in doctor.REQUIRED_COMPONENTS}
        result = doctor.combine(states)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(len(result["components"]), len(doctor.REQUIRED_COMPONENTS))

    def test_each_incomplete_component_blocks_ready_with_action(self):
        for missing in doctor.REQUIRED_COMPONENTS:
            states = {name: {"status": "ready"} for name in doctor.REQUIRED_COMPONENTS}
            states[missing] = {"status": "incomplete", "reason": "missing_dependency",
                               "remedy": "Run maccontrol --setup"}
            with self.subTest(missing=missing):
                result = doctor.combine(states)
                self.assertEqual(result["status"], "INCOMPLETE")
                self.assertEqual(result["components"][missing]["reason"], "missing_dependency")

    def test_oauth_acceptance_bound_to_current_release_and_endpoint(self):
        from scripts import setup_github_oauth
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            release = root / "releases/r1"
            release.mkdir(parents=True)
            (root / "current").symlink_to(release)
            marker = root / "data/oauth-acceptance.json"
            record = {"authenticated_mcp_success": True,
                      "endpoint": "https://mcp.example.test/mcp",
                      "release": str(release.resolve())}
            marker.write_text(json.dumps(record))
            marker.chmod(0o600)
            with patch.object(setup_github_oauth, "check",
                              return_value={"public_url": "https://mcp.example.test"}):
                self.assertTrue(doctor._oauth_acceptance(root))
                record["endpoint"] = "https://wrong.example.test/mcp"
                marker.write_text(json.dumps(record))
                self.assertFalse(doctor._oauth_acceptance(root))
                marker.chmod(0o644)
                self.assertFalse(doctor._oauth_acceptance(root))

    def test_error_or_missing_component_never_claims_ready(self):
        self.assertEqual(doctor.combine({})["status"], "INCOMPLETE")
        states = {name: {"status": "ready"} for name in doctor.REQUIRED_COMPONENTS}
        states["oauth"] = {"status": "error", "reason": "unverified"}
        self.assertEqual(doctor.combine(states)["status"], "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
