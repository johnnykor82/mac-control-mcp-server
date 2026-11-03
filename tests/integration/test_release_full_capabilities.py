"""E9 release acceptance: code exercised in tests must ship in installed release."""
from pathlib import Path
import unittest
import tempfile
import os
import subprocess
import sys
from unittest.mock import patch

from scripts import install_mac_control as installer


ROOT = Path(__file__).parents[2]


class ReleaseFullCapabilitiesTests(unittest.TestCase):
    def test_doctor_runtime_is_in_install_manifest(self):
        source = {path.relative_to(ROOT).as_posix() for path in installer.install_sources()}
        self.assertIn("scripts/doctor_mac_control.py", source)
        self.assertIn("scripts/test_github_oauth_login.py", source)
        self.assertIn("src/mac_control/argument_guidance.py", source)
        self.assertIn("docs/TOOL_ARGUMENT_ERRORS.md", source)
        self.assertIn("docs/CHATGPT_LINK_ROUTING_DIAGNOSTICS.md", source)
        self.assertIn("scripts/mclog.py", source)
        self.assertIn("src/mac_control/audit_middleware.py", source)

    def test_copied_release_runs_in_an_isolated_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "isolated-release"
            dest.mkdir()
            installer.copy_source(dest)
            for source in installer.install_sources():
                self.assertEqual((dest / source.relative_to(ROOT)).read_bytes(),
                                 source.read_bytes())
            environment = {**os.environ, "PYTHONPATH": str(dest / "src")
                           + os.pathsep + str(dest)}
            completed = subprocess.run([sys.executable, "-P", "-B", "-c",
                "from mac_control.legacy_adapter import inspect_existing_handlers; "
                "assert len(inspect_existing_handlers()) == 106; "
                "from scripts.doctor_mac_control import REQUIRED_COMPONENTS; "
                "assert 'chatbridge' in REQUIRED_COMPONENTS"],
                cwd=tmp, env=environment, capture_output=True, text=True, timeout=25)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_installation_smoke_uses_current_compatibility_registry_size(self):
        with patch.object(installer, "run") as runner:
            installer.smoke(Path("/mock/release"), Path("/mock/data"))
        command = runner.call_args.args[0]
        self.assertTrue(any("len(x) == 106" in str(x) for x in command))
        self.assertFalse(any("len(x) == 109" in str(x) for x in command))


if __name__ == "__main__":
    unittest.main()
