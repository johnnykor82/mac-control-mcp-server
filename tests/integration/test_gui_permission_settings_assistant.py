"""A refused Screen Recording request offers a native, one-click settings dialog."""
from pathlib import Path
import unittest
from unittest.mock import patch
from scripts import build_mac_control_gui as builder

SOURCE = Path(__file__).resolve().parents[2] / "src/mac_control/assets/gui_agent.swift"

class PermissionSettingsAssistantTests(unittest.TestCase):
    def test_ungranted_screen_capture_spawns_user_visible_settings_assistant(self):
        swift = SOURCE.read_text()
        self.assertIn('case "request_screen_capture":', swift)
        self.assertIn('CGRequestScreenCaptureAccess()', swift)
        self.assertIn('offerPermissionSettingsAssistant("screen")', swift)
        self.assertIn('case "request_permissions":', swift)
        self.assertIn('--permission-assistant', swift)

    def test_assistant_presents_real_alert_and_opens_exact_settings_pane(self):
        swift = SOURCE.read_text()
        self.assertIn('NSAlert()', swift)
        self.assertIn('alert.runModal()', swift)
        self.assertIn('Privacy_ScreenCapture', swift)
        self.assertIn('NSWorkspace.shared.open', swift)
        self.assertIn('NSApplication.shared', swift)

    def test_tcc_is_never_silently_granted(self):
        swift = SOURCE.read_text()
        self.assertIn('CGPreflightScreenCaptureAccess()', swift)
        self.assertIn('"screen_capture_trusted": screen', swift)

if __name__ == "__main__":
    unittest.main()
