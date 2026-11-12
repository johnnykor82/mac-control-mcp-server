"""Maintenance file tools can use explicit task-authorized paths and default workspace."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mac_control import maintenance_ops as m
from mac_control.legacy_handlers import fs_ops
class Registry:
 def __init__(self):self.tools={}
 def tool(self,**kwargs):
  def f(fn):self.tools[fn.__name__]=fn;return fn
  return f
class MaintenancePathTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory()
  self.addCleanup(t.cleanup)
  self.base=Path(t.name).resolve()
  self.ws=self.base/"AgentWorkspace";self.ws.mkdir()
  self.ext=self.base/"TaskApprovedExternal";self.ext.mkdir()
  self.patches=[
   patch.object(fs_ops,"roots",return_value={"workspace":self.ws}),
   patch.object(fs_ops,"RECOVERY",self.base/"backups"),
  ]
  for p in self.patches:p.start();self.addCleanup(p.stop)
  r=Registry();m.register(r);self.tools=r.tools
 def test_external_absolute_file_read_os_rights(self):
  f=self.ext/"notes.txt";f.write_text("user-approved")
  value=self.tools["read_file"](str(f))
  self.assertEqual(value["content"],"user-approved")
 def test_external_absolute_file_write_and_cas(self):
  f=self.ext/"notes.txt"
  result=self.tools["write_file"](str(f),"first")
  self.assertEqual(f.read_text(),"first")
  self.tools["write_file"](str(f),"second",result["sha256"])
  self.assertEqual(f.read_text(),"second")
 def test_list_external_absolute_folder(self):
  (self.ext/"test.txt").write_text("test")
  out=self.tools["list_workspace"](str(self.ext))
  self.assertIn("test.txt",{x["name"] for x in out["entries"]})
 def test_default_workspace_allows_normal_file_at_root(self):
  self.tools["write_file"]("report.txt","contents")
  self.assertEqual((self.ws/"report.txt").read_text(),"contents")

 def test_external_directory_parent_symlink_rejected(self):
  real=self.base/"realparent";real.mkdir()
  nested=real/"authorized";nested.mkdir()
  alias=self.base/"linkparent";alias.symlink_to(real,target_is_directory=True)
  with self.assertRaises(PermissionError):
   self.tools["list_workspace"](str(alias/"authorized"))
if __name__=="__main__":unittest.main()
