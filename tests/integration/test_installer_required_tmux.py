"""The standard installer provisions tmux without a second terminal opt-in."""
import unittest
from unittest.mock import Mock

from scripts import install_mac_control as install


class RequiredTmuxTests(unittest.TestCase):
    def test_noninteractive_installer_provisions_tmux(self):
        provision = Mock(return_value={"status": "ready", "available": True,
                                       "tmux_path": "/opt/homebrew/bin/tmux"})
        result = install._ensure_required_tmux(provision)
        self.assertTrue(result["available"])
        provision.assert_called_once_with(approved=True, interactive=False)

    def test_missing_tmux_is_incomplete_not_ready(self):
        provision = Mock(return_value={"status": "missing_homebrew",
                                       "available": False,
                                       "remedy": "Install Homebrew"})
        result = install._ensure_required_tmux(provision)
        self.assertFalse(result["available"])
        self.assertEqual(result["status"], "missing_homebrew")


if __name__ == "__main__":
    unittest.main()
