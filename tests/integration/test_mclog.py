"""Regression checks for the read-only mclog audit viewer."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from scripts import mclog


def event(eid, kind, status=None, instant="2026-10-24T12:30:00.000+00:00"):
    obj = {"id": eid, "event": kind, "time_utc": instant, "tool": "terminal_exec"}
    if kind == "tool_start":
        obj["arguments"] = {"command": "echo hello", "timeout_seconds": 25}
    else:
        obj["status"] = status
        obj["duration_ms"] = 15
    return json.dumps(obj) + "\n"


class MacLogTests(unittest.TestCase):
    def test_redaction_and_arguments(self):
        text = mclog.safe_args({"command": "echo hello world",
                                "timeout_seconds": 15, "access_token": "supersecret"}, 140)
        self.assertIn("command=echo hello world", text)
        self.assertNotIn("timeout", text)
        self.assertNotIn("supersecret", text)
        self.assertIn("[скрыто]", text)
        self.assertNotIn("ghp_TEST_SECRET_BEARER", mclog.safe_args({"command": "ghp_TEST_SECRET_BEARER"}, 200))
        self.assertNotIn("secretvalue", mclog.safe_args({"command": "Bearer secretvalue"}, 200))
        self.assertTrue(mclog.safe_args({"command": "x"*70}, 26).endswith("…"))

    def test_client_pid_is_not_identity(self):
        self.assertEqual(mclog.source({"pid": 3356}), "—")
        self.assertEqual(mclog.source({"client": "CLI", "pid": 3356}), "CLI")

    def test_incremental_partial_and_rotation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            active = root/"audit.jsonl"
            active.write_text(event("a", "tool_start") + event("a", "tool_end", "ok"))
            reader = mclog.AuditReader()
            rows, bad = reader.refresh(root)
            self.assertEqual((len(rows), bad, rows[0]["status"]), (1, 0, "ok"))
            rows, bad = reader.refresh(root)
            self.assertEqual(len(rows), 1)
            partial = event("b", "tool_start").strip()
            with active.open("a") as f:
                f.write(partial)
            self.assertEqual(len(reader.refresh(root)[0]), 1)
            with active.open("a") as f:
                f.write("\n" + event("b", "tool_end", "error"))
            rows, bad = reader.refresh(root)
            self.assertEqual((len(rows), bad), (2, 0))
            self.assertEqual(sum(mclog.is_error(x) for x in rows), 1)
            active.rename(root/"audit.jsonl.2026-10-23")
            active.write_text(event("c", "tool_start") + event("c", "tool_end", "ok"))
            rows, bad = reader.refresh(root)
            self.assertEqual((len(rows), bad), (3, 0))
            self.assertEqual({r["id"] for r in rows}, {"a", "b", "c"})

    def test_error_classification(self):
        self.assertFalse(mclog.is_error({"status": "running"}))
        self.assertFalse(mclog.is_error({"status": "ok"}))
        self.assertTrue(mclog.is_error({"status": "error"}))


if __name__ == "__main__":
    unittest.main()
