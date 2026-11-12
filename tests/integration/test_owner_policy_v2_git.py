"""Allow owner-approved Git remotes and scalable explicit staging."""
import unittest
from unittest.mock import patch
from mac_control.legacy_handlers import git_ops
class Registry:
 def __init__(self):self.tools={}
 def tool(self,**kwargs):
  def register(fn):self.tools[fn.__name__]=fn;return fn
  return register
class GitFlexibilityTests(unittest.TestCase):
 def setUp(self):
  r=Registry();git_ops.register(r);self.tools=r.tools
 def test_fetch_any_configured_remote(self):
  with patch.object(git_ops,"git",return_value={"exit_code":0}) as op:
   self.tools["git_fetch"]("workspace","backup")
  self.assertIn("backup",op.call_args.args[1])
 def test_pull_another_remote(self):
  def fake(project,args,timeout=15):
   if args==["branch","--show-current"]:return {"exit_code":0,"stdout":"feature\n"}
   return {"exit_code":0,"stdout":""}
  with patch.object(git_ops,"git",side_effect=fake) as op:
   self.tools["git_pull_ff"]("workspace","upstream")
  self.assertEqual(op.call_args.args[1][-2:],["upstream","feature"])
 def test_push_other_remote(self):
  def fake(project,args,timeout=15):
   if args==["branch","--show-current"]:return {"exit_code":0,"stdout":"feature\n"}
   return {"exit_code":0,"stdout":""}
  with patch.object(git_ops,"git",side_effect=fake) as op:
   self.tools["git_push"]("workspace","upstream")
  self.assertEqual(op.call_args.args[1][-2:],["upstream","HEAD:refs/heads/feature"])
 def test_stage_more_than_twenty_paths(self):
  with patch.object(git_ops,"checked_path",side_effect=lambda p,path:path),patch.object(git_ops,"git",return_value={"exit_code":0}) as op:
   self.tools["git_stage"]("workspace",[f"f{i}.py" for i in range(50)])
  self.assertEqual(len(op.call_args.args[1]),52)
if __name__=="__main__":unittest.main()
