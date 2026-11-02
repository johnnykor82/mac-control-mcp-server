"""mclog is packaged with a metadata-only audit pipeline."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import mclog
from mac_control.audit_middleware import AuditMiddleware
from scripts import install_mac_control


class MclogReleaseTests(unittest.TestCase):
    def test_versioned_mclog_launcher_and_source_are_packaged(self):
        root = Path(__file__).resolve().parents[2]
        self.assertTrue((root / "bin/mclog").is_file())
        self.assertTrue((root / "scripts/mclog.py").is_file())
        self.assertIn('MAC_CONTROL_DATA_ROOT', (root / "bin/mclog").read_text())
        self.assertEqual(mclog.DEFAULT_LOG, (
            Path(os.environ["MAC_CONTROL_DATA_ROOT"]) / "logs"
            if os.environ.get("MAC_CONTROL_DATA_ROOT")
            else Path.home() / "MacControlMCP/data/logs"
        ))

    def test_installer_copies_mclog_launcher_and_module(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "release"
            target.mkdir()
            install_mac_control.copy_source(target)
            self.assertTrue((target / "bin/mclog").is_file())
            self.assertTrue((target / "scripts/mclog.py").is_file())
            self.assertTrue((target / "bin/mclog").stat().st_mode & 0o111)

    def test_no_arguments_or_results_in_audit_records(self):
        with tempfile.TemporaryDirectory() as temp:
            audit = AuditMiddleware(Path(temp) / "logs")
            redaction_marker = "example_sensitive_value_not_for_logs"
            context = SimpleNamespace(message=SimpleNamespace(
                name="terminal_exec", arguments={"command": f"echo {redaction_marker}"}
            ))
            async def call_next(_):
                return SimpleNamespace(is_error=False, content=[redaction_marker])
            asyncio.run(audit.on_call_tool(context, call_next))
            logfile = Path(temp) / "logs/audit.jsonl"
            lines = [json.loads(x) for x in logfile.read_text().splitlines()]
            self.assertEqual([x["event"] for x in lines],
                             ["tool_start", "tool_end"])
            self.assertEqual(lines[0]["tool"], "terminal_exec")
            self.assertEqual(lines[1]["status"], "ok")
            self.assertEqual(logfile.stat().st_mode & 0o777, 0o600)
            self.assertEqual(logfile.parent.stat().st_mode & 0o777, 0o700)
            self.assertNotIn(redaction_marker, logfile.read_text())
            self.assertNotIn("arguments", logfile.read_text())
            entries, errors = mclog.load(logfile.parent)
            self.assertEqual((len(entries), errors), (1, 0))
            self.assertEqual(entries[0]["status"], "ok")

    def test_argument_info_is_bounded_redacted_and_useful(self):
        from mac_control.audit_middleware import safe_argument_info
        marker = 'this_is_a_sensitive_command_unique_83944'
        payload = {'command': 'echo ' + marker, 'project': 'workspace',
                   'timeout_seconds': 25, 'api_key': 'ghp_secret',
                   'data': {'credentials': marker}, 'path': '/tmp/fictional-secret-file'}
        info = safe_argument_info(payload)
        encoded = json.dumps(info)
        self.assertIn('workspace', encoded)
        self.assertIn('timeout_seconds', encoded)
        self.assertIn('command', encoded)
        self.assertNotIn(marker, encoded)
        self.assertNotIn('ghp_secret', encoded)
        self.assertNotIn('/tmp/fictional-secret-file', encoded)
        self.assertLessEqual(len(encoded), 500)
        self.assertEqual(safe_argument_info({}), {})
        self.assertEqual(safe_argument_info(None), {})
        self.assertEqual(safe_argument_info({"action":"private_command_94289"})["action"],
                         "[строка: 21 симв.]")
        self.assertEqual(safe_argument_info({"mode":"background"})["mode"], "background")
        self.assertEqual(safe_argument_info({"operation":"terminal_exec"})["operation"], "terminal_exec")
        self.assertEqual(safe_argument_info({"api_key":"confidential"})["api_key"], "[скрыто]")
        self.assertEqual(safe_argument_info({"user_id":12345})["user_id"], "[число]")
        self.assertEqual(safe_argument_info({"timeout_seconds":25})["timeout_seconds"], 25)
        self.assertEqual(safe_argument_info({"timeout_seconds":10**1000})["timeout_seconds"],
                         "[число]")
        self.assertEqual(safe_argument_info({"data":{"untrusted_secret":"PRIVATE"}})["data"],
                         "[объект: 1 полей]")

    def test_audit_persists_only_safe_argument_info(self):
        with tempfile.TemporaryDirectory() as temp:
            audit = AuditMiddleware(Path(temp) / "logs")
            marker = "sensitive_content_marker_not_to_log_9323"
            ctx = SimpleNamespace(message=SimpleNamespace(
                name="terminal_exec", arguments={"command": "printf " + marker,
                    "project": "workspace", "timeout_seconds": 20}
            ))
            async def run(_):
                return SimpleNamespace(is_error=False)
            asyncio.run(audit.on_call_tool(ctx, run))
            raw=(Path(temp)/"logs/audit.jsonl").read_text()
            rows=[json.loads(x) for x in raw.splitlines()]
            self.assertNotIn(marker, raw)
            self.assertNotIn("arguments", rows[0])
            self.assertIn("argument_info", rows[0])
            self.assertEqual(rows[0]["argument_info"]["project"], "workspace")
            self.assertEqual(rows[0]["argument_info"]["timeout_seconds"], 20)

    def test_exceptions_logged_without_contents_and_raised(self):
        with tempfile.TemporaryDirectory() as temp:
            audit = AuditMiddleware(Path(temp) / "logs")
            context = SimpleNamespace(message=SimpleNamespace(name="fs_write", arguments={
                "content": "private"
            }))
            async def fail(_):
                raise RuntimeError("SECRET DO NOT LOG")
            with self.assertRaisesRegex(RuntimeError, "SECRET DO NOT LOG"):
                asyncio.run(audit.on_call_tool(context, fail))
            raw = (Path(temp) / "logs/audit.jsonl").read_text()
            self.assertIn('"status": "exception"', raw)
            self.assertNotIn("SECRET DO NOT LOG", raw)
            self.assertNotIn("private", raw)


if __name__ == "__main__":
    unittest.main()
