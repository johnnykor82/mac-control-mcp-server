"""Packaged SSH tools use temporary profiles and never open real connections."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mac_control.legacy_handlers import (
    command_plugins, ssh_auth_diag, ssh_bridge_ops, ssh_manage_ops,
)


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, **options):
        def store(function):
            self.tools[function.__name__] = function
            return function
        return store


class SSHPortabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.profiles = self.home / "ssh_targets.json"
        self.profiles.write_text(json.dumps({"hosts": {"staging": {
            "host": "server.example.test", "user": "alice", "port": 2222,
        }}}))
        self.profiles.chmod(0o600)
        self.addCleanup(patch.stopall)
        patch.object(Path, "home", return_value=self.home).start()
        patch.object(ssh_bridge_ops, "CONFIG", self.profiles).start()
        patch.dict("os.environ", {"SSH_AUTH_SOCK": ""}).start()
        registry = Registry()
        for module in (ssh_auth_diag, ssh_bridge_ops, ssh_manage_ops):
            module.register(registry)
        self.tools = registry.tools
        self.run = patch.object(ssh_auth_diag.subprocess, "run").start()

    def test_identity_inspection_defaults_to_local_metadata_without_ssh(self):
        folder = self.home / ".ssh"
        folder.mkdir()
        (folder / "id_ed25519.pub").write_text("fake-public-key")
        result = self.tools["ssh_identity_inspect"]()
        self.run.assert_not_called()
        self.assertEqual(result["effective_ssh"], {})
        self.assertIsNone(result["effective_ssh_exit"])
        self.assertEqual(result["ssh_entries"][0]["name"], "id_ed25519.pub")
        self.assertEqual(result["home"], str(self.home))

    def test_existing_openssh_alias_uses_native_effective_configuration(self):
        self.run.return_value = subprocess.CompletedProcess([], 0,
            "hostname server.example.test\nuser alice\nport 2222\n"
            "identityfile /owner/key\nproxycommand fake-secret-command\n", "")
        with patch.object(ssh_bridge_ops, "_argv", wraps=ssh_bridge_ops._argv) as validate:
            result = self.tools["ssh_identity_inspect"]("staging")
        validate.assert_called_once_with("staging", "identity")
        argv = self.run.call_args.args[0]
        self.assertEqual(argv[:2], ["/usr/bin/ssh", "-G"])
        self.assertEqual(argv[-2:], ["--", "staging"])
        self.assertNotIn("-F", argv)
        self.assertIn("PermitLocalCommand=no", argv)
        self.assertNotIn("id -un", argv)
        self.assertNotIn(str(self.home / ".ssh/config"), argv)
        self.assertEqual(self.run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(self.run.call_args.kwargs["timeout"], 8)
        self.assertEqual(result["effective_ssh_exit"], 0)
        self.assertEqual(result["effective_ssh"]["hostname"], ["server.example.test"])
        self.assertNotIn("proxycommand", result["effective_ssh"])

    def test_unregistered_alias_is_accepted_but_option_injection_is_not(self):
        self.run.return_value = subprocess.CompletedProcess([], 0,
            "hostname other.example.test\nuser alice\nport 22\n", "")
        self.assertEqual(self.tools["ssh_identity_inspect"]("unregistered")["effective_ssh_exit"], 0)
        self.assertEqual(self.run.call_args.args[0][-1], "unregistered")
        self.run.reset_mock()
        for host in ("root@server.example.test", "-oProxyCommand=echo",
                     "staging;echo unsafe", ""):
            with self.subTest(host=host):
                if not host:
                    self.tools["ssh_identity_inspect"](host)
                else:
                    with self.assertRaisesRegex(ValueError, "Invalid host label"):
                        self.tools["ssh_identity_inspect"](host)
        self.run.assert_not_called()

    def test_invalid_saved_profile_refuses_before_subprocess(self):
        self.profiles.write_text(json.dumps({"hosts": {"staging": {
            "kind": "direct", "host": "server.example.test", "user": "alice", "port": 0,
        }}}))
        with patch.object(ssh_manage_ops, "CONFIG", self.profiles):
            with self.assertRaisesRegex(ValueError, "Invalid saved SSH host"):
                self.tools["ssh_identity_inspect"]("staging")
        self.run.assert_not_called()

    def test_interactive_ssh_only_needs_tmux_not_a_local_policy(self):
        with patch.object(command_plugins, "_tmux_available", return_value=None), \
             patch.object(command_plugins, "_tmux", side_effect=AssertionError("Unexpected tmux")) as tmux:
            for tool in ("ssh_open", "ssh_pty_open"):
                with self.subTest(tool=tool):
                    with self.assertRaisesRegex(RuntimeError, "tmux"):
                        self.tools[tool]("staging")
            tmux.assert_not_called()
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
