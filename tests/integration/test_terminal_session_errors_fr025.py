"""FR-025: invalid and expired tmux session errors are different."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mac_control.argument_guidance import guided_handler
from mac_control.legacy_adapter import inspect_existing_handlers
from mac_control.legacy_handlers import command_plugins


class TerminalSessionErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handler = staticmethod(inspect_existing_handlers()["terminal_read"].handler)

    def test_invalid_session_format_before_tmux(self):
        with patch.object(command_plugins, "_tmux_available", return_value="/bin/tmux"),              patch.object(command_plugins, "_tmux") as tmux:
            with self.assertRaisesRegex(ValueError, "TERMINAL_SESSION_INVALID") as ctx:
                guided_handler("terminal_read", self.handler)("other.session")
        self.assertIn("mc-", str(ctx.exception))
        self.assertIn("16", str(ctx.exception))
        self.assertIn("terminal_list", str(ctx.exception))
        tmux.assert_not_called()

    def test_expired_session_is_distinguished_from_bad_format(self):
        with patch.object(command_plugins, "_tmux_available", return_value="/bin/tmux"),              patch.object(command_plugins, "_tmux", return_value=SimpleNamespace(
                 returncode=1, stdout="", stderr="")) as tmux:
            with self.assertRaisesRegex(ValueError, "TERMINAL_SESSION_NOT_FOUND") as ctx:
                guided_handler("terminal_read", self.handler)("mc-" + "a" * 16)
        self.assertIn("terminal_list", str(ctx.exception))
        tmux.assert_called_once()


if __name__ == "__main__":
    unittest.main()
