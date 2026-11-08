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
        user_reports=Path(self.temp.name).resolve()/"AgentWorkspace/artifacts/watcher-reports"
        report_patch=patch.object(self.files,"_reports_root",return_value=user_reports)
        report_patch.start()
        self.addCleanup(report_patch.stop)
        browser_reports=Path(self.temp.name).resolve()/"AgentWorkspace/artifacts/watcher-results"
        browser_patch=patch.object(self.core,"_results_root",return_value=browser_reports)
        browser_patch.start()
        self.addCleanup(browser_patch.stop)
        self.db = self.core.connect()
        self.addCleanup(self.db.close)
        self.adapter.setup(self.db)
        self.core.register_project(self.db, 'project-one', URL)

    def test_file_dispatch_tracks_unconfirmed_send_and_hides_capability_hashes(self):
        import hashlib,json
        self.files.register(self.db,'project-one','task-one',EXECUTOR)
        before=self.core.summary(self.db,'project-one')
        self.assertEqual(before['file_dispatches'][0]['state'],'registered')
        self.assertNotIn('submit_capability_hash',json.dumps(before))
        digest=hashlib.sha256(b'harmless smoke task').hexdigest()
        first=self.files.record_dispatch(self.db,'project-one','task-one',
              'smoke-request-001',digest,'prepare')
        self.assertEqual(first['state'],'prepared')
        duplicate=self.files.record_dispatch(self.db,'project-one','task-one',
              'smoke-request-001',digest,'prepare')
        self.assertTrue(duplicate['duplicate'])
        with self.assertRaises(ValueError):
            self.files.record_dispatch(self.db,'project-one','task-one',
                 'smoke-request-001',hashlib.sha256(b'changed').hexdigest(),'prepare')
        self.files.record_dispatch(self.db,'project-one','task-one',
             'smoke-request-001',digest,'failed',error_code='platform_tool_blocked')
        self.assertEqual(self.core.summary(self.db)['file_dispatches'][0]['state'],'failed')
        with self.assertRaises(ValueError):
            self.files.record_dispatch(self.db,'project-one','task-one',
                 'new-attempt-001',digest,'prepare')

    def test_dispatch_queued_ack_is_idempotent_without_duplicate_requeue(self):
        import hashlib
        self.files.register(self.db,'project-one','task-one',EXECUTOR)
        digest=hashlib.sha256(b'harmless message').hexdigest()
        self.files.record_dispatch(self.db,'project-one','task-one','job-request-001',digest,'prepare')
        self.files.record_dispatch(self.db,'project-one','task-one','job-request-001',digest,'queued',request_id='chatbridge-request-001')
        result=self.files.record_dispatch(self.db,'project-one','task-one','job-request-001',digest,'queued',request_id='chatbridge-request-001')
        self.assertTrue(result['duplicate'])
        with self.assertRaises(ValueError):
            self.files.record_dispatch(self.db,'project-one','task-one','job-request-001',digest,'queued',request_id='different-request-001')
        with self.assertRaises(ValueError):
            self.files.recover_failed_dispatch(self.db,'project-one','task-one',
                 'job-request-001',owner_confirmed=True)

    def test_recovery_rotates_capability_only_after_failed_unsent_attempt(self):
        import hashlib
        original=self.files.register(self.db,'project-one','task-one',EXECUTOR)
        digest=hashlib.sha256(b'harmless smoke task').hexdigest()
        self.files.record_dispatch(self.db,'project-one','task-one','failed-job-001',digest,'prepare')
        self.files.record_dispatch(self.db,'project-one','task-one','failed-job-001',digest,'failed',error_code='platform_tool_blocked')
        with self.assertRaises(PermissionError):
            self.files.recover_failed_dispatch(self.db,'project-one','task-one',
                'failed-job-001',owner_confirmed=False)
        renewed=self.files.recover_failed_dispatch(self.db,'project-one','task-one',
                'failed-job-001',owner_confirmed=True)
        self.assertNotEqual(original['submission_token'],renewed['submission_token'])
        self.assertNotEqual(original['orchestrator_token'],renewed['orchestrator_token'])
        self.assertEqual(self.core.summary(self.db)['file_dispatches'][0]['state'],'registered')
        with self.assertRaises(PermissionError):
            self.files.submit(self.db,'project-one','task-one',1,'completed','Report',original['submission_token'])
        self.files.submit(self.db,'project-one','task-one',1,'completed','Report',renewed['submission_token'])
        self.files.reconcile(self.db)
        self.assertEqual(self.files.read_report(self.db,'project-one','task-one',1)['text'],'Report')
        self.assertEqual(self.core.summary(self.db)['file_dispatches'][0]['state'],'reported')
        with self.assertRaises(ValueError):
            self.files.recover_failed_dispatch(self.db,'project-one','task-one','failed-job-001',owner_confirmed=True)

    def test_stale_prepared_dispatch_distinguished_from_running_task(self):
        import hashlib,time
        self.files.register(self.db,'project-one','task-one',EXECUTOR)
        digest=hashlib.sha256(b'harmless smoke task').hexdigest()
        self.files.record_dispatch(self.db,'project-one','task-one','stale-job-001',digest,'prepare')
        self.db.execute('UPDATE file_task_dispatch SET updated_ts=?',(time.time()-1000,))
        data=self.core.summary(self.db)
        self.assertEqual(data['file_dispatches'][0]['display_state'],'uncertain')
        self.assertEqual(data['tasks'][0]['state'],'watching')
        self.assertEqual(data['tasks'][0]['dispatch_state'],'uncertain')

    def test_two_executors_failed_dispatch_recovery_report_hash_ack_and_restart(self):
        import hashlib
        first=self.files.register(self.db,'project-one','task-one',EXECUTOR)
        another='https://chatgpt.com/c/33333333-3333-3333-3333-333333333333'
        second=self.files.register(self.db,'project-one','task-two',another)
        a=hashlib.sha256(b'executor A task').hexdigest()
        b=hashlib.sha256(b'executor B task').hexdigest()
        self.files.record_dispatch(self.db,'project-one','task-one','request-exec-A',a,'prepare')
        self.files.record_dispatch(self.db,'project-one','task-one','request-exec-A',a,
                                   'failed',error_code='platform_tool_blocked')
        self.files.record_dispatch(self.db,'project-one','task-two','request-exec-B',b,'prepare')
        self.files.record_dispatch(self.db,'project-one','task-two','request-exec-B',b,
                                   'queued',request_id='request-from-chatbridge-B')
        new=self.files.recover_failed_dispatch(self.db,'project-one','task-one',
                                               'request-exec-A',owner_confirmed=True)
        with self.assertRaises(PermissionError):
            self.files.submit(self.db,'project-one','task-one',1,'completed','A report',
                              first['submission_token'])
        with self.assertRaises(PermissionError):
            self.files.submit(self.db,'project-one','task-two',1,'completed','B report',
                              new['submission_token'])
        self.files.submit(self.db,'project-one','task-one',1,'completed','A report',
                          new['submission_token'])
        self.files.submit(self.db,'project-one','task-two',1,'completed','B report',
                          second['submission_token'])
        events=self.files.reconcile(self.db)
        self.assertEqual(len(events),2)
        self.assertTrue(all(x['queued'] for x in events))
        for name,body in [('task-one','A report'),('task-two','B report')]:
            report=self.files.read_report(self.db,'project-one',name,1)
            self.assertEqual(report['text'],body)
            self.assertEqual(report['sha256'],hashlib.sha256(body.encode()).hexdigest())
        records=self.db.execute('SELECT id FROM deliveries ORDER BY id').fetchall()
        self.assertEqual(len(records),2)
        self.db.execute("UPDATE deliveries SET state='delivered', delivered_at=?",
                        (self.core.utc(),))
        for record in records:
            ack=self.core.acknowledge_delivery(self.db,'project-one',record['id'])
            self.assertTrue(ack['acknowledged'])
        self.db.close()
        self.db=self.core.connect()
        self.addCleanup(self.db.close)
        self.assertEqual(len(self.core.summary(self.db)['file_dispatches']),2)
        self.assertTrue(all(x['state']=='reported' for x in self.core.summary(self.db)['file_dispatches']))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM deliveries WHERE acknowledged_at IS NOT NULL').fetchone()[0],2)
        self.assertEqual(self.files.reconcile(self.db),[])

    def test_recovery_refuses_already_written_unindexed_report(self):
        import hashlib
        self.files.register(self.db,'project-one','task-one',EXECUTOR)
        digest=hashlib.sha256(b'task').hexdigest()
        self.files.record_dispatch(self.db,'project-one','task-one','refused-job-001',digest,'prepare')
        self.files.record_dispatch(self.db,'project-one','task-one','refused-job-001',digest,
                                   'failed',error_code='platform_tool_blocked')
        report_dir=self.files._reports_root()/'project-one'/'task-one'
        report_dir.mkdir(parents=True,mode=0o700)
        (report_dir/'000001.md').write_text('already submitted')
        with self.assertRaises(ValueError):
            self.files.recover_failed_dispatch(self.db,'project-one','task-one',
                                               'refused-job-001',owner_confirmed=True)

    def test_existing_file_report_migration_distinguishes_reported(self):
        self.files.register(self.db,'project-one','task-one',EXECUTOR)
        self.db.execute("UPDATE tasks SET last_revision=1 WHERE id='task-one'")
        self.db.execute("DELETE FROM file_task_dispatch WHERE task_id='task-one'")
        self.files.setup(self.db)
        record=self.db.execute('SELECT state FROM file_task_dispatch').fetchone()
        self.assertEqual(record['state'],'reported')

    def test_submit_auth_and_report_write_are_atomic_against_recovery(self):
        token=self.files.register(self.db,'project-one','task-one',EXECUTOR)
        original=self.files._directory
        def inspect_transaction(*args,**kwargs):
            self.assertTrue(self.db.in_transaction,
                            'Capability auth must be serialized with report write')
            return original(*args,**kwargs)
        with patch.object(self.files,'_directory',side_effect=inspect_transaction):
            result=self.files.submit(self.db,'project-one','task-one',1,
                                     'completed','Atomic report',token['submission_token'])
        self.assertTrue(result['accepted'])
        self.assertFalse(self.db.in_transaction)
        self.files.reconcile(self.db)
        self.assertEqual(self.files.read_report(self.db,'project-one','task-one',1)['text'],
                         'Atomic report')

    def test_failed_dispatch_history_survives_recovery_without_token_leak(self):
        import hashlib,json
        cap=self.files.register(self.db,'project-one','task-one',EXECUTOR)
        digest=hashlib.sha256(b'harmless task').hexdigest()
        self.files.record_dispatch(self.db,'project-one','task-one',
            'audit-request-001',digest,'prepare')
        self.files.record_dispatch(self.db,'project-one','task-one',
            'audit-request-001',digest,'failed',error_code='platform_tool_blocked')
        renewed=self.files.recover_failed_dispatch(self.db,'project-one','task-one',
            'audit-request-001',owner_confirmed=True)
        status=self.core.summary(self.db)
        self.assertEqual(status['file_dispatches'][0]['state'],'registered')
        events=status['file_dispatch_events']
        self.assertEqual([item['event'] for item in events],
                         ['prepared','failed','recovered'])
        self.assertEqual(events[1]['error_code'],'platform_tool_blocked')
        encoded=json.dumps(status)
        for secret in (cap['submission_token'],cap['orchestrator_token'],
                       renewed['submission_token'],renewed['orchestrator_token']):
            self.assertNotIn(secret,encoded)
        self.assertNotIn(digest,encoded)

    def test_concurrent_identical_dispatch_receipt_is_idempotent(self):
        import hashlib,sqlite3,threading,concurrent.futures
        self.files.register(self.db,'project-one','task-one',EXECUTOR)
        digest=hashlib.sha256(b'harmless task').hexdigest()
        barrier=threading.Barrier(3)
        def worker(_):
            db=sqlite3.connect(self.core.DBFILE,timeout=8,isolation_level=None)
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA busy_timeout=8000')
            try:
                barrier.wait(timeout=5)
                return self.files.record_dispatch(db,'project-one','task-one',
                          'race-request-001',digest,'prepare')
            finally:db.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(worker,i) for i in range(2)]
            barrier.wait(timeout=5)
            results=[job.result(timeout=8) for job in jobs]
        self.assertEqual(sorted(r['duplicate'] for r in results),[False,True])
        history=self.core.summary(self.db)['file_dispatch_events']
        self.assertEqual([row['event'] for row in history],['prepared'])

    def test_file_capabilities_and_immutable_report(self):
        result = self.files.register(self.db, 'project-one', 'task-one', EXECUTOR)
        with self.assertRaises(PermissionError):
            self.files.submit(self.db, 'project-one', 'task-one', 1, 'completed', 'Report', result['orchestrator_token'])
        self.files.submit(self.db, 'project-one', 'task-one', 1, 'completed', 'Report', result['submission_token'])
        self.files.reconcile(self.db)
        read = self.files.read_report(self.db, 'project-one', 'task-one', 1)
        self.assertEqual(read['text'], 'Report')
        self.assertTrue(self.files._reports_root().joinpath(
            'project-one','task-one','000001.md').is_file())
        self.assertFalse((self.core.RUNTIME/'inbox').exists())
        with self.assertRaises(ValueError):
            self.files.submit(self.db, 'project-one', 'task-one', 1, 'completed', 'Changed', result['submission_token'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0], 1)

    def test_legacy_file_report_is_read_after_upgrade_without_moving(self):
        import hashlib,json
        result=self.files.register(self.db,"project-one","old-task",EXECUTOR)
        old=self.core.RUNTIME/"inbox/project-one/old-task"
        old.mkdir(parents=True)
        content=b"Legacy report preserved"
        digest=hashlib.sha256(content).hexdigest()
        (old/"000001.md").write_bytes(content)
        (old/"000001.md").chmod(0o600)
        (old/"000001.ready.json").write_text(json.dumps({
            "schema":1,"project":"project-one","task":"old-task","revision":1,
            "status":"completed","sha256":digest,"bytes":len(content)}))
        (old/"000001.ready.json").chmod(0o600)
        self.files.reconcile(self.db)
        read=self.files.read_report(self.db,"project-one","old-task",1)
        self.assertEqual(read["text"],content.decode())
        self.assertEqual(read["sha256"],digest)
        self.assertTrue((old/"000001.md").exists())

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
        owned = importlib.import_module('mac_control.watcher_runtime.watcher_browser_dispatch')
        owned.register_owned_project(self.db, 'owned-browser',
            'https://chatgpt.com/c/33333333-3333-4333-8333-333333333333', '123')
        self.core.register_task(self.db, 'owned-browser', 'task-one', EXECUTOR)
        self.db.execute("UPDATE tasks SET state='completed' WHERE project_id='owned-browser'")
        self.db.execute("INSERT INTO chatbridge_task_sessions VALUES('owned-browser','task-one','session-one')")
        prompt = 'Review this result and address the remaining acceptance criteria.'
        first = module.enqueue(self.db, 'owned-browser', 'task-one', prompt, 'followup-one')
        again = module.enqueue(self.db, 'owned-browser', 'task-one', prompt, 'followup-one')
        self.assertEqual(first['revision'], again['revision'])
        self.assertTrue(again['duplicate'])
        goal=self.db.execute("SELECT state FROM goals WHERE project_id='owned-browser'").fetchone()
        self.assertEqual(goal[0], 'running')
        with self.assertRaises(ValueError):
            module.enqueue(self.db, 'owned-browser', 'task-one', prompt + ' Change.', 'followup-one')
        # A legacy browser project without verified owner is NOT an escape
        # hatch for unsupervised followup work.
        legacy_url='https://chatgpt.com/c/44444444-4444-4444-8444-444444444444'
        self.core.register_task(self.db, 'project-one', 'legacy-task', legacy_url)
        self.db.execute("UPDATE tasks SET state='completed' WHERE project_id='project-one'")
        self.db.execute("INSERT INTO chatbridge_task_sessions VALUES('project-one','legacy-task','legacy-session')")
        with self.assertRaises(PermissionError):
            module.enqueue(self.db, 'project-one', 'legacy-task', prompt, 'legacy-followup')

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
        marker = 'WC' + 'a' * 16
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
        from mac_control.workspace_config import set_root
        set_root(Path(self.temp.name), Path(self.temp.name) / "AgentWorkspace")
        env = {**os.environ, 'MAC_CONTROL_DATA_ROOT': self.temp.name, 'PYTHONPATH': str(SOURCE)}
        code = "import sys; sys.modules['playwright']=None; import runpy; sys.argv=['watcher','status']; runpy.run_module('mac_control.watcher_runtime',run_name='__main__')"
        proc = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn('"ok": true', proc.stdout)
        self.assertTrue((Path(self.temp.name) / 'run/watcher/watcher.sqlite3').is_file())


if __name__ == '__main__':
    unittest.main()
