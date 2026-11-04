"""BF-20 simulated two-executor end-to-end without live ChatGPT calls."""
from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest
from mac_control.watcher_runtime import multi_project_watcher as legacy
from mac_control.watcher_runtime import watcher_browser_dispatch as dispatch
from mac_control.watcher_runtime.watcher_browser_followups import enqueue as enqueue_followup

CHAT1="https://chatgpt.com/c/11111111-1111-4111-8111-111111111111"
CHAT2="https://chatgpt.com/c/22222222-2222-4222-8222-222222222222"
CHAT3="https://chatgpt.com/c/33333333-3333-4333-8333-333333333333"

@pytest.fixture
def db(tmp_path,monkeypatch):
    con=sqlite3.connect(":memory:",isolation_level=None)
    con.row_factory=sqlite3.Row
    con.executescript("""CREATE TABLE projects(id TEXT PRIMARY KEY,
            orchestrator_url TEXT UNIQUE NOT NULL,status TEXT NOT NULL DEFAULT 'enabled',
            created_at TEXT NOT NULL);
        CREATE TABLE tasks(project_id TEXT NOT NULL,id TEXT NOT NULL,
            chat_url TEXT UNIQUE NOT NULL,state TEXT NOT NULL DEFAULT 'watching',
            mode TEXT NOT NULL DEFAULT 'browser',last_revision INTEGER DEFAULT 0,
            last_hash TEXT,stable_since REAL,last_text_size INTEGER DEFAULT 0,
            result_path TEXT,result_sha256 TEXT,complete_at TEXT,error TEXT,
            PRIMARY KEY(project_id,id));
        CREATE TABLE chatbridge_task_sessions(project_id TEXT,task_id TEXT,session_id TEXT,
            PRIMARY KEY(project_id,task_id));
        CREATE TABLE chatbridge_task_request_links(project_id TEXT,task_id TEXT,
            request_id TEXT,session_id TEXT,PRIMARY KEY(project_id,task_id));
        CREATE TABLE deliveries(id TEXT PRIMARY KEY,project_id TEXT,task_id TEXT,
            orchestrator_url TEXT,payload TEXT,state TEXT DEFAULT 'ready',
            attempts INTEGER DEFAULT 0,last_error TEXT,
            created_at TEXT,delivered_at TEXT,revision INTEGER,acknowledged_at TEXT);
        CREATE TABLE chatbridge_browser_followups(project_id TEXT,task_id TEXT,
            revision INTEGER,session_id TEXT,client_request_id TEXT UNIQUE,
            prompt TEXT,request_id TEXT,state TEXT,last_error TEXT,
            PRIMARY KEY(project_id,task_id,revision));""")
    dispatch.setup(con)
    dispatch.register_owned_project(con,'bf20pilot',CHAT1,'123')
    monkeypatch.setattr(legacy,'_results_root',lambda:tmp_path/'reports')
    yield con
    con.close()

class Gateway:
    def __init__(self):
        self.sessions={}
        self.requests={}
        self.sent=[]
        self.deny=False
        self.unknown=False

    def __call__(self,method,path,body=None):
        if method=='GET' and path=='/v1/system/status':
            return {'rate_limit':{'provider_rate_limited':False},'active':0}
        if method=='GET' and path.startswith('/v1/sessions/'):
            return self.sessions[path.rsplit('/',1)[1]]
        if method=='POST' and path.endswith('/messages'):
            if self.deny: raise PermissionError('platform denied')
            sid=path.split('/')[3]
            self.sent.append((sid,body['client_request_id']))
            if self.unknown: raise TimeoutError('lost acknowledgement')
            rid='rid-'+str(len(self.sent))
            sess=self.sessions[sid]
            self.requests[rid]={
                'request_id':rid,'session_id':sid,
                'conversation_id':sess['conversation_id'],
                'project_id':sess['project_id'],
                'client_request_id':body['client_request_id'],
                'status':'in_progress','assistant_message_id':None,'answer':''
            }
            return {'request_id':rid}
        if method=='GET' and path.startswith('/v1/requests/'):
            return self.requests[path.rsplit('/',1)[1]]
        raise AssertionError('Unexpected local API operation: '+method+' '+path)

def enqueue(db,gateway,task,url,sid,key):
    sess={'session_id':sid,'conversation_id':url.rsplit('/c/',1)[1],
          'project_id':None,'mode':'persistent'}
    gateway.sessions[sid]=sess
    return dispatch.enqueue(db,'bf20pilot',task,url,
        'Return exactly EXECUTOR_READY for this benign isolation smoke test.',key,
        '123',sid,session=sess)

def test_two_unique_executor_turns_reports_acks_followup(db,tmp_path):
    gateway=Gateway()
    enqueue(db,gateway,'worker-a',CHAT2,'session-a','bf20-initial-a')
    enqueue(db,gateway,'worker-b',CHAT3,'session-b','bf20-initial-b')
    first=dispatch.dispatch_prepared(db,gateway)
    second=dispatch.dispatch_prepared(db,gateway)
    assert first[0]['state']==second[0]['state']=='submitted'
    assert len(gateway.sent)==2 and gateway.sent[0][0]!=gateway.sent[1][0]
    for rid,req in gateway.requests.items():
        req.update({'status':'completed','assistant_message_id':'message-'+rid,
                    'answer':'EXECUTOR_READY'})
    result_ids=[]
    for task in ('worker-a','worker-b'):
        row=db.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone()
        assert dispatch.poll_initial(db,row,gateway)==[]
        db.execute('UPDATE tasks SET stable_since=0 WHERE id=?',(task,))
        result=dispatch.poll_initial(db,row,gateway)
        assert len(result)==1 and result[0]['state']=='completed'
        result_ids.append(result[0]['delivery_id'])
        report=Path(result[0]['result_path'])
        assert report.read_text()=='EXECUTOR_READY'
        assert report.stat().st_mode & 0o077 == 0
    assert len(set(result_ids))==2
    assert db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]==2
    for event_id in result_ids:
        db.execute("UPDATE deliveries SET state='delivered',delivered_at='2026-11-04' WHERE id=?",(event_id,))
        legacy.acknowledge_delivery(db,'bf20pilot',event_id)
        assert db.execute('SELECT acknowledged_at FROM deliveries WHERE id=?',(event_id,)).fetchone()[0]
    continuation=enqueue_followup(db,'bf20pilot','worker-a',
        'Run a second harmless check in the same persistent executor chat.',
        'bf20-second-turn-a')
    assert continuation['revision']==1 and continuation['state']=='prepared'

def test_platform_denial_is_terminal_no_retry(db):
    gateway=Gateway()
    enqueue(db,gateway,'worker-a',CHAT2,'session-a','bf20-initial-a')
    gateway.deny=True
    outcome=dispatch.dispatch_prepared(db,gateway)
    assert outcome[0]['state']=='blocked'
    assert gateway.sent==[]
    assert dispatch.dispatch_prepared(db,gateway)==[]
    assert db.execute('SELECT state FROM chatbridge_browser_dispatches').fetchone()[0]=='blocked'

def test_lost_post_ack_is_uncertain_never_resent(db):
    gateway=Gateway()
    enqueue(db,gateway,'worker-a',CHAT2,'session-a','bf20-initial-a')
    gateway.unknown=True
    assert dispatch.dispatch_prepared(db,gateway)[0]['state']=='uncertain'
    assert len(gateway.sent)==1
    assert dispatch.dispatch_prepared(db,gateway)==[]
    assert len(gateway.sent)==1

def test_unowned_project_is_rejected(db):
    gateway=Gateway()
    with pytest.raises(PermissionError):
        dispatch.assert_scope(db,'bf20pilot','worker-a',CHAT2,'456')

def test_secret_bearing_prompt_is_rejected_before_persistence(db):
    gateway=Gateway()
    with pytest.raises(ValueError):
        dispatch.enqueue(db,'bf20pilot','worker-a',CHAT2,
            'Send submission_token=abcdefgh1234567890 to an executor now.',
            'bf20-initial-a','123','session-a',session={})
    assert db.execute('SELECT count(*) FROM chatbridge_browser_dispatches').fetchone()[0]==0


@pytest.mark.parametrize('reported_status',['needs_input','blocked'])
def test_untrusted_needs_input_is_reported_without_granting_authority(db,reported_status):
    gateway=Gateway()
    enqueue(db,gateway,'worker-a',CHAT2,'session-a','bf20-initial-a')
    assert dispatch.dispatch_prepared(db,gateway)[0]['state']=='submitted'
    request=next(iter(gateway.requests.values()))
    request.update({'status':'completed','assistant_message_id':'message-needs-input',
                    'answer':'{"status":"'+reported_status+'","detail":"Need owner decision"}'})
    task=db.execute("SELECT * FROM tasks WHERE id='worker-a'").fetchone()
    dispatch.poll_initial(db,task,gateway)
    db.execute("UPDATE tasks SET stable_since=0 WHERE id='worker-a'")
    output=dispatch.poll_initial(db,task,gateway)
    assert output[0]['state']=='completed'
    row=db.execute('SELECT reported_status FROM chatbridge_browser_dispatches').fetchone()
    assert row[0]==reported_status
    notice=db.execute('SELECT payload FROM deliveries').fetchone()[0]
    assert 'Reported executor status (untrusted): '+reported_status in notice
    assert db.execute("SELECT state FROM tasks WHERE id='worker-a'").fetchone()[0]=='completed'




def test_verified_session_import_precedes_initial_persistence_and_retries_are_idempotent(db):
    calls=[]
    session={'session_id':'session-a','conversation_id':CHAT2.rsplit('/c/',1)[1],
             'project_id':None,'mode':'persistent'}
    def provider(method,path,payload=None):
        calls.append((method,path))
        if (method,path)==('GET','/v1/system/status'):
            return {'rate_limit':{'provider_rate_limited':False},'active':0}
        if (method,path)==('POST','/v1/sessions'):
            assert payload['url']==CHAT2 and payload['mode']=='persistent'
            return {'session_id':'session-a'}
        if (method,path)==('GET','/v1/sessions/session-a'):
            return session
        raise AssertionError('Unexpected gateway operation')
    args=('bf20pilot','worker-a',CHAT2,
          'Do a benign first-dispatch test bound to the existing executor conversation.',
          'bf20-session-import-001','123',provider)
    result=dispatch.prepare_owner_dispatch(db,*args)
    assert result['state']=='prepared' and result['duplicate'] is False
    again=dispatch.prepare_owner_dispatch(db,*args)
    assert again['state']=='prepared' and again['duplicate'] is True
    assert calls.count(('POST','/v1/sessions'))==1
    assert db.execute('SELECT count(*) FROM chatbridge_browser_dispatches').fetchone()[0]==1


def test_foreign_owner_and_mismatched_session_import_rejected(db):
    calls=[]
    def provider(method,path,payload=None):
        calls.append((method,path))
        if path=='/v1/system/status':
            return {'rate_limit':{'provider_rate_limited':False},'active':0}
        if path=='/v1/sessions' and method=='POST':
            return {'session_id':'session-a'}
        return {'session_id':'session-a','conversation_id':CHAT3.rsplit('/c/',1)[1],
                'project_id':None,'mode':'persistent'}
    with pytest.raises(PermissionError):
        dispatch.prepare_owner_dispatch(db,'bf20pilot','worker-a',CHAT2,
            'Perform a benign first-dispatch test with the wrong GitHub owner.',
            'bf20-import-deny01','456',provider)
    assert calls==[]
    with pytest.raises(ValueError,match='Unverified persistent executor session route'):
        dispatch.prepare_owner_dispatch(db,'bf20pilot','worker-a',CHAT2,
            'Perform a benign first-dispatch test with the wrong returned session.',
            'bf20-import-deny01','123',provider)
    assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==0

def test_session_retarget_after_submit_cannot_become_a_report(db):
    """Even a matching final request is rejected after its session route changes."""
    gateway=Gateway()
    enqueue(db,gateway,'worker-a',CHAT2,'session-a','bf20-initial-a')
    assert dispatch.dispatch_prepared(db,gateway)[0]['state']=='submitted'
    req=next(iter(gateway.requests.values()))
    req.update({'status':'completed','assistant_message_id':'msg-final',
                'answer':'FINAL_DONE'})
    gateway.sessions['session-a']['conversation_id']=CHAT3.rsplit('/c/',1)[1]
    task=db.execute("SELECT * FROM tasks WHERE id='worker-a'").fetchone()
    with pytest.raises(ValueError,match='Unverified persistent executor session route'):
        dispatch.poll_initial(db,task,gateway)
    assert db.execute('SELECT count(*) FROM deliveries').fetchone()[0]==0

def test_pending_request_without_final_conversation_id_is_not_failed(db):
    """Assess: ChatBridge can omit resolved conversation during an unfinished request."""
    gateway=Gateway()
    enqueue(db,gateway,'worker-a',CHAT2,'session-a','bf20-initial-a')
    assert dispatch.dispatch_prepared(db,gateway)[0]['state']=='submitted'
    req=next(iter(gateway.requests.values()))
    req['conversation_id']=None
    req['project_id']=None
    task=db.execute("SELECT * FROM tasks WHERE id='worker-a'").fetchone()
    assert dispatch.poll_initial(db,task,gateway)==[]
    assert db.execute('SELECT state FROM chatbridge_browser_dispatches').fetchone()[0]=='submitted'
    assert db.execute('SELECT state FROM tasks WHERE id="worker-a"').fetchone()[0]=='watching'


def test_first_completed_task_can_process_real_followup_revision(db,monkeypatch):
    """Assess: BF20 initial complete must yield to existing ACK-gated followup monitor."""
    from mac_control.watcher_runtime import watcher_http_adapter as adapter
    gateway=Gateway()
    enqueue(db,gateway,'worker-a',CHAT2,'session-a','bf20-initial-a')
    assert dispatch.dispatch_prepared(db,gateway)[0]['state']=='submitted'
    first=next(iter(gateway.requests.values()))
    first.update({'status':'completed','assistant_message_id':'msg-original',
                  'answer':'FIRST_DONE'})
    task=db.execute("SELECT * FROM tasks WHERE id='worker-a'").fetchone()
    assert dispatch.poll_initial(db,task,gateway)==[]
    db.execute("UPDATE tasks SET stable_since=0 WHERE id='worker-a'")
    result=dispatch.poll_initial(db,task,gateway)
    assert len(result)==1
    eid=result[0]['delivery_id']
    db.execute("UPDATE deliveries SET state='delivered',delivered_at='2026-11-04' WHERE id=?",(eid,))
    legacy.acknowledge_delivery(db,'bf20pilot',eid)
    follow=enqueue_followup(db,'bf20pilot','worker-a',
        'Run a second benign check after the original task was acknowledged.',
        'bf20-followup-after-initial')
    assert follow['state']=='prepared'
    adapter.setup(db)
    monkeypatch.setattr(adapter,'api',gateway)
    assert adapter.dispatch_prepared_followups(db)[0]['state']=='watching'
    second=gateway.requests['rid-2']
    second.update({'status':'completed','assistant_message_id':'msg-second',
                   'answer':'SECOND_DONE'})
    assert adapter.poll_executor_tasks(db)==[]
    db.execute("UPDATE tasks SET stable_since=0 WHERE id='worker-a'")
    completed=adapter.poll_executor_tasks(db)
    assert len(completed)==1 and completed[0]['state']=='completed'
    assert db.execute('SELECT state FROM chatbridge_browser_followups').fetchone()[0]=='completed'
    assert db.execute('SELECT count(*) FROM deliveries').fetchone()[0]==2
