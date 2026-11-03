"""E1 acceptance: the authenticated server needs no secondary terminal policy."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from mac_control.legacy_handlers import command_plugins, system_ops, package_ops


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, **kwargs):
        def registered(fn):
            self.tools[fn.__name__] = fn
            return fn
        return registered


class TerminalFullAccessTests(unittest.TestCase):
    def test_shell_works_without_policy_file(self):
        registry = Registry()
        command_plugins.register(registry)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.assertFalse(hasattr(command_plugins, "POLICY"))
            with patch.object(command_plugins, "roots", return_value={"workspace": directory}), \
                 patch.object(command_plugins, "RUNTIME", directory / "run"):
                status = registry.tools["terminal_capabilities"]()
                self.assertTrue(status["enabled"])
                self.assertNotIn("policy", status)
                self.assertNotIn("policy_error", status)
                result = registry.tools["terminal_exec"]("printf E1_TEST_OK")
        self.assertEqual(result["exit_code"], 0, result["stderr"])
        self.assertEqual(result["stdout"], "E1_TEST_OK")

    @unittest.skipUnless(command_plugins._tmux_available(), "tmux unavailable")
    def test_interactive_terminal_lifecycle_without_policy(self):
        registry = Registry()
        command_plugins.register(registry)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(command_plugins, "roots", return_value={"workspace": root}), \
                 patch.object(command_plugins, "RUNTIME", root / "run"), \
                 patch.object(command_plugins, "SOCKET", root / "run/tmux.sock"):
                opened = registry.tools["terminal_open"]()
                self.assertIn("session", opened, opened)
                session = opened["session"]
                try:
                    registry.tools["terminal_send"](session, "printf PTY_E1_OK", "Enter")
                    output = ""
                    for _ in range(40):
                        output = registry.tools["terminal_read"](session)["screen"]
                        if "PTY_E1_OK" in output:
                            break
                        time.sleep(.05)
                    self.assertIn("PTY_E1_OK", output)
                    self.assertIn(session, [s["session"] for s in
                                           registry.tools["terminal_list"]()["sessions"]])
                finally:
                    registry.tools["terminal_close"](session)

    def test_no_second_approval_tools_exist(self):
        registry = Registry()
        system_ops.register(registry)
        package_ops.register(registry)
        self.assertNotIn("approved_commands", registry.tools)
        self.assertNotIn("execute_approved", registry.tools)
        self.assertNotIn("terminal_access_configure", registry.tools)


if __name__ == "__main__":
    unittest.main()
