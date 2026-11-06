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
    def test_solid_histogram_columns_and_color_tokens(self):
        self.assertEqual(mclog.histogram_cell(4, 3), "████ ")
        self.assertEqual(mclog.histogram_cell(2, 3), "     ")
        self.assertEqual(mclog.histogram_cell(2, 2), "████ ")
        parts = mclog.argument_segments("command=echo hello, project=workspace, access_token=[скрыто]")
        self.assertEqual("".join(text for text, kind in parts),
                         "command=echo hello, project=workspace, access_token=[скрыто]")
        self.assertIn(("command=", "key"), parts)
        self.assertIn(("access_token=", "key"), parts)
        self.assertIn(("[скрыто]", "secret"), parts)
        self.assertEqual(mclog.argument_segments("нет"), [("нет", "value")])

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


    def test_no_client_column_and_no_null_for_legacy_audit(self):
        from unittest.mock import patch
        class Screen:
            def __init__(self, width=115, height=14):
                self.width, self.height = width,height
                self.rows={}
            def getmaxyx(self): return (self.height,self.width)
            def erase(self):self.rows.clear()
            def addnstr(self,y,x,text,n,style=0):
                existing=self.rows.get(y,"").ljust(x)
                part=text[:n]
                self.rows[y]=existing[:x]+part+existing[x+len(part):]
            def refresh(self):pass
        e={"started":dt.datetime.now(dt.timezone.utc),
           "tool":"terminal_exec","status":"ok"}
        for width in (44,80,115):
            screen=Screen(width)
            with patch.object(mclog.curses, "color_pair", return_value=0):
                mclog.draw(screen,[e],0,Path("/tmp"),dt.datetime.now(dt.timezone.utc),0)
            text="\n".join(screen.rows.values())
            self.assertIn("АРГУМЕНТЫ"[:min(9,width)],text)
            self.assertNotIn("КЛИЕНТ",text)
            self.assertNotIn("null",text)
            self.assertIn("—",text)

    def test_args_presentation_distinguishes_unknown_and_empty(self):
        self.assertEqual(mclog.display_args({"tool":"terminal_exec"}, 80),"—")
        self.assertEqual(mclog.display_args({"tool":"terminal_exec","argument_info":{}},80),"нет")
        self.assertNotIn("null",mclog.display_args({"tool":"terminal_exec","arguments":None},80))

    def test_raw_arguments_override_legacy_info(self):
        row={"tool":"terminal_exec",
             "arguments":{"command":"echo real-command","project":"workspace"},
             "argument_info":{"command":"[команда: 17 симв.]"}}
        self.assertIn("real-command",mclog.display_args(row,160))
        self.assertNotIn("команда:",mclog.display_args(row,160))

    def test_chat_column_shows_only_when_chat_metadata_present(self):
        from unittest.mock import patch
        class Screen:
            def __init__(self,w): self.w=w;self.rows={}
            def getmaxyx(self): return (15,self.w)
            def erase(self): self.rows.clear()
            def addnstr(self,y,x,text,n,style=0):
                existing=self.rows.get(y,"").ljust(x)
                part=text[:n]
                self.rows[y]=existing[:x]+part+existing[x+len(part):]
            def refresh(self): pass
        e={"started":dt.datetime.now(dt.timezone.utc),"tool":"terminal_exec",
           "status":"ok","chat_ref":"0123456789","arguments":{"command":"echo hello"}}
        for width in (44,80,115):
            screen=Screen(width)
            with patch.object(mclog.curses,"color_pair",return_value=0):
                mclog.draw(screen,[e],0,Path("/tmp"),dt.datetime.now(dt.timezone.utc),0)
            t="\n".join(screen.rows.values())
            self.assertNotIn("КЛИЕНТ",t)
            self.assertIn("ЧАТ",t) if width>=95 else self.assertNotIn("ЧАТ",t)
            if width>=95:self.assertIn("Чат 01234567",t)

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
