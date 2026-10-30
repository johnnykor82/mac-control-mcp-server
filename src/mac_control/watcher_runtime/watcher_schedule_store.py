"""Delayed ChatGPT checks using the existing Mac Control Watcher database.

This module never uses ChatGPT private endpoints or credentials. Scheduling and
reconciliation are SQLite-only. Browser delivery is delegated to the installed
Watcher, including its global cooldown, busy-chat, dedup and navigation gates.
"""
from __future__ import annotations

import hashlib
import re
import time
import uuid
from datetime import datetime, timezone

KEY = re.compile(r"^[a-zA-Z0-9_-]{4,64}$")
ID = re.compile(r"^[0-9a-f]{32}$")
MAX_MINUTES = 43200


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS scheduled_checks (
        id TEXT PRIMARY KEY,
        chat_url TEXT NOT NULL,
        project_id TEXT NOT NULL REFERENCES projects(id),
        objective TEXT NOT NULL,
        due_at REAL NOT NULL,
        created_at TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('scheduled','queued','cancelled')),
        request_key TEXT,
        UNIQUE (chat_url,request_key))""")
    db.execute("""CREATE INDEX IF NOT EXISTS scheduled_checks_due
                  ON scheduled_checks(state,due_at)""")


def _canonical_url(url):
    from .multi_project_watcher import canonical_url
    return canonical_url(url)


def detail(db, wakeup_id):
    if not isinstance(wakeup_id,str) or not ID.fullmatch(wakeup_id):
        raise ValueError("Invalid wakeup ID")
    row=db.execute("""SELECT w.id,w.chat_url,w.project_id,w.objective,
        w.due_at,w.created_at,w.state,p.status AS project_status,
        d.state AS delivery_state,d.attempts,d.delivered_at,d.acknowledged_at,
        d.last_error FROM scheduled_checks w
        JOIN projects p ON p.id=w.project_id
        LEFT JOIN deliveries d ON d.id=w.id
        WHERE w.id=?""",(wakeup_id,)).fetchone()
    if row is None:raise ValueError("Unknown wakeup ID")
    return dict(row)


def schedule(db, chat_url, delay_minutes, objective, request_key=""):
    url=_canonical_url(chat_url)
    if type(delay_minutes) is not int or not 1<=delay_minutes<=MAX_MINUTES:
        raise ValueError("delay_minutes must be an integer in 1..43200")
    if not isinstance(objective,str) or not 3<=len(objective.strip())<=1000 or "\x00" in objective:
        raise ValueError("objective must contain 3..1000 characters")
    objective=objective.strip()
    if request_key and (not isinstance(request_key,str) or not KEY.fullmatch(request_key)):
        raise ValueError("Invalid request_key")
    db.execute("BEGIN IMMEDIATE")
    try:
        existing=(db.execute("""SELECT id,objective FROM scheduled_checks
            WHERE chat_url=? AND request_key=?""",(url,request_key)).fetchone()
            if request_key else None)
        if existing:
            if existing["objective"]!=objective:
                raise ValueError("Idempotency key already used with another objective")
            value=detail(db,existing["id"])
            value["duplicate"]=True
        else:
            pr=db.execute("SELECT id,status FROM projects WHERE orchestrator_url=?",(url,)).fetchone()
            if pr:
                if pr["status"]!="enabled":raise ValueError("Target project is paused")
                project_id=pr["id"]
            else:
                project_id="wake-"+hashlib.sha256(url.encode()).hexdigest()[:20]
                # No implicit re-enabling of old paused projects.
                db.execute("""INSERT INTO projects(id,orchestrator_url,status,created_at)
                    VALUES(?,?,'enabled',?)""",(project_id,url,utc()))
            wakeup_id=uuid.uuid4().hex
            db.execute("""INSERT INTO scheduled_checks
                (id,chat_url,project_id,objective,due_at,created_at,state,request_key)
                VALUES(?,?,?,?,?,?,'scheduled',?)""",
                (wakeup_id,url,project_id,objective,time.time()+60*delay_minutes,utc(),request_key or None))
            value=detail(db,wakeup_id)
            value["duplicate"]=False
        db.execute("COMMIT")
        return value
    except BaseException:
        db.execute("ROLLBACK")
        raise


def list_checks(db,chat_url="",limit=30):
    if chat_url:chat_url=_canonical_url(chat_url)
    limit=max(1,min(100,int(limit)))
    sql="SELECT id FROM scheduled_checks"
    args=[]
    if chat_url:
        sql+=" WHERE chat_url=?"
        args.append(chat_url)
    sql+=" ORDER BY due_at DESC LIMIT ?"
    args.append(limit)
    return [detail(db,row["id"]) for row in db.execute(sql,args).fetchall()]


def cancel(db,wakeup_id):
    current=detail(db,wakeup_id)
    if current["state"]=="cancelled":
        return {"wakeup_id":wakeup_id,"cancelled":True,"duplicate":True}
    if current["delivery_state"] not in (None,"ready"):
        raise ValueError("Delivery already underway or complete")
    db.execute("BEGIN IMMEDIATE")
    try:
        row=db.execute("SELECT state FROM deliveries WHERE id=?",(wakeup_id,)).fetchone()
        if row and row["state"]!="ready":raise ValueError("Delivery no longer cancellable")
        db.execute("UPDATE scheduled_checks SET state='cancelled' WHERE id=?",(wakeup_id,))
        db.execute("UPDATE deliveries SET state='cancelled' WHERE id=? AND state='ready'",(wakeup_id,))
        db.execute("COMMIT")
        return {"wakeup_id":wakeup_id,"cancelled":True,"duplicate":False}
    except BaseException:
        db.execute("ROLLBACK")
        raise


def due_to_deliveries(db,now=None):
    """Move due checks into existing deduplicated browser delivery pipeline.

    A paused project keeps its scheduled checks, without browser traffic.
    This routine is safe to call repeatedly or after process restarts.
    """
    now=time.time() if now is None else float(now)
    due=db.execute("""SELECT w.* FROM scheduled_checks w
      JOIN projects p ON p.id=w.project_id
      WHERE w.state='scheduled' AND w.due_at<=? AND p.status='enabled'
      ORDER BY w.due_at,w.id LIMIT 50""",(now,)).fetchall()
    queued=[]
    for r in due:
        token=r["id"]
        payload=(f"[MC-WATCH:{token}]\n"
          "Source: Mac Control Scheduled Watcher.\n"
          f"Wakeup ID: {token}\n"
          "Instruction: call watcher_guide for the installed Watcher operating guide.\n"
          f"Check objective: {r['objective']}\n"
          "Verify this event with watcher_get_wakeup, read WATCHER_USAGE.md, "
          "inspect the original task and check its actual result using tools. "
          "If continued work is authorized, perform it. If a later check is "
          "necessary, register a new watcher_schedule_wakeup in this SAME chat "
          "before completing your reply. Acknowledge this event when processed.")
        db.execute("BEGIN IMMEDIATE")
        try:
            moved=db.execute("""UPDATE scheduled_checks SET state='queued'
                        WHERE id=? AND state='scheduled'""",(token,)).rowcount
            if moved:
                db.execute("""INSERT INTO deliveries
                    (id,project_id,task_id,orchestrator_url,payload,state,created_at)
                    VALUES(?,?,?,?,?,'ready',?)""",
                    (token,r["project_id"],"wake-"+token,r["chat_url"],payload,utc()))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        if moved:queued.append({"wakeup_id":token,"queued":True})
    return queued


def acknowledge(db,wakeup_id):
    from .multi_project_watcher import acknowledge_delivery
    item=detail(db,wakeup_id)
    return acknowledge_delivery(db,item["project_id"],wakeup_id)
