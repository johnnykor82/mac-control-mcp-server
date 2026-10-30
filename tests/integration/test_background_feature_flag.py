"""Background tools are local-only and behind an owner-controlled feature flag."""
import asyncio
import unittest
from unittest.mock import patch
from scripts.dev_mcp_server import make_server
class BackgroundPreviewTests(unittest.TestCase):
 def test_disabled_by_default(self):
  with patch('mac_control.background_browser_ops.enabled',return_value=False), patch('mac_control.background_native_ops.enabled',return_value=False):
   server=make_server(include_mutations=True)
   tools=asyncio.run(server.list_tools())
   self.assertEqual(len(tools),115)
 def test_enabled_only_in_local_stdio(self):
  with patch('mac_control.background_browser_ops.enabled',return_value=True), patch('mac_control.background_native_ops.enabled',return_value=False):
   local=asyncio.run(make_server(include_mutations=True).list_tools())
   web=asyncio.run(make_server().list_tools())
  names={t.name:t for t in local}
  self.assertEqual(len(local),122)
  self.assertEqual(len(web),20)
  self.assertNotIn('background_browser_create',{t.name for t in web})
  self.assertTrue(names['background_browser_snapshot'].annotations.read_only_hint)
  self.assertFalse(names['background_browser_create'].annotations.read_only_hint)
  for name in ('background_browser_create','background_browser_action','background_browser_snapshot',
               'background_browser_capture','background_browser_list','background_browser_close',
               'background_browser_reopen'):
   self.assertIn(name,names)
