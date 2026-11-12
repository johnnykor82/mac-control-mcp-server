"""GUI paste should support longer text without changing signed helper."""
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from mac_control.legacy_handlers import gui_ops
class Registry:
 def __init__(self):self.tools={}
 def tool(self,**kw):
  def f(fn):self.tools[fn.__name__]=fn;return fn
  return f
class GuiExtendedTextTests(unittest.TestCase):
 def test_gui_type_6k_characters_restores_clipboard(self):
  registry=Registry();gui_ops.register(registry)
  fake=Mock()
  fake.poll.return_value=None
  fake.stdout.readline.side_effect=["READY\n","RESTORED\n"]
  with patch.object(gui_ops,"GUI_CLIPBOARD_HELPER",Path(__file__)),patch.object(gui_ops.subprocess,"Popen",return_value=fake),patch.object(gui_ops.select,"select",side_effect=lambda x,y,z,t:(x,[],[])),patch.object(gui_ops.time,"sleep"),patch.object(gui_ops,"_call",return_value={"ok":True}):
   result=registry.tools["gui_type"]("Z"*6000)
  self.assertEqual(result["characters"],6000)
  self.assertTrue(result["clipboard_restored"])
  self.assertTrue(fake.stdin.write.called)
 def test_gui_type_has_resource_bound_not_infinite(self):
  registry=Registry();gui_ops.register(registry)
  with self.assertRaises(ValueError):
   registry.tools["gui_type"]("Z"*40000)
if __name__=="__main__":unittest.main()
