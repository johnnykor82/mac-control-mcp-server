"""E9: repeated setup resumes the existing owned ChatBridge port."""
import plistlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import setup_chatbridge_dependency as bridge

class OwnedEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.root = self.home / "MacControlMCP"
        self.prefix = self.root / "deps/chatbridge"
        self.state = self.root / "deps/chatbridge-data"
        self.plist = self.home / ("Library/LaunchAgents/" + bridge.MANAGED_LABEL + ".plist")
        self.plist.parent.mkdir(parents=True)

    def fixture(self, port):
        self.plist.write_bytes(plistlib.dumps({
            "Label": bridge.MANAGED_LABEL,
            "ChatBridgeInstaller": "1",
            "WorkingDirectory": str(self.prefix / "releases/installed"),
            "EnvironmentVariables": {
                "CHATBRIDGE_DB": str(self.state / "state.db"),
                "CHATBRIDGE_PORT": port,
            },
        }))

    def test_reuse_managed_endpoint_even_if_default_port_busy(self):
        self.fixture("18787")
        with patch.object(bridge.Path, "home", return_value=self.home), \
             patch.object(bridge, "select_endpoint", side_effect=AssertionError("must reuse")), \
             patch.object(bridge, "verify", return_value={
                 "status": "compatible", "url": "http://127.0.0.1:18787"
             }) as check:
            result = bridge.ensure("http://127.0.0.1:8787", install_root=self.root)
        self.assertEqual(result["url"], "http://127.0.0.1:18787")
        check.assert_called_once_with("http://127.0.0.1:18787")

    def test_invalid_managed_port_fails_closed(self):
        self.fixture("0")
        with patch.object(bridge.Path, "home", return_value=self.home):
            with self.assertRaisesRegex(RuntimeError, "port"):
                bridge.owned_endpoint(self.root)

if __name__ == "__main__":
    unittest.main()
