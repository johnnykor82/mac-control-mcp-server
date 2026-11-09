"""BF-23 owner-approved v2: autonomous marker-bound ChatBridge subagents (offline TDD)."""
from __future__ import annotations

import sqlite3

import pytest

from mac_control.watcher_runtime import multi_project_watcher as legacy
from mac_control.watcher_runtime import watcher_autonomous as autonomous

ORCH = "https://chatgpt.com/c/11111111-1111-4111-8111-111111111111"
MARKER = "WC" + "a" * 16
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
            if self.marker_status == "denied":
                from mac_control.watcher_runtime.watcher_http_adapter import TransportError
                raise TransportError("ChatBridge HTTP 403")
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


def test_supervisor_goal_optin_is_atomic_with_autonomous_enqueue(db):
    from mac_control.watcher_runtime import watcher_goal_supervisor as supervisor
    result=autonomous.enqueue(
        db,"pilot23","agent-a",MARKER,PROMPT,"bf23-agent-a-0001","123",
        goal_criteria="Ensure the executor satisfies the precise requested result.",
        max_turns=4,max_elapsed_seconds=3600,max_no_progress=2)
    assert result["state"]=="marker_pending"
    assert supervisor.is_goal(db,"pilot23","agent-a")
    assert autonomous.enqueue(
        db,"pilot23","agent-a",MARKER,PROMPT,"bf23-agent-a-0001","123",
        goal_criteria="Ensure the executor satisfies the precise requested result.",
        max_turns=4,max_elapsed_seconds=3600,max_no_progress=2)["duplicate"]
    with pytest.raises(ValueError):
        autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT,
                           "bf23-agent-a-0001","123",
                           goal_criteria="Different review criteria demand a new task.",
                           max_turns=4,max_elapsed_seconds=3600,max_no_progress=2)


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


def test_explicit_marker_lookup_403_blocks_without_retries_or_sessions(db):
    b=Bridge();b.marker_status="denied"
    autonomous.enqueue(db,"pilot23","agent-a",MARKER,PROMPT,
                       "bf23-agent-a-0001","123")
    autonomous.pump(db,b,now=1_000_000)
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0]=="blocked"
    n=len(b.calls)
    for _ in range(8): autonomous.pump(db,b,now=2_000_000)
    assert len(b.calls)==n and not b.sessions


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
        lambda db,project,task,marker,prompt,key,owner,**kwargs:
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


# BF33 — read-only/synthetic regression tests of real parallel contract.
class DelayedBridge(Bridge):
    """Acknowledge dispatch but keep ChatGPT responses pending independently."""

    def __call__(self, method, path, payload=None):
        if (method, path) == ("GET", "/v1/system/status"):
            return {"rate_limit": {"provider_rate_limited": False},
                    "active": sum(r["status"] != "completed"
                                  for r in self.requests.values()), "capacity": 10}
        if method == "POST" and path.endswith("/messages"):
            out = super().__call__(method, path, payload)
            self.requests[out["request_id"]]["status"] = "running"
            return out
        return super().__call__(method, path, payload)


def test_bf33_two_workers_dispatch_concurrently_and_finish_out_of_order(db):
    b = DelayedBridge()
    for n in (1, 2):
        autonomous.enqueue(db, "pilot33", f"worker-{n}", MARKER, PROMPT,
                           f"bf33-worker-{n}-unique", "123")
    for _ in range(3):
        autonomous.pump(db, b, now=1_000_000)
    assert len(b.sent) == 2, "Second worker must dispatch while first is running"
    assert {x["state"] for x in db.execute(
        "SELECT state FROM autonomous_subagents")} == {"submitted"}
    b.requests["request-2"]["status"] = "completed"
    autonomous.pump(db, b, now=1_000_000)
    states = dict(db.execute(
        "SELECT task_id,state FROM autonomous_subagents"))
    assert states == {"worker-1": "submitted", "worker-2": "bound"}
    assert len(b.sent) == 2, "Read-only polling must never duplicate POST"


def test_bf33_paused_project_cannot_process_queued_work(db):
    b = Bridge()
    autonomous.enqueue(db, "paused33", "worker-a", MARKER, PROMPT,
                       "bf33-paused-worker-01", "123")
    autonomous.pump(db, b, now=1_000_000)
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0] == "submitted"
    db.execute("UPDATE projects SET status='paused' WHERE id='paused33'")
    before = len(b.calls)
    autonomous.pump(db, b, now=1_000_000)
    assert len(b.calls) == before
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0] == "submitted"


def test_bf33_completed_turn_waits_for_session_binding_without_resend(db):
    b = Bridge()
    autonomous.enqueue(db, "pilot33", "worker-a", MARKER, PROMPT,
                       "bf33-binding-worker-01", "123")
    autonomous.pump(db, b, now=1_000_000)
    sid = next(iter(b.sessions))
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0] == "submitted"
    conv = b.sessions[sid]["conversation_id"]
    b.sessions[sid]["conversation_id"] = None  # transient eventual consistency
    autonomous.pump(db, b, now=1_000_000)
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0] == "submitted"
    b.sessions[sid]["conversation_id"] = conv
    autonomous.pump(db, b, now=1_000_000)
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0] == "bound"
    assert len(b.sent) == 1


def test_bf33_second_worker_reports_while_first_still_running(db):
    from mac_control.watcher_runtime import watcher_browser_dispatch as initial
    b=DelayedBridge()
    for n in (1,2):
        autonomous.enqueue(db,"pilot33",f"worker-{n}",MARKER,PROMPT,
                           f"bf33-ready-{n}-unique","123")
    for _ in range(3):
        autonomous.pump(db,b,now=1_000_000)
    assert len(b.sent)==2
    b.requests["request-2"]["status"]="completed"
    autonomous.pump(db,b,now=1_000_000)
    row=db.execute("SELECT * FROM tasks WHERE id='worker-2'").fetchone()
    assert row is not None
    assert initial.poll_initial(db,row,b)==[]
    db.execute("UPDATE tasks SET stable_since=0 WHERE id='worker-2'")
    result=initial.poll_initial(db,row,b)
    assert result and result[0]["state"]=="completed"
    assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]==1
    assert db.execute("SELECT state FROM autonomous_subagents WHERE task_id='worker-1'").fetchone()[0]=="submitted"
    assert b.requests["request-1"]["status"]=="running"


def test_bf33_third_worker_waits_for_bounded_capacity(db):
    b=DelayedBridge()
    for n in (1,2,3):
        autonomous.enqueue(db,"pilot33",f"worker-{n}",MARKER,PROMPT,
                           f"bf33-cap-{n}-unique","123")
    for _ in range(4):
        autonomous.pump(db,b,now=1_000_000)
    assert len(b.sent)==2
    assert db.execute("SELECT state FROM autonomous_subagents WHERE task_id='worker-3'").fetchone()[0]=="marker_pending"


def test_bf33_provider_cooldown_prevents_even_marker_search(db):
    class Cooldown(Bridge):
        def __call__(self,method,path,payload=None):
            if (method,path)==("GET","/v1/system/status"):
                return {"active":0,"rate_limit":{"provider_rate_limited":True}}
            return super().__call__(method,path,payload)
    b=Cooldown()
    autonomous.enqueue(db,"pilot33","agent-a",MARKER,PROMPT,
                       "bf33-cooldown-01","123")
    autonomous.pump(db,b,now=1_000_000)
    assert b.calls==[]
    assert db.execute("SELECT state FROM autonomous_subagents").fetchone()[0]=="marker_pending"


def test_bf33_paused_pending_workers_do_not_keep_watcher_active(db):
    autonomous.enqueue(db,"pilot33","worker-a",MARKER,PROMPT,
                       "bf33-pause-count-01","123")
    autonomous.pump(db,Bridge(),now=1_000_000)
    assert legacy.active_work_counts(db)["pending_autonomous_subagents"]==1
    db.execute("UPDATE projects SET status='paused' WHERE id='pilot33'")
    counts=legacy.active_work_counts(db)
    assert counts["pending_autonomous_subagents"]==0
    assert counts["active"] is False


def test_bf33_both_workers_receive_initial_post_in_one_scheduler_tick(db):
    """Short model turns must still overlap rather than stagger by 20s ticks."""
    b=DelayedBridge()
    for n in (1,2):
        autonomous.enqueue(db,"pilot33",f"worker-{n}",MARKER,PROMPT,
                           f"bf33-single-tick-{n}-unique","123")
    events=autonomous.pump(db,b,now=1_000_000)
    assert len(b.sent)==2,events
    assert db.execute("SELECT COUNT(*) FROM autonomous_subagents "
        "WHERE state='submitted'").fetchone()[0]==2
    assert len({path for path,key in b.sent})==2
    assert len({key for path,key in b.sent})==2


def test_bf33_pipeline_dispatches_two_before_either_completes(db):
    """BF33 R9: short tasks must not need separate 20-second ticks to start."""
    b=DelayedBridge()
    for n in (1,2):
        autonomous.enqueue(db,"pilot33",f"parallel-{n}",MARKER,PROMPT,
                           f"bf33-pipeline-{n}-unique","123")
    events=autonomous.pump(db,b,now=1_000_000,pipeline=True)
    assert len(b.sent)==2, events
    assert [b.requests[f"request-{n}"]["status"] for n in (1,2)] == [
        "running","running"]
    assert {r["state"] for r in db.execute(
        "SELECT state FROM autonomous_subagents")}=={"submitted"}
    assert sum(e.get("new_post",False) for e in events)==2
    assert len({key for _,key in b.sent})==2
    # No automatic redelivery or extra worker despite another tick.
    autonomous.pump(db,b,now=1_000_001,pipeline=True)
    assert len(b.sent)==2


# CB33 P06R: previously delivered+ACKed autonomous work must never be
# repolled when its original project is resumed.
def _cb33_insert_legacy_complete(db, *, acked=True):
    from mac_control.watcher_runtime import watcher_browser_dispatch as dispatch
    dispatch.register_owned_project(db, "cb33-guard", ORCH, "123")
    autonomous.enqueue(db, "cb33-guard", "old-worker", MARKER, PROMPT,
                       "cb33-guard-old-unique", "123")
    legacy.register_task(db, "cb33-guard", "old-worker",
                         "https://chatgpt.com/c/" + CONVO[0])
    db.execute("""UPDATE autonomous_subagents SET state='completed'
        WHERE project_id='cb33-guard' AND task_id='old-worker'""")
    db.execute("""INSERT INTO deliveries(
        id,project_id,task_id,orchestrator_url,payload,state,created_at,
        delivered_at,acknowledged_at)
        VALUES(?,?,'old-worker',?,?,'delivered',?,?,?)""",
        ("cb33-old-delivery","cb33-guard",ORCH,"old delivery",
         "2026-11-08","2026-11-08",
         "2026-11-08" if acked else None))


def test_cb33_completed_acked_autonomous_watching_row_never_polled_or_modified(db, monkeypatch):
    from mac_control.watcher_runtime import watcher_http_adapter as adapter
    _cb33_insert_legacy_complete(db)
    before=[tuple(r) for r in db.execute(
        "SELECT * FROM tasks WHERE project_id='cb33-guard'")]
    def no_api(*args, **kwargs):
        raise AssertionError("MUST NOT read ChatBridge for completed ACKed worker")
    monkeypatch.setattr(adapter,"api",no_api)
    assert adapter.poll_executor_tasks(db,dry_run=True)==[]
    assert adapter.poll_executor_tasks(db,dry_run=False)==[]
    after=[tuple(r) for r in db.execute(
        "SELECT * FROM tasks WHERE project_id='cb33-guard'")]
    assert before==after


def test_cb33_new_worker_still_polled_while_old_acked_worker_excluded(db):
    from mac_control.watcher_runtime import watcher_http_adapter as adapter
    _cb33_insert_legacy_complete(db)
    legacy.register_task(db,"cb33-guard","new-worker",
                         "https://chatgpt.com/c/"+CONVO[1])
    observed=adapter.poll_executor_tasks(db,dry_run=True)
    assert [x["task"] for x in observed]==["cb33-guard/new-worker"]


def test_cb33_unacknowledged_autonomous_worker_not_silently_skipped(db):
    from mac_control.watcher_runtime import watcher_http_adapter as adapter
    _cb33_insert_legacy_complete(db,acked=False)
    observed=adapter.poll_executor_tasks(db,dry_run=True)
    assert [x["task"] for x in observed]==["cb33-guard/old-worker"]
