"""Large native screenshot remains a native MCP image, never truncated JSON."""
import asyncio,base64,unittest
from unittest.mock import patch
from mcp.types import ImageContent
from scripts.dev_mcp_server import make_server
from mac_control import background_native_ops as n
def native_test_server():
  # Native API is feature-flagged off on clean GitHub macOS runners.
  # Override only registration for this isolated contract test.
  with patch.object(n, 'enabled', return_value=True):
   return make_server(include_mutations=True)

class NativeImageContentTests(unittest.TestCase):
 def test_large_native_image_is_binary_content(self):
  jpeg=b'\xff\xd8'+b'Z'*175000
  encoded=base64.b64encode(jpeg).decode('ascii')
  async def run():
   with patch.object(n,'execute',return_value={'ok':True,'result':{
       'image_data':encoded,'mime_type':'image/jpeg','image_bytes':len(jpeg),
       'window_ref':'a'*64,'capture_mode':'desktopIndependentWindow'}}):
    return await native_test_server().call_tool('background_app_capture',{
       'session_token':'test','window_ref':'a'*64,'audit_context':{"task_id":"BF26-REGRESSION", "action":"Run isolated validation and inspect expected error without changing external state", "authorization_basis":"User approved development testing on 2026-11-06"}})
  answer=asyncio.run(run())
  self.assertFalse(answer.is_error)
  self.assertEqual(len(answer.content),1)
  self.assertIsInstance(answer.content[0],ImageContent)
  self.assertEqual(base64.b64decode(answer.content[0].data),jpeg)
  self.assertEqual(answer.structured_content['result']['image_bytes'],len(jpeg))
  self.assertNotIn('image_data',answer.structured_content['result'])
 def test_native_failure_preserves_structured_error(self):
  async def run():
   with patch.object(n,'execute',return_value={'ok':False,
        'error':{'code':'NOT_AUTHORIZED','message':'No session'}}):
    return await native_test_server().call_tool('background_app_capture',{
       'session_token':'bad','window_ref':'a'*64,'audit_context':{"task_id":"BF26-REGRESSION", "action":"Run isolated validation and inspect expected error without changing external state", "authorization_basis":"User approved development testing on 2026-11-06"}})
  answer=asyncio.run(run())
  self.assertEqual(answer.structured_content['error']['code'],'NOT_AUTHORIZED')
