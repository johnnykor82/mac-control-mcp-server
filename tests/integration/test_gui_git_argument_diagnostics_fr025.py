"""FR-025: GUI and Git argument errors must be actionable before side effects."""
import unittest
from unittest.mock import patch

from mac_control.argument_guidance import guided_handler
from mac_control.legacy_adapter import inspect_existing_handlers
from mac_control.legacy_handlers import gui_ops, git_ops


class GuiGitInputDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        entries = inspect_existing_handlers()
        cls.mouse = staticmethod(entries["gui_mouse"].handler)
        cls.create_branch = staticmethod(entries["git_create_branch"].handler)

    def test_mouse_action_lists_exact_allowable_actions(self):
        wrapped = guided_handler("gui_mouse", self.mouse)
        with patch.object(gui_ops, "_call") as backend:
            with self.assertRaisesRegex(ValueError, "GUI_MOUSE_ACTION_INVALID") as exc:
                wrapped("wrong_action", 0, 0)
        message = str(exc.exception)
        for action in ("move", "left_click", "right_click", "double_click", "drag"):
            self.assertIn(action, message)
        self.assertNotIn("wrong_action", message)
        backend.assert_not_called()

    def test_git_branch_invalid_input_reveals_name_rule(self):
        wrapped = guided_handler("git_create_branch", self.create_branch)
        for bad in ("1starts_digit", "contains space", ""):
            with self.subTest(bad=bad):
                with patch.object(git_ops, "git") as backend:
                    with self.assertRaisesRegex(ValueError, "GIT_BRANCH_NAME_INVALID") as exc:
                        wrapped("workspace", bad)
                self.assertIn("80", str(exc.exception))
                self.assertIn("ASCII letter", str(exc.exception))
                backend.assert_not_called()


if __name__ == "__main__":
    unittest.main()
