"""FR-025: interactive PTY sends must diagnose input without sending keys."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mac_control.argument_guidance import guided_handler
from mac_control.legacy_adapter import inspect_existing_handlers
from mac_control.legacy_handlers import command_plugins


class TerminalSendArgumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handler = staticmethod(inspect_existing_handlers()["terminal_send"].handler)

    def _check(self, text, key, expected_code):
        with patch.object(command_plugins, "_require"),              patch.object(command_plugins, "_tmux_available", return_value="/usr/bin/tmux"),              patch.object(command_plugins, "_tmux", return_value=SimpleNamespace(
                 returncode=0, stdout="", stderr="")) as tmux:
            wrapped = guided_handler("terminal_send", self.handler)
            with self.assertRaisesRegex(ValueError, expected_code) as exc:
                wrapped("mc-" + "a" * 16, text=text, key=key)
            self.assertEqual(tmux.call_count, 1, "No send-keys may run")
        return str(exc.exception)

    def test_text_limit_reports_exact_size_and_safe_alternative(self):
        msg = self._check("x" * 4001, "", "TERMINAL_TEXT_TOO_LONG")
        self.assertIn("4001", msg)
        self.assertIn("4000", msg)
        self.assertIn("fs_write", msg)

    def test_invalid_key_lists_supported_key_names(self):
        msg = self._check("", "Wrong-Key", "TERMINAL_KEY_INVALID")
        self.assertIn("Enter", msg)
        self.assertIn("C-c", msg)
        self.assertNotIn("Wrong-Key", msg)

    def test_empty_send_explains_required_text_or_key(self):
        msg = self._check("", "", "TERMINAL_SEND_EMPTY")
        self.assertIn("text", msg)
        self.assertIn("key", msg)

    def test_nonstring_text_does_not_crash(self):
        msg = self._check(42, "", "TERMINAL_TEXT_INVALID")
        self.assertIn("text", msg)


if __name__ == "__main__":
    unittest.main()
