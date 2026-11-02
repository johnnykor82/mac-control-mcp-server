"""Capture requests cannot escape the authorized AX session window."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mac_control import background_native_ops as n
class NativeWindowCaptureTests(unittest.TestCase):
 def test_stale_window_never_invokes_gui(self):
  meta={'bundle_id':'test.app','pid':333,'launch_date':12}
  inventory={'ok':True,'result':{'windows':[{'window_ref':'a'*64,'title':'fixture','bounds':{'x':1,'y':1,'width':30,'height':30}}]}}
  with patch.object(n,'helper',return_value=inventory),patch('mac_control.legacy_handlers.gui_ops._call') as gui:
   self.assertEqual(n.capture_verified(meta,'b'*64)['error']['code'],'STALE_OR_AMBIGUOUS_WINDOW')
   gui.assert_not_called()
 def test_gui_capture_and_ephemeral_cleanup(self):
  metadata={'bundle_id':'test.app','pid':333,'launch_date':12}
  inventory={'ok':True,'result':{'windows':[{'window_ref':'a'*64,'title':'fixture','bounds':{'x':1,'y':1,'width':30,'height':30}}]}}
  with tempfile.TemporaryDirectory() as tmp,patch.object(n,'DATA_ROOT',Path(tmp)),patch.object(n,'helper',return_value=inventory):
   folder=Path(tmp)/'run/gui-captures';folder.mkdir(parents=True,mode=0o700)
   def fake_call(operation,**kw):
    self.assertEqual(operation,'capture_window')
    self.assertEqual(kw['pid'],333)
    self.assertEqual(kw['title'],'fixture')
    self.assertEqual(kw['width'],30)
    Path(kw['destination']).write_bytes(b'\xff\xd8'+b'A'*1300)
    return {'capture_mode':'desktopIndependentWindow'}
   with patch('mac_control.legacy_handlers.gui_ops._call',side_effect=fake_call):
    response=n.capture_verified(metadata,'a'*64)
   self.assertTrue(response['ok'],response)
   self.assertEqual(response['result']['image_bytes'],1302)
   self.assertFalse(list(folder.iterdir()),'Capture artifact not wiped')
