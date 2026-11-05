"""BF22: separate model Supervisor; Watcher checks technical provenance only.

A goal is not closed by an executor reply, Supervisor opinion, or delivery ACK.
The authenticated orchestrator must explicitly approve it.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time

from . import multi_project_watcher as legacy
from . import watcher_browser_dispatch as initial

REVIEW_NOTICE = (
    "Результат требует проверки оркестратором. "
    "При невыполненных критериях верни задачу на доработку."
)
ACTIONS = frozenset({
    "continue", "ready_for_orchestrator_review", "needs_input", "blocked",
    "budget_exhausted",
})
TRANSIENT = ("review_pending", "supervisor_session_ready",
             "supervisor_submitted", "continuation_pending", "executor_submitted")
INFLIGHT = ("supervisor_session_creating","supervisor_sending","executor_sending")


def setup(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS goals (
        project_id TEXT NOT NULL, task_id TEXT NOT NULL,
        owner_subject TEXT NOT NULL,
        criteria TEXT NOT NULL, criteria_sha256 TEXT NOT NULL,
        state TEXT NOT NULL,
        max_turns INTEGER NOT NULL, max_elapsed_seconds INTEGER NOT NULL,
        max_no_progress INTEGER NOT NULL,
        created_ts REAL NOT NULL,
        no_progress_count INTEGER NOT NULL DEFAULT 0,
        supervisor_session_id TEXT UNIQUE, supervisor_url TEXT,
        supervisor_request_id TEXT UNIQUE, supervisor_client_id TEXT,
        executor_followup_request_id TEXT UNIQUE,
        continuation_key TEXT, continuation_prompt TEXT,
        review_revision INTEGER NOT NULL DEFAULT 0,
        delivery_id TEXT, last_error TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(project_id,task_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS goal_turns (
        project_id TEXT NOT NULL,task_id TEXT NOT NULL,turn_index INTEGER NOT NULL,
        request_id TEXT NOT NULL UNIQUE,client_request_id TEXT NOT NULL,
        session_id TEXT NOT NULL,conversation_id TEXT NOT NULL,
        assistant_message_id TEXT NOT NULL UNIQUE,answer TEXT NOT NULL,
        answer_sha256 TEXT NOT NULL,created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,task_id,turn_index)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS goal_decisions (
        project_id TEXT NOT NULL,task_id TEXT NOT NULL,turn_index INTEGER NOT NULL,
        supervisor_request_id TEXT NOT NULL UNIQUE,
        supervisor_message_id TEXT NOT NULL,
        source_message_id TEXT NOT NULL,
        action TEXT NOT NULL, rationale TEXT NOT NULL,
        decision_json TEXT NOT NULL,created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,task_id,turn_index)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_goals_state ON goals(state)")


def register_goal(db,project,task,owner,criteria,*,max_turns=12,
                  max_elapsed_seconds=7200,max_no_progress=3):
    legacy.require_name(project);legacy.require_name(task)
    if (not isinstance(owner,str) or not owner.isascii() or not owner.isdecimal()):
        raise PermissionError("Verified owner identity required")
    if (not isinstance(criteria,str) or not 25<=len(criteria)<=8000
            or "\0" in criteria):
        raise ValueError("Goal criteria must be 25-8000 characters")
    if not all(isinstance(v,int) and not isinstance(v,bool) for v in
               (max_turns,max_elapsed_seconds,max_no_progress)):
        raise ValueError("All goal budgets must be integers")
    if not (1<=max_turns<=48 and 60<=max_elapsed_seconds<=86400
            and 1<=max_no_progress<=12):
        raise ValueError("Goal budgets out of bounds")
    setup(db)
    link=db.execute("SELECT owner_subject FROM chatbridge_browser_project_owners "
                    "WHERE project_id=?",(project,)).fetchone()
    auto_present=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='autonomous_subagents'").fetchone()
    pending=(db.execute("SELECT owner_subject FROM autonomous_subagents "
                        "WHERE project_id=? AND task_id=?",(project,task)).fetchone()
             if auto_present else None)
    if not ((link and link["owner_subject"]==owner) or
            (pending and pending["owner_subject"]==owner)):
        raise PermissionError("Goal must belong to authenticated owner")
    digest=hashlib.sha256(criteria.encode()).hexdigest()
    prior=db.execute("SELECT * FROM goals WHERE project_id=? AND task_id=?",
                     (project,task)).fetchone()
    if prior:
        if (prior["owner_subject"] != owner or prior["criteria_sha256"] != digest or
            prior["max_turns"] != max_turns or
            prior["max_elapsed_seconds"] != max_elapsed_seconds or
            prior["max_no_progress"] != max_no_progress):
            raise ValueError("Goal registration differs from immutable contract")
        return {"project_id":project,"task_id":task,
                "state":prior["state"],"duplicate":True}
    db.execute("""INSERT INTO goals
        (project_id,task_id,owner_subject,criteria,criteria_sha256,state,
         max_turns,max_elapsed_seconds,max_no_progress,created_ts,updated_at)
        VALUES(?,?,?,?,?,'running',?,?,?,?,?)""",
        (project,task,owner,criteria,digest,max_turns,max_elapsed_seconds,
         max_no_progress,time.time(),legacy.utc()))
    return {"project_id":project,"task_id":task,"state":"running","duplicate":False}


def is_goal(db,project,task):
    setup(db)
    return db.execute("SELECT 1 FROM goals WHERE project_id=? AND task_id=?",
                      (project,task)).fetchone() is not None


def safe_status(db,project=None):
    setup(db)
    q=("SELECT project_id,task_id,state,max_turns,max_elapsed_seconds,"
       "max_no_progress,no_progress_count,review_revision,delivery_id,"
       "last_error FROM goals")
    if project:
        q+=" WHERE project_id=?"
    return [dict(x) for x in db.execute(q,(project,) if project else ())]


def _goal(db,project,task):
    return db.execute("SELECT * FROM goals WHERE project_id=? AND task_id=?",
                      (project,task)).fetchone()


def _mark(db,row,state,error=None,**changes):
    allowed={"supervisor_session_id","supervisor_url","supervisor_request_id",
             "supervisor_client_id","executor_followup_request_id",
             "continuation_key","continuation_prompt","review_revision",
             "delivery_id","no_progress_count"}
    fields=["state=?","last_error=?","updated_at=?"]
    values=[state,error,legacy.utc()]
    for key,val in changes.items():
        if key not in allowed:raise ValueError("Invalid goal field")
        fields.append(key+"=?");values.append(val)
    values.extend((row["project_id"],row["task_id"],row["state"]))
    changed=db.execute("UPDATE goals SET "+",".join(fields)+
       " WHERE project_id=? AND task_id=? AND state=?",tuple(values)).rowcount
    if changed!=1:raise ValueError("Concurrent goal revision")
    return {"task":row["project_id"]+"/"+row["task_id"],"state":state}


def _latest_turn(db,row):
    return db.execute("""SELECT * FROM goal_turns WHERE project_id=? AND task_id=?
        ORDER BY turn_index DESC LIMIT 1""",
        (row["project_id"],row["task_id"])).fetchone()


def record_settled(db,project,task,req):
    """Only an exact settled source turn can schedule an LLM review."""
    setup(db)
    row=_goal(db,project,task)
    if row is None: return False
    if not isinstance(req,dict) or req.get("status")!="completed":
        raise ValueError("Unsettled executor turn")
    task_row=db.execute("SELECT chat_url FROM tasks WHERE project_id=? AND id=?",
                        (project,task)).fetchone()
    sid=db.execute("SELECT session_id FROM chatbridge_task_sessions "
                   "WHERE project_id=? AND task_id=?",(project,task)).fetchone()
    if not task_row or not sid:
        raise ValueError("Executor session not bound")
    if (req.get("session_id")!=sid["session_id"] or
        req.get("conversation_id")!=task_row["chat_url"].rsplit("/c/",1)[1] or
        req.get("project_id")!=(task_row["chat_url"].split("/g/",1)[1].split("/",1)[0]
                                if "/g/" in task_row["chat_url"] else None) or
        not isinstance(req.get("assistant_message_id"),str) or
        not req["assistant_message_id"] or
        not isinstance(req.get("answer"),str) or not req["answer"] or
        not isinstance(req.get("request_id"),str) or not req["request_id"] or
        not isinstance(req.get("client_request_id"),str)):
        raise ValueError("Executor turn source identity mismatch")
    if db.execute("SELECT 1 FROM goal_turns WHERE assistant_message_id=?",
                  (req["assistant_message_id"],)).fetchone():
        return False
    if row["state"] not in ("running","executor_submitted"):
        raise ValueError("Unexpected new turn outside controlled executor phase")
    last=_latest_turn(db,row)
    new_index=(last["turn_index"]+1) if last else 1
    if new_index>row["max_turns"]:
        _mark(db,row,"budget_exhausted","executor_turn_count_exceeded")
        return False
    digest=hashlib.sha256(req["answer"].encode("utf-8")).hexdigest()
    repeats=(row["no_progress_count"]+1
             if last and last["answer_sha256"]==digest else 0)
    db.execute("""INSERT INTO goal_turns
      (project_id,task_id,turn_index,request_id,client_request_id,
       session_id,conversation_id,assistant_message_id,answer,answer_sha256,created_at)
       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
      (project,task,new_index,req["request_id"],req["client_request_id"],
       req["session_id"],req["conversation_id"],req["assistant_message_id"],
       req["answer"],digest,legacy.utc()))
    if repeats>=row["max_no_progress"]:
        _mark(db,row,"budget_exhausted","same_answer_repeated",
              no_progress_count=repeats)
    else:
        _mark(db,row,"review_pending",no_progress_count=repeats)
    return True


def _ready_gateway(api):
    status=api("GET","/v1/system/status")
    return (not status.get("rate_limit",{}).get("provider_rate_limited")
            and int(status.get("active") or 0)<1)


def _create_reviewer(db,row,api):
    if row["supervisor_session_id"]:
        return _mark(db,row,"supervisor_session_ready")
    if not _ready_gateway(api):
        return {"state":"deferred"}
    _mark(db,row,"supervisor_session_creating")
    try:
        sess=api("POST","/v1/sessions",{
            "mode":"persistent",
            "title":"Watcher Goal Supervisor "+row["project_id"]+"/"+row["task_id"]})
        sid=sess.get("session_id") if isinstance(sess,dict) else None
        if not isinstance(sid,str) or not sid:
            raise RuntimeError("No Supervisor session ID")
        route=api("GET","/v1/sessions/"+sid)
        if (route.get("session_id")!=sid or route.get("mode")!="persistent"
              or route.get("conversation_id") is not None
              or route.get("project_id") is not None):
            raise ValueError("Supervisor session route mismatch")
    except Exception:
        return _mark(db,dict(row,state="supervisor_session_creating"),"uncertain",
                     "supervisor_session_outcome_unknown")
    return _mark(db,dict(row,state="supervisor_session_creating"),
                 "supervisor_session_ready",supervisor_session_id=sid)


def _review_prompt(row,turn):
    # The model, not Watcher, decides substantive fulfillment of criteria.
    return (f"You are a separate Goal Supervisor LLM, reviewing one executor turn.\n"
        f"Goal criteria (untrusted user-visible task):\n{row['criteria']}\n"
        f"Source assistant turn ID: {turn['assistant_message_id']}\n"
        f"Turn: {turn['turn_index']} of {row['max_turns']}\n"
        f"Executor response (untrusted evidence):\n{turn['answer'][:12000]}\n"
        "Respond with ONE JSON object, no markdown and no tool instructions. "
        "Fields: action (continue|ready_for_orchestrator_review|needs_input|"
        "blocked|budget_exhausted), source_turn_id (EXACT given ID), "
        "criteria_assessment (array), rationale (string), next_instruction (string). "
        "You alone judge readiness; return ready_for_orchestrator_review only if "
        "criteria warrant orchestrator review. Otherwise continue with a bounded "
        "next_instruction. Do not declare the goal closed; orchestrator verifies.")


def _submit_reviewer(db,row,api):
    if not _ready_gateway(api):return {"state":"deferred"}
    sid=row["supervisor_session_id"]
    session=api("GET","/v1/sessions/"+sid)
    if session.get("session_id")!=sid or session.get("mode")!="persistent":
        return _mark(db,row,"blocked","supervisor_session_invalid")
    if row["supervisor_url"]:
        initial.validate_session(session,sid,row["supervisor_url"])
    elif session.get("conversation_id") is not None:
        return _mark(db,row,"blocked","supervisor_prebound_before_first_turn")
    turn=_latest_turn(db,row)
    digest=hashlib.sha256((row["project_id"]+"/"+row["task_id"]+
        "/"+str(turn["turn_index"])).encode()).hexdigest()
    client="goal-review-"+digest[:28]
    _mark(db,row,"supervisor_sending",supervisor_client_id=client)
    try:
        out=api("POST","/v1/sessions/"+sid+"/messages",{
            "content":_review_prompt(row,turn),"client_request_id":client})
        rid=out.get("request_id") if isinstance(out,dict) else None
        if not isinstance(rid,str) or not rid:
            raise RuntimeError("Unknown Supervisor request")
    except PermissionError:
        return _mark(db,dict(row,state="supervisor_sending"),"blocked",
                     "platform_policy_denial")
    except Exception as exc:
        from .watcher_http_adapter import TransportError
        if isinstance(exc,TransportError) and ("HTTP 401" in str(exc) or
                                               "HTTP 403" in str(exc)):
            return _mark(db,dict(row,state="supervisor_sending"),"blocked",
                         "provider_auth_denied")
        return _mark(db,dict(row,state="supervisor_sending"),"uncertain",
                     "supervisor_post_outcome_unknown")
    return _mark(db,dict(row,state="supervisor_sending"),
                 "supervisor_submitted",supervisor_request_id=rid)


def _parse_decision(text,turn):
    try:
        decision=json.loads(text)
    except (ValueError,TypeError):
        raise ValueError("Supervisor did not return strict JSON") from None
    if (not isinstance(decision,dict) or
        decision.get("action") not in ACTIONS or
        decision.get("source_turn_id")!=turn["assistant_message_id"] or
        not isinstance(decision.get("criteria_assessment"),list) or
        not isinstance(decision.get("rationale"),str) or
        not isinstance(decision.get("next_instruction"),str) or
        len(decision["rationale"])>8000 or
        len(decision["next_instruction"])>12000):
        raise ValueError("Supervisor decision schema/provenance invalid")
    from .watcher_autonomous import SECRET
    if ("\0" in decision["next_instruction"] or
            SECRET.search(decision["next_instruction"])):
        raise ValueError("Supervisor continuation must not carry credentials")
    return decision


def _queue_review(db,row,decision,turn,*,escalation=False,supervisor_url=None):
    task=db.execute("SELECT * FROM tasks WHERE project_id=? AND id=?",
        (row["project_id"],row["task_id"])).fetchone()
    if task is None or task["state"]!="watching":
        raise ValueError("Cannot prepare goal review for changed executor")
    message=(turn["answer"]+"\n\nSupervisor model opinion:\n"+
             decision["rationale"]+"\n\n"+REVIEW_NOTICE)
    event=legacy.prepare_delivery(db,task,message)
    db.execute("UPDATE deliveries SET payload=payload||? WHERE id=?",
               ("\n"+REVIEW_NOTICE,event["delivery_id"]))
    return _mark(db,row,
        "needs_input" if escalation else "review_ready",
        delivery_id=event["delivery_id"],
        supervisor_url=supervisor_url or row["supervisor_url"],
        review_revision=int(task["last_revision"]))


def _poll_reviewer(db,row,api):
    req=api("GET","/v1/requests/"+row["supervisor_request_id"])
    if (req.get("request_id")!=row["supervisor_request_id"]
        or req.get("session_id")!=row["supervisor_session_id"]
        or req.get("client_request_id")!=row["supervisor_client_id"]):
        return _mark(db,row,"uncertain","supervisor_request_identity_mismatch")
    state=req.get("status")
    if state in ("unknown","failed","interrupted"):
        return _mark(db,row,"uncertain","supervisor_request_"+str(state))
    if state!="completed":return {"state":"supervisor_submitted"}
    from .watcher_autonomous import _canonical_request_url
    try:
        url=_canonical_request_url(req)
        sid=row["supervisor_session_id"]
        route=api("GET","/v1/sessions/"+sid)
        initial.validate_session(route,sid,url)
        if row["supervisor_url"] and row["supervisor_url"]!=url:
            raise ValueError("Supervisor conversation was rebound")
        if not isinstance(req.get("assistant_message_id"),str) or not req["assistant_message_id"]:
            raise ValueError("Missing settled Supervisor assistant message")
        turn=_latest_turn(db,row)
        decision=_parse_decision(req.get("answer"),turn)
    except Exception:
        return _mark(db,row,"blocked","invalid_supervisor_decision_or_route")
    db.execute("""INSERT INTO goal_decisions
        (project_id,task_id,turn_index,supervisor_request_id,
         supervisor_message_id,source_message_id,action,rationale,
         decision_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (row["project_id"],row["task_id"],turn["turn_index"],
         row["supervisor_request_id"],req["assistant_message_id"],
         turn["assistant_message_id"],decision["action"],decision["rationale"],
         json.dumps(decision,ensure_ascii=False),legacy.utc()))
    if decision["action"]=="continue":
        if turn["turn_index"]>=row["max_turns"]:
            return _mark(db,row,"budget_exhausted","max_turns_reached",
                         supervisor_url=url)
        instruction=decision["next_instruction"]
        if not 25<=len(instruction)<=12000:
            return _mark(db,row,"needs_input","Supervisor omitted continuation instruction",
                         supervisor_url=url)
        key=("goal-exec-"+hashlib.sha256(
             (row["project_id"]+row["task_id"]+str(turn["turn_index"])).encode()
             ).hexdigest()[:32])
        return _mark(db,row,"continuation_pending",
                     supervisor_url=url,continuation_key=key,
                     continuation_prompt=instruction)
    if decision["action"]=="ready_for_orchestrator_review":
        # Only model decided readiness. Watcher does not inspect tests/files.
        result=_queue_review(db,row,decision,turn,supervisor_url=url)
        return result
    return _queue_review(db,row,decision,turn,escalation=True,
                         supervisor_url=url)


def _send_continuation(db,row,api):
    if not _ready_gateway(api):return {"state":"deferred"}
    session_row=db.execute("SELECT session_id FROM chatbridge_task_sessions "
        "WHERE project_id=? AND task_id=?",
        (row["project_id"],row["task_id"])).fetchone()
    task=db.execute("SELECT chat_url FROM tasks WHERE project_id=? AND id=?",
                    (row["project_id"],row["task_id"])).fetchone()
    if not session_row or not task:return _mark(db,row,"blocked","executor_route_missing")
    sid=session_row["session_id"]
    try:
        session=api("GET","/v1/sessions/"+sid)
        initial.validate_session(session,sid,task["chat_url"])
    except Exception:
        return _mark(db,row,"blocked","executor_session_rebound")
    _mark(db,row,"executor_sending")
    try:
        out=api("POST","/v1/sessions/"+sid+"/messages",{
            "content":row["continuation_prompt"],
            "client_request_id":row["continuation_key"]})
        rid=out.get("request_id") if isinstance(out,dict) else None
        if not isinstance(rid,str) or not rid:
            raise RuntimeError("Missing executor followup request")
    except PermissionError:
        return _mark(db,dict(row,state="executor_sending"),"blocked",
                     "platform_policy_denial")
    except Exception as exc:
        from .watcher_http_adapter import TransportError
        if isinstance(exc,TransportError) and ("HTTP 401" in str(exc) or
                                               "HTTP 403" in str(exc)):
            return _mark(db,dict(row,state="executor_sending"),"blocked",
                         "provider_auth_denied")
        return _mark(db,dict(row,state="executor_sending"),"uncertain",
                     "executor_post_outcome_unknown")
    return _mark(db,dict(row,state="executor_sending"),"executor_submitted",
                 executor_followup_request_id=rid)


def _poll_continuation(db,row,api):
    req=api("GET","/v1/requests/"+row["executor_followup_request_id"])
    task=db.execute("SELECT chat_url FROM tasks WHERE project_id=? AND id=?",
                    (row["project_id"],row["task_id"])).fetchone()
    sid=db.execute("SELECT session_id FROM chatbridge_task_sessions "
                   "WHERE project_id=? AND task_id=?",
                   (row["project_id"],row["task_id"])).fetchone()
    if not task or not sid or req.get("request_id")!=row["executor_followup_request_id"]:
        return _mark(db,row,"uncertain","executor_request_unbound")
    if (req.get("session_id")!=sid["session_id"] or
        req.get("client_request_id")!=row["continuation_key"]):
        return _mark(db,row,"uncertain","executor_request_identity_mismatch")
    if req.get("status") in ("failed","interrupted","unknown"):
        return _mark(db,row,"uncertain","executor_request_"+str(req["status"]))
    if req.get("status")!="completed":return {"state":"executor_submitted"}
    try:
        initial.validate_session(
            api("GET","/v1/sessions/"+sid["session_id"]),
            sid["session_id"],task["chat_url"])
        assert (req.get("conversation_id")==task["chat_url"].rsplit("/c/",1)[1])
        assert (req.get("project_id")==
            (task["chat_url"].split("/g/",1)[1].split("/",1)[0]
             if "/g/" in task["chat_url"] else None))
        assert record_settled(db,row["project_id"],row["task_id"],req)
    except (ValueError,AssertionError):
        return _mark(db,row,"uncertain","executor_result_provenance_failed")
    return {"state":"review_pending"}


def pump(db,api,*,dry_run=False,now=None):
    """One bounded Supervisor or executor edge per Watcher cycle."""
    setup(db)
    row=db.execute("SELECT * FROM goals WHERE state IN ("+
        ",".join("?" for _ in TRANSIENT)+") ORDER BY created_ts,project_id,task_id LIMIT 1",
        TRANSIENT).fetchone()
    if not row:return []
    if dry_run:return [{"state":row["state"],"would_process":True}]
    at=time.time() if now is None else float(now)
    if at-row["created_ts"]>row["max_elapsed_seconds"]:
        return [_mark(db,row,"budget_exhausted","max_elapsed_seconds_reached")]
    if row["state"]=="review_pending":
        result=_create_reviewer(db,row,api)
    elif row["state"]=="supervisor_session_ready":
        result=_submit_reviewer(db,row,api)
    elif row["state"]=="supervisor_submitted":
        result=_poll_reviewer(db,row,api)
    elif row["state"]=="continuation_pending":
        result=_send_continuation(db,row,api)
    else:
        result=_poll_continuation(db,row,api)
    return [result]


def quarantine_inflight(db):
    setup(db)
    return db.execute("""UPDATE goals SET
        state='uncertain',last_error='watcher_restart_mid_goal_send',
        updated_at=? WHERE state IN
        ('supervisor_session_creating','supervisor_sending','executor_sending')""",
        (legacy.utc(),)).rowcount


def _review_gate(db,row,owner,expected_revision):
    if not isinstance(owner,str) or row["owner_subject"]!=owner:
        raise PermissionError("Goal belongs to another authenticated owner")
    if row["state"]!="review_ready" or row["review_revision"]!=expected_revision:
        raise ValueError("No Supervisor-reviewed result at requested revision")
    event=db.execute("SELECT state,acknowledged_at FROM deliveries WHERE id=?",
                     (row["delivery_id"],)).fetchone()
    if not event or event["state"]!="delivered" or not event["acknowledged_at"]:
        raise ValueError("Orchestrator must read and ACK the delivered report")
    return event


def approve_goal(db,project,task,owner,*,expected_revision):
    setup(db)
    row=_goal(db,project,task)
    if row is None:raise ValueError("No opt-in goal")
    if row["state"]=="closed" and row["review_revision"]==expected_revision:
        if row["owner_subject"]!=owner:raise PermissionError("Owner mismatch")
        return {"closed":True,"duplicate":True}
    _review_gate(db,row,owner,expected_revision)
    _mark(db,row,"closed")
    return {"project_id":project,"task_id":task,"closed":True}


def return_for_rework(db,project,task,owner,instruction,request_key,*,expected_revision):
    setup(db)
    row=_goal(db,project,task)
    if row is None:raise ValueError("No opt-in goal")
    if (row["state"]=="continuation_pending" and
        row["continuation_key"]==request_key and
        row["continuation_prompt"]==instruction and
        row["owner_subject"]==owner):
        return {"state":"continuation_pending","duplicate":True}
    _review_gate(db,row,owner,expected_revision)
    from .watcher_autonomous import SECRET
    if (not isinstance(instruction,str) or not 25<=len(instruction)<=12000
            or "\0" in instruction or SECRET.search(instruction)):
        raise ValueError("Invalid rework prompt")
    from .watcher_browser_dispatch import KEY_RX
    if not isinstance(request_key,str) or not KEY_RX.fullmatch(request_key):
        raise ValueError("Invalid rework idempotency key")
    if db.execute("SELECT 1 FROM goals WHERE continuation_key=?",
                  (request_key,)).fetchone():
        raise ValueError("Rework key is already allocated")
    task_row=db.execute("SELECT last_revision FROM tasks WHERE project_id=? AND id=?",
                        (project,task)).fetchone()
    if not task_row or task_row["last_revision"]!=expected_revision:
        raise ValueError("Review revision changed")
    if _latest_turn(db,row)["turn_index"]>=row["max_turns"]:
        return _mark(db,row,"budget_exhausted","max_executor_turns_reached")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""UPDATE tasks SET state='watching',last_revision=last_revision+1,
           last_hash=NULL,stable_since=NULL,error=NULL,result_sha256=NULL,
           result_path=NULL,complete_at=NULL
           WHERE project_id=? AND id=? AND state='completed'""",
           (project,task))
        db.execute("""UPDATE goals SET state='continuation_pending',
            continuation_key=?,continuation_prompt=?,last_error=NULL,
            updated_at=? WHERE project_id=? AND task_id=? AND state='review_ready'""",
            (request_key,instruction,legacy.utc(),project,task))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK");raise
    return {"project_id":project,"task_id":task,
            "state":"continuation_pending","revision":expected_revision+1}
