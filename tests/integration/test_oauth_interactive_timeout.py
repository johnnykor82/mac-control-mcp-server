"""The owner must have the full GitHub OAuth callback window to authorize MCP."""
import sys
import types
import unittest
from unittest.mock import patch

from scripts.test_github_oauth_login import verify_login


class OAuthInteractiveTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_initialize_window_exceeds_human_consent_window(self):
        props = {}
        class OAuth:
            def __init__(self, **kw):
                props['callback_timeout'] = kw['callback_timeout']
        class Result:
            is_error = False
        class Client:
            def __init__(self, endpoint, **kw):
                props['init_timeout'] = kw['init_timeout']
            async def __aenter__(self):return self
            async def __aexit__(self, *args):return None
            async def call_tool(self, *args, **kwargs):return Result()
        fastmcp=types.ModuleType('fastmcp')
        fastmcp.Client=Client
        client=types.ModuleType('fastmcp.client')
        auth=types.ModuleType('fastmcp.client.auth')
        auth.OAuth=OAuth
        with patch.dict(sys.modules, {'fastmcp':fastmcp,'fastmcp.client':client,'fastmcp.client.auth':auth}):
            report=await verify_login('https://example.test/maccontrol/mcp')
        self.assertTrue(report['github_oauth_login_verified'])
        self.assertGreater(props['init_timeout'],props['callback_timeout'])


if __name__=='__main__':
    unittest.main()
