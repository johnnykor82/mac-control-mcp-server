"""Opt-in REAL SSH/SFTP MCP E2E against an isolated test sshd.

Run with MCP_SSH_E2E_CONFIG=/absolute/path/to/test_ssh_config
and MCP_SSH_E2E_ROOT=/absolute/private/test/directory. Never use production.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import secrets
import unittest
from unittest.mock import patch

from fastmcp import FastMCP
from mac_control.legacy_handlers import ssh_manage_ops as ssh
from mac_control.legacy_handlers import ssh_file_transfer as tf


@unittest.skipUnless(os.environ.get("MCP_SSH_E2E_CONFIG") and
                     os.environ.get("MCP_SSH_E2E_ROOT"), "isolate SSH fixture not configured")
class LiveSftpMcpTests(unittest.TestCase):
    def test_generated_script_via_mcp_compiles_and_roundtrips(self):
        config=Path(os.environ["MCP_SSH_E2E_CONFIG"])
        directory=Path(os.environ["MCP_SSH_E2E_ROOT"])
        assert config.is_file() and directory.is_dir()
        alias="mac-control-e2e-test"
        target=directory/("test_"+secrets.token_hex(6)+".py")
        result=directory/("return_"+secrets.token_hex(6)+".py")
        text="# coding: utf-8\n"+("print(42) # Пример теста через MCP\n"*700)
        digest=hashlib.sha256(text.encode()).hexdigest()
        self.assertGreater(len(text.encode()),10*1024)

        def approved(value):
            if value != alias:
                raise ValueError("Unapproved test host")
            return {"kind":"alias","alias":alias}

        async def run():
            server=FastMCP("SFTP real E2E")
            ssh.register(server)
            tf.register(server)
            names={t.name for t in await server.list_tools()}
            self.assertTrue({"ssh_write_text","ssh_exec","ssh_download"} <= names)
            with patch.object(ssh,"_spec",side_effect=approved), \
                 patch.object(ssh,"SSH_CONFIG",config), \
                 patch.object(tf,"_safe_local",side_effect=lambda path,require_existing=False:Path(path)):
                response=await server.call_tool("ssh_write_text",{
                    "host":alias,"remote_path":str(target),"content":text})
                self.assertEqual(response.structured_content["sha256"],digest)
                self.assertTrue(response.structured_content["verified"])
                compilation=await server.call_tool("ssh_exec",{
                    "host":alias,"command":"python3 -m py_compile '"+str(target)+"'"})
                self.assertEqual(compilation.structured_content["exit_code"],0)
                downloaded=await server.call_tool("ssh_download",{
                    "host":alias,"remote_path":str(target),"local_path":str(result),
                    "expected_sha256":digest})
                self.assertEqual(downloaded.structured_content["sha256"],digest)
                self.assertEqual(result.read_text(),text)
        try:
            asyncio.run(run())
        finally:
            target.unlink(missing_ok=True)
            result.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
