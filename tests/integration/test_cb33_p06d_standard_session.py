"""P06D: Watcher local standard orchestrator session reuse without unsafe import."""
import sqlite3

import pytest

from mac_control.watcher_runtime import watcher_http_adapter as adapter

URL = "https://chatgpt.com/c/11111111-2222-4333-8444-555555555555"
CID = URL.rsplit("/", 1)[1]
SID = "standard-session-1"
DID = "d" * 32


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
      CREATE TABLE deliveries(id TEXT PRIMARY KEY,project_id TEXT,orchestrator_url TEXT,created_at TEXT);
      CREATE TABLE chatbridge_delivery_links(delivery_id TEXT PRIMARY KEY,session_id TEXT,request_id TEXT,last_status TEXT);
      INSERT INTO deliveries VALUES('""" + DID + """','isolated-p06d','""" + URL + """','2026-11-11');
    """)
    yield conn
    conn.close()


def gateway(monkeypatch, rows):
    seen = []
    def api(method, route, payload=None):
        seen.append((method, route))
        if (method,route)==("GET","/v1/sessions?limit=250&offset=0"):
            return {"data": rows, "limit":250, "offset":0}
        if method=="GET" and route.startswith("/v1/sessions/"):
            session_id=route.rsplit("/",1)[-1]
            return next((r for r in rows if r.get("session_id")==session_id), None)
        if method=="POST":
            raise AssertionError("Must reuse existing standard session without provider/session POST")
        raise AssertionError((method,route))
    monkeypatch.setattr(adapter, "api", api)
    return seen


def valid_session(**override):
    return {"session_id": SID, "conversation_id": CID, "url": URL, "project_id": None,
            "mode": "standard", **override}


def test_existing_unique_standard_orchestrator_reused_without_post(db, monkeypatch):
    seen=gateway(monkeypatch,[valid_session()])
    sid,rid=adapter.ensure_session(db,db.execute("SELECT * FROM deliveries").fetchone())
    assert sid==SID and rid is None
    assert all(method=="GET" for method,_ in seen)
    link=db.execute("SELECT session_id,request_id FROM chatbridge_delivery_links").fetchone()
    assert link["session_id"]==SID and link["request_id"] is None


def test_existing_duplicate_target_fails_closed_without_post(db,monkeypatch):
    gateway(monkeypatch,[valid_session(), valid_session(session_id="second-session")])
    with pytest.raises(adapter.TransportError):
        adapter.ensure_session(db, db.execute("SELECT * FROM deliveries").fetchone())
    assert db.execute("SELECT COUNT(*) FROM chatbridge_delivery_links").fetchone()[0]==0


def test_existing_wrong_project_identity_fails_closed(db,monkeypatch):
    gateway(monkeypatch,[valid_session(project_id="g-p-"+"a"*32)])
    with pytest.raises(adapter.TransportError):
        adapter.ensure_session(db, db.execute("SELECT * FROM deliveries").fetchone())
    assert db.execute("SELECT COUNT(*) FROM chatbridge_delivery_links").fetchone()[0]==0


def test_existing_unapproved_mode_fails_closed(db,monkeypatch):
    gateway(monkeypatch,[valid_session(mode="temporary")])
    with pytest.raises(adapter.TransportError):
        adapter.ensure_session(db, db.execute("SELECT * FROM deliveries").fetchone())
