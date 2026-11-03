"""Auto cannot silently inject foreground keyboard or mouse actions."""
import asyncio
import unittest
from unittest.mock import patch
from scripts.dev_mcp_server import make_server

class ModeSemanticsTests(unittest.TestCase):
 def test_modes_deny_foreground_without_dispatch(self):
  async def scenario():
   # Explicitly activate optional modules only for this in-process test fixture.
   # Clean CI runners have no owner-specific feature_flags.json.
   with patch('mac_control.background_browser_ops.enabled', return_value=True), \
        patch('mac_control.background_native_ops.enabled', return_value=True):
    server=make_server(include_mutations=True)
   native={'session_token':'not-a-token','window_ref':'0'*64,'element_path':[0],
           'expected_role':'AXButton','expected_title':'Commit','action':'AXPress'}
   browser={'session_token':'not-a-token','action':'click'}
   with patch('mac_control.background_browser_ops._call',side_effect=AssertionError('unexpected background dispatch')), \
        patch('mac_control.background_native_ops.execute',side_effect=AssertionError('unexpected native dispatch')):
    for name,args in [('background_browser_action',browser),('background_app_action',native)]:
     for mode,code in [('foreground','REQUIRES_FOREGROUND'),('surprise','INVALID_MODE')]:
      result=await server.call_tool(name,{**args,'mode':mode})
      self.assertFalse(result.structured_content['ok'])
      self.assertEqual(result.structured_content['error']['code'],code)
  asyncio.run(scenario())
