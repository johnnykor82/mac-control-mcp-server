"""Independent ChatBridge packaging contract for Mac Control's optional dependency."""
from __future__ import annotations

import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import setup_chatbridge_dependency as dependency
from scripts import install_mac_control as installer


class ChatBridgeDependencyTests(unittest.TestCase):
    def test_requires_separate_chatbridge_release_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RuntimeError):
                dependency.install(Path(temporary))

    def test_installer_invokes_standalone_install_script_not_own_chrome(self):
        with tempfile.TemporaryDirectory() as temporary:
            src = Path(temporary)
            for filename in ("install.sh", "LICENSE", "scripts/installer.py"):
                path = src / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("not used in this unit test")
            (src / "pyproject.toml").write_text('name = "chatbridge-gateway"\n')
            with patch.object(dependency.subprocess, "run",
                              return_value=SimpleNamespace(returncode=0)) as runner, \
                 patch.object(dependency, "assert_installable"), \
                 patch.object(dependency, "verify", return_value={"status": "compatible"}):
                result = dependency.install(src)
        self.assertEqual(result["status"], "compatible")
        args = runner.call_args.args[0]
        self.assertIn("scripts/installer.py", str(args))
        self.assertIn("install", args)
        self.assertIn("--port", args)

    def test_optional_bearer_header(self):
        for key in ("", "test-secret"):
            with patch.dict(os.environ, {"MACCONTROL_CHATBRIDGE_API_KEY": key}), \
                 patch.object(dependency.urllib.request, "urlopen",
                              return_value=io.BytesIO(b'{"background": true}')) as opener:
                dependency.verify()
            self.assertEqual(opener.call_args.args[0].get_header("Authorization"),
                             "Bearer " + key if key else None)

    def test_custom_port_passed_to_installer(self):
        with tempfile.TemporaryDirectory() as temporary:
            src = Path(temporary)
            for filename in ("install.sh", "LICENSE", "scripts/installer.py"):
                path = src / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            (src / "pyproject.toml").write_text('name = "chatbridge-gateway"\n')
            with patch.object(dependency.subprocess, "run",
                              return_value=SimpleNamespace(returncode=0)) as runner, \
                 patch.object(dependency, "assert_installable"), \
                 patch.object(dependency, "verify", return_value={}):
                dependency.install(src, url="http://localhost:9876")
            args = runner.call_args.args[0]
            self.assertEqual(args[args.index("--port") + 1], "9876")

    def test_running_rejected_service_is_never_reinstalled(self):
        errors = (dependency.urllib.error.HTTPError(dependency.DEFAULT_URL,
                  401, "Unauthorized", {}, None), RuntimeError("Incompatible API"))
        for error in errors:
            with patch.object(installer, "paths", return_value={}), \
                 patch.object(installer.shutil, "which", return_value="uv"), \
                 patch.object(installer.sys, "platform", "darwin"), \
                 patch.object(dependency, "verify", side_effect=error), \
                 patch.object(dependency, "install") as install_dependency:
                with self.assertRaises(RuntimeError):
                    installer.install(Path("unused"), True, chatbridge_source=Path("source"))
            install_dependency.assert_not_called()

    def test_rejects_non_loopback_chatbridge_origin(self):
        for url in ("http://example.com:8787", "https://127.0.0.1:8787",
                    "http://user:secret@127.0.0.1:8787"):
            with self.assertRaises(ValueError):
                dependency.verify(url)


if __name__ == "__main__":
    unittest.main()
