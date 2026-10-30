"""Regression coverage for revisioned results and metadata-only audit monitoring."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mac_control.legacy_handlers import watcher_ops
from mac_control.watcher_runtime import multi_project_watcher as core
from mac_control.watcher_runtime import mcp_error_monitor as monitor

ORCHESTRATOR = 'https://chatgpt.com/c/11111111-1111-1111-1111-111111111111'
EXECUTOR = 'https://chatgpt.com/c/22222222-2222-2222-2222-222222222222'


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, **options):
        def store(fn):
            self.tools[fn.__name__] = fn
            return fn
        return store


class WatcherResultMonitorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.runtime = self.root / 'run/watcher'
        self.results = self.runtime / 'results'
        self.database = self.runtime / 'watcher.sqlite3'
        for module, name, value in (
            (core, 'ROOT', self.root),
            (core, 'RUNTIME', self.runtime),
            (core, 'DBFILE', self.database),
            (core, 'RESULTS', self.results),
            (watcher_ops, 'DB', self.database),
            (watcher_ops, 'RESULTS', self.results),
        ):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.db = core.connect()
        self.addCleanup(self.db.close)
        core.register_project(self.db, 'project-one', ORCHESTRATOR)
        core.register_task(self.db, 'project-one', 'task-one', EXECUTOR)
        registry = Registry()
        watcher_ops.register(registry)
        self.read_result = registry.tools['watcher_read_result']

    def completed_result(self, revision=0, text='Verified executor report'):
        self.db.execute('UPDATE tasks SET last_revision=?', (revision,))
        task = self.db.execute('SELECT * FROM tasks').fetchone()
        event = core.prepare_delivery(self.db, task, text)
        return Path(event['result_path']), hashlib.sha256(text.encode()).hexdigest()

    def test_initial_result_preserves_sha256(self):
        path, digest = self.completed_result(0)
        self.assertEqual(path.name, 'task-one.md')
        result = self.read_result('project-one', 'task-one')
        self.assertTrue(result['found'])
        self.assertEqual(result['text'], 'Verified executor report')
        self.assertEqual(result['sha256'], digest)
        self.assertEqual(hashlib.sha256(result['text'].encode()).hexdigest(), digest)

    def test_followup_result_reads_exact_revision_and_preserves_sha256(self):
        path, digest = self.completed_result(1, 'Followup revision report')
        self.assertEqual(path.name, 'task-one-r01.md')
        result = self.read_result('project-one', 'task-one')
        self.assertTrue(result['found'])
        self.assertEqual(result['text'], 'Followup revision report')
        self.assertEqual(result['sha256'], digest)

    def test_indexed_path_for_another_revision_is_rejected(self):
        path, _ = self.completed_result(1)
        other = path.with_name('task-one-r02.md')
        other.write_bytes(path.read_bytes())
        other.chmod(0o600)
        self.db.execute('UPDATE tasks SET result_path=?', (str(other),))
        with self.assertRaises(PermissionError):
            self.read_result('project-one', 'task-one')

    def test_symlinked_report_is_rejected(self):
        path, _ = self.completed_result(1)
        other = self.root / 'other.md'
        path.rename(other)
        path.symlink_to(other)
        with self.assertRaises(PermissionError):
            self.read_result('project-one', 'task-one')

    def test_modified_report_hash_is_rejected(self):
        path, _ = self.completed_result(1)
        path.write_text('Changed after completion')
        with self.assertRaisesRegex(RuntimeError, 'SHA256'):
            self.read_result('project-one', 'task-one')

    def test_metadata_only_exceptions_are_counted_without_queued_prompts(self):
        core.register_project(self.db, 'mac-control',
            'https://chatgpt.com/c/33333333-3333-3333-3333-333333333333')
        audit = self.root / 'audit.jsonl'
        audit.touch(mode=0o600)
        # Initialize the cursor before appending, so this exercises normal
        # monitoring rather than bootstrap mode (which never sends alerts).
        self.assertEqual(monitor.scan(self.db, log_path=audit)['new_errors'], 0)
        records = [{'event': 'tool_end', 'status': 'exception', 'tool': 'fs_write',
                    'id': str(index), 'duration_ms': 1.0} for index in range(6)]
        records.append({'event': 'tool_end', 'status': 'ok', 'tool': 'fs_read'})
        audit.write_text(''.join(json.dumps(record) + '\n' for record in records))
        result = monitor.scan(self.db, log_path=audit)
        self.assertEqual(result['new_errors'], 6)
        self.assertEqual(result['queued_alerts'], 0)
        issue = self.db.execute('SELECT category,severity,count FROM monitor_issues').fetchone()
        self.assertEqual(tuple(issue), ('unclassified', 'info', 6))
        self.assertEqual(self.db.execute('SELECT count(*) FROM monitor_alerts').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 0)
        self.assertEqual(monitor.scan(self.db, log_path=audit)['new_errors'], 0)


if __name__ == '__main__':
    unittest.main()
