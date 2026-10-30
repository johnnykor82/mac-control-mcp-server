"""Watcher-to-ChatBridge HTTP transport, independent of Chrome/CDP/DOM.

Reuses Watcher's SQLite queue and schedule metadata. A delivery is never
blindly duplicated: a stable client_request_id maps to exactly one gateway
request, surviving process interruption. Existing paused projects stay paused.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import multi_project_watcher as legacy
from . import watcher_telemetry as telemetry

from .config import api_key, gateway
BASE = gateway()
TERMINAL = {"completed", "failed", "interrupted", "unknown"}
TIMEOUT = 30
POLL_SECONDS = 20


class TransportError(RuntimeError):
    pass


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransportError("ChatBridge redirects are not permitted")


_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}), RejectRedirects())


def api(method: str, path: str, payload: dict | None = None):
    if not path.startswith("/") or "://" in path:
        raise ValueError("Invalid API path")
    headers = {"Accept": "application/json"}
    token = api_key()
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    started = time.monotonic()
    outcome = "ok"
    try:
        with _HTTP.open(req, timeout=TIMEOUT) as response:
            return json.loads(response.read(6 * 1024 * 1024))
    except urllib.error.HTTPError as e:
        outcome = "http_429" if e.code == 429 else ("http_503" if e.code == 503 else "http_error")
        raise TransportError(f"ChatBridge HTTP {e.code}") from None
    except (OSError, ValueError) as e:
        outcome = "transport_error"
        raise TransportError(f"ChatBridge transport {type(e).__name__}") from e
    finally:
        # Passive in-memory aggregation: NEVER hold up a request for telemetry.
        try:
            telemetry.observe(method, path, outcome, time.monotonic() - started)
        except Exception:  # noqa: BLE001, S110 - telemetry must never block delivery
            pass


def setup(db: sqlite3.Connection):
    db.execute("""
        CREATE TABLE IF NOT EXISTS chatbridge_delivery_links(
            delivery_id TEXT PRIMARY KEY REFERENCES deliveries(id),
            session_id TEXT NOT NULL,
            request_id TEXT,
            last_status TEXT,
            last_checked_at TEXT,
            last_error TEXT
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_cb_delivery_status ON chatbridge_delivery_links(last_status)")
    db.execute("""CREATE TABLE IF NOT EXISTS chatbridge_task_sessions (
        project_id TEXT NOT NULL,task_id TEXT NOT NULL,
        session_id TEXT NOT NULL,PRIMARY KEY(project_id,task_id)
    )""")
    from .watcher_browser_followups import setup as setup_followups
    setup_followups(db)
    from .watcher_busy_batch import setup as setup_batches
    setup_batches(db)
    # Local gateway request lookup and bounded remote polling. Both are
    # additive to the durable Watcher SQLite schema.
    db.execute("""CREATE TABLE IF NOT EXISTS chatbridge_task_request_links(
        project_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        PRIMARY KEY(project_id,task_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS chatbridge_external_poll_budget(
        project_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        next_check_at REAL NOT NULL DEFAULT 0,
        PRIMARY KEY(project_id,task_id)
    )""")


def marker_already_present(session_id: str, delivery_id: str):
    """Check only the gateway's existing SQLite copy: NEVER refresh provider history.

    The persisted client_request_id is the authority for exactly-once delivery
    after a crash. A previously imported marker is merely a cheap extra guard.
    """
    token = f"[MC-WATCH:{delivery_id}]"
    cursor = 0
    for _ in range(100):
        response = api("GET", f"/v1/sessions/{session_id}/messages?limit=500&after={cursor}")
        rows = response.get("data", [])
        if any(row.get("role") == "user" and token in str(row.get("content") or "")
               for row in rows):
            return True
        next_cursor = response.get("next_cursor", cursor)
        if not rows or next_cursor == cursor:
            return False
        cursor = next_cursor
    raise TransportError("Local gateway history exceeded supported scan size")


def session_import(url: str, title: str) -> dict:
    """Explicitly bind Watcher conversations; never rely on gateway defaults."""
    target = legacy.canonical_url(url)
    result = {"url": target, "title": title, "mode": "persistent"}
    match = re.match(r"https://chatgpt[.]com/g/(g-p-[0-9a-f]{32})/c/", target)
    if match:
        result["project_id"] = match.group(1)
    return result


def verify_route(record, sid, url, *, require_project=True):
    """Fail closed when a gateway identity no longer names the physical chat."""
    target = legacy.canonical_url(url)
    match = re.search(r"/g/(g-p-[0-9a-f]{32})/c/", target)
    expected_project = match.group(1) if match else None
    if (not isinstance(record, dict) or record.get("session_id") != sid
            or record.get("conversation_id") != target.rsplit("/c/", 1)[1]
            or ((require_project or "project_id" in record)
                and record.get("project_id") != expected_project)):
        raise TransportError("ChatBridge physical chat identity mismatch")


def guard_orchestrator(db: sqlite3.Connection, delivery, sid: str) -> None:
    """Protect a Watcher-owned physical chat against unsafe session rotation.

    Older ChatBridge 'standard' sessions are not rotatable; preserve their
    existing delivery path. A persistent/continued session requires a durable
    guard confirmed by ChatBridge before any subsequent model submission.
    These are local HTTP operations only, never ChatGPT provider calls.
    """
    session = api("GET", f"/v1/sessions/{sid}")
    verify_route(session, sid, delivery["orchestrator_url"])
    if session.get("mode") == "standard":
        return  # legacy standard sessions cannot be rotated in ChatBridge
    if session.get("mode") not in ("persistent", "continued"):
        raise TransportError("Watcher target has unexpected session mode")
    project_id = str(delivery["project_id"])
    stable_id = "watcher_orchestrator_" + hashlib.sha256(project_id.encode()).hexdigest()[:24]
    response = api("PUT", f"/v1/sessions/{sid}/rotation-guards/{stable_id}", {
        "owner": "watcher", "reason": "Orchestrator pinned; pending deliveries or wakeups",
    })
    if (not isinstance(response, dict) or response.get("session_id") != sid
            or response.get("guard_id") != stable_id or response.get("owner") != "watcher"):
        raise TransportError("ChatBridge orchestrator rotation guard not confirmed")
    # Rotation may have finished between the first identity read and guard.
    # Once the guard is held, the rechecked physical target stays pinned.
    verify_route(api("GET", f"/v1/sessions/{sid}"), sid, delivery["orchestrator_url"])


def ensure_session(db: sqlite3.Connection, delivery):
    link = db.execute(
        "SELECT * FROM chatbridge_delivery_links WHERE delivery_id=?",
        (delivery["id"],),
    ).fetchone()
    if link:
        guard_orchestrator(db, delivery, link["session_id"])
        return link["session_id"], link["request_id"]
    # Subsequent notifications to one orchestrator must reuse the same
    # gateway session: project session re-import can itself trigger a new
    # provider-authenticated page/history verification. Consult SQLite
    # delivery links first, then validate the saved identity via local GET.
    previous = db.execute("""
        SELECT l.session_id FROM chatbridge_delivery_links l
        JOIN deliveries d ON d.id=l.delivery_id
        WHERE d.project_id=? AND d.orchestrator_url=? AND d.id<>?
        ORDER BY d.created_at DESC, d.rowid DESC LIMIT 1
    """, (delivery["project_id"], delivery["orchestrator_url"], delivery["id"])).fetchone()
    if previous:
        sid = previous["session_id"]
        session = api("GET", f"/v1/sessions/{sid}")
        target = legacy.canonical_url(delivery["orchestrator_url"])
        pid_match = re.search(r"/g/(g-p-[0-9a-f]{32})/c/", target)
        expected_project = pid_match.group(1) if pid_match else None
        expected_conversation = target.rsplit("/c/", 1)[1]
        if (
            session.get("session_id") != sid
            or session.get("mode") != "persistent"
            or session.get("conversation_id") != expected_conversation
            or session.get("project_id") != expected_project
        ):
            db.execute(
                "UPDATE deliveries SET state='delivery_uncertain',last_error='session_route_mismatch' "
                "WHERE id=?", (delivery["id"],)
            )
            raise TransportError("Cached orchestrator session identity mismatch")
    else:
        session = api("POST", "/v1/sessions", session_import(
            delivery["orchestrator_url"], "watcher:" + delivery["project_id"],
        ))
        sid = session["session_id"]
    guard_orchestrator(db, delivery, sid)
    db.execute(
        "INSERT OR IGNORE INTO chatbridge_delivery_links(delivery_id,session_id,last_status) VALUES(?,?,'prepared')",
        (delivery["id"], sid),
    )
    row = db.execute(
        "SELECT session_id,request_id FROM chatbridge_delivery_links WHERE delivery_id=?",
        (delivery["id"],),
    ).fetchone()
    return row["session_id"], row["request_id"]


def finish(db, delivery_id, request, status):
    if status == "completed":
        db.execute(
            "UPDATE deliveries SET state='delivered',delivered_at=?,last_error=NULL WHERE id=?",
            (legacy.utc(), delivery_id),
        )
        return {"id": delivery_id, "state": "delivered", "request_id": request}
    if status in {"failed", "interrupted", "unknown"}:
        # A failed request may already have delivered the user message.
        # Never send a new request without operator reconciliation.
        db.execute(
            "UPDATE deliveries SET state='delivery_uncertain',last_error=? WHERE id=?",
            (f"ChatBridge {status}: request_id={request}", delivery_id),
        )
        return {"id": delivery_id, "state": "delivery_uncertain", "request_id": request}
    return {"id": delivery_id, "state": "attempting", "request_id": request}


def process_one(db, delivery, dry_run: bool = False):
    did = delivery["id"]
    project = db.execute(
        "SELECT status,orchestrator_url FROM projects WHERE id=?",
        (delivery["project_id"],),
    ).fetchone()
    if not project or project["status"] != "enabled":
        return {"id": did, "state": "deferred", "reason": "project_not_enabled"}
    if legacy.canonical_url(delivery["orchestrator_url"]) != project["orchestrator_url"]:
        db.execute(
            "UPDATE deliveries SET state='delivery_uncertain',last_error='route_changed' WHERE id=?",
            (did,),
        )
        return {"id": did, "state": "delivery_uncertain", "reason": "route_changed"}
    if dry_run:
        return {"id": did, "state": delivery["state"], "would_send": True,
                "project_id": delivery["project_id"]}
    sid, rid = ensure_session(db, delivery)
    if rid:
        status = api("GET", f"/v1/requests/{rid}")["status"]
        db.execute(
            "UPDATE chatbridge_delivery_links SET last_status=?,last_checked_at=? WHERE delivery_id=?",
            (status, legacy.utc(), did),
        )
        return finish(db, did, rid, status)
    if delivery["state"] == "ready":
        if marker_already_present(sid, did):
            db.execute(
                "UPDATE deliveries SET state='delivered',delivered_at=?,last_error=NULL WHERE id=?",
                (legacy.utc(), did),
            )
            db.execute(
                "UPDATE chatbridge_delivery_links SET last_status='deduplicated' WHERE delivery_id=?",
                (did,),
            )
            return {"id": did, "state": "delivered", "deduplicated": True}
        db.execute(
            "UPDATE deliveries SET state='attempting',attempts=attempts+1 WHERE id=?",
            (did,),
        )
    # If the process crashed after POST but before persisting request_id, the
    # same session+key returns the *existing* gateway request without resending.
    response = api("POST", f"/v1/sessions/{sid}/messages", {
        "content": delivery["payload"],
        "client_request_id": "watcher-delivery-" + did,
    })
    rid = response["request_id"]
    db.execute(
        "UPDATE chatbridge_delivery_links SET request_id=?,last_status=?,last_checked_at=? WHERE delivery_id=?",
        (rid, response.get("status", "queued"), legacy.utc(), did),
    )
    return {"id": did, "state": "attempting", "request_id": rid}


def queue_followup_alert(db, project: str, task: str, revision: int, reason: str):
    """Escalate uncertain revisions to orchestrator without another model call."""
    import hashlib
    event_id=hashlib.sha256(
        f"watcher/followup-uncertain/{project}/{task}/{revision}".encode()
    ).hexdigest()[:32]
    owner=db.execute(
        "SELECT orchestrator_url FROM projects WHERE id=?", (project,)
    ).fetchone()
    if not owner:
        raise ValueError("Missing orchestrator for follow-up uncertainty")
    note=(
        f"[MC-WATCH:{event_id}]\n"
        "Watcher: executor continuation requires reconciliation; NOT completed.\n"
        f"Project: {project}\nTask: {task}\nRevision: {revision}\n"
        f"Reason: {reason}\n"
        "No automatic resend was attempted. Inspect watcher_status.browser_followups "
        "and the ChatBridge request before deciding how to proceed."
    )
    db.execute("""INSERT OR IGNORE INTO deliveries
        (id,project_id,task_id,orchestrator_url,payload,state,created_at)
        VALUES(?,?,?,?,?,'ready',?)""",
        (event_id,project,task,owner["orchestrator_url"],note,legacy.utc()))
    return event_id


def quarantine_crashed_followups(db):
    """On exclusive Watcher startup, recover pre-POST states without resending.

    A request may have reached ChatGPT even if the process died before the
    HTTP acknowledgement was recorded. A new worker must not blindly POST
    the same prompt; notify the orchestrator for read-only reconciliation.
    """
    from .watcher_browser_followups import setup as setup_followups
    setup_followups(db)
    rows=db.execute("""SELECT project_id,task_id,revision FROM
        chatbridge_browser_followups WHERE state='sending'""").fetchall()
    alerts=[]
    for r in rows:
        db.execute("BEGIN IMMEDIATE")
        try:
            changed=db.execute("""UPDATE chatbridge_browser_followups SET
                state='uncertain',last_error='watcher_restarted_during_send'
                WHERE project_id=? AND task_id=? AND revision=? AND state='sending'""",
                (r["project_id"],r["task_id"],r["revision"])).rowcount
            if changed:
                eid=queue_followup_alert(db,r["project_id"],r["task_id"],
                                         r["revision"],"watcher_restarted_during_send")
                alerts.append({"task":r["project_id"]+"/"+r["task_id"],
                               "state":"uncertain","delivery_id":eid})
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    return alerts


def dispatch_prepared_followups(db, dry_run: bool = False):
    """Dispatch queued revisions with idempotent IDs; quarantine lost ACK."""
    from .watcher_browser_followups import prepare_for_dispatch
    rows=prepare_for_dispatch(db)
    if dry_run:
        return [{"task":r["project_id"]+"/"+r["task_id"],"would_send":True} for r in rows]
    if not rows:
        return []
    gateway=api("GET","/v1/system/status")
    if gateway.get("rate_limit",{}).get("provider_rate_limited"):
        return [{"state":"deferred","reason":"provider_cooldown"}]
    # Even two overlapping expensive ChatGPT tool sessions can trigger
    # provider-wide 429; launch the next turn only after the last finishes.
    if int(gateway.get("active") or 0) >= 1:
        return [{"state":"deferred","reason":"other_request_active"}]
    output=[]
    for r in rows[:1]:
        name=r["project_id"]+"/"+r["task_id"]
        task=db.execute("SELECT chat_url FROM tasks WHERE project_id=? AND id=?",
                        (r["project_id"],r["task_id"])).fetchone()
        target=legacy.canonical_url(task["chat_url"])
        expected_project=target.split("/g/",1)[1].split("/",1)[0] if "/g/" in target else None
        try:
            session=api("GET","/v1/sessions/"+r["session_id"])
            if (session.get("conversation_id")!=target.rsplit("/c/",1)[1]
                    or session.get("project_id")!=expected_project
                    or session.get("mode")!="persistent"):
                raise ValueError("executor_session_route_mismatch")
        except (TransportError,ValueError) as exc:
            db.execute("""UPDATE chatbridge_browser_followups
                SET state='uncertain',last_error=? WHERE
                project_id=? AND task_id=? AND revision=?""",
                (type(exc).__name__,r["project_id"],r["task_id"],r["revision"]))
            queue_followup_alert(db,r["project_id"],r["task_id"],
                                 r["revision"],"session_route_mismatch")
            output.append({"task":name,"state":"uncertain","reason":"session_mismatch"})
            continue
        # Durable pre-POST marker: a process crash must not cause an
        # automatic re-POST. Use explicit operator reconciliation instead.
        db.execute("""UPDATE chatbridge_browser_followups SET state='sending'
            WHERE project_id=? AND task_id=? AND revision=? AND state='prepared'""",
            (r["project_id"],r["task_id"],r["revision"]))
        try:
            response=api("POST",f"/v1/sessions/{r['session_id']}/messages",{
                "content":r["prompt"],"client_request_id":r["client_request_id"]})
            rid=response["request_id"]
            if not isinstance(rid,str) or not rid:
                raise TransportError("Missing gateway request ID")
        except (TransportError,KeyError) as exc:
            db.execute("""UPDATE chatbridge_browser_followups
                SET state='uncertain',last_error=? WHERE
                project_id=? AND task_id=? AND revision=?""",
                (type(exc).__name__,r["project_id"],r["task_id"],r["revision"]))
            queue_followup_alert(db,r["project_id"],r["task_id"],
                                 r["revision"],"send_ack_missing")
            output.append({"task":name,"state":"uncertain","reason":"submit_ack_missing"})
            continue
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""UPDATE chatbridge_browser_followups SET
                state='submitted',request_id=?,last_error=NULL WHERE
                project_id=? AND task_id=? AND revision=? AND state='sending'""",
                (rid,r["project_id"],r["task_id"],r["revision"]))
            db.execute("""UPDATE tasks SET state='watching',last_revision=?,
                last_hash=NULL,stable_since=NULL,last_text_size=0,
                result_path=NULL,result_sha256=NULL,complete_at=NULL,error=NULL
                WHERE project_id=? AND id=? AND state='completed'""",
                (r["revision"],r["project_id"],r["task_id"]))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        output.append({"task":name,"state":"watching","revision":r["revision"],
                       "request_id":rid})
    return output


def _local_request_for_executor(db, task, session_id):
    """Use saved provider-verified gateway requests without browsing ChatGPT.

    If the executor was submitted through ChatBridge, it has a durable local
    request ID. Local listing and GET /requests don't fetch provider history.
    An externally authored conversation has no gateway request, and returns None.
    """
    p,t=task["project_id"],task["id"]
    cid=legacy.canonical_url(task["chat_url"]).rsplit("/c/",1)[1]
    linked=db.execute("""SELECT request_id FROM chatbridge_task_request_links
        WHERE project_id=? AND task_id=?""",(p,t)).fetchone()
    if linked:
        req=api("GET","/v1/requests/"+linked["request_id"])
        if req.get("request_id")!=linked["request_id"] or req.get("session_id")!=session_id:
            raise TransportError("Saved gateway request identity mismatch")
        if req.get("conversation_id") not in (None,cid):
            raise TransportError("Saved gateway request changed conversation")
        return req

    # Read purely local gateway SQLite summary; unlike /turn-state, this does
    # NOT create a Chrome page and requires no provider session/history fetch.
    # ChatBridge caps requested pagination at 250 even if limit=500 is sent.
    # Use the actual API maximum to avoid silently missing later sessions.
    page_size=250
    for offset in range(0,4000,page_size):
        data=api("GET",f"/v1/sessions?limit={page_size}&offset={offset}&mode=persistent")
        entries=data.get("data",[])
        current=next((r for r in entries if r.get("session_id")==session_id),None)
        if current:
            rid=current.get("active_request_id")
            if not rid:
                return None
            req=api("GET","/v1/requests/"+rid)
            if (req.get("request_id")!=rid or req.get("session_id")!=session_id
                    or req.get("conversation_id") not in (None,cid)):
                raise TransportError("Gateway task request identity mismatch")
            db.execute("""INSERT OR IGNORE INTO chatbridge_task_request_links
                (project_id,task_id,request_id,session_id) VALUES(?,?,?,?)""",
                (p,t,rid,session_id))
            return req
        if len(entries)<page_size:
            break
    return None


def _external_probe_allowed(db, task, now=None, min_interval=180.0):
    """Persisted per-task poll budget for chats NOT submitted by ChatBridge."""
    now=time.time() if now is None else now
    p,t=task["project_id"],task["id"]
    last=db.execute("""SELECT next_check_at FROM chatbridge_external_poll_budget
        WHERE project_id=? AND task_id=?""",(p,t)).fetchone()
    if last and now < last["next_check_at"]:
        return False
    db.execute("""INSERT INTO chatbridge_external_poll_budget
        (project_id,task_id,next_check_at) VALUES(?,?,?)
        ON CONFLICT(project_id,task_id) DO UPDATE
        SET next_check_at=excluded.next_check_at""",(p,t,now+min_interval))
    return True


def reconcile_uncertain_followups(db, dry_run: bool = False):
    """Unblock a previously uncertain send ONLY after local completion proof.

    No POST, navigation, or provider history fetch is allowed here. The
    immutable gateway request_id, session_id, conversation_id and request
    key must match the Watcher continuation before restoring its poll state.
    An already delivered uncertainty notification is never rewritten.
    """
    # Legacy/isolated delivery-only schemas legitimately omit the tasks table.
    # Reconciliation is applicable only when browser-task metadata exists.
    columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
    if not {"project_id", "id", "chat_url", "state", "error"} <= columns:
        return []
    rows = db.execute("""SELECT f.*,t.chat_url,t.state AS task_state,t.error AS task_error,
          p.status AS project_status FROM chatbridge_browser_followups f
          JOIN tasks t ON t.project_id=f.project_id AND t.id=f.task_id
          JOIN projects p ON p.id=f.project_id
          WHERE f.state='uncertain' AND f.request_id IS NOT NULL
            AND t.state='blocked' AND t.error='ChatBridge unknown'
            AND p.status='enabled' ORDER BY f.project_id,f.task_id""").fetchall()
    updates = []
    for f in rows:
        try:
            current = api("GET", "/v1/requests/" + f["request_id"])
        except TransportError:
            continue
        expected_cid = legacy.canonical_url(f["chat_url"]).rsplit("/c/", 1)[-1]
        expected_project = (
            f["chat_url"].split("/g/", 1)[1].split("/", 1)[0]
            if "/g/" in f["chat_url"] else None
        )
        if (current.get("status") != "completed"
                or current.get("request_id") != f["request_id"]
                or current.get("session_id") != f["session_id"]
                or current.get("conversation_id") != expected_cid
                or current.get("project_id") != expected_project
                or current.get("client_request_id") != f["client_request_id"]
                or not current.get("assistant_message_id")
                or not current.get("answer")):
            continue
        event = {"task": f["project_id"] + "/" + f["task_id"],
                 "revision": f["revision"], "state": "recovered"}
        if dry_run:
            event["would_recover"] = True
            updates.append(event)
            continue
        db.execute("BEGIN IMMEDIATE")
        try:
            moved = db.execute("""UPDATE chatbridge_browser_followups
                SET state='submitted',last_error=NULL
                WHERE project_id=? AND task_id=? AND revision=?
                  AND state='uncertain' AND request_id=?""",
                (f["project_id"], f["task_id"], f["revision"], f["request_id"]),
            ).rowcount
            if moved:
                changed = db.execute("""UPDATE tasks SET state='watching',error=NULL
                    WHERE project_id=? AND id=? AND state='blocked'
                      AND error='ChatBridge unknown'""",
                    (f["project_id"], f["task_id"]),
                ).rowcount
                if not changed:
                    raise RuntimeError("Task changed during reconciliation")
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        if moved:
            updates.append(event)
    return updates


def poll_executor_tasks(db, dry_run: bool = False):
    """Complete registered executor chats using ChatBridge backend end_turn data."""
    rows = db.execute("""
        SELECT t.* FROM tasks t JOIN projects p ON p.id=t.project_id
        WHERE t.state='watching' AND t.mode='browser' AND p.status='enabled'
        ORDER BY t.project_id,t.id
    """).fetchall()
    events = []
    for task in rows:
        name = f"{task['project_id']}/{task['id']}"
        if dry_run:
            events.append({"task": name, "state": "watching", "would_poll": True})
            continue
        try:
            mapping = db.execute(
                "SELECT session_id FROM chatbridge_task_sessions WHERE project_id=? AND task_id=?",
                (task["project_id"], task["id"]),
            ).fetchone()
            if mapping:
                sid = mapping["session_id"]
            else:
                session = api("POST", "/v1/sessions", session_import(
                    task["chat_url"], "watcher-executor:" + name,
                ))
                sid = session["session_id"]
                db.execute(
                    "INSERT OR IGNORE INTO chatbridge_task_sessions VALUES(?,?,?)",
                    (task["project_id"], task["id"], sid),
                )
            # A saved session ID can rotate or be rebound after registration.
            # Verify its physical conversation before any provider poll or result.
            verify_route(api("GET", f"/v1/sessions/{sid}"), sid, task["chat_url"])
            followup=db.execute("""SELECT * FROM chatbridge_browser_followups
                WHERE project_id=? AND task_id=?
                ORDER BY revision DESC LIMIT 1""",
                (task["project_id"],task["id"])).fetchone()
            if followup and followup["state"] == "submitted":
                current=api("GET", f"/v1/requests/{followup['request_id']}")
                if (current.get("request_id")!=followup["request_id"]
                        or current.get("session_id")!=sid
                        or (current.get("conversation_id") is not None
                            and current.get("conversation_id")!=task["chat_url"].rsplit("/c/",1)[1])
                        or (current.get("status")=="completed"
                            and current.get("conversation_id") is None)):
                    db.execute("""UPDATE chatbridge_browser_followups
                        SET state='uncertain',last_error='request_identity_mismatch'
                        WHERE project_id=? AND task_id=? AND revision=?""",
                        (task["project_id"],task["id"],followup["revision"]))
                    db.execute("""UPDATE tasks SET state='blocked',error='request_identity_mismatch'
                        WHERE project_id=? AND id=?""",(task["project_id"],task["id"]))
                    queue_followup_alert(db,task["project_id"],task["id"],
                                         followup["revision"],"request_identity_mismatch")
                    events.append({"task":name,"state":"uncertain","reason":"request_mismatch"})
                    continue
                if current.get("status") == "completed":
                    verify_route(current, sid, task["chat_url"])
                status=current.get("status")
                if status in ("unknown","failed","interrupted"):
                    db.execute("""UPDATE chatbridge_browser_followups SET
                        state='uncertain',last_error=? WHERE project_id=? AND task_id=? AND revision=?""",
                        (str(status),task["project_id"],task["id"],followup["revision"]))
                    db.execute("""UPDATE tasks SET state='blocked',error=?
                        WHERE project_id=? AND id=?""",
                        ("ChatBridge "+str(status),task["project_id"],task["id"]))
                    queue_followup_alert(db,task["project_id"],task["id"],
                                         followup["revision"],"ChatBridge_"+str(status))
                    events.append({"task":name,"state":"uncertain","reason":status})
                    continue
                final=status=="completed"
                text=current.get("answer","") if final else ""
            else:
                linked=_local_request_for_executor(db,task,sid)
                if linked is not None:
                    # Gateway 'completed' is set ONLY after provider end_turn.
                    # No second tab, navigation, auth/session or history read.
                    state=linked.get("status")
                    if state in ("unknown","failed","interrupted"):
                        db.execute("""UPDATE tasks SET state='blocked',error=?
                            WHERE project_id=? AND id=?""",
                            ("ChatBridge "+str(state),task["project_id"],task["id"]))
                        queue_followup_alert(db,task["project_id"],task["id"],
                                             0,"ChatBridge_"+str(state))
                        events.append({"task":name,"state":"uncertain","reason":state})
                        continue
                    final=state=="completed"
                    text=linked.get("answer","") if final else ""
                    if final:
                        verify_route(linked, sid, task["chat_url"])
                else:
                    # External/iPhone-authored chat: we cannot invent a local
                    # gateway request. Read provider state sparsely, not every
                    # 20 seconds and never during global provider cooldown.
                    if not _external_probe_allowed(db,task):
                        continue
                    if api("GET","/v1/system/status").get("rate_limit",{}).get(
                        "provider_rate_limited"
                    ):
                        continue
                    current=api("GET", f"/v1/sessions/{sid}/turn-state")
                    # The turn-state endpoint exposes sid/cid; project binding
                    # comes from the session GET above (and is checked if returned).
                    verify_route(current, sid, task["chat_url"], require_project=False)
                    final=bool(current.get("completed"))
                    text=current.get("content","") if final else ""
            if legacy.completion_test(
                db, task["project_id"], task["id"], text,
                generating=not final, now_monotonic=time.monotonic(),
            ):
                events.append(legacy.prepare_delivery(db, task, text))
                if followup and followup["state"] == "submitted":
                    db.execute("""UPDATE chatbridge_browser_followups SET state='completed'
                        WHERE project_id=? AND task_id=? AND revision=?""",
                        (task["project_id"],task["id"],followup["revision"]))
        except TransportError as exc:
            db.execute(
                "UPDATE tasks SET error=? WHERE project_id=? AND id=?",
                (type(exc).__name__, task["project_id"], task["id"]),
            )
            events.append({"task": name, "state": "deferred", "reason": type(exc).__name__})
    return events


def recover_missing_revision_deliveries(db, dry_run: bool = False):
    """Requeue already completed executor reports whose delivery was lost.

    Historical browser deliveries have revision NULL and a per-task UNIQUE
    index. Revisioned follow-ups must use their positive revision instead.
    Only a durable, SHA256-verified result file can authorize this backfill.
    No ChatGPT request, browser tab, or prompt submission is involved.
    """
    task_columns = {r[1] for r in db.execute("PRAGMA table_info(tasks)")}
    delivery_columns = {r[1] for r in db.execute("PRAGMA table_info(deliveries)")}
    if "last_revision" not in task_columns or "revision" not in delivery_columns:
        return []
    rows = db.execute("""SELECT f.project_id,f.task_id,f.revision,
        t.result_path,t.result_sha256,t.chat_url,p.orchestrator_url
        FROM chatbridge_browser_followups f
        JOIN tasks t ON t.project_id=f.project_id AND t.id=f.task_id
        JOIN projects p ON p.id=f.project_id
        WHERE f.state='completed' AND f.revision>0
          AND t.state='completed' AND t.last_revision=f.revision
          AND p.status='enabled' AND t.result_path IS NOT NULL
          AND t.result_sha256 IS NOT NULL
          AND NOT EXISTS(
              SELECT 1 FROM deliveries d
              WHERE d.project_id=f.project_id AND d.task_id=f.task_id
                AND d.revision=f.revision
          ) ORDER BY f.project_id,f.task_id""").fetchall()
    events = []
    for item in rows:
        project, task, revision = (
            item["project_id"], item["task_id"], int(item["revision"])
        )
        expected = legacy.RESULTS / project / f"{task}-r{revision:02d}.md"
        actual = Path(item["result_path"])
        # A trusted report must have the exact expected path and byte digest.
        # Never follow symlinks or read arbitrary filesystem paths from SQLite.
        if actual != expected or actual.parent.is_symlink() or actual.is_symlink() or not actual.is_file():
            continue
        if actual.stat().st_size > 16 * 1024 * 1024:
            continue
        from .watcher_file_runtime import _read
        data = _read(actual, 16 * 1024 * 1024)
        digest = hashlib.sha256(data).hexdigest()
        if digest != item["result_sha256"]:
            continue
        event_key = f"{project}/{task}/r{revision}/{digest}"
        event_id = hashlib.sha256(event_key.encode()).hexdigest()[:32]
        notice = (
            f"[MC-WATCH:{event_id}]\n"
            "Watcher: executor task completed.\n"
            f"Project: {project}\nTask: {task}\n"
            f"Executor chat: {item['chat_url']}\n"
            f"Report path on Mac: {actual}\n"
            f"Report SHA256: {digest}\n"
            "Orchestrator: fetch and verify the report using Mac Control, review acceptance "
            "criteria, then decide the next step. Do not make production changes automatically."
        )
        event = {"task": f"{project}/{task}", "revision": revision,
                 "state": "delivery_restored", "delivery_id": event_id}
        if dry_run:
            event["would_restore"] = True
            events.append(event)
            continue
        db.execute("BEGIN IMMEDIATE")
        try:
            inserted = db.execute("""INSERT OR IGNORE INTO deliveries
                (id,project_id,task_id,orchestrator_url,payload,state,created_at,revision)
                VALUES(?,?,?,?,?,'ready',?,?)""",
                (event_id,project,task,item["orchestrator_url"],notice,legacy.utc(),revision))
            if inserted.rowcount != 1:
                found = db.execute("""SELECT id FROM deliveries
                    WHERE project_id=? AND task_id=? AND revision=?""",
                    (project,task,revision)).fetchone()
                if not found or found["id"] != event_id:
                    raise RuntimeError("Missing revision delivery cannot be safely restored")
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        events.append(event)
    return events


def iteration(db, dry_run=False):
    from .watcher_file_runtime import reconcile as reconcile_files
    from .watcher_schedule_store import due_to_deliveries

    results = []
    results.extend(reconcile_uncertain_followups(db, dry_run=dry_run))
    results.extend(dispatch_prepared_followups(db, dry_run=dry_run))
    results.extend(poll_executor_tasks(db, dry_run=dry_run))
    results.extend(recover_missing_revision_deliveries(db, dry_run=dry_run))
    if not dry_run:
        results.extend(due_to_deliveries(db))
        counts = legacy.active_work_counts(db)
        if counts["watching_file_tasks"]:
            results.extend(reconcile_files(db))
        if counts["browser_active"]:
            from .mcp_error_monitor import scan as scan_errors
            monitor = scan_errors(db)
            if monitor.get("new_errors") or monitor.get("queued_alerts"):
                results.append({"mcp_errors_detected": monitor["new_errors"],
                                "queued_alerts": monitor["queued_alerts"]})
    from .watcher_busy_batch import batch_for, busy, choose, prepare, process
    rows = db.execute("""
        SELECT d.* FROM deliveries d JOIN projects p ON p.id=d.project_id
        WHERE p.status='enabled' AND d.state IN ('ready','attempting')
        ORDER BY CASE WHEN d.state='attempting' THEN 0 ELSE 1 END,
                 d.created_at,d.rowid
    """).fetchall()
    # One outstanding message per orchestrator. There is NO debounce: if idle,
    # send the first ready event immediately. If busy, leave events in SQLite;
    # all waiting ready events can be delivered together when it becomes idle.
    projects = {}
    for delivery in rows:
        projects.setdefault(delivery["project_id"], []).append(delivery)
    submitted_this_round = False
    for project, pending in projects.items():
        first = pending[0]
        try:
            if dry_run:
                results.append({"id":first["id"],"state":first["state"],
                                "would_send":True,"pending":len(pending)})
                continue
            existing = batch_for(db, first["id"])
            if existing:
                had_request = bool(existing["request_id"])
                results.append(process(db, sys.modules[__name__], existing))
                if not had_request:
                    submitted_this_round = True
                continue
            if first["state"] == "attempting":
                results.append(process_one(db, first))
                continue
            if submitted_this_round:
                continue  # One new ChatGPT request per global Watcher cycle.
            block = busy(sys.modules[__name__], project,
                         legacy.canonical_url(first["orchestrator_url"]))
            if block:
                if first["last_error"] != block:
                    db.execute("UPDATE deliveries SET last_error=? WHERE id=? AND state='ready'",
                               (block, first["id"]))
                continue
            ready = [r for r in pending if r["state"] == "ready"]
            selected = choose(ready)
            was_held = first["last_error"] in (
                "provider_cooldown", "gateway_busy", "orchestrator_busy")
            if len(selected) >= 2 and was_held:
                group = prepare(db, sys.modules[__name__], selected)
                if group:
                    result = process(db, sys.modules[__name__], group)
                    results.append(result)
                    submitted_this_round = bool(result.get("request_id"))
                continue
            result = process_one(db, first)
            results.append(result)
            submitted_this_round = bool(result.get("request_id"))
        except (TransportError, ValueError, RuntimeError) as exc:
            results.append({"id":first["id"],"state":"deferred",
                            "error":type(exc).__name__})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "once", "dry-run"])
    args = parser.parse_args()
    db = legacy.connect()
    setup(db)
    try:
        try:
            telemetry.attach(db)
        except Exception as exc:  # noqa: BLE001 - auxiliary observability
            # Auxiliary observability must never stop delivery.
            print(json.dumps({"telemetry": "unavailable",
                              "error_type": type(exc).__name__}), flush=True)
        if args.command == "run":
            lockfile = legacy.RUNTIME / "singleton.lock"
            if lockfile.is_symlink():
                raise PermissionError("Symlink Watcher lock")
            legacy.private_file(lockfile)
            with lockfile.open("a+") as lock:
                os.chmod(lockfile, 0o600)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                recovered=quarantine_crashed_followups(db)
                print(json.dumps({"http_watcher": "started", "api": BASE,
                                  "crashed_followups": recovered}), flush=True)
                while True:
                    try:
                        events = iteration(db)
                        if events:
                            print(json.dumps({"events": events}, ensure_ascii=False), flush=True)
                    except Exception as exc:  # noqa: BLE001 - keep daemon alive
                        print(json.dumps({"error": type(exc).__name__,
                                          "detail": "Watcher iteration failed"}), flush=True)
                    finally:
                        try:
                            if legacy.active_work_counts(db)["active"]:
                                telemetry.maybe_sample(api)
                            telemetry.flush()
                        except Exception as exc:  # noqa: BLE001 - telemetry is optional
                            print(json.dumps({"telemetry": "sample_failed",
                                              "error_type": type(exc).__name__}), flush=True)
                    time.sleep(POLL_SECONDS)
        else:
            try:
                print(json.dumps({
                    "events": iteration(db, dry_run=args.command == "dry-run")
                }, ensure_ascii=False))
            finally:
                if args.command != "dry-run":
                    try:
                        if legacy.active_work_counts(db)["active"]:
                            telemetry.maybe_sample(api)
                        telemetry.flush()
                    except Exception as exc:  # noqa: BLE001
                        print(json.dumps({"telemetry": "sample_failed",
                                          "error_type": type(exc).__name__}), flush=True)
    finally:
        telemetry.detach()
        db.close()


if __name__ == "__main__":
    main()
