"""BF23-BF2: source-bound old receipt recovery must never resend."""
import sqlite3
import pytest
from mac_control.watcher_runtime import watcher_http_adapter as adapter

URL="https://chatgpt.com/c/11111111-2222-4333-8444-555555555555"
DID="a"*32
RID="request-123"
SID="session-123"
UID="00000000-1111-4222-8333-444444444444"

@pytest.fixture
def db():
    d=sqlite3.connect(":memory:",isolation_level=None)
    d.row_factory=sqlite3.Row
    d.executescript("""
    CREATE TABLE projects(id TEXT PRIMARY KEY,status TEXT,orchestrator_url TEXT);
    CREATE TABLE deliveries(id TEXT PRIMARY KEY,project_id TEXT,task_id TEXT,
      orchestrator_url TEXT,payload TEXT,state TEXT,attempts INTEGER,
      last_error TEXT,delivered_at TEXT,created_at TEXT,acknowledged_at TEXT,revision INTEGER);
    CREATE TABLE chatbridge_delivery_links(delivery_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,request_id TEXT,last_status TEXT,last_checked_at TEXT,last_error TEXT);
    INSERT INTO projects VALUES('project-1','enabled','""" + URL + """');
    INSERT INTO deliveries VALUES('""" + DID + """','project-1','worker-a',
        '""" + URL + """','[MC-WATCH:""" + DID + """] Original immutable report',
        'attempting',1,NULL,NULL,'2026-11-05T00:00:00Z',NULL,0);
    INSERT INTO chatbridge_delivery_links(delivery_id,session_id,request_id,last_status)
      VALUES('""" + DID + """','""" + SID + """','""" + RID + """','thinking');
    """)
    try: yield d
    finally: d.close()

def fixture_gateway(db,monkeypatch,*,status="thinking",changes=None,msg_changes=None):
    monkeypatch.setattr(adapter,"ensure_session",lambda d,row:(SID,RID))
    payload=db.execute("SELECT payload FROM deliveries").fetchone()[0]
    request=dict(request_id=RID,session_id=SID,
        client_request_id="watcher-delivery-"+DID,
        conversation_id=URL.rsplit("/c/",1)[1],
        user_message_id=UID,status=status)
    request.update(changes or {})
    message=dict(role="user",request_id=RID,message_id=UID,content=payload)
    message.update(msg_changes or {})
    calls=[]
    def api(method,path,body=None):
        calls.append((method,path))
        if (method,path)==("GET","/v1/requests/"+RID):return request
        if (method,path)==("GET",f"/v1/sessions/{SID}/messages?limit=500&after=0"):
            return {"data":[message],"next_cursor":0}
        raise AssertionError("Unexpected provider write or route: "+method+" "+path)
    monkeypatch.setattr(adapter,"api",api)
    return calls

@pytest.mark.parametrize("status",["thinking","unknown","completed"])
def test_confirmed_original_receipt_repairs_without_resending(db,monkeypatch,status):
    calls=fixture_gateway(db,monkeypatch,status=status)
    delivery=db.execute("SELECT * FROM deliveries").fetchone()
    result=adapter.process_one(db,delivery)
    assert result["state"]=="delivered"
    assert db.execute("SELECT state FROM deliveries").fetchone()[0]=="delivered"
    assert db.execute("SELECT last_status FROM chatbridge_delivery_links").fetchone()[0]=="receipt_confirmed"
    assert all(method=="GET" for method,_ in calls)
    assert len(calls)==2
    assert adapter.process_one(db,db.execute("SELECT * FROM deliveries").fetchone())["state"]=="delivered"
    assert all(method=="GET" for method,_ in calls)

@pytest.mark.parametrize("field,value,part",[
 ("client_request_id","watcher-delivery-"+"b"*32,"request"),
 ("session_id","other-session","request"),
 ("conversation_id","99999999-9999-4999-8999-999999999999","request"),
 ("user_message_id",None,"request"),
 ("message_id","other-message","message"),
 ("request_id","other-request","message"),
 ("role","assistant","message"),
 ("content","similar but wrong payload","message"),
])
def test_wrong_evidence_never_claims_delivery(db,monkeypatch,field,value,part):
    changes={field:value} if part=="request" else None
    msg_changes={field:value} if part=="message" else None
    calls=fixture_gateway(db,monkeypatch,changes=changes,msg_changes=msg_changes)
    result=adapter.process_one(db,db.execute("SELECT * FROM deliveries").fetchone())
    assert result["state"]=="attempting"
    assert db.execute("SELECT state FROM deliveries").fetchone()[0]=="attempting"
    assert all(m=="GET" for m,_ in calls)


def test_completed_with_wrong_provenance_is_never_delivered(db,monkeypatch):
    calls=fixture_gateway(db,monkeypatch,status="completed",
        msg_changes={"content":"tampered receipt payload"})
    result=adapter.process_one(db,db.execute("SELECT * FROM deliveries").fetchone())
    assert result["state"]=="delivery_uncertain"
    assert db.execute("SELECT state FROM deliveries").fetchone()[0]=="delivery_uncertain"
    assert all(method=="GET" for method,_ in calls)
