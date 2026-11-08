"""BF22: Supervisor LLM decides readiness; orchestrator alone closes goal."""
from __future__ import annotations
import json
import sqlite3

import pytest

from mac_control.watcher_runtime import multi_project_watcher as legacy
from mac_control.watcher_runtime import watcher_browser_dispatch as initial
from mac_control.watcher_runtime import watcher_goal_supervisor as goals

ORCH="https://chatgpt.com/c/11111111-1111-4111-8111-111111111111"
WORK="https://chatgpt.com/c/22222222-2222-4222-8222-222222222222"
CRITERIA="Confirm that the executor returns an auditable, concise result."


@pytest.fixture
def db(tmp_path,monkeypatch):
    c=sqlite3.connect(":memory:",isolation_level=None)
    c.row_factory=sqlite3.Row
    c.executescript("""
    CREATE TABLE projects(id TEXT PRIMARY KEY,orchestrator_url TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL DEFAULT 'enabled',created_at TEXT NOT NULL);
    CREATE TABLE tasks(project_id TEXT,id TEXT,chat_url TEXT UNIQUE NOT NULL,
        state TEXT DEFAULT 'watching',mode TEXT DEFAULT 'browser',
        last_revision INTEGER DEFAULT 0,last_hash TEXT,stable_since REAL,
        last_text_size INTEGER DEFAULT 0,result_path TEXT,result_sha256 TEXT,
        complete_at TEXT,error TEXT,PRIMARY KEY(project_id,id));
    CREATE TABLE chatbridge_task_sessions(project_id TEXT,task_id TEXT,session_id TEXT,
        PRIMARY KEY(project_id,task_id));
    CREATE TABLE deliveries(id TEXT PRIMARY KEY,project_id TEXT,task_id TEXT,
        orchestrator_url TEXT,payload TEXT,state TEXT DEFAULT 'ready',
        attempts INTEGER DEFAULT 0,last_error TEXT,created_at TEXT,
        delivered_at TEXT,revision INTEGER,acknowledged_at TEXT);
    """)
    initial.setup(c)
    goals.setup(c)
    initial.register_owned_project(c,"pilot23",ORCH,"123")
    legacy.register_task(c,"pilot23","agent-a",WORK)
    c.execute("INSERT INTO chatbridge_task_sessions VALUES('pilot23','agent-a','sid-executor')")
    monkeypatch.setattr(legacy,"_results_root",lambda:tmp_path/"reports")
    yield c
    c.close()


def first_request():
    return {"request_id":"worker-request-1","session_id":"sid-executor",
            "conversation_id":WORK.rsplit("/c/",1)[1],"project_id":None,
            "client_request_id":"bf23-agent-a-0001","status":"completed",
            "assistant_message_id":"message-1","answer":"EXECUTOR_READY"}


class Bridge:
    def __init__(self,actions=("ready_for_orchestrator_review",)):
        self.actions=list(actions)
        self.requests={}
        self.sessions={"sid-executor":{"session_id":"sid-executor",
            "mode":"persistent","conversation_id":WORK.rsplit("/c/",1)[1],
            "project_id":None}}
        self.sent=[]
        self.supervisor_messages=0
        self.executor_messages=0
    def __call__(self,method,path,payload=None):
        if (method,path)==("GET","/v1/system/status"):
            return {"active":0,"rate_limit":{"provider_rate_limited":False}}
        if (method,path)==("POST","/v1/sessions"):
            assert payload["mode"]=="persistent" and not payload.get("url")
            sid="sid-supervisor"
            self.sessions[sid]={"session_id":sid,"mode":"persistent",
                "conversation_id":None,"project_id":None}
            return dict(self.sessions[sid])
        if method=="GET" and path.startswith("/v1/sessions/"):
            return dict(self.sessions[path.split("/")[3]])
        if method=="POST" and path.endswith("/messages"):
            sid=path.split("/")[3]
            assert payload["client_request_id"]
            self.sent.append((sid,payload["client_request_id"]))
            if sid=="sid-supervisor":
                idx=self.supervisor_messages
                self.supervisor_messages+=1
                action=self.actions[min(idx,len(self.actions)-1)]
                rid=f"supervisor-request-{idx+1}"
                self.sessions[sid]["conversation_id"]="33333333-3333-4333-8333-333333333333"
                source=f"message-{idx+1}"
                answer=json.dumps({"action":action,"source_turn_id":source,
                    "criteria_assessment":[],"rationale":"Supervisor model opinion",
                    "next_instruction":"Continue with a second concise verification result."})
                assistant=f"supervisor-message-{idx+1}"
            else:
                self.executor_messages+=1
                idx=self.executor_messages+1
                rid=f"worker-request-{idx}"
                answer="EXECUTOR_READY_REVISION_"+str(idx)
                assistant=f"message-{idx}"
            self.requests[rid]={"request_id":rid,"session_id":sid,
                "client_request_id":payload["client_request_id"],
                "project_id":None,"conversation_id":self.sessions[sid]["conversation_id"],
                "assistant_message_id":assistant,"status":"completed","answer":answer}
            return {"request_id":rid}
        if method=="GET" and path.startswith("/v1/requests/"):
            return self.requests[path.rsplit("/",1)[1]]
        raise AssertionError(f"Unexpected {method} {path}")


def registered_goal(db, turns=4):
    goals.register_goal(db,"pilot23","agent-a","123",CRITERIA,
                        max_turns=turns,max_elapsed_seconds=7200,max_no_progress=3)
    assert goals.record_settled(db,"pilot23","agent-a",first_request())


def drain(db,bridge,n=16):
    for _ in range(n):
        goals.pump(db,bridge)


def test_watcher_first_goal_result_never_notifies_before_supervisor(db):
    from mac_control.watcher_runtime import watcher_http_adapter as adapter
    goals.register_goal(db,"pilot23","agent-a","123",CRITERIA,
                        max_turns=4,max_elapsed_seconds=7200,max_no_progress=3)
    db.execute("""INSERT INTO chatbridge_browser_dispatches
        (project_id,task_id,executor_url,session_id,owner_subject,
         client_request_id,prompt,prompt_sha256,state,request_id,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        ("pilot23","agent-a",WORK,"sid-executor","123",
         "bf23-agent-a-0001","Benign first-turn goal task prompt.",
         "0"*64,"submitted","worker-request-1","2026-11-04"))
    b=Bridge()
    b.requests["worker-request-1"]=first_request()
    row=db.execute("SELECT * FROM tasks WHERE id='agent-a'").fetchone()
    assert initial.poll_initial(db,row,b)==[]
    assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]==0
    assert db.execute("SELECT COUNT(*) FROM goal_turns").fetchone()[0]==1
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_pending"
    assert db.execute("SELECT state FROM chatbridge_browser_dispatches").fetchone()[0]=="completed"
    # Old browser poll must never reinterpret this goal-enabled initial turn.
    assert initial.poll_initial(db,row,b)==[]
    assert db.execute("SELECT COUNT(*) FROM goal_turns").fetchone()[0]==1
    assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]==0


def test_goal_contract_is_explicit_optin_and_preserves_executor(db):
    assert not goals.is_goal(db,"pilot23","agent-a")
    registered_goal(db)
    assert goals.is_goal(db,"pilot23","agent-a")
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_pending"
    assert db.execute("SELECT state FROM tasks").fetchone()[0]=="watching"
    assert goals.record_settled(db,"pilot23","agent-a",first_request()) is False
    assert db.execute("SELECT COUNT(*) FROM goal_turns").fetchone()[0]==1


def test_supervisor_ready_creates_review_not_closed(db):
    registered_goal(db)
    g=Bridge()
    drain(db,g)
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_ready"
    assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]==1
    payload=db.execute("SELECT payload FROM deliveries").fetchone()[0]
    assert "Результат требует проверки оркестратором." in payload
    assert db.execute("SELECT COUNT(*) FROM goal_decisions").fetchone()[0]==1
    with pytest.raises((ValueError,PermissionError)):
        goals.approve_goal(db,"pilot23","agent-a","123",expected_revision=0)
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_ready"


def test_ack_is_not_goal_approval(db):
    registered_goal(db)
    drain(db,Bridge())
    delivery=db.execute("SELECT id FROM deliveries").fetchone()[0]
    db.execute("UPDATE deliveries SET state='delivered',delivered_at='2026-11-04' WHERE id=?",(delivery,))
    legacy.acknowledge_delivery(db,"pilot23",delivery)
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_ready"
    assert goals.approve_goal(db,"pilot23","agent-a","123",expected_revision=0)["closed"]
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="closed"


def test_supervisor_continue_does_not_notify_intermediate(db):
    registered_goal(db)
    bridge=Bridge(("continue","ready_for_orchestrator_review"))
    for _ in range(6):
        goals.pump(db,bridge)
    assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]==0
    drain(db,bridge,22)
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_ready"
    assert db.execute("SELECT COUNT(*) FROM goal_turns").fetchone()[0]==2
    assert db.execute("SELECT COUNT(*) FROM goal_decisions").fetchone()[0]==2
    assert bridge.executor_messages==1
    assert ("sid-executor",) == tuple(set(sid for sid,key in bridge.sent if sid=="sid-executor"))


def test_orchestrator_rework_uses_original_session_and_second_review(db):
    registered_goal(db)
    bridge=Bridge(("ready_for_orchestrator_review","ready_for_orchestrator_review"))
    drain(db,bridge)
    event=db.execute("SELECT id FROM deliveries").fetchone()[0]
    db.execute("UPDATE deliveries SET state='delivered',delivered_at='2026-11-04' WHERE id=?",(event,))
    legacy.acknowledge_delivery(db,"pilot23",event)
    outcome=goals.return_for_rework(db,"pilot23","agent-a","123",
        "Please repeat the test with more precise evidence and explain the outcome.",
        "bf22-rework-agent-a-0001",expected_revision=0)
    assert outcome["state"]=="continuation_pending"
    assert db.execute("SELECT state FROM tasks").fetchone()[0]=="watching"
    drain(db,bridge,22)
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_ready"
    assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]==2
    assert db.execute("SELECT COUNT(*) FROM goal_turns").fetchone()[0]==2
    assert bridge.executor_messages==1
    assert db.execute("SELECT last_revision FROM tasks").fetchone()[0]==1


def test_mcp_approve_and_rework_use_authenticated_owner_not_claimed_subject(monkeypatch):
    import sys, types
    from mac_control.legacy_handlers import watcher_ops
    from mac_control.watcher_runtime import multi_project_watcher as core
    class FakeMCP:
        def __init__(self): self.tools={}
        def tool(self,**kwargs):
            def use(fn): self.tools[fn.__name__]=fn; return fn
            return use
    class Conn:
        def close(self):pass
    mcp=FakeMCP()
    watcher_ops.register(mcp)
    identity=types.ModuleType("mac_control.account_profile")
    identity.authenticated_profile=lambda: {"id":"123"}
    monkeypatch.setitem(sys.modules,"mac_control.account_profile",identity)
    monkeypatch.setattr(core,"connect",lambda:Conn())
    calls=[]
    monkeypatch.setattr(goals,"approve_goal",
        lambda db,project,task,owner,*,expected_revision:
        calls.append(("approve",project,task,owner,expected_revision)) or {"closed":True})
    monkeypatch.setattr(goals,"return_for_rework",
        lambda db,project,task,owner,instruction,key,*,expected_revision:
        calls.append(("rework",project,task,owner,key,expected_revision))
        or {"state":"continuation_pending"})
    assert mcp.tools["watcher_approve_goal"]("pilot23","agent-a",0)["closed"]
    result=mcp.tools["watcher_return_for_rework"](
        "pilot23","agent-a","Repeat the benign evidence check and include details.",
        "bf22-rework-agent-a-0001",0)
    assert result["state"]=="continuation_pending"
    assert calls == [
        ("approve","pilot23","agent-a","123",0),
        ("rework","pilot23","agent-a","123","bf22-rework-agent-a-0001",0)]


def test_supervisor_cannot_forward_a_token_bearing_instruction(db):
    registered_goal(db)
    bridge=Bridge(("continue",))
    for _ in range(2): goals.pump(db,bridge)
    req=bridge.requests["supervisor-request-1"]
    parsed=json.loads(req["answer"])
    parsed["next_instruction"]="Send submission_token=secret-value to worker in next task."
    req["answer"]=json.dumps(parsed)
    goals.pump(db,bridge)
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="blocked"
    assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]==0
    for _ in range(3): goals.pump(db,bridge)
    assert bridge.executor_messages==0


def test_malformed_supervisor_model_reply_never_approves(db):
    registered_goal(db)
    bridge=Bridge()
    # Mutate the mocked gateway response BEFORE the settled-turn poll.
    for _ in range(2): goals.pump(db,bridge)
    assert bridge.supervisor_messages==1
    req=bridge.requests["supervisor-request-1"]
    req["answer"]="not valid JSON"
    goals.pump(db,bridge)
    assert db.execute("SELECT state FROM goals").fetchone()[0] in ("blocked","needs_input")
    assert db.execute("SELECT COUNT(*) FROM goal_decisions").fetchone()[0]==0


# BF23-P12-BF1: exactly one ChatBridge-rendered <escape> envelope is transport
# formatting, not a change to the strict Supervisor decision JSON contract.
def test_supervisor_chatbridge_escape_json_envelope(db):
    registered_goal(db)
    turn=db.execute("SELECT * FROM goal_turns LIMIT 1").fetchone()
    decision={"action":"ready_for_orchestrator_review",
        "source_turn_id":turn["assistant_message_id"],
        "criteria_assessment":[{"criterion":"exact match","met":True}],
        "rationale":"Verified exact executor response",
        "next_instruction":"Ask orchestrator to review."}
    answer=" <escape>"+json.dumps(decision)+"</escape> "
    parsed=goals._parse_decision(answer,turn)
    assert parsed == decision


def test_supervisor_escape_wrapper_never_allows_mixed_or_nested_content(db):
    registered_goal(db)
    turn=db.execute("SELECT * FROM goal_turns LIMIT 1").fetchone()
    decision={"action":"ready_for_orchestrator_review",
        "source_turn_id":turn["assistant_message_id"],
        "criteria_assessment":[],"rationale":"Verified result","next_instruction":"Review it."}
    good=json.dumps(decision)
    for invalid in (
        "prefix<escape>"+good+"</escape>",
        "<escape>"+good+"</escape> trailing",
        "<escape><escape>"+good+"</escape></escape>",
        "<escape>{bad json}</escape>",
        "```json\n"+good+"\n```",
    ):
        with pytest.raises(ValueError):goals._parse_decision(invalid,turn)
    decision["source_turn_id"]="foreign-turn"
    with pytest.raises(ValueError):
        goals._parse_decision("<escape>"+json.dumps(decision)+"</escape>",turn)


def _prepare_exact_blocked_supervisor(db,bridge):
    registered_goal(db)
    for _ in range(2):goals.pump(db,bridge)
    req=bridge.requests["supervisor-request-1"]
    req["answer"]="<escape>"+req["answer"]+"</escape>"
    db.execute("UPDATE goals SET state='blocked',last_error='invalid_supervisor_decision_or_route'")
    return req


def test_reconcile_blocked_supervisor_reads_existing_completed_reply_once(db):
    bridge=Bridge()
    req=_prepare_exact_blocked_supervisor(db,bridge)
    sent_before=list(bridge.sent)
    out=goals.reconcile_blocked_review(db,"pilot23","agent-a","123",bridge)
    # Recovery is one durable CAS transition; the existing Watcher tick
    # re-polls the SAME completed request to create the immutable delivery.
    assert out["state"]=="supervisor_recovering"
    assert db.execute("SELECT count(*) FROM goal_decisions").fetchone()[0]==0
    assert goals.reconcile_blocked_review(db,"pilot23","agent-a","123",bridge)["duplicate"]
    goals.pump(db,bridge)
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_ready"
    assert db.execute("SELECT count(*) FROM goal_decisions").fetchone()[0]==1
    assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0]==1
    assert "Результат требует проверки оркестратором." in db.execute("SELECT payload FROM deliveries").fetchone()[0]
    assert sent_before==bridge.sent  # ZERO new ChatBridge POSTs
    again=goals.reconcile_blocked_review(db,"pilot23","agent-a","123",bridge)
    assert again["duplicate"] is True
    assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0]==1
    assert sent_before==bridge.sent


def test_reconcile_blocked_supervisor_rejects_foreign_owner_and_wrong_error(db):
    bridge=Bridge();_prepare_exact_blocked_supervisor(db,bridge)
    sent_before=list(bridge.sent)
    with pytest.raises(PermissionError):
        goals.reconcile_blocked_review(db,"pilot23","agent-a","999",bridge)
    assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0]==0
    db.execute("UPDATE goals SET last_error='platform_policy_denial'")
    with pytest.raises(ValueError):
        goals.reconcile_blocked_review(db,"pilot23","agent-a","123",bridge)
    assert sent_before==bridge.sent


def test_reconcile_blocked_supervisor_rejects_changed_reply_or_route(db):
    bridge=Bridge();req=_prepare_exact_blocked_supervisor(db,bridge)
    req["client_request_id"]="not-the-saved-id"
    out=goals.reconcile_blocked_review(db,"pilot23","agent-a","123",bridge)
    assert out["state"] in ("blocked","uncertain")
    assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0]==0
    assert db.execute("SELECT count(*) FROM goal_decisions").fetchone()[0]==0
    assert bridge.executor_messages==0


def test_mcp_reconcile_uses_authenticated_owner_only(monkeypatch):
    import sys,types
    from mac_control.legacy_handlers import watcher_ops
    from mac_control.watcher_runtime import multi_project_watcher as core
    from mac_control.watcher_runtime import watcher_http_adapter as adapter
    class FakeMCP:
        def __init__(self): self.tools={}
        def tool(self,**kwargs):
            def decorate(fn): self.tools[fn.__name__]=fn;return fn
            return decorate
    class Conn:
        def close(self): pass
    identity=types.ModuleType('mac_control.account_profile')
    identity.authenticated_profile=lambda:{'id':'123'}
    monkeypatch.setitem(sys.modules,'mac_control.account_profile',identity)
    monkeypatch.setattr(core,'connect',lambda:Conn())
    calls=[]
    monkeypatch.setattr(goals,'reconcile_blocked_review',
        lambda db,project,task,owner,api: calls.append((project,task,owner,api is adapter.api)) or {'state':'supervisor_recovering'})
    mcp=FakeMCP();watcher_ops.register(mcp)
    assert mcp.tools['watcher_reconcile_goal_review']('pilot23','agent-a')['state']=='supervisor_recovering'
    assert calls==[('pilot23','agent-a','123',True)]


def test_completed_supervisor_recovery_survives_elapsed_budget(db):
    # Already completed review was blocked by display formatting; elapsed
    # budget may stop NEW model work, but must not discard old audited proof.
    bridge=Bridge();_prepare_exact_blocked_supervisor(db,bridge)
    sent_before=list(bridge.sent)
    db.execute("UPDATE goals SET created_ts=?",(__import__('time').time()-12000,))
    out=goals.reconcile_blocked_review(db,"pilot23","agent-a","123",bridge)
    assert out["recovered"] is True
    goals.pump(db,bridge,now=__import__('time').time())
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_ready"
    assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0]==1
    assert bridge.sent==sent_before


def test_bf33_two_independent_reviews_progress_in_same_cycle(db,monkeypatch):
    registered_goal(db)
    other = "https://chatgpt.com/c/44444444-4444-4444-8444-444444444444"
    legacy.register_task(db,"pilot23","agent-b",other)
    db.execute("INSERT INTO chatbridge_task_sessions VALUES(?,?,?)",
               ("pilot23","agent-b","sid-executor-b"))
    goals.register_goal(db,"pilot23","agent-b","123",CRITERIA)
    request=first_request()
    request.update(request_id="worker-request-b",session_id="sid-executor-b",
                   conversation_id=other.rsplit("/c/",1)[1],
                   assistant_message_id="message-b",
                   client_request_id="bf33-worker-b-unique")
    assert goals.record_settled(db,"pilot23","agent-b",request)
    # Isolate fairness from artificial Supervisor sessions in the fixture.
    def fake_create(d,row,api):
        return goals._mark(d,row,"supervisor_session_ready",
                           supervisor_session_id="sup-"+row["task_id"])
    monkeypatch.setattr(goals,"_create_reviewer",fake_create)
    goals.pump(db,Bridge())
    assert dict(db.execute("SELECT task_id,state FROM goals")) == {
        "agent-a":"supervisor_session_ready",
        "agent-b":"supervisor_session_ready",
    }


def test_bf33_paused_project_does_not_advance_supervisor(db):
    registered_goal(db)
    db.execute("UPDATE projects SET status='paused' WHERE id='pilot23'")
    bridge=Bridge()
    assert goals.pump(db,bridge)==[]
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_pending"
    assert not bridge.sent


def test_bf33_paused_reviews_do_not_consume_active_project_capacity(db,monkeypatch):
    registered_goal(db)
    goals.register_goal(db,"pilot23","paused-second","123",CRITERIA)
    for task in ("agent-a","paused-second"):
        db.execute("UPDATE goals SET state='supervisor_session_ready',supervisor_session_id=? WHERE project_id='pilot23' AND task_id=?",
                   ("paused-"+task,task))
    db.execute("UPDATE projects SET status='paused' WHERE id='pilot23'")
    from mac_control.watcher_runtime import watcher_browser_dispatch as dispatch
    dispatch.register_owned_project(
        db,"active33","https://chatgpt.com/c/55555555-5555-4555-8555-555555555555","123")
    goals.register_goal(db,"active33","new-worker","123",CRITERIA)
    db.execute("UPDATE goals SET state='review_pending' WHERE project_id='active33'")
    def create(d,row,api):
        return goals._mark(d,row,"supervisor_session_ready",
                           supervisor_session_id="active-new-supervisor")
    monkeypatch.setattr(goals,"_create_reviewer",create)
    goals.pump(db,Bridge())
    assert db.execute("SELECT state FROM goals WHERE project_id='active33'").fetchone()[0]=="supervisor_session_ready"


def test_bf33_p07_followup_auto_installs_supervisor_for_original_executor(db):
    from mac_control.watcher_runtime import watcher_browser_followups as followups
    assert not goals.is_goal(db, "pilot23", "agent-a")
    db.execute("UPDATE tasks SET state='completed',result_sha256=?,result_path=?,complete_at=? "
               "WHERE project_id='pilot23' AND id='agent-a'",
               ("f" * 64, "/tmp/immutable-original.md", "2026-11-08"))
    message = ("Research how bounded parallel queues differ from serial execution. "
               "Compare fairness, overlap, cancellation and backpressure, with evidence.")
    result=followups.enqueue(db,"pilot23","agent-a",message,"bf33-p07-same-a-01")
    assert result["state"]=="prepared" and result["revision"]==1
    assert goals.is_goal(db,"pilot23","agent-a")
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="running"
    assert db.execute("SELECT session_id FROM chatbridge_task_sessions").fetchone()[0]=="sid-executor"


def test_bf33_p07_completed_followup_goes_to_supervisor_not_direct_delivery(db):
    from mac_control.watcher_runtime import watcher_browser_followups as followups
    from mac_control.watcher_runtime import watcher_http_adapter as adapter
    db.execute("UPDATE tasks SET state='completed',result_sha256=?,result_path=?,complete_at=? "
               "WHERE project_id='pilot23' AND id='agent-a'",
               ("f" * 64, "/tmp/immutable-original.md", "2026-11-08"))
    prompt="Research parallel dispatch for multiple independent tasks, with a concise comparison of approaches."
    followups.enqueue(db,"pilot23","agent-a",prompt,"bf33-p07-followup-a-01")
    db.execute("UPDATE chatbridge_browser_followups SET state='submitted',request_id='followup-request-1'")
    db.execute("UPDATE tasks SET state='watching',last_revision=1,stable_since=NULL,result_sha256=NULL,result_path=NULL")
    bridge=Bridge()
    bridge.requests["followup-request-1"]={
        "request_id":"followup-request-1","session_id":"sid-executor",
        "conversation_id":WORK.rsplit("/c/",1)[1],"project_id":None,
        "client_request_id":"bf33-p07-followup-a-01",
        "status":"completed","assistant_message_id":"followup-message-1",
        "answer":"Research shows two concurrent requests may finish out-of-order."}
    monkeypatch = __import__("pytest").MonkeyPatch()
    old=adapter.api
    adapter.api=bridge
    try:
        adapter.poll_executor_tasks(db)
    finally:
        adapter.api=old
        monkeypatch.undo()
    assert db.execute("SELECT COUNT(*) FROM goal_turns").fetchone()[0]==1
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_pending"
    assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]==0
    assert db.execute("SELECT state FROM chatbridge_browser_followups").fetchone()[0]=="completed"


def test_bf33_p07_retrofit_followup_requires_independent_supervisor_before_delivery(db,monkeypatch):
    from mac_control.watcher_runtime import watcher_browser_followups as followups
    from mac_control.watcher_runtime import watcher_http_adapter as adapter
    db.execute("UPDATE tasks SET state='completed',result_sha256=?,result_path=?,complete_at=? "
               "WHERE project_id='pilot23' AND id='agent-a'",
               ("f"*64,"/tmp/original-immutable-result.md","2026-11-08"))
    followups.enqueue(db,"pilot23","agent-a",
                      "Research advantages and failure modes of multi-executor parallel scheduling.",
                      "bf33-p07-reviewed-research-a-01")
    db.execute("UPDATE chatbridge_browser_followups SET state='submitted',request_id='followup-request-review'")
    db.execute("UPDATE tasks SET state='watching',last_revision=1,stable_since=NULL,result_path=NULL,result_sha256=NULL")
    bridge=Bridge()
    bridge.requests["followup-request-review"]={
        "request_id":"followup-request-review","session_id":"sid-executor",
        "conversation_id":WORK.rsplit("/c/",1)[1],"project_id":None,
        "client_request_id":"bf33-p07-reviewed-research-a-01","status":"completed",
        "assistant_message_id":"message-1",
        "answer":"Bounded concurrency permits overlapping requests. Fairness and 429 backpressure are separate."}
    monkeypatch.setattr(adapter,"api",bridge)
    events=adapter.poll_executor_tasks(db)
    assert events and events[0]["state"]=="goal_review_pending"
    assert db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]==0
    for _ in range(8):
        goals.pump(db,bridge)
        if db.execute("SELECT state FROM goals").fetchone()[0]=="review_ready":
            break
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="review_ready"
    assert db.execute("SELECT COUNT(*) FROM goal_decisions").fetchone()[0]==1
    report=db.execute("SELECT * FROM deliveries").fetchone()
    assert report is not None and "Результат требует проверки оркестратором" in report["payload"]
    from pathlib import Path
    completed=db.execute("SELECT result_path,result_sha256 FROM tasks WHERE id='agent-a'").fetchone()
    body=Path(completed["result_path"]).read_text()
    import hashlib
    assert "Supervisor model opinion:" in body
    assert hashlib.sha256(body.encode()).hexdigest()==completed["result_sha256"]
    assert db.execute("SELECT session_id FROM chatbridge_task_sessions").fetchone()[0]=="sid-executor"
    assert db.execute("SELECT COUNT(*) FROM goal_turns").fetchone()[0]==1


def test_bf33_p07_public_spawn_always_installs_supervisor(db,monkeypatch):
    import contextlib
    from mac_control.legacy_handlers import watcher_ops
    from mac_control import account_profile
    from mac_control.watcher_runtime import watcher_autonomous as auto
    class Tools:
        def __init__(self):self.ops={}
        def tool(self,**kwargs):
            def register(fn):
                self.ops[fn.__name__]=fn
                return fn
            return register
    tools=Tools()
    watcher_ops.register(tools)
    monkeypatch.setattr(account_profile,"authenticated_profile",lambda:{"id":"123"})
    monkeypatch.setattr(legacy,"connect",lambda:db)
    monkeypatch.setattr(watcher_ops,"closing",lambda db:contextlib.nullcontext(db))
    # Initial spawn must never opt out implicitly just because no goal_criteria.
    out=tools.ops["watcher_spawn_subagent"](
        "pilot23","new-agent", "WC0123456789abcdef",
        "Research bounded concurrency, fairness and independent review mechanisms in agents.",
        "bf33-p07-mandatory-initial-a-01")
    assert out["state"]=="marker_pending"
    assert goals.is_goal(db,"pilot23","new-agent")
    criteria=db.execute("SELECT criteria FROM goals WHERE task_id='new-agent'").fetchone()[0]
    assert "Research bounded concurrency" in criteria


def test_bf33_p07_supervised_followup_transaction_rolls_back_on_crash(db,monkeypatch):
    from mac_control.watcher_runtime import watcher_browser_followups as followups
    from mac_control.watcher_runtime import watcher_http_adapter as adapter
    db.execute("UPDATE tasks SET state='completed',result_sha256=?,result_path=?,complete_at=? "
               "WHERE project_id='pilot23' AND id='agent-a'",
               ("f"*64,"/tmp/immutable-prior.md","2026-11-08"))
    followups.enqueue(db,"pilot23","agent-a",
                      "Research fairness and crash-safe state transitions for parallel orchestration.",
                      "bf33-p07-crash-rollback-a-01")
    db.execute("UPDATE chatbridge_browser_followups SET state='submitted',request_id='rev-1-request'")
    db.execute("UPDATE tasks SET state='watching',last_revision=1,result_sha256=NULL,result_path=NULL")
    b=Bridge()
    b.requests["rev-1-request"]={"request_id":"rev-1-request","session_id":"sid-executor",
        "conversation_id":WORK.rsplit("/c/",1)[1],"project_id":None,
        "client_request_id":"bf33-p07-crash-rollback-a-01","status":"completed",
        "assistant_message_id":"crash-message-1","answer":"Study of concurrency with evidence."}
    monkeypatch.setattr(adapter,"api",b)
    real=goals.record_settled
    def crash_after_recording(*args,**kwargs):
        real(*args,**kwargs)
        raise sqlite3.OperationalError("simulated disk contention after goal insert")
    monkeypatch.setattr(goals,"record_settled",crash_after_recording)
    out=adapter.poll_executor_tasks(db)
    assert out and out[0]["state"]=="deferred"
    assert db.execute("SELECT COUNT(*) FROM goal_turns").fetchone()[0]==0
    assert db.execute("SELECT state FROM goals").fetchone()[0]=="running"
    assert db.execute("SELECT state FROM chatbridge_browser_followups").fetchone()[0]=="submitted"
