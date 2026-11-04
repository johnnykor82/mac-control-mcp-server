"""BF-20 initial tokenless browser handoff: isolated TDD tests."""
import sqlite3
import pytest

from mac_control.watcher_runtime import multi_project_watcher as legacy
from mac_control.watcher_runtime import watcher_browser_dispatch as dispatch

URL_1 = "https://chatgpt.com/c/11111111-1111-4111-8111-111111111111"
URL_2 = "https://chatgpt.com/c/22222222-2222-4222-8222-222222222222"
URL_3 = "https://chatgpt.com/c/33333333-3333-4333-8333-333333333333"

@pytest.fixture
def db():
    con=sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory=sqlite3.Row
    con.executescript("""CREATE TABLE projects(id TEXT PRIMARY KEY, orchestrator_url TEXT, status TEXT DEFAULT 'enabled', created_at TEXT NOT NULL);
        CREATE TABLE tasks(project_id TEXT,id TEXT,chat_url TEXT UNIQUE,state TEXT DEFAULT 'watching',
          mode TEXT DEFAULT 'browser', last_revision INTEGER DEFAULT 0, error TEXT,
          PRIMARY KEY(project_id,id));
        CREATE TABLE chatbridge_task_sessions(project_id TEXT,task_id TEXT,session_id TEXT,
          PRIMARY KEY(project_id,task_id));
        CREATE TABLE chatbridge_task_request_links(project_id TEXT,task_id TEXT,request_id TEXT,session_id TEXT,
          PRIMARY KEY(project_id,task_id));""")
    dispatch.setup(con)
    dispatch.register_owned_project(con,'bf20pilot',URL_1,'123')
    yield con
    con.close()

def enqueue(db, project='bf20pilot', task='worker-a', url=URL_2, key='bf20-request-a', prompt='Perform a benign smoke test for dispatch only.', subject='123'):
    sid = 'session-001' if task == 'worker-a' else 'session-002'
    return dispatch.enqueue(db,project,task,url,prompt,key,subject,session_id=sid,
                            session={'session_id':sid,'conversation_id':url.rsplit('/c/',1)[1],
                                     'project_id':None,'mode':'persistent'})

def test_first_send_is_durable_idempotent_and_has_owner(db):
    first=enqueue(db)
    assert first['state']=='prepared' and first['duplicate'] is False
    second=enqueue(db)
    assert second['duplicate'] is True and second['client_request_id']==first['client_request_id']
    row=db.execute('SELECT * FROM chatbridge_browser_dispatches').fetchone()
    assert row['owner_subject']=='123' and row['prompt_sha256'] and row['request_id'] is None

def test_conflict_and_foreign_owner_are_rejected(db):
    enqueue(db)
    with pytest.raises(ValueError): enqueue(db,key='bf20-request-a',url=URL_3)
    with pytest.raises(PermissionError): enqueue(db,subject='456')

def test_two_executor_isolation_and_wrong_project(db):
    enqueue(db)
    second=enqueue(db,task='worker-b',url=URL_3,key='bf20-request-b')
    assert second['task_id']=='worker-b'
    assert db.execute('SELECT count(*) FROM chatbridge_browser_dispatches').fetchone()[0]==2
    with pytest.raises(ValueError): enqueue(db,project='unknown',task='worker-c',key='bf20-request-c')

def test_wrong_session_identity_rejected_before_database_mutation(db):
    with pytest.raises(ValueError):
        dispatch.enqueue(db,'bf20pilot','worker-a',URL_2,'Perform a benign smoke test for dispatch only.',
            'bf20-request-a','123','session-001',session={'session_id':'session-001','conversation_id':'wrong',
                'project_id':None,'mode':'persistent'})
    assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==0

def test_stale_sending_is_uncertain_and_never_prepared_again(db):
    enqueue(db)
    db.execute("UPDATE chatbridge_browser_dispatches SET state='sending'")
    assert dispatch.quarantine_inflight(db)==1
    assert dispatch.prepare_for_dispatch(db)==[]
    assert db.execute('SELECT state FROM chatbridge_browser_dispatches').fetchone()[0]=='uncertain'

def test_request_provenance_rejects_unverified_final_result(db):
    enqueue(db)
    row=db.execute('SELECT * FROM chatbridge_browser_dispatches').fetchone()
    good={'request_id':'request-aaa','session_id':'session-001','conversation_id':URL_2.rsplit('/c/',1)[1],
          'project_id':None,'client_request_id':row['client_request_id'],
          'status':'completed','assistant_message_id':'msg-aaa','answer':'EXECUTOR_READY'}
    db.execute("UPDATE chatbridge_browser_dispatches SET state='submitted',request_id='request-aaa'")
    assert dispatch.verify_completed_result(db,'bf20pilot','worker-a',good)=='msg-aaa'
    for field,value in [('request_id','other'),('client_request_id','other'),('assistant_message_id',None),
                        ('conversation_id','other'),('session_id','other'),('status','running')]:
        broken={**good,field:value}
        with pytest.raises(ValueError): dispatch.verify_completed_result(db,'bf20pilot','worker-a',broken)
