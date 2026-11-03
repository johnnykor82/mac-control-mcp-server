"""Session capabilities and privileged scope of native backend."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mac_control import background_native_ops as native
class NativeCapabilityTests(unittest.TestCase):
 def test_session_scope_revoke_and_invalid_token(self):
  calls=[]
  def mock_helper(op,**args):
   calls.append((op,args))
   if op=='windows':
    return {'ok':True,'result':{'windows':[{'pid':444,'window_ref':'a'*64}],
          'launch_date':100.25,'bundle_id':'com.example.test'}}
   return {'ok':True,'result':{'operation':op,'params':args}}
  with tempfile.TemporaryDirectory() as temp,patch.object(native,'ROOT',Path(temp)),patch.object(native,'helper',side_effect=mock_helper):
   c=native.begin('com.example.test');self.assertTrue(c['ok'])
   token=c['result']['session_token']
   self.assertEqual(native.execute('0'*40+'.'+'0'*64,'windows')['error']['code'],'NOT_AUTHORIZED')
   good=native.execute(token,'action',window_ref='a'*64,action='AXPress')
   self.assertTrue(good['ok'])
   self.assertEqual(good['result']['params']['expected_pid'],444)
   self.assertEqual(good['result']['params']['expected_launch_date'],100.25)
   self.assertTrue(native.execute(token,'end')['ok'])
   self.assertEqual(native.execute(token,'action')['error']['code'],'NOT_AUTHORIZED')
   self.assertFalse(any('session_token' in repr(args) for _,args in calls))
 def test_invalid_app_not_exposed_to_helper(self):
  with patch.object(native,'helper') as helper:
   self.assertFalse(native.begin('../../bad')['ok'])
   helper.assert_not_called()
