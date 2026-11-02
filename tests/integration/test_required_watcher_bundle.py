"""E5: ChatBridge and Watcher form one readiness dependency."""
import unittest
from scripts import install_mac_control as install


class RequiredWatcherBundleTests(unittest.TestCase):
    def test_ready_requires_authenticated_chatbridge_and_running_watcher(self):
        self.assertTrue(install._bundle_ready(True, {"authenticated": True}, "running"))
        for status in ("disabled", "not_installed", "loaded", "stopped"):
            with self.subTest(status=status):
                self.assertFalse(install._bundle_ready(True, {"authenticated": True}, status))
        self.assertFalse(install._bundle_ready(True, {"authenticated": False}, "running"))
        self.assertFalse(install._bundle_ready(False, {"authenticated": True}, "running"))

    def test_cannot_install_watcher_without_chatbridge(self):
        with self.assertRaisesRegex(RuntimeError, "ChatBridge"):
            install._validate_bundle(False, True)


if __name__ == "__main__":
    unittest.main()
