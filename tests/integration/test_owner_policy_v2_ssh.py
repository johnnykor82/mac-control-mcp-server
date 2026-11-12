"""SSH works for new owner-approved hosts and arbitrary accessible identity keys."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mac_control.legacy_handlers import ssh_manage_ops as ssh

class Registry:
 def __init__(self):self.tools={}
 def tool(self,**kwargs):
  def register(fn):self.tools[fn.__name__]=fn;return fn
  return register

class SSHOwnerPolicyTests(unittest.TestCase):
 def test_new_host_without_saved_alias_and_safe_tofu(self):
  argv=ssh._command("ops@new.example.net","uptime")
  self.assertIn("ops@new.example.net",argv)
  self.assertIn("StrictHostKeyChecking=accept-new",argv)
  self.assertNotIn("StrictHostKeyChecking=no",argv)
  self.assertIn("ForwardAgent=no",argv)

 def test_ip_address_without_alias(self):
  argv=ssh._command("192.0.2.25","uptime")
  self.assertIn("192.0.2.25",argv)

 def test_any_accessible_owner_key_outside_ssh_dir(self):
  with tempfile.TemporaryDirectory() as root:
   key=Path(root)/"owner-key"
   key.write_text("fake test identity metadata")
   key.chmod(0o600)
   argv=ssh._command("ops@new.example.net","uptime",identity_file=str(key))
   self.assertEqual(Path(argv[argv.index("-i")+1]).resolve(),key.resolve())

 def test_register_key_not_confined_to_dot_ssh(self):
  with tempfile.TemporaryDirectory() as root:
   key=Path(root)/"key";key.write_text("placeholder");key.chmod(0o600)
   registry=Registry();ssh.register(registry)
   with patch.object(ssh,"_read_config",return_value={}),patch.object(ssh,"_write_config") as save:
    registry.tools["ssh_profile_register"]("temporary","new.example.net","ops",22,str(key))
   self.assertTrue(save.called)
 def test_arbitrary_diagnostic_command_not_fixed_shortcut(self):
  from mac_control.legacy_handlers import ssh_bridge_ops as bridge
  from unittest.mock import Mock
  registry=Registry();bridge.register(registry)
  with patch.object(ssh,"_command",return_value=["/usr/bin/ssh","-T","--","ops@new.example.net","cat /proc/loadavg"]) as command, patch.object(bridge.subprocess,"run",return_value=Mock(returncode=0,stdout="load",stderr="")):
   result=registry.tools["ssh_diagnostic"]("ops@new.example.net","cat /proc/loadavg")
  self.assertEqual(result["stdout"],"load")
  command.assert_called()

if __name__=="__main__":unittest.main()
