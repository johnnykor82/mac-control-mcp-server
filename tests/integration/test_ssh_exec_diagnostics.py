"""FR-022 diagnostic contract for remote SSH command length validation."""
import subprocess
import unittest
from unittest.mock import patch

from mac_control.legacy_handlers import ssh_manage_ops


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, *, annotations):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn
        return register


class SSHExecDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        registry = Registry()
        ssh_manage_ops.register(registry)
        self.ssh_exec = registry.tools["ssh_exec"]

    @patch.object(ssh_manage_ops.subprocess, "run")
    @patch.object(ssh_manage_ops, "_command")
    def test_mcp_command_5027_is_accepted_without_ssh(self, build_argv, run):
        build_argv.return_value = ["/usr/bin/ssh", "--", "example", "cmd"]
        run.return_value = subprocess.CompletedProcess([], 0, "ok", "")
        response = self.ssh_exec("example", "x" * 5027, 30)
        self.assertEqual(response["exit_code"], 0)
        self.assertEqual(response["stdout"], "ok")
        run.assert_called_once()
        self.assertEqual(build_argv.call_args.args[1], "x" * 5027)

    @patch.object(ssh_manage_ops.subprocess, "run")
    @patch.object(ssh_manage_ops, "_command")
    def test_65536_bytes_allowed(self, build_argv, run):
        build_argv.return_value = ["ssh"]
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.assertEqual(self.ssh_exec("example", "x" * 65536)["exit_code"], 0)
        run.assert_called_once()

    @patch.object(ssh_manage_ops.subprocess, "run")
    @patch.object(ssh_manage_ops, "_command")
    def test_invalid_lengths_are_actionable_before_network(self, build_argv, run):
        for value in ("x" * 65537, "ю" * 32769):
            with self.subTest(input_bytes=len(value.encode())):
                with self.assertRaises(ValueError) as error:
                    self.ssh_exec("example", value)
                message = str(error.exception)
                self.assertIn("SSH_COMMAND_TOO_LONG", message)
                self.assertIn(str(len(value.encode())), message)
                self.assertIn("65536", message)
                self.assertIn("ssh_write_text", message)
                self.assertIn("ssh_upload", message)
                self.assertNotIn(value[:128], message)
        run.assert_not_called()
        build_argv.assert_not_called()

    @patch.object(ssh_manage_ops.subprocess, "run")
    def test_empty_and_nonstring_are_actionable(self, run):
        for value in ("", None, 42):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "SSH_COMMAND_INVALID") as error:
                    self.ssh_exec("example", value)
                self.assertIn("command", str(error.exception))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
