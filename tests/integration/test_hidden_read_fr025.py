"""FR-025.4/FR-027: hidden paths support complete CRUD inside approved roots."""
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
        self.fs_recovery = self.data / 'backups/fs_recovery'
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

    def test_hidden_files_and_maintenance_write_have_full_crud(self):
        file = 'projects/repo/.gitignore'
        created = self.fs['fs_write']('workspace', file, '*.log\n')
        self.assertEqual(self.fs['fs_read']('workspace', file)['lines'][0]['text'], '*.log')
        replaced = self.fs['fs_replace']('workspace', file, '*.log', '*.tmp', created['sha256'])
        self.assertEqual(self.fs['fs_read']('workspace', file)['lines'][0]['text'], '*.tmp')
        result = self.maintenance['write_file']('workspace/' + file, 'one\n',
                                                replaced['sha256'])
        self.assertEqual(self.fs['fs_read']('workspace', file)['lines'][0]['text'], 'one')
        self.assertIsNotNone(result['backup'])
        # A dotfile at workspace root is no different from a nested dotfile.
        self.maintenance['write_file']('.gitignore', 'root\n')
        self.assertTrue((self.workspace / '.gitignore').is_file())
        for path in ('projects/repo/.env', 'projects/repo/.ssh/data.txt',
                     'projects/repo/.planning/work/PLAN.md'):
            old = self.fs['fs_read']('workspace', path)
            written = self.fs['fs_write']('workspace', path, 'edited\n',
                                           old['sha256'])
            self.assertIsNotNone(written['backup_id'])
            self.assertEqual(self.fs['fs_read']('workspace', path)['lines'][0]['text'], 'edited')

    def test_hidden_directory_lifecycle_is_recoverable_and_cas_protected(self):
        folder = 'projects/repo/.temporary'
        moved = 'projects/repo/.renamed'
        self.fs['fs_mkdir']('workspace', folder)
        self.fs['fs_write']('workspace', folder + '/.config', 'secret fixture')
        self.fs['fs_move']('workspace', folder, moved)
        self.assertFalse((self.workspace / folder).exists())
        self.assertTrue((self.workspace / moved / '.config').exists())
        original = self.fs['fs_stat']('workspace', moved)
        self.assertEqual(len(original['sha256']), 64)
        trashed = self.fs['fs_trash']('workspace', moved, original['sha256'])
        self.assertTrue(trashed['directory'])
        self.assertFalse((self.workspace / moved).exists())
        self.assertTrue((self.fs_recovery / trashed['backup_id']).is_dir())
        restored = self.fs['fs_restore']('workspace', moved, trashed['backup_id'])
        self.assertTrue(restored['directory'])
        self.assertEqual(self.fs['fs_read']('workspace', moved + '/.config')['lines'][0]['text'],
                         'secret fixture')

    def test_existing_dotgit_directory_can_be_trashed_and_restored(self):
        path = 'projects/repo/.git'
        sha = self.fs['fs_stat']('workspace', path)['sha256']
        result = self.fs['fs_trash']('workspace', path, sha)
        self.assertFalse((self.workspace / path).exists())
        self.fs['fs_restore']('workspace', path, result['backup_id'])
        self.assertTrue((self.workspace / path / 'data.txt').is_file())

    def test_hidden_file_trash_and_restore_preserve_content(self):
        path = 'projects/repo/.gitignore'
        original = self.fs['fs_write']('workspace', path, '__pycache__/\n')
        with self.assertRaises(ValueError):
            self.fs['fs_trash']('workspace', path, '0' * 64)
        self.assertTrue((self.workspace / path).is_file())
        saved = self.fs['fs_trash']('workspace', path, original['sha256'])
        self.assertFalse(saved['directory'])
        self.assertFalse((self.workspace / path).exists())
        restored = self.fs['fs_restore']('workspace', path, saved['backup_id'])
        self.assertEqual(restored['sha256'], original['sha256'])
        self.assertEqual((self.workspace / path).read_text(), '__pycache__/\n')

    def test_directory_symlink_entries_are_never_followed(self):
        outside = self.root / 'private.txt'
        outside.write_text('leave intact')
        folder = self.workspace / 'projects/repo/.hidden'
        folder.mkdir()
        (folder / 'external').symlink_to(outside)
        path = 'projects/repo/.hidden'
        sha = self.fs['fs_stat']('workspace', path)['sha256']
        removed = self.fs['fs_trash']('workspace', path, sha)
        self.assertFalse(folder.exists())
        self.assertEqual(outside.read_text(), 'leave intact')
        self.fs['fs_restore']('workspace', path, removed['backup_id'])
        self.assertTrue((folder / 'external').is_symlink())
        self.assertEqual(outside.read_text(), 'leave intact')

    def test_recovery_symlink_does_not_redirect_hidden_deletion(self):
        outside = self.root / 'untrusted-recovery'
        outside.mkdir()
        self.fs_recovery.parent.mkdir(parents=True)
        self.fs_recovery.symlink_to(outside, target_is_directory=True)
        file = 'projects/repo/.gitignore'
        content = self.fs['fs_write']('workspace', file, 'authorized')
        with self.assertRaises(PermissionError):
            self.fs['fs_trash']('workspace', file, content['sha256'])
        self.assertEqual((self.workspace / file).read_text(), 'authorized')
        self.assertEqual(list(outside.iterdir()), [])

    def test_directory_cas_prevents_stale_delete_and_overwrite(self):
        path = 'projects/repo/.planning'
        original = self.fs['fs_stat']('workspace', path)['sha256']
        (self.workspace / path / 'new.txt').write_text('after stat')
        with self.assertRaises(ValueError):
            self.fs['fs_trash']('workspace', path, original)
        with self.assertRaises((ValueError, PermissionError)):
            self.fs['fs_trash']('workspace', '.', original)
        with self.assertRaises(ValueError):
            self.fs['fs_move']('workspace', path, path + '/nested')
        sha = self.fs['fs_stat']('workspace', path)['sha256']
        trashed = self.fs['fs_trash']('workspace', path, sha)
        (self.workspace / path).mkdir()
        with self.assertRaises(FileExistsError):
            self.fs['fs_restore']('workspace', path, trashed['backup_id'])
        self.assertTrue((self.fs_recovery / trashed['backup_id']).is_dir())

    def test_hidden_paths_preserve_root_and_symlink_protection_for_writes(self):
        outside = self.root / 'external'
        outside.mkdir()
        (self.workspace / 'projects/repo/.planning/outbound').symlink_to(outside)
        for path in ('../.gitignore', '/tmp/.gitignore', 'projects/repo/.planning/outbound/file'):
            with self.subTest(path=path), self.assertRaises((ValueError, PermissionError)):
                self.fs['fs_write']('workspace', path, 'bad')
        self.assertEqual(list(outside.iterdir()), [])

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
