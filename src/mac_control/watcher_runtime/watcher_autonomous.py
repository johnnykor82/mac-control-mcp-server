"""BF23: durable, owner-bound autonomous browser workers via verified ChatBridge.

Never trusts a marker as authentication. The MCP owner is authenticated before
enqueue. No worker chat URL or browser session is supplied by the caller.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import uuid

from . import multi_project_watcher as legacy
from . import watcher_browser_dispatch as initial
from . import watcher_chat_resolver as marker_resolver
from .watcher_browser_followups import MAX_PROMPT

STATES = (
    "marker_pending", "session_pending", "session_creating", "session_ready",
    "sending", "submitted", "bound", "completed", "uncertain", "blocked",
    "needs_input",
)
ACTIVE = ("marker_pending", "session_pending", "session_ready", "submitted")
SECRET = re.compile(
    r"authorization\s*:\s*bearer|submission_token|orchestrator_token|"
    r"capability_token|session_cookie", re.IGNORECASE
)
MAX_MARKER_ATTEMPTS = 12
MAX_DELAY_SECONDS = 900


def setup(db: sqlite3.Connection) -> None:
    initial.setup(db)
    marker_resolver.setup(db)
    db.execute("""CREATE TABLE IF NOT EXISTS autonomous_subagents (
        project_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        orchestrator_marker TEXT NOT NULL,
        orchestrator_url TEXT,
        owner_subject TEXT NOT NULL,
        prompt TEXT NOT NULL,
        prompt_sha256 TEXT NOT NULL,
        request_key TEXT NOT NULL UNIQUE,
        state TEXT NOT NULL CHECK(state IN (
            'marker_pending','session_pending','session_creating',
            'session_ready','sending','submitted','bound','completed',
            'uncertain','blocked','needs_input')),
        marker_attempts INTEGER NOT NULL DEFAULT 0,
        next_lookup_at REAL NOT NULL DEFAULT 0,
        session_id TEXT UNIQUE,
        request_id TEXT UNIQUE,
        executor_url TEXT UNIQUE,
        assistant_message_id TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(project_id,task_id)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_autonomous_state "
               "ON autonomous_subagents(state,next_lookup_at)")


def _validate(project, task, marker, prompt, key, owner):
    legacy.require_name(project)
    legacy.require_name(task)
    if not isinstance(marker, str) or not marker_resolver.MARKER.fullmatch(marker):
        raise ValueError("A unique WATCHER-CHAT-<32 lowercase hex> marker is required")
    if not isinstance(owner, str) or not owner.isascii() or not owner.isdecimal():
        raise PermissionError("Verified GitHub owner required")
    if not isinstance(key, str) or initial.KEY_RX.fullmatch(key) is None:
        raise ValueError("Stable nonsecret 8-72 character request key required")
    if not isinstance(prompt, str) or not 25 <= len(prompt) <= MAX_PROMPT:
        raise ValueError("Invalid prompt size")
    if "\0" in prompt or SECRET.search(prompt):
        raise ValueError("Credential-bearing prompt prohibited")
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def enqueue(db, project, task, marker, prompt, key, owner):
    """Persist immutable pending request BEFORE any external browser operation."""
    digest = _validate(project, task, marker, prompt, key, owner)
    setup(db)
    db.execute("BEGIN IMMEDIATE")
    try:
        known = db.execute("""SELECT * FROM autonomous_subagents
            WHERE request_key=? OR (project_id=? AND task_id=?)""",
                           (key, project, task)).fetchone()
        if known:
            if known["owner_subject"] != owner:
                raise PermissionError("Subagent belongs to another owner")
            if (known["project_id"] != project or known["task_id"] != task
                    or known["orchestrator_marker"] != marker
                    or known["prompt_sha256"] != digest
                    or known["request_key"] != key):
                raise ValueError("Idempotency key or task differs from immutable request")
            result = {"project_id": project, "task_id": task,
                      "state": known["state"], "duplicate": True}
            db.execute("COMMIT")
            return result
        existing = db.execute(
            "SELECT owner_subject FROM chatbridge_browser_project_owners "
            "WHERE project_id=?", (project,)).fetchone()
        if existing and existing["owner_subject"] != owner:
            raise PermissionError("Project is owned by another authenticated GitHub user")
        if db.execute("SELECT 1 FROM projects WHERE id=?", (project,)).fetchone() and not existing:
            raise PermissionError("Cannot adopt legacy project into owner-bound BF23")
        conflicting = db.execute("""SELECT 1 FROM autonomous_subagents
            WHERE project_id=? AND orchestrator_marker<>? LIMIT 1""",
                                 (project, marker)).fetchone()
        if conflicting:
            raise ValueError("Project's orchestrator marker is immutable")
        if db.execute("SELECT 1 FROM tasks WHERE project_id=? AND id=?",
                      (project, task)).fetchone():
            raise ValueError("An existing task cannot be claimed")
        now = legacy.utc()
        db.execute("""INSERT INTO autonomous_subagents
            (project_id,task_id,orchestrator_marker,owner_subject,
             prompt,prompt_sha256,request_key,state,created_at,updated_at)
             VALUES(?,?,?,?,?,?,?,'marker_pending',?,?)""",
                   (project,task,marker,owner,prompt,digest,key,now,now))
        db.execute("COMMIT")
        return {"project_id":project,"task_id":task,
                "state":"marker_pending","duplicate":False}
    except BaseException:
        db.execute("ROLLBACK")
        raise


def safe_status(db, project: str | None = None):
    setup(db)
    query = """SELECT project_id,task_id,state,marker_attempts,request_id,
        session_id,executor_url,last_error,created_at,updated_at
        FROM autonomous_subagents"""
    query += " WHERE project_id=?" if project else ""
    return [dict(x) for x in db.execute(query, (project,) if project else ())]


def _mark(db, row, state, error=None, **changes):
    fields = ["state=?", "last_error=?", "updated_at=?"]
    values = [state, error, legacy.utc()]
    for key,value in changes.items():
        if key not in ("orchestrator_url", "session_id", "request_id",
                       "executor_url", "assistant_message_id",
                       "marker_attempts", "next_lookup_at"):
            raise ValueError("Invalid state field")
        fields.append(key+"=?")
        values.append(value)
    values.extend((row["project_id"],row["task_id"],row["state"]))
    changed=db.execute("UPDATE autonomous_subagents SET "+",".join(fields)+
        " WHERE project_id=? AND task_id=? AND state=?", tuple(values)).rowcount
    if changed != 1:
        raise ValueError("Autonomous worker changed concurrently")
    return {"task":row["project_id"]+"/"+row["task_id"], "state":state}


def _status(api):
    data=api("GET", "/v1/system/status")
    if data.get("rate_limit", {}).get("provider_rate_limited"):
        return False
    return int(data.get("active") or 0) < 1


def _lookup(db, row, api, now):
    marker=row["orchestrator_marker"]
    try:
        identity=marker_resolver.resolve(marker, db=db, transport=api)
        source=db.execute(
            "SELECT source FROM chat_marker_registry WHERE marker=?",
            (marker,)).fetchone()
        if (identity.get("evidence_verified") is not True
            or identity.get("matches") != 1 or not source
            or source["source"] != "chatbridge_verified_assistant_message"):
            return _mark(db,row,"blocked","not_verified_assistant_marker")
        url=legacy.canonical_url(identity["chat_url"])
        initial.register_owned_project(db,row["project_id"],url,
                                       row["owner_subject"])
        return _mark(db,row,"session_pending",orchestrator_url=url)
    except Exception as exc:
        from .watcher_http_adapter import TransportError
        detail=str(exc)
        if isinstance(exc,TransportError) and "HTTP 404" in detail:
            attempts=row["marker_attempts"]+1
            if attempts >= MAX_MARKER_ATTEMPTS:
                return _mark(db,row,"needs_input","marker_not_indexed",
                             marker_attempts=attempts)
            wait=min(30*2**(attempts-1),MAX_DELAY_SECONDS)
            return _mark(db,row,"marker_pending","awaiting_chatgpt_search_index",
                         marker_attempts=attempts,next_lookup_at=now+wait)
        if isinstance(exc,TransportError) and ("HTTP 409" in detail):
            return _mark(db,row,"blocked","ambiguous_marker")
        if isinstance(exc,(PermissionError,ValueError)):
            return _mark(db,row,"blocked","marker_identity_rejected")
        # Read-only lookup can be retried, but not a provider message POST.
        attempts=row["marker_attempts"]+1
        if attempts >= MAX_MARKER_ATTEMPTS:
            return _mark(db,row,"needs_input","marker_lookup_unavailable",
                         marker_attempts=attempts)
        return _mark(db,row,"marker_pending","marker_lookup_unavailable",
                     marker_attempts=attempts,
                     next_lookup_at=now+min(30*2**(attempts-1),MAX_DELAY_SECONDS))


def _create_session(db,row,api):
    if not _status(api):
        return {"task":row["project_id"]+"/"+row["task_id"],"state":"deferred"}
    # From this point, a crash/timeout cannot safely allocate a second session.
    _mark(db,row,"session_creating")
    try:
        response=api("POST","/v1/sessions",{
            "mode":"persistent",
            "title":"Watcher executor "+row["project_id"]+"/"+row["task_id"],
        })
        sid=response.get("session_id") if isinstance(response,dict) else None
        if not isinstance(sid,str) or not sid:
            raise RuntimeError("Missing ChatBridge session ID")
        session=api("GET","/v1/sessions/"+sid)
        if (session.get("session_id")!=sid or session.get("mode")!="persistent"
              or session.get("conversation_id") is not None
              or session.get("project_id") is not None):
            raise ValueError("New session was pre-bound or mismatched")
    except Exception:
        return _mark(db,dict(row,state="session_creating"),"uncertain",
                     "session_create_outcome_unknown")
    return _mark(db,dict(row,state="session_creating"),"session_ready",
                 session_id=sid)


def _send_first(db,row,api):
    if not _status(api):
        return {"task":row["project_id"]+"/"+row["task_id"],"state":"deferred"}
    sid=row["session_id"]
    try:
        sess=api("GET","/v1/sessions/"+sid)
        if (sess.get("session_id")!=sid or sess.get("mode")!="persistent"
              or sess.get("project_id") is not None
              or sess.get("conversation_id") is not None):
            return _mark(db,row,"blocked","pre_send_session_route_mismatch")
    except Exception:
        return _mark(db,row,"uncertain","session_verification_unavailable")
    _mark(db,row,"sending")
    try:
        response=api("POST","/v1/sessions/"+sid+"/messages",
                     {"content":row["prompt"],
                      "client_request_id":row["request_key"]})
        rid=response.get("request_id") if isinstance(response,dict) else None
        if not isinstance(rid,str) or not rid:
            raise RuntimeError("Missing ChatBridge request ID")
    except PermissionError:
        return _mark(db,dict(row,state="sending"),"blocked","platform_policy_denial")
    except Exception as exc:
        from .watcher_http_adapter import TransportError
        if (isinstance(exc,TransportError)
                and ("HTTP 401" in str(exc) or "HTTP 403" in str(exc))):
            return _mark(db,dict(row,state="sending"),"blocked","provider_auth_denied")
        return _mark(db,dict(row,state="sending"),"uncertain",
                     "initial_post_outcome_unknown")
    return _mark(db,dict(row,state="sending"),"submitted",request_id=rid)


def _canonical_request_url(request):
    conv=request.get("conversation_id")
    try:
        canonical=str(uuid.UUID(conv))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("ChatBridge final conversation ID missing/invalid") from None
    project=request.get("project_id")
    if project is None:
        return legacy.canonical_url("https://chatgpt.com/c/"+canonical)
    if not isinstance(project,str) or not re.fullmatch(r"g-p-[0-9a-f]{32}",project):
        raise ValueError("Unverified provider project ID")
    return legacy.canonical_url("https://chatgpt.com/g/"+project+"/c/"+canonical)


def _bind_result(db,row,api):
    req=api("GET","/v1/requests/"+row["request_id"])
    if (req.get("request_id")!=row["request_id"] or
        req.get("session_id")!=row["session_id"] or
        req.get("client_request_id")!=row["request_key"]):
        return _mark(db,row,"uncertain","request_identity_mismatch")
    status=req.get("status")
    if status in ("failed","interrupted","unknown"):
        return _mark(db,row,"uncertain","provider_request_"+str(status))
    if status!="completed":
        return {"task":row["project_id"]+"/"+row["task_id"],"state":"submitted"}
    try:
        url=_canonical_request_url(req)
        sid=row["session_id"]
        session=api("GET","/v1/sessions/"+sid)
        initial.validate_session(session,sid,url)
        message_id=req.get("assistant_message_id")
        if (not isinstance(message_id,str) or not message_id
                or not isinstance(req.get("answer"),str) or not req["answer"]):
            raise ValueError("No final assistant turn")
        if url==row["orchestrator_url"]:
            raise ValueError("Executor cannot be orchestrator")
        initial.setup(db)
        db.execute("BEGIN IMMEDIATE")
        try:
            current=db.execute("""SELECT state FROM autonomous_subagents
                WHERE project_id=? AND task_id=?""",
                (row["project_id"],row["task_id"])).fetchone()
            if not current or current["state"]!="submitted":
                raise ValueError("Concurrent source-bound change")
            legacy.register_task(db,row["project_id"],row["task_id"],url)
            db.execute("""INSERT INTO chatbridge_task_sessions
                (project_id,task_id,session_id) VALUES(?,?,?)""",
                (row["project_id"],row["task_id"],sid))
            db.execute("""INSERT INTO chatbridge_browser_dispatches
                (project_id,task_id,executor_url,session_id,owner_subject,
                client_request_id,prompt,prompt_sha256,state,request_id,
                assistant_message_id,created_at)
                VALUES(?,?,?,?,?,?,?,?,'submitted',?,?,?)""",
                (row["project_id"],row["task_id"],url,sid,row["owner_subject"],
                 row["request_key"],row["prompt"],row["prompt_sha256"],
                 row["request_id"],message_id,row["created_at"]))
            db.execute("""UPDATE autonomous_subagents
                SET state='bound',executor_url=?,assistant_message_id=?,
                updated_at=?,last_error=NULL
                WHERE project_id=? AND task_id=? AND state='submitted'""",
                (url,message_id,legacy.utc(),row["project_id"],row["task_id"]))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    except Exception:
        return _mark(db,row,"uncertain","completed_turn_binding_failed")
    return {"task":row["project_id"]+"/"+row["task_id"],
            "state":"bound","executor_url":url}


def pump(db,api,*,now=None,dry_run=False):
    """One durable provider edge per tick; existing Watcher owns report delivery."""
    setup(db)
    at=time.time() if now is None else float(now)
    row=db.execute("""SELECT * FROM autonomous_subagents
        WHERE (state='marker_pending' AND next_lookup_at<=?)
          OR state IN ('session_pending','session_ready','submitted')
        ORDER BY created_at,task_id LIMIT 1""",(at,)).fetchone()
    if not row:
        return []
    if dry_run:
        return [{"task":row["project_id"]+"/"+row["task_id"],
                 "state":row["state"],"would_process":True}]
    state=row["state"]
    if state=="marker_pending":
        result=_lookup(db,row,api,at)
    elif state=="session_pending":
        result=_create_session(db,row,api)
    elif state=="session_ready":
        result=_send_first(db,row,api)
    else:
        result=_bind_result(db,row,api)
    return [result]


def quarantine_inflight(db):
    """Startup: never replay an ambiguous session-create or message POST."""
    setup(db)
    return db.execute("""UPDATE autonomous_subagents SET
        state='uncertain',last_error='watcher_restart_while_sending',
        updated_at=?
        WHERE state IN ('session_creating','sending')""",
                      (legacy.utc(),)).rowcount


def sync_completed(db):
    """Expose completed state only when legacy immutably indexed the report."""
    setup(db)
    db.execute("""UPDATE autonomous_subagents SET state='completed',
        updated_at=? WHERE state='bound' AND EXISTS(
        SELECT 1 FROM tasks t WHERE t.project_id=autonomous_subagents.project_id
        AND t.id=autonomous_subagents.task_id AND t.state='completed'
        AND t.result_sha256 IS NOT NULL)""", (legacy.utc(),))
