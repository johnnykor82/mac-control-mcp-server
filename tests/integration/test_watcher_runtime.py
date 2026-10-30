"""Portable Watcher contracts; all work stays in temporary local files."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'src'
URL = 'https://chatgpt.com/c/11111111-1111-1111-1111-111111111111'
EXECUTOR = 'https://chatgpt.com/c/22222222-2222-2222-2222-222222222222'
sys.path.insert(0, str(SOURCE))


class WatcherRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.core = importlib.import_module('mac_control.watcher_runtime.multi_project_watcher')
        self.files = importlib.import_module('mac_control.watcher_runtime.watcher_file_runtime')
        self.schedule = importlib.import_module('mac_control.watcher_runtime.watcher_schedule_store')
        self.adapter = importlib.import_module('mac_control.watcher_runtime.watcher_http_adapter')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name) / 'run' / 'watcher'
        for name, value in [('RUNTIME', root), ('DBFILE', root / 'watcher.sqlite3'), ('RESULTS', root / 'results')]:
            patcher = patch.object(self.core, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.db = self.core.connect()
        self.addCleanup(self.db.close)
        self.adapter.setup(self.db)
        self.core.register_project(self.db, 'project-one', URL)

    def test_file_capabilities_and_immutable_report(self):
        result = self.files.register(self.db, 'project-one', 'task-one', EXECUTOR)
        with self.assertRaises(PermissionError):
            self.files.submit(self.db, 'project-one', 'task-one', 1, 'completed', 'Report', result['orchestrator_token'])
        self.files.submit(self.db, 'project-one', 'task-one', 1, 'completed', 'Report', result['submission_token'])
        self.files.reconcile(self.db)
        read = self.files.read_report(self.db, 'project-one', 'task-one', 1)
        self.assertEqual(read['text'], 'Report')
        with self.assertRaises(ValueError):
            self.files.submit(self.db, 'project-one', 'task-one', 1, 'completed', 'Changed', result['submission_token'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0], 1)

    def test_schedule_is_durable_and_idempotent(self):
        first = self.schedule.schedule(self.db, URL, 1, 'Verify result', 'request-one')
        again = self.schedule.schedule(self.db, URL, 1, 'Verify result', 'request-one')
        self.assertEqual(first['id'], again['id'])
        self.assertTrue(again['duplicate'])
        self.assertEqual(len(self.schedule.due_to_deliveries(self.db, first['due_at'] + 1)), 1)
        self.assertEqual(self.schedule.due_to_deliveries(self.db, first['due_at'] + 2), [])
        payload = self.db.execute('SELECT payload FROM deliveries').fetchone()[0]
        self.assertNotIn('/Users/openclaw', payload)

    def test_followup_queue_idempotency(self):
        module = importlib.import_module('mac_control.watcher_runtime.watcher_browser_followups')
        self.core.register_task(self.db, 'project-one', 'task-one', EXECUTOR)
        self.db.execute("UPDATE tasks SET state='completed'")
        self.db.execute("INSERT INTO chatbridge_task_sessions VALUES('project-one','task-one','session-one')")
        prompt = 'Review this result and address the remaining acceptance criteria.'
        first = module.enqueue(self.db, 'project-one', 'task-one', prompt, 'followup-one')
        again = module.enqueue(self.db, 'project-one', 'task-one', prompt, 'followup-one')
        self.assertEqual(first['revision'], again['revision'])
        self.assertTrue(again['duplicate'])
        with self.assertRaises(ValueError):
            module.enqueue(self.db, 'project-one', 'task-one', prompt + ' Change.', 'followup-one')

    def test_idle_http_cycle_never_opens_network(self):
        with patch.object(self.adapter, 'api', side_effect=AssertionError('Unexpected network')):
            self.assertEqual(self.adapter.iteration(self.db), [])

    def test_idle_cli_once_never_opens_network(self):
        from contextlib import redirect_stdout
        import io
        with patch.object(self.core, 'connect', return_value=self.db), \
             patch.object(self.adapter.sys, 'argv', ['watcher', 'once']), \
             patch.object(self.adapter, 'api', side_effect=AssertionError('Unexpected network')), \
             patch.object(self.adapter.telemetry, 'maybe_sample', side_effect=AssertionError('Idle sample')), \
             redirect_stdout(io.StringIO()) as output:
            self.adapter.main()
        self.assertEqual(output.getvalue().strip(), '{"events": []}')

    def test_gateway_rejects_remote_and_url_credentials(self):
        config = importlib.import_module('mac_control.watcher_runtime.config')
        for url in ['http://example.com:8787', 'http://user:secret@127.0.0.1:8787', 'http://127.0.0.1:8787/path']:
            with self.assertRaises(ValueError):
                config.validate_gateway(url)
        self.assertEqual(config.validate_gateway('http://127.0.0.1:8787'), 'http://127.0.0.1:8787')

    def test_marker_cache_reuses_verified_identity(self):
        resolver = importlib.import_module('mac_control.watcher_runtime.watcher_chat_resolver')
        marker = 'WATCHER-CHAT-' + 'a' * 32
        response = {'chat_url': URL, 'evidence_verified': True,
                    'verification': 'user_message', 'matches': 1}
        with patch.object(self.adapter, 'api', return_value=response) as api:
            self.assertFalse(resolver.resolve(marker, db=self.db)['cached'])
            self.assertTrue(resolver.resolve(marker, db=self.db)['cached'])
            self.assertEqual(api.call_count, 1)

    def test_paused_project_retains_scheduled_check(self):
        first = self.schedule.schedule(self.db, URL, 1, 'Verify result', 'request-one')
        self.db.execute("UPDATE projects SET status='paused'")
        self.assertEqual(self.schedule.due_to_deliveries(self.db, first['due_at'] + 1), [])
        self.assertEqual(self.schedule.detail(self.db, first['id'])['state'], 'scheduled')

    def test_state_refuses_symlink_and_public_permissions(self):
        self.db.close()
        self.core.RUNTIME.chmod(0o755)
        with self.assertRaises(PermissionError):
            self.core.connect()
        self.core.RUNTIME.chmod(0o700)
        self.core.DBFILE.chmod(0o644)
        with self.assertRaises(PermissionError):
            self.core.connect()
        self.core.DBFILE.chmod(0o600)
        self.core.DBFILE.unlink()
        other = Path(self.temp.name) / 'other.sqlite3'
        other.touch(mode=0o600)
        self.core.DBFILE.symlink_to(other)
        with self.assertRaises(PermissionError):
            self.core.connect()

    def test_http_errors_do_not_echo_gateway_body(self):
        import io
        from urllib.error import HTTPError
        error = HTTPError('http://127.0.0.1', 500, 'fail', {}, io.BytesIO(b'private-report-and-token'))
        with patch.object(self.adapter._HTTP, 'open', side_effect=error):
            with self.assertRaises(self.adapter.TransportError) as exc:
                self.adapter.api('GET', '/v1/system/status')
        self.assertNotIn('private-report-and-token', str(exc.exception))

    def test_delivery_reconciliation_does_not_repeat_send(self):
        wake = self.schedule.schedule(self.db, URL, 1, 'Verify result', 'request-one')
        self.schedule.due_to_deliveries(self.db, wake['due_at'] + 1)
        calls = []
        def fake(method, route, payload=None):
            calls.append((method, route, payload))
            if route == '/v1/sessions':
                return {'session_id': 'session-one'}
            if route == '/v1/sessions/session-one':
                return {'session_id': 'session-one', 'mode': 'standard',
                        'conversation_id': URL.rsplit('/', 1)[1], 'project_id': None}
            if route.endswith('/messages'):
                return {'request_id': 'request-one', 'status': 'queued'}
            if route == '/v1/requests/request-one':
                return {'status': 'completed'}
            raise AssertionError(route)
        with patch.object(self.adapter, 'api', side_effect=fake), patch.object(self.adapter, 'marker_already_present', return_value=False):
            delivery = self.db.execute('SELECT * FROM deliveries').fetchone()
            self.adapter.process_one(self.db, delivery)
            delivery = self.db.execute('SELECT * FROM deliveries').fetchone()
            result = self.adapter.process_one(self.db, delivery)
        self.assertEqual(result['state'], 'delivered')
        sends = [c for c in calls if c[0] == 'POST' and c[1].endswith('/messages')]
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0][2]['client_request_id'], 'watcher-delivery-' + wake['id'])

    def test_delivery_refuses_rebound_cached_and_new_sessions(self):
        wake = self.schedule.schedule(self.db, URL, 1, 'Verify result', 'request-one')
        self.schedule.due_to_deliveries(self.db, wake['due_at'] + 1)
        delivery = self.db.execute('SELECT * FROM deliveries').fetchone()
        good = {'session_id': 'session-one', 'mode': 'standard',
                'conversation_id': URL.rsplit('/', 1)[1], 'project_id': None}
        for cached in (False, True):
            for field, wrong in [('session_id', 'other-session'),
                                 ('conversation_id', EXECUTOR.rsplit('/', 1)[1]),
                                 ('project_id', 'g-p-' + 'a' * 32)]:
                with self.subTest(cached=cached, field=field):
                    self.db.execute('DELETE FROM chatbridge_delivery_links')
                    if cached:
                        self.db.execute("INSERT INTO chatbridge_delivery_links(delivery_id,session_id) VALUES(?,?)",
                                        (delivery['id'], 'session-one'))
                    def fake(method, route, payload=None):
                        if method == 'POST' and route == '/v1/sessions':
                            return {'session_id': 'session-one'}
                        if method == 'GET' and route == '/v1/sessions/session-one':
                            return {**good, field: wrong}
                        raise AssertionError('Unexpected action: ' + method + ' ' + route)
                    with patch.object(self.adapter, 'api', side_effect=fake):
                        with self.assertRaises(self.adapter.TransportError):
                            self.adapter.process_one(self.db, delivery)

    def test_rotation_between_identity_read_and_guard_is_rejected(self):
        wake = self.schedule.schedule(self.db, URL, 1, 'Verify result', 'request-one')
        self.schedule.due_to_deliveries(self.db, wake['due_at'] + 1)
        delivery = self.db.execute('SELECT * FROM deliveries').fetchone()
        guarded = False
        def fake(method, route, payload=None):
            nonlocal guarded
            if route == '/v1/sessions':
                return {'session_id': 'session-one'}
            if method == 'GET' and route == '/v1/sessions/session-one':
                return {'session_id': 'session-one', 'mode': 'persistent',
                        'conversation_id': (EXECUTOR if guarded else URL).rsplit('/', 1)[1],
                        'project_id': None}
            if method == 'PUT':
                guarded = True
                return {'session_id': 'session-one', 'owner': 'watcher',
                        'guard_id': route.rsplit('/', 1)[1]}
            raise AssertionError('Unexpected action ' + route)
        with patch.object(self.adapter, 'api', side_effect=fake):
            with self.assertRaises(self.adapter.TransportError):
                self.adapter.process_one(self.db, delivery)

    def test_executor_refuses_rebound_session_and_wrong_turn(self):
        self.core.register_task(self.db, 'project-one', 'task-one', EXECUTOR)
        self.db.execute("INSERT INTO chatbridge_task_sessions VALUES('project-one','task-one','session-one')")
        good = {'session_id': 'session-one', 'mode': 'persistent',
                'conversation_id': EXECUTOR.rsplit('/', 1)[1], 'project_id': None}
        for drift in ('session', 'turn'):
            with self.subTest(drift=drift):
                self.db.execute('DELETE FROM chatbridge_external_poll_budget')
                def fake(method, route, payload=None):
                    if route == '/v1/sessions/session-one':
                        return {**good, 'conversation_id': URL.rsplit('/', 1)[1]} if drift == 'session' else good
                    if route.startswith('/v1/sessions?'):
                        return {'data': []}
                    if route == '/v1/system/status':
                        return {'rate_limit': {}}
                    if route.endswith('/turn-state'):
                        return {**good, 'conversation_id': URL.rsplit('/', 1)[1],
                                'completed': True, 'content': 'Wrong chat report'}
                    raise AssertionError(route)
                with patch.object(self.adapter, 'api', side_effect=fake), \
                     patch.object(self.core, 'completion_test', side_effect=AssertionError('Wrong result accepted')):
                    events = self.adapter.poll_executor_tasks(self.db)
                self.assertEqual(events[0]['state'], 'deferred')
                self.assertEqual(self.db.execute('SELECT state FROM tasks').fetchone()[0], 'watching')
                self.assertEqual(self.db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0], 0)

    def test_cli_works_without_playwright_and_uses_isolated_root(self):
        env = {**os.environ, 'MAC_CONTROL_DATA_ROOT': self.temp.name, 'PYTHONPATH': str(SOURCE)}
        code = "import sys; sys.modules['playwright']=None; import runpy; sys.argv=['watcher','status']; runpy.run_module('mac_control.watcher_runtime',run_name='__main__')"
        proc = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn('"ok": true', proc.stdout)
        self.assertTrue((Path(self.temp.name) / 'run/watcher/watcher.sqlite3').is_file())


if __name__ == '__main__':
    unittest.main()
