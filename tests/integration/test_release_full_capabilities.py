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
        self.assertIn("src/mac_control/account_profile.py", source)

    def test_self_update_runtime_modules_are_copied_into_installed_release(self):
        payload = {path.relative_to(ROOT).as_posix() for path in installer.install_sources()}
        for name in ('src/mac_control/self_update.py',
                     'scripts/self_update_watchdog.py'):
            self.assertIn(name, payload)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'snapshot'
            installer.copy_source(target)
            for name in ('src/mac_control/self_update.py',
                         'scripts/self_update_watchdog.py'):
                self.assertTrue((target / name).is_file(), name)
            env = {**os.environ, 'PYTHONPATH': str(target / 'src') + os.pathsep + str(target)}
            proc = subprocess.run([sys.executable, '-P', '-B', '-c',
                'from mac_control import self_update; '
                'from scripts import self_update_watchdog; '
                'assert callable(self_update.start); '
                'assert callable(self_update_watchdog.run_transaction)'],
                cwd=target, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)

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
                "assert len(inspect_existing_handlers()) == 112; "
                "from scripts.doctor_mac_control import REQUIRED_COMPONENTS; "
                "assert 'chatbridge' in REQUIRED_COMPONENTS; "
                "from scripts.dev_mcp_server import make_server; import asyncio; "
                "remote=asyncio.run(make_server(auth=object()).list_tools()); "
                "local=asyncio.run(make_server().list_tools()); "
                "assert 'get_profile' in {t.name for t in remote}; "
                "assert 'get_profile' not in {t.name for t in local}"],
                cwd=tmp, env=environment, capture_output=True, text=True, timeout=25)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_installation_smoke_uses_current_compatibility_registry_size(self):
        with patch.object(installer, "run") as runner:
            installer.smoke(Path("/mock/release"), Path("/mock/data"))
        command = runner.call_args.args[0]
        self.assertTrue(any("len(x) == 112" in str(x) for x in command))
        self.assertFalse(any("len(x) == 109" in str(x) for x in command))


if __name__ == "__main__":
    unittest.main()
