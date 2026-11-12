"""launchd tool targets system/user/GUI domains without artificial single-domain list."""
import unittest
from unittest.mock import Mock,patch
from mac_control.legacy_handlers import system_ops
class Registry:
 def __init__(self):self.tools={}
 def tool(self,**kwargs):
  def f(fn):self.tools[fn.__name__]=fn;return fn
  return f
class LaunchdOwnerPolicyTests(unittest.TestCase):
 def setUp(self):
  r=Registry();system_ops.register(r);self.tools=r.tools
 def test_read_system_launchdaemon(self):
  with patch.object(system_ops,"execute",return_value={"stdout":"state = running\n","exit_code":0}) as run:
   self.tools["launchd_status"]("com.example.daemon",domain="system")
  self.assertIn("system/com.example.daemon",run.call_args.args[0])
 def test_restart_user_service_with_uid(self):
  with patch.object(system_ops,"execute",return_value={"exit_code":0}) as run,patch.object(system_ops,"_managed_service",return_value=Mock(LABEL="org.maccontrol.mcpserver.remote")):
   self.tools["launchd_restart"]("com.example.agent",domain="gui",uid=511)
  self.assertIn("gui/511/com.example.agent",run.call_args.args[0])
 def test_invalid_domain_rejected_no_launchctl(self):
  with patch.object(system_ops,"execute") as run:
   with self.assertRaises(ValueError):
    self.tools["launchd_restart"]("com.example.agent",domain="root/../../escape")
  run.assert_not_called()
if __name__=="__main__":unittest.main()
