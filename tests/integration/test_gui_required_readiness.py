"""E6: a manually skipped GUI cannot satisfy standard installer readiness."""
import unittest
from unittest.mock import patch

from scripts import guided_setup


class GUIRequiredReadinessTests(unittest.TestCase):
    def test_diagnostic_gui_optout_is_incomplete_before_network_setup(self):
        with patch.object(guided_setup, "guided_network") as network, \
             patch.object(guided_setup, "gui_permissions") as gui:
            status = guided_setup._setup_locked(object(), with_gui=False, language="ru")
        self.assertEqual(status["status"], "setup_incomplete")
        self.assertIn("gui", status["reason"])
        network.assert_not_called()
        gui.assert_not_called()


if __name__ == "__main__":
    unittest.main()
