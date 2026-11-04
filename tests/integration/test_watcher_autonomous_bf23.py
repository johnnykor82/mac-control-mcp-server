"""BF-23 owner-approved v2: autonomous marker-bound ChatBridge subagents (offline TDD)."""
from __future__ import annotations

import sqlite3

import pytest

from mac_control.watcher_runtime import multi_project_watcher as legacy
from mac_control.watcher_runtime import watcher_autonomous as autonomous

ORCH = "https://chatgpt.com/c/11111111-1111-4111-8111-111111111111"
MARKER = "WATCHER-CHAT-" + "a" * 32
PROMPT = "Return exactly EXECUTOR_READY for this isolated watcher integration test."
CONVO = (
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE projects(id TEXT PRIMARY KEY, orchestrator_url TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'enabled',created_at TEXT NOT NULL);
        CREATE TABLE tasks(project_id TEXT NOT NULL,id TEXT NOT NULL,
            chat_url TEXT UNIQUE NOT NULL,state TEXT DEFAULT 'watching',
            mode TEXT NOT NULL DEFAULT 'browser',last_revision INTEGER DEFAULT 0,
            last_hash TEXT,stable_since REAL,last_text_size INTEGER DEFAULT 0,
            result_path TEXT,result_sha256 TEXT,complete_at TEXT,error TEXT,
            PRIMARY KEY(project_id,id));
        CREATE TABLE chatbridge_task_sessions(project_id TEXT,task_id TEXT,session_id TEXT,
            PRIMARY KEY(project_id,task_id));
        CREATE TABLE chatbridge_task_request_links(project_id TEXT,task_id TEXT,
            request_id TEXT,session_id TEXT,PRIMARY KEY(project_id,task_id));
        CREATE TABLE deliveries(id TEXT PRIMARY KEY, project_id TEXT,task_id TEXT,
            orchestrator_url TEXT,payload TEXT,state TEXT DEFAULT 'ready',
            attempts INTEGER DEFAULT 0,last_error TEXT,created_at TEXT,
            delivered_at TEXT,revision INTEGER,acknowledged_at TEXT);
        CREATE TABLE chatbridge_browser_followups(project_id TEXT,task_id TEXT,
            revision INTEGER,session_id TEXT,client_request_id TEXT UNIQUE,
            prompt TEXT,request_id TEXT,state TEXT,last_error TEXT,
            PRIMARY KEY(project_id,task_id,revision));
    """)
    from mac_control.watcher_runtime import watcher_browser_dispatch as dispatch
    dispatch.setup(db)
    monkeypatch.setattr(legacy, "_results_root", lambda: tmp_path / "reports")
    autonomous.setup(db)
    yield db
    db.close()


class Bridge:
    def __init__(self):
        self.calls = []
        self.sessions = {}
        self.requests = {}
        self.sent = []
        self.marker_status = "ok"
        self.fail_session = False
        self.fail_send = False
        self.assistant_role = True

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path))
        if (method, path) == ("POST", "/v1/chats/resolve-marker"):
            if self.marker_status == "missing":
                from mac_control.watcher_runtime.watcher_http_adapter import TransportError
                raise TransportError("ChatBridge HTTP 404")
            if self.marker_status == "ambiguous":
                from mac_control.watcher_runtime.watcher_http_adapter import TransportError
                raise TransportError("ChatBridge HTTP 409")
            assert payload == {"marker": MARKER}
            return {"chat_url": ORCH, "verification":
                    "assistant_message" if self.assistant_role else "user_message",
                    "evidence_verified": True, "matches": 1}
        if (method, path) == ("GET", "/v1/system/status"):
            return {"rate_limit": {"provider_rate_limited": False}, "active": 0}
        if (method, path) == ("POST", "/v1/sessions"):
            assert payload["mode"] == "persistent"
            assert not payload.get("url") and not payload.get("conversation_id")
            if self.fail_session:
                raise TimeoutError("unknown create-session receipt")
            sid = f"session-{len(self.sessions)+1}"
            self.sessions[sid] = {"session_id": sid, "mode": "persistent",
                "conversation_id": None, "project_id": None}
            return dict(self.sessions[sid])
        if method == "GET" and path.startswith("/v1/sessions/"):
            return dict(self.sessions[path.rsplit("/", 1)[1]])
        if method == "POST" and path.endswith("/messages"):
            if self.fail_send:
                self.sent.append((path, payload["client_request_id"]))
                raise TimeoutError("lost message POST acknowledgement")
            sid = path.split("/")[3]
            assert sid in self.sessions
            rid = f"request-{len(self.sent)+1}"
            self.sent.append((path, payload["client_request_id"]))
            idx = int(sid.split("-")[1])-1
            conv = CONVO[idx]
            self.sessions[sid]["conversation_id"] = conv
            self.requests[rid] = {
                "request_id": rid, "session_id": sid,
                "conversation_id": conv, "project_id": None,
                "client_request_id": payload["client_request_id"],
                "assistant_message_id": f"answer-{rid}",
                "status": "completed", "answer": "EXECUTOR_READY",
            }
            return {"request_id": rid}
        if method == "GET" and path.startswith("/v1/requests/"):
            return dict(self.requests[path.rsplit("/", 1)[1]])
        raise AssertionError(f"Unexpected ChatBridge call: {method} {path}")


def drain(db, bridge, count=12):
    for _ in range(count):
        autonomous.pump(db, bridge, now=1_000_000)


def test_owner_api_registers_without_any_urls_or_network(db):
    result = autonomous.enqueue(db, "pilot23", "agent-a", MARKER, PROMPT,
                                "bf23-agent-a-0001", "123")
    assert result["state"] == "marker_pending"
    assert result["duplicate"] is False
    assert autonomous.enqueue(db, "pilot23", "agent-a", MARKER, PROMPT,
                              "bf23-agent-a-0001", "123")["duplicate"]
    assert db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    with pytest.raises((PermissionError, ValueError)):
        autonomous.enqueue(db, "pilot23", "agent-a", MARKER, PROMPT,
                           "bf23-agent-a-0001", "999")


def test_owner_api_prevents_credential_payloads_and_changed_duplicate(db):
    with pytest.raises(ValueError):
        autonomous.enqueue(db,"pilot23","agent-a",MARKER,
                           "Send submission_token=secret to an unrelated worker.",
                           "bf23-agent-a-0001","123")
    autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT,"bf23-agent-a-0001","123")
    with pytest.raises(ValueError):
        autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT+" changed",
                           "bf23-agent-a-0001","123")


def test_assistant_marker_lookup_then_persistent_session_and_exact_result(db):
    b = Bridge()
    autonomous.enqueue(db, "pilot23", "agent-a", MARKER, PROMPT, "bf23-agent-a-0001", "123")
    drain(db, b)
    r = dict(db.execute("SELECT * FROM autonomous_subagents").fetchone())
    assert r["state"] in ("bound", "completed")
    assert r["orchestrator_url"] == ORCH
    assert r["executor_url"] == "https://chatgpt.com/c/" + CONVO[0]
    assert r["assistant_message_id"] == "answer-request-1"
    assert len(b.sent) == 1
    assert len(b.sessions) == 1
    assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM chatbridge_browser_dispatches").fetchone()[0] == 1


def test_two_children_retain_one_orchestrator_and_distinct_sessions(db):
    b = Bridge()
    for name in ("agent-a", "agent-b"):
        autonomous.enqueue(db, "pilot23", name, MARKER, PROMPT,
                           "bf23-"+name+"-0001", "123")
    drain(db, b, 24)
    rows = db.execute("SELECT * FROM autonomous_subagents ORDER BY task_id").fetchall()
    assert len(rows) == 2
    assert all(r["state"] in ("bound", "completed") for r in rows)
    assert len({r["session_id"] for r in rows}) == 2
    assert len({r["executor_url"] for r in rows}) == 2
    assert {r["orchestrator_url"] for r in rows} == {ORCH}
    assert len(b.sent) == 2
    assert db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


def test_bound_new_session_reuses_bf20_immutable_report_and_ack(db):
    from pathlib import Path
    from mac_control.watcher_runtime import watcher_browser_dispatch as initial
    b=Bridge()
    autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT,
                       "bf23-agent-a-0001","123")
    drain(db,b)
    task=db.execute("SELECT * FROM tasks WHERE id='agent-a'").fetchone()
    assert initial.poll_initial(db,task,b)==[]
    db.execute("UPDATE tasks SET stable_since=0 WHERE id='agent-a'")
    events=initial.poll_initial(db,task,b)
    assert len(events)==1 and events[0]["state"]=="completed"
    assert Path(events[0]["result_path"]).read_text()=="EXECUTOR_READY"
    assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]==1
    event_id=events[0]["delivery_id"]
    db.execute("UPDATE deliveries SET state='delivered',delivered_at='2026-11-04' "
               "WHERE id=?",(event_id,))
    ack=legacy.acknowledge_delivery(db,"pilot23",event_id)
    assert ack["acknowledged"]
    autonomous.sync_completed(db)
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0]=="completed"


def test_404_search_is_queued_without_creating_workers(db):
    b = Bridge(); b.marker_status = "missing"
    autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT,"bf23-agent-a-0001","123")
    autonomous.pump(db,b,now=1_000_000)
    r = db.execute("SELECT * FROM autonomous_subagents").fetchone()
    assert r["state"] == "marker_pending" and r["marker_attempts"] == 1
    assert not b.sessions and not b.sent
    before = len(b.calls)
    autonomous.pump(db,b,now=1_000_001)
    assert len(b.calls) == before
    b.marker_status="ok"
    # Respect the persisted indexing backoff instead of suppressing it in tests.
    for _ in range(12):
        autonomous.pump(db,b,now=1_001_000)
    assert db.execute("SELECT executor_url FROM autonomous_subagents").fetchone()[0]


def test_ambiguous_or_user_role_marker_fails_closed(db):
    for reason in ("ambiguous", "user"):
        x = Bridge()
        if reason == "ambiguous": x.marker_status = "ambiguous"
        else: x.assistant_role=False
        autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT,
                           "bf23-agent-a-0001","123")
        autonomous.pump(db,x,now=1_000_000)
        assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0] == "blocked"
        assert not x.sessions
        db.execute("DELETE FROM autonomous_subagents")


def test_create_session_lost_ack_quarantines_without_second_create(db):
    b=Bridge();b.fail_session=True
    autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT,"bf23-agent-a-0001","123")
    drain(db,b)
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0] == "uncertain"
    n=b.calls.count(("POST","/v1/sessions"))
    drain(db,b)
    assert b.calls.count(("POST","/v1/sessions")) == n == 1


def test_message_lost_ack_quarantines_without_resend(db):
    b=Bridge();b.fail_send=True
    autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT,"bf23-agent-a-0001","123")
    drain(db,b)
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0] == "uncertain"
    n=len(b.sent)
    drain(db,b)
    assert len(b.sent)==n==1


def test_restart_quarantines_inflight_only(db):
    autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT,"bf23-agent-a-0001","123")
    db.execute("UPDATE autonomous_subagents SET state='session_creating'")
    assert autonomous.quarantine_inflight(db)==1
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0]=="uncertain"
    assert autonomous.quarantine_inflight(db)==0


def test_owner_authenticated_mcp_spawn_uses_inprocess_subject(monkeypatch):
    import sys
    import types
    from mac_control.legacy_handlers import watcher_ops
    from mac_control.watcher_runtime import multi_project_watcher as core
    from mac_control.watcher_runtime import watcher_autonomous
    class FakeMCP:
        def __init__(self): self.tools = {}
        def tool(self, **kwargs):
            def register(function):
                self.tools[function.__name__] = function
                return function
            return register

    mcp = FakeMCP()
    watcher_ops.register(mcp)
    fake = types.ModuleType("mac_control.account_profile")
    fake.authenticated_profile = lambda: {"id":"123"}
    monkeypatch.setitem(sys.modules, "mac_control.account_profile", fake)
    class FakeConnection:
        def close(self): pass
    monkeypatch.setattr(core, "connect", lambda: FakeConnection())
    calls = []
    monkeypatch.setattr(watcher_autonomous,"enqueue",
        lambda db,project,task,marker,prompt,key,owner:
        calls.append((project,task,marker,owner)) or {"state":"marker_pending"})
    out=mcp.tools["watcher_spawn_subagent"](
        "pilot23","agent-a",MARKER,PROMPT,"bf23-agent-a-0001")
    assert out["state"]=="marker_pending"
    assert calls==[("pilot23","agent-a",MARKER,"123")]


def test_summary_redacts_prompt_marker_and_owner(db):
    autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT,"bf23-agent-a-0001","123")
    result=autonomous.safe_status(db)
    assert len(result)==1
    assert "prompt" not in result[0]
    assert "owner_subject" not in result[0]
    assert "marker" not in result[0]
    assert result[0]["state"] == "marker_pending"
