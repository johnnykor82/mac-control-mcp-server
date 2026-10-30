"""Durable continuation of a completed Watcher browser executor in the SAME chat.

Watcher queues follow-ups without sending while registering them. The HTTP
adapter dispatches each revision at most once with a stable idempotency key,
then tracks the specific gateway request (not the preceding completed turn).
Unknown POST outcomes are quarantined, never retried blindly.
"""
from __future__ import annotations

import re
import sqlite3

ALLOWED_STATES = ("prepared", "sending", "submitted", "uncertain", "completed", "failed")
MAX_PROMPT = 32000


def setup(db: sqlite3.Connection):
    db.execute("""CREATE TABLE IF NOT EXISTS chatbridge_browser_followups(
        project_id TEXT NOT NULL, task_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision > 0),
        session_id TEXT NOT NULL,
        client_request_id TEXT NOT NULL UNIQUE,
        prompt TEXT NOT NULL,
        request_id TEXT,
        state TEXT NOT NULL CHECK(state IN
            ('prepared','sending','submitted','uncertain','completed','failed')),
        last_error TEXT,
        PRIMARY KEY(project_id,task_id,revision)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_cb_browser_followup_state
                  ON chatbridge_browser_followups(state)""")


def enqueue(db, project: str, task: str, prompt: str, request_key: str):
    from .multi_project_watcher import require_name
    require_name(project)
    require_name(task)
    if not isinstance(request_key,str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,72}",request_key):
        raise ValueError("Request key must have 8..72 safe characters")
    if not isinstance(prompt,str) or not 25 <= len(prompt) <= MAX_PROMPT or "\0" in prompt:
        raise ValueError("Prompt must contain 25..32000 characters")
    setup(db)
    db.execute("BEGIN IMMEDIATE")
    try:
        duplicate=db.execute("""SELECT * FROM chatbridge_browser_followups
            WHERE client_request_id=?""",(request_key,)).fetchone()
        if duplicate:
            if (duplicate["project_id"],duplicate["task_id"],duplicate["prompt"]) != (project,task,prompt):
                raise ValueError("Idempotency key already used with different payload")
            db.execute("COMMIT")
            return {"project_id":project,"task_id":task,
                "revision":duplicate["revision"],"state":duplicate["state"],
                "duplicate":True}
        row=db.execute("""SELECT t.*,p.status AS project_status
            FROM tasks t JOIN projects p ON p.id=t.project_id
            WHERE t.project_id=? AND t.id=?""",(project,task)).fetchone()
        if not row or row["mode"]!="browser" or row["state"]!="completed":
            raise ValueError("Only completed browser tasks can be continued")
        if row["project_status"]!="enabled":
            raise ValueError("Project is paused")
        unacked=db.execute("""SELECT COUNT(*) FROM deliveries
            WHERE project_id=? AND task_id=? AND (
              state!='delivered' OR acknowledged_at IS NULL
            )""",(project,task)).fetchone()[0]
        if unacked:
            raise ValueError("Prior task result not delivered and acknowledged")
        mapping=db.execute("""SELECT session_id FROM chatbridge_task_sessions
           WHERE project_id=? AND task_id=?""",(project,task)).fetchone()
        if not mapping:
            raise ValueError("Executor ChatBridge session is not yet registered")
        existing=db.execute("""SELECT * FROM chatbridge_browser_followups
            WHERE project_id=? AND task_id=? ORDER BY revision DESC LIMIT 1""",
            (project,task)).fetchone()
        if existing and existing["state"] not in ("completed","failed"):
            if (existing["client_request_id"]!=request_key or
                    existing["prompt"]!=prompt):
                raise ValueError("Existing continuation in progress; cannot supersede")
            result={"project_id":project,"task_id":task,
                    "revision":existing["revision"],"state":existing["state"],
                    "duplicate":True}
        else:
            rev=int(row["last_revision"])+1
            db.execute("""INSERT INTO chatbridge_browser_followups
                (project_id,task_id,revision,session_id,client_request_id,prompt,state)
                VALUES(?,?,?,?,?,?,'prepared')""",
                (project,task,rev,mapping["session_id"],request_key,prompt))
            result={"project_id":project,"task_id":task,
                    "revision":rev,"state":"prepared","duplicate":False}
        db.execute("COMMIT")
        return result
    except BaseException:
        db.execute("ROLLBACK")
        raise


def prepare_for_dispatch(db):
    """Only one prepared continuation per executor, with prior ACK enforced."""
    setup(db)
    return db.execute("""SELECT f.* FROM chatbridge_browser_followups f
        JOIN projects p ON p.id=f.project_id
        JOIN tasks t ON t.project_id=f.project_id AND t.id=f.task_id
        WHERE f.state='prepared' AND p.status='enabled' AND
              t.state='completed' ORDER BY f.project_id,f.task_id LIMIT 2""").fetchall()
