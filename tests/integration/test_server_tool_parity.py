"""Fixed stable registration snapshot, independent of any live installation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
# AST snapshot of server/admin/extensions registration closure, including
# dispatcher wrappers, nested command plugins and gui_tool decorator aliases.
STABLE_TOOLS = frozenset({
    'approved_commands',
    'audit_search',
    'audit_tail',
    'chrome_chat_adopt',
    'chrome_chat_archive',
    'chrome_chat_cleanup',
    'chrome_chat_new',
    'chrome_chat_read',
    'chrome_chat_restore',
    'chrome_chat_save',
    'chrome_chat_send',
    'chrome_chat_switch',
    'chrome_chat_ui_status',
    'chrome_chat_wait',
    'chrome_orchestrator_launch',
    'chrome_orchestrator_status',
    'custom_command',
    'custom_query',
    'execute_approved',
    'fs_list',
    'fs_mkdir',
    'fs_move',
    'fs_read',
    'fs_replace',
    'fs_restore',
    'fs_search',
    'fs_stat',
    'fs_trash',
    'fs_write',
    'git_branches',
    'git_commit',
    'git_create_branch',
    'git_diff',
    'git_fetch',
    'git_history',
    'git_pull_ff',
    'git_push',
    'git_stage',
    'git_status',
    'gui_displays',
    'gui_focus',
    'gui_mouse',
    'gui_open_app',
    'gui_press',
    'gui_request_permissions',
    'gui_screenshot',
    'gui_scroll',
    'gui_status',
    'gui_tree',
    'gui_type',
    'gui_wait_title',
    'gui_windows',
    'launchd_restart',
    'launchd_status',
    'list_workspace',
    'local_http_probe',
    'machine_health',
    'mcp_bridge_call',
    'mcp_bridge_list',
    'mcp_bridge_read',
    'mcp_diagnostics',
    'mcp_targets',
    'network_listeners',
    'package_capabilities',
    'package_install',
    'package_installed',
    'package_job_status',
    'process_snapshot',
    'project_roots',
    'project_task',
    'read_file',
    'read_service_log',
    'restart_server',
    'ssh_auth_diagnostics',
    'ssh_diagnostic',
    'ssh_exec',
    'ssh_identity_inspect',
    'ssh_open',
    'ssh_profile_approve_alias',
    'ssh_profile_inventory',
    'ssh_profile_register',
    'ssh_pty_open',
    'ssh_targets',
    'system_info',
    'terminal_access_configure',
    'terminal_capabilities',
    'terminal_close',
    'terminal_exec',
    'terminal_list',
    'terminal_open',
    'terminal_read',
    'terminal_resize',
    'terminal_send',
    'watcher_ack_delivery',
    'watcher_ack_wakeup',
    'watcher_cancel_wakeup',
    'watcher_error_status',
    'watcher_followup_browser_task',
    'watcher_get_wakeup',
    'watcher_guide',
    'watcher_list_wakeups',
    'watcher_pause_project',
    'watcher_read_report',
    'watcher_read_result',
    'watcher_register_file_task',
    'watcher_register_project',
    'watcher_register_task',
    'watcher_resolve_current_chat',
    'watcher_resume_project',
    'watcher_resume_task',
    'watcher_schedule_wakeup',
    'watcher_status',
    'watcher_submit_report',
    'write_file',
})


class ServerToolParityTests(unittest.TestCase):
    def test_installed_tool_parity_and_watcher_feature_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / 'home'
            data = Path(folder) / 'data'
            data.mkdir()
            helper = home / 'Applications/MacControlMCPServer.app/Contents/MacOS/MacControlMCPServer'
            helper.parent.mkdir(parents=True)
            helper.touch()
            flags = data / 'feature_flags.json'
            flags.write_text(json.dumps({'native_gui': True, 'background_browser': True,
                                         'background_native': False, 'watcher': True}))
            env = {**os.environ, 'HOME': str(home), 'MAC_CONTROL_DATA_ROOT': str(data),
                   'PYTHONPATH': str(ROOT / 'src') + os.pathsep + str(ROOT)}
            code = r"""
import asyncio, json
from scripts.dev_mcp_server import make_server
from mac_control import maintenance_ops
from mac_control.runtime_paths import DATA_ROOT

async def names():
    return sorted(tool.name for tool in await make_server(include_mutations=True).list_tools())

class Collector:
    def __init__(self): self.handlers = {}
    def tool(self, *args, **kwargs):
        def register(fn):
            self.handlers[kwargs.get('name', fn.__name__)] = fn
            return fn
        return register

full = asyncio.run(names())
collector = Collector()
maintenance_ops.register(collector)
help_result = asyncio.run(collector.handlers['custom_query']('help'))
assert any(row['name'] == 'watcher_status' for row in help_result['operations'])
flags = DATA_ROOT / 'feature_flags.json'
value = json.loads(flags.read_text()); value['watcher'] = False
flags.write_text(json.dumps(value))
disabled = asyncio.run(names())
assert not any(name.startswith('watcher_') for name in disabled)
for wrapper in ('custom_query', 'custom_command'):
    try:
        asyncio.run(collector.handlers[wrapper]('watcher_status', {}))
    except ValueError as exc:
        assert 'disabled' in str(exc)
    else:
        raise AssertionError('Disabled Watcher reachable through ' + wrapper)
print(json.dumps({'full': full, 'disabled': disabled}))
"""
            result = subprocess.run([sys.executable, '-c', code], env=env, cwd=ROOT,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads(result.stdout)
            full = set(report['full'])
            self.assertEqual(len(STABLE_TOOLS), 114)
            self.assertEqual(len(full), 122)
            self.assertFalse(STABLE_TOOLS - full, sorted(STABLE_TOOLS - full))
            self.assertIn('watcher_followup_browser_task', full)
            self.assertIn('custom_query', full)
            self.assertIn('custom_command', full)


if __name__ == '__main__':
    unittest.main()
