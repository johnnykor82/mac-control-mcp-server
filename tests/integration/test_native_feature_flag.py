import asyncio
import unittest
from unittest.mock import patch
from scripts.dev_mcp_server import make_server
class NativeFeatureFlagTests(unittest.TestCase):
 def test_disabled_by_default_or_untrusted_http(self):
  with patch('mac_control.background_browser_ops.enabled',return_value=True),patch('mac_control.background_native_ops.enabled',return_value=True):
   web=asyncio.run(make_server().list_tools())
   local=asyncio.run(make_server(include_mutations=True).list_tools())
  self.assertEqual(len(web),20)
  self.assertEqual(len(local),117)
  names={x.name:x for x in local}
  for name in ('background_app_list','background_app_create','background_app_windows',
       'background_app_elements','background_app_action','background_app_capture','background_app_close'):
   self.assertIn(name,names)
   self.assertNotIn(name,{t.name for t in web})
  self.assertTrue(names['background_app_elements'].annotations.read_only_hint)
  self.assertFalse(names['background_app_action'].annotations.read_only_hint)
