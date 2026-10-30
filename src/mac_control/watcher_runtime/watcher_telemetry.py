"""Passive, privacy-minimal Watcher / ChatBridge telemetry.

No ChatGPT provider endpoint is called. Reads existing local /metrics every
5 minutes, counts existing Watcher -> localhost calls in memory, aggregates in
SQLite by 5-minute bucket. Historical counters are never backfilled.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from collections import defaultdict
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

SAMPLE_SECONDS = 300
BUCKET_SECONDS = 300
KEEP_SECONDS = 90 * 86400
from ..runtime_paths import DATA_ROOT
DEFAULT_DB = DATA_ROOT / "run" / "watcher" / "watcher.sqlite3"

_active = False
_calls = defaultdict(lambda: [0, 0, 0])  # calls, errors, elapsed_ms
_db = None


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS watcher_telemetry_calls (
      bucket_start INTEGER NOT NULL,
      operation TEXT NOT NULL,
      outcome TEXT NOT NULL,
      calls INTEGER NOT NULL DEFAULT 0,
      errors INTEGER NOT NULL DEFAULT 0,
      total_ms INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(bucket_start, operation, outcome)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS watcher_telemetry_gateway (
      sampled_at INTEGER PRIMARY KEY,
      history_reads INTEGER NOT NULL,
      turn_state_reads INTEGER NOT NULL,
      readiness_page_loads INTEGER NOT NULL,
      provider_429_events INTEGER NOT NULL,
      active_slots INTEGER NOT NULL,
      queued INTEGER NOT NULL,
      incidents INTEGER NOT NULL,
      retry_after INTEGER NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS watcher_telemetry_meta (
      key TEXT PRIMARY KEY, value TEXT NOT NULL
    )""")


def attach(db):
    global _db, _active
    setup(db)
    _db = db
    _active = True


def detach():
    global _db, _active
    _db = None
    _active = False
    _calls.clear()


def operation(method, path):
    """Fixed vocabulary only: never record path IDs, query text or prompts."""
    if method == "POST" and re.fullmatch(r"/v1/sessions/[^/]+/sync", path):
        return "provider_history_sync"
    if method == "GET" and re.fullmatch(r"/v1/sessions/[^/]+/turn-state", path):
        return "provider_history_poll"
    if method == "POST" and re.fullmatch(r"/v1/requests/[^/]+/reconcile", path):
        return "provider_reconciliation"
    if method == "POST" and re.fullmatch(r"/v1/sessions/[^/]+/messages", path):
        return "submit_model_turn"
    if method == "POST" and path == "/v1/sessions":
        return "session_import"
    if method == "GET" and re.fullmatch(r"/v1/requests/[^/]+", path):
        return "local_request_status"
    if method == "GET" and re.fullmatch(r"/v1/sessions/[^/]+/messages\?.*", path):
        return "local_message_history"
    if method == "GET" and path.startswith("/v1/sessions?"):
        return "local_session_index"
    if method == "GET" and re.fullmatch(r"/v1/sessions/[^/]+", path):
        return "local_session_metadata"
    if method == "GET" and path == "/v1/system/status":
        return "local_gateway_status"
    if method == "GET" and path == "/metrics":
        return "local_gateway_metrics"
    return "other_local_api"


def observe(method, path, outcome, elapsed_seconds, *, now=None):
    if not _active:
        return
    bucket = int(time.time() if now is None else now) // BUCKET_SECONDS * BUCKET_SECONDS
    key = (bucket, operation(method, path), outcome)
    row = _calls[key]
    row[0] += 1
    row[1] += outcome != "ok"
    row[2] += max(0, int(elapsed_seconds * 1000))


def flush(*, now=None):
    if not _active or _db is None or not _calls:
        return 0
    rows = list(_calls.items())
    # During setup/shutdown a SQLite transaction may be open elsewhere.
    # Flush is only called after the Watcher iteration has returned.
    with _db:
        for (bucket, name, outcome), (count, errors, ms) in rows:
            _db.execute("""INSERT INTO watcher_telemetry_calls
               (bucket_start,operation,outcome,calls,errors,total_ms)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(bucket_start,operation,outcome) DO UPDATE SET
                 calls=calls+excluded.calls,errors=errors+excluded.errors,
                 total_ms=total_ms+excluded.total_ms""",
                (bucket, name, outcome, count, errors, ms))
        cutoff=int(time.time() if now is None else now)-KEEP_SECONDS
        _db.execute("DELETE FROM watcher_telemetry_calls WHERE bucket_start < ?",(cutoff,))
    _calls.clear()
    return len(rows)


def maybe_sample(api, *, now=None):
    """One local /metrics GET every 300 seconds, never a provider call."""
    if not _active or _db is None:
        return False
    at=int(time.time() if now is None else now)
    latest=_db.execute("SELECT MAX(sampled_at) FROM watcher_telemetry_gateway").fetchone()[0]
    if latest is not None and at-latest < SAMPLE_SECONDS:
        return False
    response=api("GET","/metrics")
    checks=response.get("provider_checks",{})
    limits=response.get("rate_limit",{})
    def number(obj,key):
        value=obj.get(key,0)
        return max(0,int(value or 0))
    values=(at,number(checks,"history_reads"),number(checks,"turn_state_reads"),
        number(checks,"readiness_page_loads"),number(checks,"provider_429_events"),
        number(response,"active_slots"),number(response,"queued"),
        number(limits,"incidents"),number(limits,"retry_after"))
    with _db:
        _db.execute("""INSERT OR IGNORE INTO watcher_telemetry_gateway
            (sampled_at,history_reads,turn_state_reads,readiness_page_loads,
             provider_429_events,active_slots,queued,incidents,retry_after)
            VALUES(?,?,?,?,?,?,?,?,?)""",values)
        cutoff=at-KEEP_SECONDS
        _db.execute("DELETE FROM watcher_telemetry_gateway WHERE sampled_at < ?",(cutoff,))
    return True


COUNTERS = ("history_reads","turn_state_reads",
            "readiness_page_loads","provider_429_events")


def _coverage(rows, start, end):
    return {
        "samples": len(rows),
        "first": rows[0]["sampled_at"] if rows else None,
        "last": rows[-1]["sampled_at"] if rows else None,
        "window_start": start,
        "window_end": end,
        "complete_window": bool(rows and rows[0]["sampled_at"] <= start+SAMPLE_SECONDS
                                and rows[-1]["sampled_at"] >= end-SAMPLE_SECONDS),
    }


def _deltas(rows):
    totals={key:0 for key in COUNTERS}
    resets={key:0 for key in COUNTERS}
    for previous,current in pairwise(rows):
        for key in COUNTERS:
            diff=current[key]-previous[key]
            if diff<0:
                resets[key]+=1
                # Reset is a new counter epoch. Do not count the new absolute
                # value as a delta: it may include traffic before the sample.
            else:
                totals[key]+=diff
    return totals,resets


def report(db, hours=24, *, now=None):
    now=int(time.time() if now is None else now)
    start=now-max(1,min(int(hours),24*90))*3600
    db.row_factory=sqlite3.Row
    calls=[dict(r) for r in db.execute("""SELECT operation,SUM(calls) calls,
         SUM(errors) errors,SUM(total_ms) total_ms FROM watcher_telemetry_calls
         WHERE bucket_start >= ? AND bucket_start <= ?
         GROUP BY operation ORDER BY calls DESC""",
         (start//BUCKET_SECONDS*BUCKET_SECONDS,now))]
    samples=[dict(r) for r in db.execute("""SELECT * FROM watcher_telemetry_gateway
         WHERE sampled_at >= ? AND sampled_at <= ? ORDER BY sampled_at""",(start,now))]
    delta,resets=_deltas(samples)
    coverage=_coverage(samples,start,now)
    provider_hourly={}
    for previous,current in pairwise(samples):
        hour=current["sampled_at"]//3600*3600
        if hour not in provider_hourly:
            provider_hourly[hour]={key:0 for key in COUNTERS}
        for key in COUNTERS:
            diff=current[key]-previous[key]
            if diff>=0:
                provider_hourly[hour][key]+=diff
    watcher_hourly=[dict(r) for r in db.execute("""
        SELECT (bucket_start/3600)*3600 hour_start,operation,
               SUM(calls) calls,SUM(errors) errors
        FROM watcher_telemetry_calls WHERE bucket_start >= ? AND bucket_start <= ?
        GROUP BY hour_start,operation ORDER BY hour_start,operation
    """,(start//BUCKET_SECONDS*BUCKET_SECONDS,now))]
    # An explicit 'unobserved' state prevents zero-looking metrics before the
    # system has accumulated enough real samples.
    return {
        "generated_at_utc":datetime.fromtimestamp(now,UTC).isoformat(),
        "hours":hours,
        "coverage":coverage,
        "gateway_provider_deltas":delta if len(samples)>1 else None,
        "gateway_counter_resets":resets if len(samples)>1 else None,
        "gateway_hourly_deltas":[{"hour_start":hour,**totals}
            for hour,totals in sorted(provider_hourly.items())],
        "watcher_api_operations":calls,
        "watcher_hourly_operations":watcher_hourly,
        "classification": {
            "local_gateway_http_requests": "Calls to 127.0.0.1, not external ChatGPT requests",
            "provider_history_poll": "Local HTTP endpoint that triggers provider history fetch",
            "provider_history_sync": "Local HTTP endpoint that triggers provider history fetch",
            "provider_429_events": "Observed responses, not necessarily independent cooldown incidents",
            "caveat":"Samples every 5 minutes: deltas omit traffic before the first sample, "
                     "and the classification is not a complete network HAR. "
                     "No provider endpoint was queried for this report."
        },
    }


def main():
    parser=argparse.ArgumentParser(description="Read-only on-demand ChatBridge/Watcher telemetry")
    parser.add_argument("command",choices=["report"])
    parser.add_argument("--hours",type=int,default=24)
    parser.add_argument("--db",type=Path,default=DEFAULT_DB)
    parser.add_argument("--json",action="store_true")
    args=parser.parse_args()
    if args.hours<1 or args.hours>24*90:
        parser.error("--hours must be 1..2160")
    db=sqlite3.connect(f"file:{args.db}?mode=ro",uri=True)
    try:
        result=report(db,args.hours)
    finally:
        db.close()
    if args.json:
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    coverage=result["coverage"]
    def when(timestamp):
        return (datetime.fromtimestamp(timestamp,UTC).isoformat()
                if timestamp is not None else "not yet sampled")
    print("ChatBridge + Watcher telemetry | last",args.hours,"hours")
    print("Coverage:",coverage["samples"],"gateway samples,",
          when(coverage["first"]),"→",when(coverage["last"]))
    if not coverage["complete_window"]:
        print("WARNING: Partial coverage; do not extrapolate to entire window.")
    print("Gateway deltas:",result["gateway_provider_deltas"] or "insufficient samples")
    print("Counter resets:",result["gateway_counter_resets"] or "insufficient samples")
    print("Hourly provider delta:")
    for row in result["gateway_hourly_deltas"]:
        print("  ",datetime.fromtimestamp(row["hour_start"],UTC).strftime("%Y-%m-%d %H:00 UTC"),
              {k:row[k] for k in COUNTERS})
    print("Watcher local API operations:")
    for row in result["watcher_api_operations"]:
        print("  ",row["operation"],"calls",row["calls"],"errors",row["errors"],
              "total_ms",row["total_ms"])


if __name__=="__main__":
    main()
