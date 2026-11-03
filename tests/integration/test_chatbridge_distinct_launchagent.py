"""E9: managed ChatBridge never collides with an unrelated gateway label."""
import plistlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts import setup_chatbridge_dependency as bridge


class DistinctChatBridgeAgentTests(unittest.TestCase):
    def test_managed_service_uses_its_own_launchagent_label(self):
        self.assertNotEqual(bridge.MANAGED_LABEL, "net.chatbridge.gateway")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            foreign = home / "Library/LaunchAgents/net.chatbridge.gateway.plist"
            foreign.parent.mkdir(parents=True)
            foreign.write_bytes(plistlib.dumps({"Label": "net.chatbridge.gateway"}))
            with patch.object(bridge.Path, "home", return_value=home), \
                 patch.object(bridge.subprocess, "run",
                              return_value=SimpleNamespace(returncode=1)):
                bridge.assert_installable("http://127.0.0.1:18080",
                                           label=bridge.MANAGED_LABEL)
            self.assertTrue(foreign.exists())


if __name__ == "__main__":
    unittest.main()
