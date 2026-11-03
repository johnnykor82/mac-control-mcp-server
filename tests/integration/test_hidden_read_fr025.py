"""FR-025.4: read hidden paths without loosening mutation or root boundaries."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mac_control import maintenance_ops as maintenance
from mac_control.legacy_handlers import fs_ops
from mac_control.workspace_config import set_root


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, **_kwargs):
        def register(callback):
            self.tools[callback.__name__] = callback
            return callback
        return register


class HiddenReadTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.data = self.root / 'data'
        self.workspace = self.root / 'workspace'
        self.data.mkdir()
        self.workspace.mkdir()
        set_root(self.data, self.workspace)
        self.addCleanup(patch.stopall)
        patch.object(maintenance, 'DATA_ROOT', self.data).start()
        patch.object(fs_ops, 'ROOT', self.data).start()
        patch.object(fs_ops, 'TRUSTED_CONFIG', self.data / 'allowed_projects.json').start()
        patch.object(fs_ops, 'RECOVERY', self.data / 'backups/fs_recovery').start()
        registry = Registry()
        fs_ops.register(registry)
        self.fs = registry.tools
        registry = Registry()
        maintenance.register(registry)
        self.maintenance = registry.tools
        self.plan = 'projects/repo/.planning/work/PLAN.md'
        document = self.workspace / self.plan
        document.parent.mkdir(parents=True)
        document.write_text('# Approved PLAN\nStep 1\n')
        for hidden in ('.git', '.venv', '.ssh'):
            folder = self.workspace / 'projects/repo' / hidden
            folder.mkdir()
            (folder / 'data.txt').write_text(f'inside {hidden}\n')
        (self.workspace / 'projects/repo/.env').write_text('fixture-only\n')

    def test_fs_read_hidden_plan_and_hidden_dotfiles(self):
        self.assertEqual(self.fs['fs_read']('workspace', self.plan)['lines'][0]['text'], '# Approved PLAN')
        for hidden in ('.git', '.venv', '.ssh'):
            path = f'projects/repo/{hidden}/data.txt'
            self.assertIn(hidden, self.fs['fs_read']('workspace', path)['lines'][0]['text'])
        self.assertEqual(self.fs['fs_read']('workspace', 'projects/repo/.env')['lines'][0]['text'], 'fixture-only')

    def test_fs_list_stat_search_in_hidden_paths(self):
        names = [item['name'] for item in self.fs['fs_list']('workspace', 'projects/repo')['entries']]
        for name in ('.planning', '.git', '.venv', '.ssh', '.env'):
            self.assertIn(name, names)
        self.assertIn('PLAN.md', [x['name'] for x in self.fs['fs_list']('workspace', 'projects/repo/.planning/work')['entries']])
        self.assertEqual(self.fs['fs_stat']('workspace', 'projects/repo/.env')['bytes'], len('fixture-only\n'))
        found = self.fs['fs_search']('workspace', 'Approved PLAN', 'projects/repo/.planning')
        self.assertEqual([x['file'] for x in found['matches']], [self.plan])

    def test_maintenance_read_file_and_list_workspace_hidden(self):
        self.assertTrue(self.maintenance['read_file']('workspace/' + self.plan)['ok'])
        self.assertTrue(self.maintenance['read_file'](str(self.workspace / self.plan))['ok'])
        result = self.maintenance['list_workspace']('workspace/projects/repo')
        self.assertIn('.planning', [item['name'] for item in result['entries']])
        nested = self.maintenance['list_workspace']('workspace/projects/repo/.planning')
        self.assertIn('work', [item['name'] for item in nested['entries']])

    def test_hidden_mutations_still_denied(self):
        for path in (self.plan, 'projects/repo/.env', 'projects/repo/.ssh/data.txt'):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                self.fs['fs_write']('workspace', path, 'blocked')
            with self.subTest(path=path), self.assertRaises(PermissionError):
                self.maintenance['write_file']('workspace/' + path, 'blocked')
        self.assertEqual((self.workspace / self.plan).read_text(), '# Approved PLAN\nStep 1\n')

    def test_other_hidden_mutations_remain_denied(self):
        src = 'projects/repo/.planning/work/PLAN.md'
        dst = 'projects/repo/new-plan.md'
        mutation_calls = (
            lambda: self.fs['fs_replace']('workspace', src, 'Step 1', 'Step 2', '0'*64),
            lambda: self.fs['fs_mkdir']('workspace', 'projects/repo/.private'),
            lambda: self.fs['fs_move']('workspace', src, dst),
            lambda: self.fs['fs_trash']('workspace', src, '0'*64),
            lambda: self.fs['fs_restore']('workspace', src, '123456789012-aaaaaaaaaa.bak'),
        )
        for action in mutation_calls:
            with self.subTest(action=action), self.assertRaises(PermissionError):
                action()
        self.assertTrue((self.workspace / src).is_file())
        self.assertFalse((self.workspace / dst).exists())

    def test_no_traversal_or_symlink_escape_for_read(self):
        external = self.root / 'outside.txt'
        external.write_text('private')
        (self.workspace / 'projects/repo/.planning/work/link.txt').symlink_to(external)
        for operation in ('fs_read', 'fs_stat'):
            with self.subTest(operation=operation), self.assertRaises(PermissionError):
                self.fs[operation]('workspace', 'projects/repo/.planning/work/link.txt')
        with self.assertRaises(ValueError):
            self.fs['fs_read']('workspace', '../outside.txt')
        with self.assertRaises(ValueError):
            self.fs['fs_read']('workspace', '/etc/passwd')


if __name__ == '__main__':
    unittest.main()
