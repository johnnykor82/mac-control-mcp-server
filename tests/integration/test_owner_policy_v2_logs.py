"""Any explicitly owner-authorized readable logfile, with safe redaction and bounds."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mac_control import maintenance_ops as m

class Registry:
 def __init__(self):self.tools={}
 def tool(self,**kwargs):
  def register(fn):self.tools[fn.__name__]=fn;return fn
  return register

class GenericServiceLogTests(unittest.TestCase):
 def setUp(self):
  registry=Registry();m.register(registry);self.tools=registry.tools
  temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
  self.root=Path(temporary.name).resolve()
  self.log=self.root/"other-service.log"
  self.log.write_text('healthy\npassword="DO_NOT_EXPOSE"\nqueue: 0\n')

 def test_absolute_logfile_outside_mcp_service_list_is_readable_and_redacted(self):
  result=self.tools["read_service_log"](str(self.log),10)
  self.assertFalse(result.get("missing",False))
  self.assertIn("healthy",result["lines"])
  self.assertIn("queue: 0",result["lines"])
  self.assertNotIn("DO_NOT_EXPOSE"," ".join(result["lines"]))

 def test_mcp_diagnostics_lists_explicit_log_file(self):
  with patch.object(m,"_owned_service",return_value=(None,{"status":"running"})):
   result=self.tools["mcp_diagnostics"](log_paths=[str(self.log)])
  self.assertEqual(result["log_bytes"][str(self.log)],self.log.stat().st_size)

 def test_relative_traversal_still_rejected(self):
  with self.assertRaises(ValueError):
   self.tools["read_service_log"]("../private.txt")

 def test_parent_symlink_is_not_accepted(self):
  real=self.root/"real";real.mkdir()
  source=real/"private.log";source.write_text("private\\n")
  linked=self.root/"link";linked.symlink_to(real,target_is_directory=True)
  alias=linked/"private.log"
  result=self.tools["read_service_log"](str(alias))
  self.assertTrue(result.get("missing"))
  with patch.object(m,"_owned_service",return_value=(None,{"status":"running"})):
   metadata=self.tools["mcp_diagnostics"](log_paths=[str(alias)])
  self.assertIsNone(metadata["log_bytes"][str(alias)])

if __name__=="__main__":unittest.main()
