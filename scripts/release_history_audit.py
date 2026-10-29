#!/usr/bin/env python3
"""Git history hygiene audit (offline, bounded).

Scans locally reachable blob objects for obvious credential signatures;
prints only blob ID, historical path and line number, never secret values.
Not a provenance, license, or complete secret-leak guarantee.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from release_audit import PATTERNS

ROOT = Path(__file__).resolve().parents[1]
MAX_BLOB_BYTES = 2 * 1024 * 1024
CRITICAL = [(name, pattern) for name, severity, pattern in PATTERNS
            if severity == "critical"]


def cmd(*argv: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *argv], check=True,
                          input=input_bytes, capture_output=True).stdout


def audit_history() -> dict:
    records = []
    seen = set()
    for record in cmd("rev-list", "--objects", "--all").splitlines():
        sha, sep, name = record.partition(b" ")
        if sep and sha not in seen:
            records.append((sha.decode(), name.decode(errors="replace")))
            seen.add(sha)
    findings = []
    scanned = 0
    skipped = 0
    for sha, name in records:
        meta = cmd("cat-file", "-s", sha)
        size = int(meta.strip())
        if size > MAX_BLOB_BYTES:
            skipped += 1
            continue
        typ = cmd("cat-file", "-t", sha).strip()
        if typ != b"blob":
            continue
        data = cmd("cat-file", "blob", sha)
        scanned += 1
        for line_num, line in enumerate(data.splitlines(), 1):
            for kind, pattern in CRITICAL:
                if pattern.search(line):
                    findings.append({"kind": kind, "blob": sha[:12],
                                     "historical_path": name, "line": line_num})
    return {
        "schema": 1, "scanned_blobs": scanned, "skipped_large_objects": skipped,
        "critical_findings": findings,
        "limitations": [
            "Only local Git refs are scanned, not deleted or unreachable Git objects.",
            "Heuristic signatures miss many secrets and do not validate revocation.",
            "A license and private-data review is still required before publication.",
        ],
    }


if __name__ == "__main__":
    result = audit_history()
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["critical_findings"] or result["skipped_large_objects"] else 0)
