"""FR-025: rejected Watcher IDs must explain allowable identity syntax."""
import unittest
from unittest.mock import patch

from mac_control.argument_guidance import guided_handler
from mac_control.legacy_adapter import inspect_existing_handlers
from mac_control.legacy_handlers import watcher_ops


class WatcherIdDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.status = staticmethod(inspect_existing_handlers()["watcher_status"].handler)
        cls.register_project = staticmethod(
            inspect_existing_handlers()["watcher_register_project"].handler)

    def test_invalid_project_id_has_actionable_preflight_error(self):
        for bad in ("Capital Letters", "a", 34, "", "some/id"):
            with self.subTest(value_type=type(bad).__name__):
                with patch.object(watcher_ops, "_cli") as caller:
                    with self.assertRaisesRegex(ValueError, "WATCHER_ID_INVALID") as exc:
                        self.register_project(bad, "https://chatgpt.com/c/example")
                self.assertIn("2", str(exc.exception))
                self.assertIn("56", str(exc.exception))
                self.assertIn("watcher_guide", str(exc.exception))
                caller.assert_not_called()

    def test_guided_status_retains_specific_message(self):
        wrapped = guided_handler("watcher_status", self.status)
        with patch.object(watcher_ops, "_cli") as caller:
            with self.assertRaisesRegex(ValueError, "WATCHER_ID_INVALID") as exc:
                wrapped("invalid with space")
        self.assertIn("watcher_status", str(exc.exception))
        caller.assert_not_called()


if __name__ == "__main__":
    unittest.main()
