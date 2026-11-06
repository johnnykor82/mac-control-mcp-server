"""FR025.3 E2E: execute immutable source payload against isolated file tools.

Never call a real service, SSH host or user's workspace. Only copied release
files and the approved test temporary directory are written.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from scripts import install_mac_control as installer


class StagedReleaseCompatibilityE2ETests(unittest.TestCase):
    def test_packaged_mcp_file_alias_and_legacy_cas_interoperate(self):
        with tempfile.TemporaryDirectory(prefix="fr025-staged-") as tmp:
            # macOS /var is often a symlink to /private/var. The real
            # workspace and backup paths must have no symlink ancestor;
            # never disable maintenance_ops._no_symlinks to fix a fixture.
            root = Path(tmp).resolve(strict=True)
            self.assertEqual(root, root.resolve(strict=True))
            release = root / "releases" / "candidate"
            release.mkdir(parents=True)
            installer.copy_source(release)
            workspace = root / "workspace"
            workspace.mkdir()
            data = root / "isolated-data"
            data.mkdir()

            script = textwrap.dedent("""
                import asyncio
                from pathlib import Path
                from scripts.dev_mcp_server import make_server
                from mac_control.workspace_config import set_root

                root = Path(__import__('os').environ['MAC_CONTROL_DATA_ROOT'])
                ws = Path(__import__('os').environ['FR025_TEST_WORKSPACE'])
                set_root(root, ws)

                async def main():
                    server = make_server(include_mutations=True)
                    names = {t.name for t in await server.list_tools()}
                    assert 'write_file' in names and 'fs_write' in names
                    relative = 'projects/android-license-audit/reports/INITIAL_AUDIT.md'
                    audit_context = {
                        'task_id': 'FR025-E2E',
                        'action': 'Exercise isolated staged file alias with a versioned CAS write and read',
                        'authorization_basis': 'User-approved offline integration fixture on 2026-11-06',
                    }
                    first = await server.call_tool('write_file',
                        {'path': relative, 'content': '# staged v1', 'audit_context':audit_context})
                    assert not first.is_error, first
                    digest = first.structured_content['sha256']

                    second = await server.call_tool('fs_write', {
                        'project': 'workspace',
                        'path': relative,
                        'content': '# staged v2',
                        'expected_sha256': digest, 'audit_context': audit_context,
                    })
                    assert not second.is_error, second
                    read = await server.call_tool('read_file',
                        {'path': 'workspace/' + relative, 'audit_context': audit_context})
                    assert read.structured_content['content'] == '# staged v2'
                    assert (ws / relative).read_text() == '# staged v2'
                    assert (root / 'backups' / 'fs_recovery').is_dir()
                    assert not (ws.parent / 'outside.txt').exists()
                    print('STAGED_ALIAS_AND_LEGACY_CAS_E2E_PASS')

                asyncio.run(main())
            """)
            env = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join((str(release / "src"), str(release))),
                "MAC_CONTROL_DATA_ROOT": str(data),
                "FR025_TEST_WORKSPACE": str(workspace),
                "PYTHONNOUSERSITE": "1",
            }
            completed = subprocess.run(
                [sys.executable, "-P", "-B", "-c", script],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=28,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("STAGED_ALIAS_AND_LEGACY_CAS_E2E_PASS",
                          completed.stdout)
            self.assertFalse((root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
