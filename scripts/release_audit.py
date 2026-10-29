#!/usr/bin/env python3
"""Offline scan of Git-tracked files for obvious publish blockers.

This is a pre-publication gate, not a substitute for secret/history review.
Prints file paths and line numbers, never matched secret contents.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATTERNS = [
    ("private_key", "critical", re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("github_token", "critical", re.compile(rb"gh(?:p|o|u|s|r)_[A-Za-z0-9]{25,}")),
    ("github_fine_grained", "critical", re.compile(rb"github_pat_[A-Za-z0-9_]{25,}")),
    ("openai_like_token", "critical", re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{28,}")),
    ("aws_access_key", "critical", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("embedded_credential_assignment", "critical",
     re.compile(rb"(?im)^\s*(?:export\s+)?(?:[A-Z_]*SECRET|[A-Z_]*PASSWORD|[A-Z_]*API_KEY)\s*=\s*['\x22]?[A-Za-z0-9_+/.=-]{16,}")),
    ("user_specific_absolute_path", "warning", re.compile(rb"/Users/[a-zA-Z0-9._-]+/")),
    ("personal_namespace", "warning", re.compile(rb"net\.johnnykor\.|johnnykor82")),
]
SENSITIVE_ENDINGS = (".pem", ".p12", ".p8", ".key", ".mobileprovision")


def tracked() -> list[pathlib.Path]:
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                            check=True, capture_output=True)
    return [ROOT / path.decode("utf-8", errors="surrogateescape")
            for path in result.stdout.split(b"\x00") if path]


def audit() -> dict:
    findings = []
    paths = tracked()
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file() or path.is_symlink():
            findings.append({"severity": "critical", "type": "missing_or_symlink", "file": relative, "line": 0})
            continue
        if path.name.lower().endswith(SENSITIVE_ENDINGS):
            findings.append({"severity": "critical", "type": "credential_file_extension", "file": relative, "line": 0})
        if path.stat().st_size > 1024 * 1024:
            findings.append({"severity": "warning", "type": "large_tracked_file", "file": relative, "line": 0})
            continue
        for number, line in enumerate(path.read_bytes().splitlines(), 1):
            for kind, severity, pattern in PATTERNS:
                # Known scanner self-tests and documentation may contain regex examples;
                # still report them for human classification.
                if pattern.search(line):
                    findings.append({"severity": severity, "type": kind,
                                     "file": relative, "line": number})
    return {"schema": 1, "tracked_files": len(paths), "critical_count": sum(
        f["severity"] == "critical" for f in findings),
        "warning_count": sum(f["severity"] == "warning" for f in findings),
        "findings": findings,
        "limitations": [
            "Scans current Git-tracked working tree only, not history or remote repositories.",
            "Pattern matching cannot find all credentials or prove they were revoked.",
            "Review full Git history and source licenses before publication.",
            "Warnings are evidence of non-portable hardcoded configuration, not automatically leaked secrets.",
        ]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="Fail if critical findings are present")
    args = parser.parse_args()
    result = audit()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Tracked: {result['tracked_files']} | critical: {result['critical_count']} | warnings: {result['warning_count']}")
        for finding in result["findings"]:
            print(f"{finding['severity']} {finding['type']} {finding['file']}:{finding['line']}")
        for note in result["limitations"]:
            print("LIMITATION:", note)
    return 1 if args.strict and result["critical_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
