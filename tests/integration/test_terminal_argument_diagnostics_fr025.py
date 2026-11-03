"""FR-025: terminal argument validation must be actionable and preflight."""
import unittest
from unittest.mock import patch

from mac_control.legacy_adapter import inspect_existing_handlers
from mac_control.argument_guidance import guided_handler
from mac_control.legacy_handlers import command_plugins


class TerminalCommandErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handler = staticmethod(inspect_existing_handlers()["terminal_exec"].handler)

    def test_large_command_reports_limit_and_local_file_remedy(self):
        with patch.object(command_plugins, "_require"), patch.object(
                command_plugins, "_cwd") as cwd:
            with self.assertRaisesRegex(ValueError, "TERMINAL_COMMAND_TOO_LONG") as ctx:
                self.handler("x" * 8001)
        msg = str(ctx.exception)
        self.assertIn("8001", msg)
        self.assertIn("8000", msg)
        self.assertIn("fs_write", msg)
        self.assertIn("terminal_exec", msg)
        self.assertNotIn("x" * 20, msg)
        cwd.assert_not_called()

    def test_empty_nonstring_and_nul_are_preflight_errors(self):
        for payload in (None, "", 17, "echo" + chr(0)):
            with self.subTest(kind=type(payload).__name__):
                with patch.object(command_plugins, "_require"), patch.object(
                        command_plugins, "_cwd") as cwd:
                    with self.assertRaisesRegex(ValueError, "TERMINAL_COMMAND_INVALID"):
                        self.handler(payload)
                cwd.assert_not_called()

    def test_8000_character_boundary_passes_validation_without_execution(self):
        class PastValidation(Exception):
            pass
        with patch.object(command_plugins, "_require"), patch.object(
                command_plugins, "_cwd", side_effect=PastValidation) as cwd:
            with self.assertRaises(PastValidation):
                self.handler("x" * 8000)
        cwd.assert_called_once()

    def test_guided_wrapper_preserves_diagnostic_code_and_count(self):
        wrapped = guided_handler("terminal_exec", self.handler)
        with patch.object(command_plugins, "_require"), patch.object(
                command_plugins, "_cwd") as cwd:
            with self.assertRaisesRegex(ValueError, "TERMINAL_COMMAND_TOO_LONG") as ctx:
                wrapped("x" * 8001)
        self.assertIn("8001", str(ctx.exception))
        cwd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
