"""Portable Watcher SQLite state and CLI; ChatBridge exclusively owns Chrome."""

from __future__ import annotations

import argparse

import fcntl

import hashlib

import json

import os

import re

import sqlite3
import stat

import sys

import time

import uuid

from datetime import datetime, timezone

from pathlib import Path

from urllib.parse import urlsplit

from ..runtime_paths import DATA_ROOT
ROOT = DATA_ROOT

RUNTIME = ROOT / "run" / "watcher"

DBFILE = RUNTIME / "watcher.sqlite3"

RESULTS = RUNTIME / "results"

PERIOD = 120

BROWSER_POLL_INTERVAL = 120

MIN_CHAT_REFRESH_SECONDS = 180  # conservative 3-minute floor after site blocking

BLOCK_COOLDOWN_SECONDS = 3600

STABLE_SECONDS = 12

ORCHESTRATOR_IDLE_SECONDS = 5

NAME_RX = re.compile(r"^[a-z0-9][a-z0-9_-]{1,55}$")

CHAT_RX = re.compile(r"^/c/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)

PROJECT_CHAT_RX = re.compile(r"^/g/(g-p-[0-9a-f]{32})(?:-[a-z0-9-]+)?/c/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$", re.I)

MARKER_RX = re.compile(r"\[MC-WATCH:([a-f0-9]{32})\]")

def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def require_name(name: str):
    if not isinstance(name, str) or not NAME_RX.fullmatch(name):
        raise ValueError("ID must be 2–56 lowercase alphanumeric/hyphen/underscore characters")
    return name

def canonical_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Chat URL required")
    p = urlsplit(value)
    if p.scheme != "https" or p.hostname != "chatgpt.com" or p.port is not None:
        raise ValueError("Only https://chatgpt.com/c/... URLs are accepted")
    if p.username or p.password or p.query or p.fragment or p.netloc != "chatgpt.com":
        raise ValueError("Invalid chat URL or unexpected URL components")
    project = PROJECT_CHAT_RX.fullmatch(p.path)
    if project:
        return f"https://chatgpt.com/g/{project.group(1).lower()}/c/{project.group(2).lower()}"
    if not CHAT_RX.fullmatch(p.path):
        raise ValueError("Invalid chat URL or unexpected URL components")
    return "https://chatgpt.com" + p.path.lower()

def private_directory(path):
    if path.is_symlink():
        raise PermissionError("Symlink in Watcher state")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PermissionError("Watcher state must be owner-private")


def private_file(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError("Watcher file must be owner-private")
    finally:
        os.close(fd)


def ensure_dir():
    if ROOT.is_symlink() or RUNTIME.parent.is_symlink():
        raise PermissionError("Symlink in Watcher state ancestors")
    private_directory(RUNTIME)
    private_directory(RESULTS)


def connect():
    ensure_dir()
    if DBFILE.is_symlink():
        raise PermissionError("Symlink Watcher database")
    for sidecar in (Path(str(DBFILE) + "-wal"), Path(str(DBFILE) + "-shm")):
        if sidecar.exists() or sidecar.is_symlink():
            if sidecar.is_symlink():
                raise PermissionError("Symlink Watcher database sidecar")
            private_file(sidecar)
    private_file(DBFILE)
    db = sqlite3.connect(DBFILE, timeout=8, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=8000")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, orchestrator_url TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'enabled', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            project_id TEXT NOT NULL REFERENCES projects(id),
            id TEXT NOT NULL, chat_url TEXT UNIQUE NOT NULL,
            state TEXT NOT NULL DEFAULT 'watching',
            last_hash TEXT, stable_since REAL, last_text_size INTEGER DEFAULT 0,
            result_path TEXT, result_sha256 TEXT, complete_at TEXT,
            error TEXT,
            PRIMARY KEY(project_id,id)
        );
        CREATE TABLE IF NOT EXISTS deliveries (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            task_id TEXT NOT NULL, orchestrator_url TEXT NOT NULL,
            payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'ready',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT, created_at TEXT NOT NULL, delivered_at TEXT
        );
        -- Per-revision delivery indexes are installed by file-protocol migration.
        -- Do not recreate the old unconditional index: a file task may have
        -- multiple delivered revisions.
        CREATE TABLE IF NOT EXISTS orchestrator_gates(
            project_id TEXT PRIMARY KEY REFERENCES projects(id),
            idle_since REAL,
            state TEXT NOT NULL DEFAULT 'unknown',
            last_checked TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_load_backoff(
            project_id TEXT PRIMARY KEY REFERENCES projects(id),
            next_retry_at REAL NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS navigation_budget(
            chat_url TEXT PRIMARY KEY,
            last_navigation REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS browser_poll_budget(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            last_poll_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS service_backoff(
            name TEXT PRIMARY KEY,
            until_at REAL NOT NULL,
            reason TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
    """)
    # Safe additive migration for existing persistent watcher SQLite.
    columns={row["name"] for row in db.execute("PRAGMA table_info(deliveries)")}
    if "acknowledged_at" not in columns:
        db.execute("ALTER TABLE deliveries ADD COLUMN acknowledged_at TEXT")
    from .watcher_file_runtime import setup as setup_file_protocol
    setup_file_protocol(db)
    from .watcher_schedule_store import setup as setup_scheduled_checks
    setup_scheduled_checks(db)
    from .watcher_tab_lifecycle import setup as setup_tab_leases
    setup_tab_leases(db)
    return db

def active_work_counts(db):
    """Only enabled projects count; paused and completed tasks produce no CDP activity."""
    tasks=db.execute("""SELECT COUNT(*) FROM tasks t
        JOIN projects p ON p.id=t.project_id
        WHERE t.state='watching' AND t.mode='browser' AND p.status='enabled'""").fetchone()[0]
    deliveries=db.execute("""SELECT COUNT(*) FROM deliveries d
        JOIN projects p ON p.id=d.project_id
        WHERE d.state IN ('ready','attempting') AND p.status='enabled'""").fetchone()[0]
    file_tasks=db.execute("""SELECT COUNT(*) FROM tasks t
        JOIN projects p ON p.id=t.project_id
        WHERE t.mode='file' AND t.state='watching' AND p.status='enabled'""").fetchone()[0]
    return {"watching_tasks":tasks,"watching_file_tasks":file_tasks,
            "pending_deliveries":deliveries,
            "browser_active":bool(tasks or deliveries),
            "active":bool(tasks or deliveries or file_tasks)}

def current_site_backoff(db, at=None):
    when=time.time() if at is None else float(at)
    row=db.execute("SELECT until_at,reason FROM service_backoff WHERE name='chatgpt'",
                   ).fetchone()
    return row is not None and when < float(row["until_at"])

def note_site_block(db, page):
    """Detect explicit service rate limiting without inspecting cookies or requests."""
    signaled=page.evaluate("""() => {
      // Never interpret a sentence quoted in an actual conversation
      // as a site-level rate limit. Only inspect the error/blocked UI.
      const hasChat=!!document.querySelector(
        '[data-user-message-bubble="true"],h4[data-conversation-role="assistant"]'
      );
      if (hasChat) return false;
      const body=(document.body?.innerText||'').slice(0,3500);
      return /too many requests|rate limit exceeded|unusual activity detected|слишком много запросов|превышен лимит запросов/i.test(body);
    }""")
    if signaled:
        db.execute("""INSERT INTO service_backoff(name,until_at,reason,recorded_at)
            VALUES('chatgpt',?,'rate_limit_message_visible',?)
            ON CONFLICT(name) DO UPDATE SET until_at=excluded.until_at,
              reason=excluded.reason,recorded_at=excluded.recorded_at""",
            (time.time()+BLOCK_COOLDOWN_SECONDS,utc()))
    return bool(signaled)

def assert_unique_url(db, url, allow_project=None):
    pr=db.execute("SELECT id FROM projects WHERE orchestrator_url=?",(url,)).fetchone()
    if pr and pr["id"] != allow_project:
        raise ValueError("Chat URL is another project's orchestrator")
    task=db.execute("SELECT project_id,id FROM tasks WHERE chat_url=?",(url,)).fetchone()
    if task:
        raise ValueError(f"Chat URL already belongs to task {task['project_id']}/{task['id']}")

def register_project(db, name, url):
    name=require_name(name); url=canonical_url(url)
    assert_unique_url(db,url,allow_project=name)
    previous=db.execute("SELECT orchestrator_url FROM projects WHERE id=?",(name,)).fetchone()
    if previous and previous["orchestrator_url"] != url:
        raise ValueError("Existing project's orchestrator is immutable; use a new project_id")
    db.execute("INSERT OR IGNORE INTO projects(id,orchestrator_url,created_at) VALUES(?,?,?)",
               (name,url,utc()))
    return {"project_id":name,"orchestrator_url":url}

def register_task(db, project, task, url):
    project=require_name(project);task=require_name(task);url=canonical_url(url)
    pr=db.execute("SELECT * FROM projects WHERE id=? AND status='enabled'",(project,)).fetchone()
    if not pr: raise ValueError("Unknown or disabled project")
    if pr["orchestrator_url"]==url:raise ValueError("Executor cannot be orchestrator")
    assert_unique_url(db,url)
    prev=db.execute("SELECT chat_url FROM tasks WHERE project_id=? AND id=?",(project,task)).fetchone()
    if prev and prev["chat_url"] != url:
        raise ValueError("Existing task's chat URL is immutable")
    db.execute("""INSERT OR IGNORE INTO tasks(project_id,id,chat_url,state)
               VALUES(?,?,?,'watching')""",(project,task,url))
    return {"project_id":project,"task_id":task,"executor_url":url,"state":"watching"}

def completion_test(db, project, task, text, generating, now_monotonic):
    """Persist two-stable-reads state, triggering only after no spinner."""
    row=db.execute("SELECT * FROM tasks WHERE project_id=? AND id=?",(project,task)).fetchone()
    if row["state"] != "watching":
        return False
    digest=hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
    if not text or generating:
        db.execute("""UPDATE tasks SET last_hash=?,stable_since=NULL,last_text_size=?,error=NULL
                      WHERE project_id=? AND id=?""",(digest,len(text),project,task))
        return False
    if row["last_hash"] != digest or row["stable_since"] is None:
        db.execute("""UPDATE tasks SET last_hash=?,stable_since=?,last_text_size=?,error=NULL
                      WHERE project_id=? AND id=?""",(digest,now_monotonic,len(text),project,task))
        return False
    return now_monotonic-float(row["stable_since"])>=STABLE_SECONDS

def prepare_delivery(db, row, text):
    """Atomic creation of an immutable result and matching delivery record."""
    project=row["project_id"];task=row["id"];url=row["chat_url"]
    p=db.execute("SELECT orchestrator_url FROM projects WHERE id=?",(project,)).fetchone()
    if not p:raise ValueError("Unregistered project")
    outdir=RESULTS / project
    private_directory(outdir)
    revision=int(row["last_revision"])
    target=outdir / (task + (f"-r{revision:02d}" if revision else "") + ".md")
    if target.exists() or target.is_symlink():
        raise RuntimeError("Result file already exists; refusing to overwrite")
    content=text.encode("utf-8")
    fd=os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd,"wb") as handle:
        handle.write(content);handle.flush();os.fsync(handle.fileno())
    digest=hashlib.sha256(content).hexdigest()
    # Revision identity is part of the delivery ID, so repeated identical
    # report text on two different executor turns cannot swallow an event.
    event_key=(f"{project}/{task}/{digest}" if revision==0
               else f"{project}/{task}/r{revision}/{digest}")
    event_id=hashlib.sha256(event_key.encode()).hexdigest()[:32]
    notification=(f"[MC-WATCH:{event_id}]\n"
        "Watcher: executor task completed.\n"
        f"Project: {project}\nTask: {task}\n"
        f"Executor chat: {url}\n"
        f"Report path on Mac: {target}\n"
        f"Report SHA256: {digest}\n"
        "Orchestrator: fetch and verify the report using Mac Control, review acceptance "
        "criteria, then decide the next step. Do not make production changes automatically.")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""UPDATE tasks SET state='completed', result_path=?,result_sha256=?,
                       complete_at=?,error=NULL WHERE project_id=? AND id=? AND state='watching'""",
                   (str(target),digest,utc(),project,task))
        # Browser follow-up revisions need a non-NULL revision: otherwise
        # the legacy per-task partial UNIQUE index silently drops their
        # notifications (INSERT OR IGNORE) after the first completed turn.
        inserted=db.execute("""INSERT OR IGNORE INTO deliveries
            (id,project_id,task_id,orchestrator_url,payload,state,created_at,revision)
            VALUES(?,?,?,?,?,'ready',?,?)""",
            (event_id,project,task,p["orchestrator_url"],notification,utc(),
             revision if revision > 0 else None))
        if inserted.rowcount != 1:
            raise RuntimeError("Result delivery was not created; check unique indexes")
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return {"task":f"{project}/{task}","state":"completed","result_path":str(target),
            "hash":digest,"delivery_id":event_id}

def acknowledge_delivery(db, project_id: str, event_id: str):
    """Explicit idempotent receipt from a reviewing orchestrator.

    Only acknowledge a delivered event in the specified project. An
    acknowledgement is not a new tool execution or a release approval.
    """
    project=require_name(project_id)
    if not re.fullmatch(r"[0-9a-f]{32}",event_id):
        raise ValueError("Invalid event ID")
    row=db.execute(
        "SELECT task_id,state,acknowledged_at FROM deliveries "
        "WHERE project_id=? AND id=?",(project,event_id)).fetchone()
    if row is None:
        raise ValueError("No event with this ID in the requested project")
    if row["state"]!="delivered":
        raise ValueError("Only delivered events may be acknowledged")
    if row["acknowledged_at"] is None:
        db.execute("UPDATE deliveries SET acknowledged_at=? WHERE id=? AND project_id=?",
                   (utc(),event_id,project))
    return {"project_id":project,"event_id":event_id,
            "task_id":row["task_id"],"acknowledged":True}

def project_delivery_barrier(db, page, delivery):
    """Require explicit ack or a visible reply to previous event.

    Avoid deadlocking when ChatGPT virtualizes older conversation DOM nodes.
    """
    previous=db.execute("""SELECT id,acknowledged_at FROM deliveries
       WHERE project_id=? AND state='delivered' AND delivered_at IS NOT NULL
       ORDER BY delivered_at DESC,id DESC LIMIT 1""",(delivery["project_id"],)).fetchone()
    if previous is None or previous["acknowledged_at"]:
        return True
    if previous_event_answered(page, "[MC-WATCH:"+previous["id"]+"]"):
        db.execute("UPDATE deliveries SET acknowledged_at=? WHERE id=? AND acknowledged_at IS NULL",
                   (utc(),previous["id"]))
        return True
    return False

def summary(db, project=None):
    if project:
        require_name(project)
    projects=[dict(x) for x in db.execute("SELECT * FROM projects" + (" WHERE id=?" if project else ""),
                                          (project,) if project else ())]
    tasks=[dict(x) for x in db.execute("SELECT * FROM tasks"+(" WHERE project_id=?" if project else ""),
                                      (project,) if project else ())]
    deliveries=[dict(x) for x in db.execute(
        "SELECT id,project_id,task_id,orchestrator_url,state,attempts,last_error,delivered_at,acknowledged_at FROM deliveries"+
        (" WHERE project_id=?" if project else ""),(project,) if project else ())]
    gates=[dict(x) for x in db.execute(
        "SELECT project_id,idle_since,state,last_checked FROM orchestrator_gates"+
        (" WHERE project_id=?" if project else ""),(project,) if project else ())]
    # Local-only diagnostics; does not touch Chrome or any website.
    navigation=[dict(x) for x in db.execute(
        "SELECT chat_url,last_navigation FROM navigation_budget ORDER BY last_navigation DESC LIMIT 20"
        ).fetchall()]
    cooldown=db.execute("SELECT until_at,reason FROM service_backoff WHERE name='chatgpt'").fetchone()
    from .watcher_browser_followups import setup as setup_browser_followups
    setup_browser_followups(db)
    followups=[dict(row) for row in db.execute(
        "SELECT project_id,task_id,revision,request_id,client_request_id,state,last_error "
        "FROM chatbridge_browser_followups" + (" WHERE project_id=?" if project else ""),
        (project,) if project else ()).fetchall()]
    from .watcher_tab_lifecycle import summary as tab_lifecycle_summary
    return {"projects":projects,"tasks":tasks,"deliveries":deliveries,
            "browser_followups":followups,
            "orchestrator_gates":gates,"active_work":active_work_counts(db),
            "owned_tabs":tab_lifecycle_summary(db),
            "navigation_budget":navigation,
            "site_cooldown":dict(cooldown) if cooldown else None,
            "minimum_navigation_seconds":MIN_CHAT_REFRESH_SECONDS,
            "minimum_poll_seconds":PERIOD}

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('register-project')
    p.add_argument('project_id')
    p.add_argument('orchestrator_url')
    p = sub.add_parser('register-task')
    p.add_argument('project_id')
    p.add_argument('task_id')
    p.add_argument('executor_url')
    p = sub.add_parser('register-file')
    p.add_argument('project_id')
    p.add_argument('task_id')
    p.add_argument('executor_url')
    p = sub.add_parser('submit-file')
    p = sub.add_parser('read-file')
    p.add_argument('project_id')
    p.add_argument('task_id')
    p.add_argument('--revision', type=int, default=0)
    p = sub.add_parser('resume-file')
    p = sub.add_parser('followup-browser')
    p = sub.add_parser('schedule-check')
    p = sub.add_parser('resolve-chat')
    p = sub.add_parser('list-checks')
    p.add_argument('--chat-url', default='')
    p = sub.add_parser('get-check')
    p.add_argument('wakeup_id')
    p = sub.add_parser('cancel-check')
    p.add_argument('wakeup_id')
    p = sub.add_parser('ack-check')
    p.add_argument('wakeup_id')
    p = sub.add_parser('status')
    p.add_argument('--project')
    p = sub.add_parser('ack-delivery')
    p.add_argument('project_id')
    p.add_argument('event_id')
    p = sub.add_parser('poll-once')
    p.add_argument('--project')
    p = sub.add_parser('run')
    p.add_argument('--interval', type=int, default=PERIOD)
    p = sub.add_parser('pause-project')
    p.add_argument('project_id')
    p = sub.add_parser('resume-project')
    p.add_argument('project_id')
    args = parser.parse_args()
    db = connect()
    try:
        if args.cmd == 'register-project':
            output = register_project(db, args.project_id, args.orchestrator_url)
        elif args.cmd == 'register-task':
            output = register_task(db, args.project_id, args.task_id, args.executor_url)
        elif args.cmd == 'register-file':
            from .watcher_file_runtime import register as register_file
            output = register_file(db, args.project_id, args.task_id, args.executor_url)
        elif args.cmd == 'submit-file':
            from .watcher_file_runtime import submit as submit_file
            payload = json.load(sys.stdin)
            output = submit_file(db, payload['project_id'], payload['task_id'], payload['revision'], payload['status'], payload['content'], payload['capability_token'])
        elif args.cmd == 'read-file':
            from .watcher_file_runtime import read_report as read_file_report
            output = read_file_report(db, args.project_id, args.task_id, args.revision)
        elif args.cmd == 'resume-file':
            from .watcher_file_runtime import resume as resume_file
            payload = json.load(sys.stdin)
            output = resume_file(db, payload['project_id'], payload['task_id'], payload['expected_revision'], payload['capability_token'])
        elif args.cmd == 'followup-browser':
            from .watcher_browser_followups import enqueue
            payload = json.load(sys.stdin)
            output = enqueue(db, payload['project_id'], payload['task_id'], payload['prompt'], payload['request_key'])
        elif args.cmd == 'schedule-check':
            from .watcher_schedule_store import schedule
            payload = json.load(sys.stdin)
            url = payload.get('chat_url', '')
            if not url:
                if current_site_backoff(db):
                    raise RuntimeError('ChatGPT browser cooldown active')
                from .watcher_chat_resolver import resolve
                url = resolve(payload.get('evidence_text', ''), db=db)['chat_url']
            output = schedule(db, url, payload['delay_minutes'], payload['objective'], payload.get('request_key', ''))
        elif args.cmd == 'resolve-chat':
            if current_site_backoff(db):
                raise RuntimeError('ChatGPT browser cooldown active')
            from .watcher_chat_resolver import resolve
            output = resolve(json.load(sys.stdin)['evidence_text'], db=db)
        elif args.cmd == 'list-checks':
            from .watcher_schedule_store import list_checks
            output = {'checks': list_checks(db, args.chat_url)}
        elif args.cmd == 'get-check':
            from .watcher_schedule_store import detail
            output = detail(db, args.wakeup_id)
        elif args.cmd == 'cancel-check':
            from .watcher_schedule_store import cancel
            output = cancel(db, args.wakeup_id)
        elif args.cmd == 'ack-check':
            from .watcher_schedule_store import acknowledge
            output = acknowledge(db, args.wakeup_id)
        elif args.cmd == 'status':
            output = summary(db, args.project)
        elif args.cmd == 'ack-delivery':
            output = acknowledge_delivery(db, args.project_id, args.event_id)
        elif args.cmd == 'poll-once':
            raise ValueError('Use python -m mac_control.watcher_runtime run or once')
        elif args.cmd in ('pause-project', 'resume-project'):
            project = require_name(args.project_id)
            target_state = 'paused' if args.cmd == 'pause-project' else 'enabled'
            row = db.execute('SELECT id FROM projects WHERE id=?', (project,)).fetchone()
            if not row:
                raise ValueError('Unknown project')
            db.execute('UPDATE projects SET status=? WHERE id=?', (target_state, project))
            output = {'project_id': project, 'status': target_state}
        elif args.cmd == 'run':
            raise ValueError('Use python -m mac_control.watcher_runtime run or once')
        print(json.dumps({'ok': True, 'data': output}, ensure_ascii=False))
    finally:
        db.close()
