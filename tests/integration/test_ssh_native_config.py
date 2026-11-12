"""E2: existing OpenSSH host aliases work without internal host approval."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mac_control.legacy_handlers import ssh_manage_ops as ssh
from mac_control.legacy_handlers import ssh_bridge_ops as diag
from mac_control.legacy_handlers import ssh_file_transfer as transfers


class NativeConfigTests(unittest.TestCase):
    def test_existing_config_alias_needs_no_managed_host_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / ".ssh/config"
            config.parent.mkdir()
            config.write_text(
                "Host jump\n  HostName jump.example.test\n"
                "Host production\n  HostName production.example.test\n  ProxyJump jump\n"
            )
            with patch.object(ssh, "CONFIG", root / "missing_registry.json"), \
                 patch.object(ssh, "SSH_CONFIG", config):
                command = ssh._command("production", "uptime")
        self.assertEqual(command[0], ssh.SSH)
        self.assertEqual(command[-2:], ["production", "uptime"])
        self.assertNotIn("-F", command)
        self.assertIn("StrictHostKeyChecking=accept-new", command)

    def test_diagnostics_and_sftp_share_one_openssh_configuration(self):
        with patch.object(ssh, "_read_config", return_value={}):
            normal = ssh._command("production")
            diagnostic = diag._argv("production", "uptime")
            transfer = transfers._ssh_command("production")
            sftp = transfers._sftp_argv("production")
        self.assertEqual(diagnostic[-2:], ["production", "uptime"])
        self.assertEqual(transfer, normal)
        self.assertEqual(sftp[-1], "production")
        self.assertNotIn("-F", sftp)

    def test_invalid_option_instead_of_host_is_rejected(self):
        with patch.object(ssh, "_read_config", return_value={}):
            for host in ("-oProxyCommand=bad", "alias; echo bad", ""):
                with self.subTest(host=host), self.assertRaises(ValueError):
                    ssh._command(host, "uptime")


if __name__ == "__main__":
    unittest.main()
