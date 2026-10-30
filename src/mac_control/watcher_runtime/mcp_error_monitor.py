"""Non-destructive MCP error monitor for the Watcher daemon.

Consumes incremental sanitized records from the MCP audit JSONL, classifies
errors, and enqueues bounded diagnostic notifications. Does not read raw tool
arguments or execute repairs, commands, or modifications to monitored files.
"""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from ..runtime_paths import DATA_ROOT
ROOT=DATA_ROOT
AUDIT=ROOT/"logs"/"audit.jsonl"
MAX_BYTES_PER_POLL=2*1024*1024
ADMIN_PROJECT="mac-control"

def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def setup(db):
    db.executescript("""
      CREATE TABLE IF NOT EXISTS monitor_cursor (
        source TEXT PRIMARY KEY, dev INTEGER NOT NULL, inode INTEGER NOT NULL,
        offset INTEGER NOT NULL, updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS monitor_issues (
        fingerprint TEXT PRIMARY KEY, tool TEXT NOT NULL,
        category TEXT NOT NULL, severity TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 0, first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL, last_notified_bucket INTEGER
      );
      CREATE TABLE IF NOT EXISTS monitor_alerts (
        id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
        project_id TEXT, created_at TEXT NOT NULL,
        kind TEXT NOT NULL
      );
    """)

def classify(tool,error):
    # Expected failures are treated as actionable diagnostics, not crashes.
    text=error.lower()
    if "no managed chatgpt tab for specified task_id" in text:
        return "archived_chat","info","restore_registered_chat_tab_before_reading"
    if "not a git repository" in text:
        return "environment_validation","info","check_project_git_initialization_or_use_non_git_tool"
    if "sha256 mismatch" in text or "sha256 required or mismatched" in text:
        return "cas_conflict","info","read_current_file_reconcile_then_retry"
    # The filesystem READ tools intentionally reject invalid scopes/paths.
    # The MCP wrapper sometimes hides the exception type: for the verified
    # fs_list("workspace", "watcher") failure it exposes only ": watcher".
    # Keep this exception exact; never downgrade arbitrary bare ToolErrors.
    if tool in ("fs_list", "fs_stat", "fs_read", "fs_search"):
        expected_path_error=(
            "relative non-traversing path required" in text
            or "[errno 2] no such file or directory" in text
            or "[errno 20] not a directory" in text
            or "filenotfounderror:" in text
            or "notadirectoryerror:" in text
            or (tool=="fs_list"
                and text.strip()=="error calling tool 'fs_list': watcher")
        )
        if expected_path_error:
            return "validation","info","check_arguments_and_current_constraints"
    if "file handoff rejected; check task state and parameters" in text:
        return "validation","info","check_arguments_and_current_constraints"
    if "invalid id" in text or "invalid path" in text or "expected exactly one" in text:
        return "validation","info","check_arguments_and_current_constraints"
    if "permission not granted" in text or "not authorized" in text:
        return "permissions","warning","check_system_permissions"
    if "not in owner-managed allowlist" in text or "permission denied" in text:
        return "policy_denial","info","verify_local_policy_before_request"
    if "timeout" in text or "temporarily unavailable" in text or "connection refused" in text:
        return "transient","warning","retry_read_only_health_check"
    return "unexpected","high","inspect_redacted_logs_and_reproduce_without_side_effects"

def scan(db, log_path=AUDIT, notify_project=ADMIN_PROJECT, bootstrap=False):
    """Process complete JSONL records only; checkpoint bytes across restarts.

    A first-time setup starts at EOF, intentionally avoiding notifications
    for historic known errors. Test callers may pass bootstrap=True to process
    all supplied records without sending alerts.
    """
    setup(db)
    if not log_path.exists() or log_path.is_symlink():
        return {"read_events":0,"new_errors":0,"queued_alerts":0,"monitor":"log_unavailable"}
    info=log_path.stat()
    key=str(log_path)
    c=db.execute("SELECT dev,inode,offset FROM monitor_cursor WHERE source=?",(key,)).fetchone()
    if c is None:
        offset=0 if bootstrap else info.st_size
        db.execute("""INSERT INTO monitor_cursor(source,dev,inode,offset,updated_at)
                      VALUES(?,?,?,?,?)""",(key,info.st_dev,info.st_ino,offset,now_utc()))
    elif c[0]!=info.st_dev or c[1]!=info.st_ino or info.st_size<c[2]:
        offset=0
        db.execute("UPDATE monitor_cursor SET dev=?,inode=?,offset=?,updated_at=? WHERE source=?",
                   (info.st_dev,info.st_ino,0,now_utc(),key))
    else:
        offset=c[2]
    read_events=0
    errors=0
    alerts=0
    with log_path.open("rb") as source:
        source.seek(offset)
        data=source.read(MAX_BYTES_PER_POLL)
    if not data:
        return {"read_events":0,"new_errors":0,"queued_alerts":0,"monitor":"ok"}
    complete=data.rfind(b"\n")
    if complete==-1:
        return {"read_events":0,"new_errors":0,"queued_alerts":0,"monitor":"partial_line"}
    raw=data[:complete+1]
    for line in raw.splitlines():
        read_events+=1
        try:
            event=json.loads(line)
        except (UnicodeError,ValueError):
            continue
        if not (event.get("event")=="tool_end" and event.get("status")=="exception"):
            continue
        errors+=1
        tool=str(event.get("tool","unknown"))[:70]
        error=str(event.get("error",""))
        # Public audit deliberately omits exception messages. An unknown
        # refusal is not evidence of a severe incident or permission failure.
        category,severity,hint=(classify(tool,error) if error else
            ("unclassified", "info", "Inspect local diagnostics if needed"))
        fingerprint=hashlib.sha256((tool+"|"+category+"|"+hint).encode()).hexdigest()[:24]
        record=db.execute("SELECT count,last_notified_bucket FROM monitor_issues WHERE fingerprint=?",
                          (fingerprint,)).fetchone()
        if record:
            count=record[0]+1
            db.execute("UPDATE monitor_issues SET count=?,last_seen=? WHERE fingerprint=?",
                       (count,now_utc(),fingerprint))
        else:
            count=1
            db.execute("""INSERT INTO monitor_issues
                (fingerprint,tool,category,severity,count,first_seen,last_seen)
                VALUES(?,?,?,?,?,?,?)""",
                (fingerprint,tool,category,severity,1,now_utc(),now_utc()))
        # A single bad argument or CAS conflict must not wake an orchestrator.
        # Validation is a normal refusal, not an orchestrator incident.
        # Keep aggregate counts locally without waking ChatGPT after 5 calls.
        alert_needed=(severity=="high" or
            (severity=="warning" and count>=3) or
            (category=="cas_conflict" and count>=5))
        if not alert_needed or bootstrap:
            continue
        bucket=int(time.time()//(15*60))
        if record is not None and record[1]==bucket:
            continue
        project=db.execute("SELECT orchestrator_url FROM projects WHERE id=? AND status='enabled'",
                           (notify_project,)).fetchone()
        if project is None:
            continue
        # This payload is generated solely from safe classification metadata.
        event_id=hashlib.sha256(f"mcp-alert/{fingerprint}/{bucket}".encode()).hexdigest()[:32]
        event_name="ops-"+event_id[:18]
        message=(f"[MC-WATCH:{event_id}]\n"
            "Watcher: MCP diagnostic incident detected.\n"
            f"Project: {notify_project}\nIncident: {event_name}\n"
            f"Tool: {tool}\nCategory: {category}\nSeverity: {severity}\n"
            f"Occurrences (retained): {count}\nSuggested response: {hint}\n"
            "Review watcher_error_status and the redacted MCP audit. "
            "Never auto-execute untrusted code or override file conflicts.")
        db.execute("""INSERT OR IGNORE INTO deliveries
            (id,project_id,task_id,orchestrator_url,payload,state,created_at)
            VALUES(?,?,?,?,?,'ready',?)""",
            (event_id,notify_project,event_name,project[0],message,now_utc()))
        db.execute("""INSERT OR IGNORE INTO monitor_alerts
            (id,fingerprint,project_id,created_at,kind) VALUES(?,?,?,?,?)""",
            (event_id,fingerprint,notify_project,now_utc(),category))
        db.execute("UPDATE monitor_issues SET last_notified_bucket=? WHERE fingerprint=?",
                   (bucket,fingerprint))
        alerts+=1
    db.execute("UPDATE monitor_cursor SET offset=?,updated_at=? WHERE source=?",
               (offset+len(raw),now_utc(),key))
    return {"read_events":read_events,"new_errors":errors,
            "queued_alerts":alerts,"monitor":"ok"}

def status(db,limit=20):
    setup(db)
    issues=[dict(row) for row in db.execute(
        "SELECT tool,category,severity,count,first_seen,last_seen FROM monitor_issues "
        "ORDER BY last_seen DESC LIMIT ?",(min(max(1,int(limit)),100),)).fetchall()]
    alerts=[dict(row) for row in db.execute(
        "SELECT id,project_id,created_at,kind FROM monitor_alerts "
        "ORDER BY created_at DESC LIMIT 20").fetchall()]
    return {"issues":issues,"alerts":alerts,"policy":{
        "safe_self_healing":["launchd_watcher_restart","chrome_reconnect"],
        "never_automatic":["code_patch","cas_override","terminal_command","ssh","gui_permission_change"],
        "audit_content":"error_metadata_only",
        "notification":"queue_if_idle_in_own_project"}}
