"""Maintenance compatibility tools use fixtures; no live launchd or processes."""
import asyncio
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mac_control import maintenance_ops as maintenance
from mac_control.legacy_handlers import fs_ops


class Registry:
    def __init__(self):
        self.tools = {}
        self.annotations = {}

    def tool(self, **options):
        def store(fn):
            self.tools[fn.__name__] = fn
            self.annotations[fn.__name__] = options['annotations']
            return fn
        return store


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.data = self.root / 'data'
        self.workspace = self.data / 'workspace'
        self.workspace.mkdir(parents=True)
        self.logs = self.data / 'logs'
        self.logs.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(maintenance, 'DATA_ROOT', self.data).start()
        patch.object(fs_ops, 'ROOT', self.data).start()
        patch.object(fs_ops, 'WORKSPACE', self.workspace).start()
        patch.object(fs_ops, 'TRUSTED_CONFIG', self.data / 'allowed_projects.json').start()
        patch.object(fs_ops, 'RECOVERY', self.data / 'backups/fs_recovery').start()
        registry = Registry()
        maintenance.register(registry)
        self.registry = registry
        self.tools = registry.tools

    def test_registers_all_compatibility_tools_with_safe_annotations(self):
        self.assertEqual(set(self.tools), {'audit_tail', 'audit_search', 'list_workspace',
            'process_snapshot', 'read_service_log', 'mcp_diagnostics', 'read_file',
            'write_file', 'restart_server', 'custom_query', 'custom_command'})
        self.assertFalse(self.registry.annotations['custom_command']['readOnlyHint'])
        self.assertTrue(self.registry.annotations['custom_query']['readOnlyHint'])

    def test_workspace_files_are_cas_protected_and_backed_up(self):
        write, read = self.tools['write_file'], self.tools['read_file']
        first = write('workspace/example.txt', 'one')
        result = read(str(self.workspace / 'example.txt'))
        self.assertEqual(result['content'], 'one')
        self.assertEqual(first['sha256'], result['sha256'])
        with self.assertRaises(ValueError):
            write('workspace/example.txt', 'two')
        with self.assertRaises(ValueError):
            write('workspace/example.txt', 'two', '0' * 64)
        updated = write('workspace/example.txt', 'two', result['sha256'])
        self.assertTrue(updated['backup'])
        self.assertEqual(read('workspace/example.txt')['content'], 'two')
        self.assertEqual(list((self.data / 'backups/fs_recovery').iterdir())[0].read_text(), 'one')

    def test_sensitive_paths_symlinks_and_release_writes_are_denied(self):
        for name in ('workspace/../remote_auth.json', 'workspace/.env',
                     'workspace/.ssh/id_rsa', 'extensions.py', '/etc/passwd'):
            self.assertFalse(self.tools['read_file'](name)['ok'])
            with self.assertRaises((ValueError, PermissionError)):
                self.tools['write_file'](name, 'bad')
        outside = self.root / 'private.txt'
        outside.write_text('secret')
        (self.workspace / 'link.txt').symlink_to(outside)
        self.assertFalse(self.tools['read_file']('workspace/link.txt')['ok'])
        with self.assertRaises(PermissionError):
            self.tools['write_file']('workspace/link.txt', 'bad')
        with self.assertRaises(SyntaxError):
            self.tools['write_file']('workspace/bad.py', 'not python!')
        self.assertFalse((self.workspace / 'bad.py').exists())

    def test_read_and_write_size_limits(self):
        large = self.workspace / 'large.txt'
        large.write_bytes(b'x' * (maintenance.MAX_FILE + 1))
        self.assertEqual(self.tools['read_file']('workspace/large.txt')['error_code'], 'FILE_TOO_LARGE')
        with self.assertRaises(ValueError):
            self.tools['write_file']('workspace/new.txt', 'x' * (maintenance.MAX_FILE + 1))

    def test_list_workspace_uses_filesystem_sensitive_guards(self):
        (self.workspace / 'normal.txt').write_text('ok')
        (self.workspace / '.env').write_text('secret')
        (self.workspace / 'id_rsa').write_text('secret')
        (self.workspace / 'link').symlink_to(self.root)
        self.assertEqual([x['name'] for x in self.tools['list_workspace']()['entries']], ['normal.txt'])
        for path in ('workspace/../logs', 'other', '/tmp'):
            with self.assertRaises((ValueError, PermissionError)):
                self.tools['list_workspace'](path)

    def test_audit_is_metadata_only_and_tolerates_corrupt_records(self):
        (self.logs / 'audit.jsonl').write_text('\n'.join([
            json.dumps({'tool': 'read_file', 'event': 'tool_end', 'status': 'ok',
                        'arguments': {'secret': 'never-return'}, 'result': 'private'}),
            'broken', json.dumps({'tool': 'fs_read', 'status': 'error'}), '[]']) + '\n')
        tail = self.tools['audit_tail']()
        self.assertEqual(len(tail['events']), 2)
        self.assertNotIn('never-return', json.dumps(tail))
        result = self.tools['audit_search'](tool='fs_read', status='error')
        self.assertEqual(len(result['matches']), 1)
        self.assertEqual(result['matches'][0]['tool'], 'fs_read')
        self.assertEqual(self.tools['audit_search'](contains='never-return')['matches'], [])

    def test_service_logs_are_allowlisted_scrubbed_and_symlink_safe(self):
        (self.logs / 'remote-mcp.stderr.log').write_text('password="secret with spaces"\nAuthorization: Bearer opaque-token\nclient_secret=hidden\nghp_abcdefghijklmnop\n-----BEGIN ' + 'PRIVATE KEY-----\nbase64-private-material\n-----END PRIVATE KEY-----\n')
        result = self.tools['read_service_log']('stderr')
        encoded = json.dumps(result)
        for secret in ('secret with spaces', 'opaque-token', 'hidden', 'ghp_abcdefghijklmnop', 'base64-private-material'):
            self.assertNotIn(secret, encoded)
        with self.assertRaises(ValueError):
            self.tools['read_service_log']('../remote_auth.json')
        (self.logs / 'restart.log').symlink_to(self.root / 'private')
        self.assertTrue(self.tools['read_service_log']('restart')['missing'])

    def test_process_snapshot_never_returns_command_arguments(self):
        with patch.object(maintenance.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0,
                '100 1 0.0 1.0 4000 /usr/bin/python3\n101 1 0 0 10 /usr/bin/unrelated\n', '')) as run:
            result = self.tools['process_snapshot']()
        self.assertEqual(result['processes'][0]['executable'], 'python3')
        self.assertNotIn('args', ' '.join(run.call_args.args[0]))
        self.assertEqual(result['total_matched'], 1)

    def test_custom_registry_rejects_unknown_dynamic_and_write_through_query(self):
        query = self.tools['custom_query']
        command = self.tools['custom_command']
        operations = asyncio.run(query())['operations']
        names = {x['name'] for x in operations}
        self.assertIn('watcher_status', names)
        self.assertIn('fs_write', names)
        (self.workspace / 'command_plugins.py').write_text('raise Exception("DO NOT LOAD")')
        with self.assertRaises(PermissionError):
            asyncio.run(query('fs_write', {'project': 'workspace', 'path': 'x', 'content': 'x'}))
        with self.assertRaises(ValueError):
            asyncio.run(command('eval', {'text': 'anything'}))
        with self.assertRaises(TypeError):
            asyncio.run(query('fs_list', {'unexpected': True}))
        with self.assertRaises(ValueError):
            asyncio.run(command('fs_write', {'content': 'x' * (128 * 1024)}))
        result = asyncio.run(command('fs_write', {'project': 'workspace', 'path': 'dispatched.txt', 'content': 'written'}))
        self.assertEqual(result['operation'], 'fs_write')
        self.assertEqual((self.workspace / 'dispatched.txt').read_text(), 'written')

    def test_uninstalled_restart_does_not_spawn(self):
        with patch.object(maintenance.subprocess, 'Popen') as spawn:
            result = self.tools['restart_server']()
        self.assertEqual(result['status'], 'not_installed')
        spawn.assert_not_called()

    def test_wrappers_obey_the_same_installed_feature_flags(self):
        from mac_control import dev_enabled_operations as enabled
        (self.data / 'feature_flags.json').write_text(json.dumps({
            'watcher': False, 'native_gui': False, 'background_browser': False,
        }))
        with patch.dict(os.environ, {'MAC_CONTROL_DATA_ROOT': str(self.data)}), \
             patch.object(enabled, 'DATA_ROOT', self.data):
            names = {x['name'] for x in asyncio.run(self.tools['custom_query']())['operations']}
            self.assertIn('fs_read', names)
            for name in ('gui_screenshot', 'watcher_status', 'chrome_chat_read'):
                self.assertNotIn(name, names)
                with self.assertRaises(ValueError):
                    asyncio.run(self.tools['custom_command'](name))

    def test_shipped_helper_import_works_outside_release_working_directory(self):
        environment = dict(os.environ)
        environment['PYTHONPATH'] = os.pathsep.join((str(maintenance.RELEASE_ROOT / 'src'),
                                                    str(maintenance.RELEASE_ROOT / 'scripts')))
        result = subprocess.run([sys.executable, '-P', '-B', '-c',
            'from mac_control.maintenance_ops import _service_helper; '
            'assert _service_helper().LABEL == "org.maccontrol.mcpserver.remote"'],
            cwd=self.root, env=environment, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_owned_service_checks_exact_plist_and_preserves_foreign_job(self):
        from scripts import setup_remote_service as service
        marker = self.root / '.mac-control-installer-owned'
        marker.write_text('owned')
        release = self.root / 'releases/test'
        (release / 'bin').mkdir(parents=True)
        launcher = release / 'bin/mac-control-remote-mcp.sh'
        launcher.write_text('# fixture')
        launcher.chmod(0o700)
        helper = release / 'scripts/setup_remote_service.py'
        helper.parent.mkdir()
        helper.write_text('# fixture')
        (self.root / 'current').symlink_to(release)
        self.data.chmod(0o700)
        self.logs.chmod(0o700)
        with patch.object(maintenance, '_service_helper', return_value=service), \
             patch.object(maintenance, 'RELEASE_ROOT', release), \
             patch.object(service.sys, 'platform', 'darwin'), \
             patch.object(service.os, 'geteuid', return_value=501), \
             patch.object(service.Path, 'home', return_value=self.root):
            _, plist, expected = service._layout(self.root, None)
            plist.parent.mkdir(parents=True)
            plist.write_bytes(plistlib.dumps(expected))
            plist.chmod(0o600)
            stdout = ('path = ' + str(plist) + '\nprogram = ' + expected['ProgramArguments'][0]
                      + '\nstate = running\npid = 1234\n')
            with patch.object(service, '_launchctl', return_value=subprocess.CompletedProcess([], 0, stdout, '')) as launch:
                source, state = maintenance._owned_service()
                self.assertEqual(source, helper)
                self.assertEqual(state['pid'], '1234')
                self.assertEqual(launch.call_args.args[0], 'print')
            with patch.object(service, '_launchctl', return_value=subprocess.CompletedProcess([], 0,
                    stdout.replace(expected['ProgramArguments'][0], '/foreign/service'), '')):
                with self.assertRaises(RuntimeError):
                    maintenance._owned_service()

    def test_restart_uses_verified_owned_helper_only(self):
        helper = self.root / 'releases/r1/scripts/setup_remote_service.py'
        helper.parent.mkdir(parents=True)
        helper.write_text('# shipped fixture\n')
        with patch.object(maintenance, '_owned_service', return_value=(helper, {'status': 'running'})), \
             patch.object(maintenance.subprocess, 'Popen') as spawn:
            result = self.tools['restart_server']()
        self.assertEqual(result['status'], 'restart_scheduled')
        argv = spawn.call_args.args[0]
        self.assertIn('mac_control.maintenance_ops', argv)
        self.assertIn('--restart-worker', argv)
        self.assertEqual(argv[-1], str(self.root))
        self.assertTrue(spawn.call_args.kwargs['start_new_session'])


if __name__ == '__main__':
    unittest.main()
