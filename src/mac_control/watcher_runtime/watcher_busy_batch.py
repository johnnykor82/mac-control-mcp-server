"""Durable conditional batching for Watcher HTTP notifications.

No artificial debounce: ready notifications are combined only when multiple
events accumulated while the ChatBridge gateway/orchestrator was busy.
"""
from __future__ import annotations

import hashlib

MAX_EVENTS = 12
MAX_CHARS = 48000


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS chatbridge_notification_batches(
       id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
       orchestrator_url TEXT NOT NULL, session_id TEXT NOT NULL,
       client_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
       request_id TEXT, state TEXT NOT NULL, created_at TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS chatbridge_notification_batch_items(
       delivery_id TEXT PRIMARY KEY REFERENCES deliveries(id),
       batch_id TEXT NOT NULL REFERENCES chatbridge_notification_batches(id))""")


def busy(adapter, project, target):
    """Read ONLY gateway-local state, never ChatGPT backend or a new tab."""
    health = adapter.api("GET", "/v1/system/status")
    if health.get("rate_limit", {}).get("provider_rate_limited"):
        return "provider_cooldown"
    # Conservative global guard following observed provider 429 under overlap.
    if int(health.get("active") or 0):
        return "gateway_busy"
    cid = target.rsplit("/c/", 1)[1]
    pid = target.split("/g/", 1)[1].split("/c/", 1)[0] if "/g/" in target else None
    for offset in range(0, 4000, 250):
        result = adapter.api("GET",
            f"/v1/sessions?limit=250&offset={offset}&mode=persistent")
        sessions = result.get("data")
        if not isinstance(sessions, list):
            raise adapter.TransportError("Invalid local session listing; defer notification")
        for s in sessions:
            if s.get("conversation_id") == cid and s.get("project_id") == pid:
                return "orchestrator_busy" if s.get("active_request_id") else None
        if len(sessions) < 250:
            return None
    # The target might be beyond the bounded local pagination range; fail closed.
    return "session_lookup_incomplete"


def batch_for(db, delivery_id):
    return db.execute("""SELECT b.* FROM chatbridge_notification_batches b
       JOIN chatbridge_notification_batch_items i ON i.batch_id=b.id
       WHERE i.delivery_id=?""", (delivery_id,)).fetchone()


def choose(rows):
    selected = []
    total = 200
    for r in rows:
        size = len(r["payload"]) + 50
        if size > MAX_CHARS or total + size > MAX_CHARS or len(selected) >= MAX_EVENTS:
            break
        selected.append(r)
        total += size
    return selected



def existing_markers(adapter, session_id, ids):
    """One local paginated scan for all batch markers; never provider sync."""
    tokens={"[MC-WATCH:"+did+"]":did for did in ids}
    found=set()
    cursor=0
    for _ in range(100):
        response=adapter.api("GET",f"/v1/sessions/{session_id}/messages?limit=500&after={cursor}")
        for row in response.get("data",[]):
            if row.get("role") != "user":
                continue
            body=str(row.get("content") or "")
            for token,did in tokens.items():
                if token in body:
                    found.add(did)
        next_cursor=response.get("next_cursor",cursor)
        if not response.get("data") or next_cursor==cursor or len(found)==len(ids):
            return found
        cursor=next_cursor
    raise adapter.TransportError("Local marker scan exceeded supported history length")


def prepare(db, adapter, rows):
    """Write the exact batch membership and prompt BEFORE network submission."""
    assert len(rows) >= 2
    first = rows[0]
    sid, rid = adapter.ensure_session(db, first)
    if rid:
        raise RuntimeError("First delivery already submitted")
    # One local scan instead of N repeated scans; each event retains its ACK.
    found=existing_markers(adapter,sid,[r["id"] for r in rows])
    if found:
        for did in found:
            db.execute("""UPDATE deliveries SET state='delivered',
                delivered_at=?,last_error=NULL WHERE id=? AND state='ready'""",
                (adapter.legacy.utc(),did))
            db.execute("""INSERT OR IGNORE INTO chatbridge_delivery_links
                (delivery_id,session_id,last_status) VALUES(?,?,'deduplicated')""",
                (did,sid))
        return None
    project = first["project_id"]
    target = adapter.legacy.canonical_url(first["orchestrator_url"])
    if any(r["project_id"] != project or r["state"] != "ready" or
           adapter.legacy.canonical_url(r["orchestrator_url"]) != target
           for r in rows):
        raise ValueError("Inconsistent batch members")
    ids = [r["id"] for r in rows]
    bid = hashlib.sha256(("batch-v1/" + project + "/" + "/".join(ids)).encode()).hexdigest()[:32]
    content = ("Watcher: Multiple notifications were queued while the orchestrator "
               "was busy. Handle EACH [MC-WATCH:id] separately; each needs its own "
               "verification and ACK.\n\n" +
               "\n\n--- separate notification ---\n\n".join(r["payload"] for r in rows))
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""INSERT INTO chatbridge_notification_batches
          (id,project_id,orchestrator_url,session_id,client_key,payload,state,created_at)
          VALUES(?,?,?,?,?,?,'attempting',?)""",
          (bid,project,target,sid,"watcher-batch-"+bid,content,adapter.legacy.utc()))
        for r in rows:
            db.execute("""INSERT INTO chatbridge_notification_batch_items
                         (delivery_id,batch_id) VALUES(?,?)""",(r["id"],bid))
            db.execute("""INSERT OR IGNORE INTO chatbridge_delivery_links
                         (delivery_id,session_id,last_status) VALUES(?,?,'batched')""",
                         (r["id"],sid))
            db.execute("""UPDATE deliveries SET state='attempting', attempts=attempts+1
                         WHERE id=? AND state='ready'""",(r["id"],))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return db.execute("SELECT * FROM chatbridge_notification_batches WHERE id=?",(bid,)).fetchone()


def process(db, adapter, batch):
    """All members share one ChatBridge request, not one ACK."""
    bid=batch["id"]
    rid=batch["request_id"]
    owner=db.execute("SELECT status,orchestrator_url FROM projects WHERE id=?",
                     (batch["project_id"],)).fetchone()
    if (not owner or owner["status"]!="enabled" or
            adapter.legacy.canonical_url(owner["orchestrator_url"])!=batch["orchestrator_url"]):
        db.execute("""UPDATE deliveries SET state='delivery_uncertain',
            last_error='batch_route_changed' WHERE id IN
            (SELECT delivery_id FROM chatbridge_notification_batch_items WHERE batch_id=?)""",
            (bid,))
        db.execute("UPDATE chatbridge_notification_batches SET state='uncertain' WHERE id=?",(bid,))
        return {"batch":bid,"state":"delivery_uncertain","reason":"route_changed"}
    if not rid:
        session=adapter.api("GET",f"/v1/sessions/{batch['session_id']}")
        target=batch["orchestrator_url"]
        cid=target.rsplit("/c/",1)[1]
        pid=target.split("/g/",1)[1].split("/c/",1)[0] if "/g/" in target else None
        if (session.get("session_id")!=batch["session_id"] or
            session.get("conversation_id")!=cid or
            session.get("project_id")!=pid or
            session.get("mode")!="persistent"):
            db.execute("""UPDATE deliveries SET state='delivery_uncertain',
                last_error='batch_session_mismatch' WHERE id IN
                (SELECT delivery_id FROM chatbridge_notification_batch_items WHERE batch_id=?)""",
                (bid,))
            db.execute("UPDATE chatbridge_notification_batches SET state='uncertain' WHERE id=?",(bid,))
            return {"batch":bid,"state":"delivery_uncertain","reason":"session_mismatch"}
        # After a crash or lost HTTP ACK, retry the SAME immutable idempotency
        # key and SAME session. ChatBridge returns the existing request.
        response=adapter.api("POST",f"/v1/sessions/{batch['session_id']}/messages",
            {"content":batch["payload"],"client_request_id":batch["client_key"]})
        rid=response["request_id"]
        if not rid:
            raise adapter.TransportError("Batch missing gateway request_id")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("UPDATE chatbridge_notification_batches SET request_id=? WHERE id=?",
                       (rid,bid))
            db.execute("""UPDATE chatbridge_delivery_links SET request_id=?,last_status=?
                 WHERE delivery_id IN (SELECT delivery_id FROM
                 chatbridge_notification_batch_items WHERE batch_id=?)""",
                 (rid,response.get("status","queued"),bid))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return {"batch":bid,"state":"attempting","request_id":rid}
    result=adapter.api("GET",f"/v1/requests/{rid}")
    if (result.get("request_id")!=rid or
            result.get("session_id")!=batch["session_id"] or
            result.get("conversation_id")!=batch["orchestrator_url"].rsplit("/c/",1)[1]):
        db.execute("""UPDATE deliveries SET state='delivery_uncertain',
            last_error='batch_request_identity_mismatch' WHERE id IN
            (SELECT delivery_id FROM chatbridge_notification_batch_items WHERE batch_id=?)""",
            (bid,))
        db.execute("UPDATE chatbridge_notification_batches SET state='uncertain' WHERE id=?",(bid,))
        return {"batch":bid,"state":"delivery_uncertain","reason":"request_mismatch"}
    status=result["status"]
    if status not in ("completed","failed","unknown","interrupted"):
        return {"batch":bid,"state":"attempting","request_id":rid}
    delivered=status=="completed"
    db.execute("BEGIN IMMEDIATE")
    try:
        if delivered:
            db.execute("""UPDATE deliveries SET state='delivered', delivered_at=?,
                last_error=NULL WHERE id IN (SELECT delivery_id FROM
                chatbridge_notification_batch_items WHERE batch_id=?)""",
                (adapter.legacy.utc(),bid))
        else:
            db.execute("""UPDATE deliveries SET state='delivery_uncertain',
                last_error=? WHERE id IN (SELECT delivery_id FROM
                chatbridge_notification_batch_items WHERE batch_id=?)""",
                ("ChatBridge "+status+": batch="+bid,bid))
        db.execute("UPDATE chatbridge_notification_batches SET state=? WHERE id=?",
                   ("delivered" if delivered else "uncertain",bid))
        db.execute("""UPDATE chatbridge_delivery_links SET last_status=?,
            last_checked_at=? WHERE delivery_id IN (SELECT delivery_id FROM
            chatbridge_notification_batch_items WHERE batch_id=?)""",
            (status,adapter.legacy.utc(),bid))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return {"batch":bid,"state":"delivered" if delivered else "delivery_uncertain",
            "request_id":rid}
