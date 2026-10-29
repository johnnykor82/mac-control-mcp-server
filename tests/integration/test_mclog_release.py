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
            else Path.home() / "Library/Application Support/MacControl/MCPServer/data/logs"
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
