"""E9 watcher interpreter must not inherit group-writable system Python."""
from pathlib import Path
import unittest

from scripts import install_mac_control as installer


class ManagedRuntimeTests(unittest.TestCase):
    def test_new_release_virtualenv_uses_uv_managed_python(self):
        command = installer._release_venv_command("/path/to/uv", Path("/tmp/isolated-release"))
        self.assertEqual(command, [
            "/path/to/uv", "venv", "--managed-python", "--python", "3.13",
            "/tmp/isolated-release/.venv",
        ])


if __name__ == "__main__":
    unittest.main()
