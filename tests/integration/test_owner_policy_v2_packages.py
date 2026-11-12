"""Package tooling must support native Homebrew formulas, casks and taps."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from mac_control.legacy_handlers import package_ops as pkg
class Registry:
 def __init__(self):self.tools={}
 def tool(self,**kw):
  def f(fn):self.tools[fn.__name__]=fn;return fn
  return f
class PackageKindsTests(unittest.TestCase):
 def setUp(self):
  r=Registry();pkg.register(r);self.tools=r.tools
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.root=Path(tmp.name)
 def test_install_worker_cask(self):
  folder=self.root/"0123456789abcdef";folder.mkdir()
  (folder/"status.json").write_text(json.dumps({"status":"queued"}))
  with patch.object(pkg,"STATE",self.root),patch.object(pkg,"brew",return_value="/usr/local/bin/brew"),patch.object(pkg.subprocess,"run",return_value=Mock(returncode=0)) as run:
   self.assertEqual(pkg._worker("0123456789abcdef","firefox","cask"),0)
  self.assertEqual(run.call_args.args[0],["/usr/local/bin/brew","install","--cask","firefox"])
 def test_install_worker_tap(self):
  folder=self.root/"0123456789abcdef";folder.mkdir()
  (folder/"status.json").write_text(json.dumps({"status":"queued"}))
  with patch.object(pkg,"STATE",self.root),patch.object(pkg,"brew",return_value="/usr/local/bin/brew"),patch.object(pkg.subprocess,"run",return_value=Mock(returncode=0)) as run:
   self.assertEqual(pkg._worker("0123456789abcdef","homebrew/cask","tap"),0)
  self.assertEqual(run.call_args.args[0],["/usr/local/bin/brew","tap","homebrew/cask"])
 def test_installed_cask(self):
  with patch.object(pkg,"brew",return_value="/opt/homebrew/bin/brew"),patch.object(pkg,"_run",return_value=Mock(returncode=0,stdout="1.2")) as run:
   value=self.tools["package_installed"]("firefox","cask")
  self.assertTrue(value["installed"])
  self.assertEqual(run.call_args.args[0],["/opt/homebrew/bin/brew","list","--cask","--versions","firefox"])
 def test_capabilities_include_cask_tap(self):
  with patch.object(pkg,"brew",return_value="/opt/homebrew/bin/brew"),patch.object(pkg,"_run",return_value=Mock(stdout="brew")):
   value=self.tools["package_capabilities"]()
  self.assertTrue(value["cask_installs_supported"])
  self.assertTrue(value["tap_installs_supported"])
if __name__=="__main__":unittest.main()
