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
        self.assertEqual(mclog.histogram_cell(4, 3), "┃┃┃ ")
        self.assertEqual(mclog.histogram_cell(2, 3), "    ")
        self.assertEqual(mclog.histogram_cell(2, 2), "┃┃┃ ")
        parts = mclog.argument_segments("command=echo hello, project=workspace, access_token=[скрыто]")
        self.assertEqual("".join(text for text, kind in parts),
                         "command=echo hello, project=workspace, access_token=[скрыто]")
        self.assertIn(("command=", "key"), parts)
        self.assertIn(("access_token=", "key"), parts)
        self.assertIn(("[скрыто]", "secret"), parts)
        self.assertEqual(mclog.argument_segments("нет"), [("нет", "value")])

    def test_three_argument_modes_safely_wrap_and_label(self):
        e = {
            "tool": "terminal_exec",
            "audit_context": {
                "task_id": "UX3-04",
                "action": "Read the long report and validate details without changes",
                "authorization_basis": "Approved by owner on 2026-11-06 under plan UX3",
            },
            "arguments": {
                "audit_context": {
                    "task_id": "UX3-04",
                    "action": "Read the long report and validate details without changes",
                    "authorization_basis": "Approved by owner on 2026-11-06 under plan UX3",
                },
                "command": "echo " + "longargument" * 8,
                "password": "SECRET_SHOULD_NEVER_APPEAR",
            },
        }
        compact = mclog.render_event_arguments(e, 35, "compact")
        wrapped = mclog.render_event_arguments(e, 35, "wrap")
        detailed = mclog.render_event_arguments(e, 35, "detail")
        self.assertEqual(len(compact), 1)
        self.assertGreater(len(wrapped), 3)
        self.assertGreaterEqual(len(detailed), 8)
        self.assertTrue(detailed[0].startswith("Задача: UX3-04"))
        self.assertTrue(any(x.startswith("Действие:") for x in detailed))
        self.assertTrue(any(x.startswith("Основание:") for x in detailed))
        self.assertTrue(any(x.startswith("Команда:") for x in detailed))
        for lines in (compact, wrapped, detailed):
            self.assertTrue(all(len(x) <= 35 for x in lines))
            self.assertNotIn("SECRET_SHOULD_NEVER_APPEAR", "\n".join(lines))
        self.assertIn("[скрыто]", " ".join(detailed))
        self.assertIn("longargument", " ".join(detailed))

    def test_draw_three_modes_aligns_continuations_to_argument_column(self):
        from unittest.mock import patch
        class Screen:
            def __init__(self):
                self.width, self.height, self.rows = 95, 34, {}
            def getmaxyx(self): return self.height, self.width
            def erase(self): self.rows = {}
            def addnstr(self, y, x, value, n, style=0):
                value = value[:n]
                old = self.rows.get(y, "").ljust(x)
                self.rows[y] = old[:x] + value + old[x+len(value):]
            def refresh(self): pass

        t = dt.datetime.now(dt.timezone.utc)
        e = {"started": t, "tool": "terminal_exec", "status": "ok",
             "audit_context": {
                 "task_id": "UX3-04",
                 "action": "Read and inspect a long historical command output with details",
                 "authorization_basis": "User-approved detailed UX on 2026-11-06",
             },
             "arguments": {"command": "printf " + "longtext" * 16}}
        for mode in ("compact", "wrap", "detail"):
            screen = Screen()
            with patch.object(mclog.curses, "color_pair", return_value=0):
                off, used = mclog.draw(screen, [e], 0, Path("/tmp"), t, 0, mode=mode)
            self.assertEqual(off, 0)
            self.assertGreaterEqual(used, 1)
            rows = list(screen.rows.values())
            self.assertTrue(all(len(x) <= screen.width for x in rows), mode)
            if mode == "compact":
                self.assertFalse(any("Основание:" in x for x in rows))
            elif mode == "detail":
                self.assertTrue(any("Задача: UX3-04" in x for x in rows))
                self.assertTrue(any("Команда:" in x for x in rows))
            else:
                self.assertTrue(any("Действие:" in x for x in rows))
            data_lines = [x for x in rows if "longtext" in x]
            if mode != "compact":
                self.assertGreaterEqual(len(data_lines), 2)

    def test_detail_all_fields_wrap_without_escaping_column(self):
        context = {
            "task_id": "UI-LONG-" + "9" * 48,
            "action": "Detailed action with several words " * 5,
            "authorization_basis": "User explicitly approved this operation on 2026-11-06 " * 4,
        }
        event = {"audit_context": context, "arguments": {
            "command": "python3 -c " + "x" * 145, "token": "HIDDEN_CREDENTIAL",
        }}
        lines = mclog.render_event_arguments(event, 30, "detail")
        self.assertEqual(len([x for x in lines if x.startswith("Задача:")]), 1)
        self.assertEqual(len([x for x in lines if x.startswith("Действие:")]), 1)
        self.assertEqual(len([x for x in lines if x.startswith("Основание:")]), 1)
        self.assertEqual(len([x for x in lines if x.startswith("Команда:")]), 1)
        self.assertGreater(len(lines), 20)
        self.assertTrue(all(len(x) <= 30 for x in lines))
        self.assertIn("x" * 20, " ".join(lines))
        self.assertIn("[скрыто]", " ".join(lines))
        self.assertNotIn("HIDDEN_CREDENTIAL", " ".join(lines))

    def test_fast_navigation_handles_keyboard_bursts_and_wheel(self):
        self.assertEqual(mclog.scroll_delta(mclog.curses.KEY_DOWN, 10), 1)
        self.assertEqual(mclog.scroll_delta(mclog.curses.KEY_NPAGE, 10), 10)
        self.assertEqual(mclog.scroll_delta(mclog.curses.KEY_PPAGE, 10), -10)
        self.assertEqual(mclog.scroll_delta(ord("k"), 10), -1)
        self.assertEqual(mclog.scroll_delta(ord("q"), 10), 0)
        self.assertEqual(mclog.wheel_delta(0b1000000000000000), 0)

    def test_long_single_record_scrolls_its_own_continuations(self):
        from unittest.mock import patch
        class Screen:
            def __init__(self):self.rows={}
            def getmaxyx(self):return (19,85)
            def erase(self):self.rows={}
            def addnstr(self,y,x,text,n,style=0):
                old=self.rows.get(y,"").ljust(x);t=text[:n]
                self.rows[y]=old[:x]+t+old[x+len(t):]
            def refresh(self):pass
        now=dt.datetime.now(dt.timezone.utc)
        event={"started":now,"tool":"terminal_exec","status":"ok",
               "audit_context":{"task_id":"UI-MANY",
                                "action":"Long operation " * 20,
                                "authorization_basis":"Owner approval 2026-11-06 " * 14},
               "arguments":{"command":"printf " + "TALLROW" * 60}}
        with patch.object(mclog.curses,"color_pair",return_value=0):
            a=Screen();mclog.draw(a,[event],0,Path("/tmp"),now,0,mode="detail")
            b=Screen();offset,_=mclog.draw(b,[event],0,Path("/tmp"),now,5,mode="detail")
        self.assertEqual(offset,5)
        self.assertNotEqual(a.rows,b.rows)
        self.assertTrue(any("Основание:" in line or "Команда:" in line or "Действие:" in line for line in list(a.rows.values())+list(b.rows.values())))

    def test_main_batches_repeated_scroll_keys_before_redraw(self):
        from unittest.mock import patch
        class InputScreen:
            def __init__(self):
                self.keys = [mclog.curses.KEY_DOWN] * 140 + [-1, ord("q")]
            def getmaxyx(self):return (40, 110)
            def nodelay(self, value):pass
            def keypad(self, value):pass
            def getch(self):return self.keys.pop(0) if self.keys else ord("q")
        screen=InputScreen()
        with (patch.object(mclog.curses, "has_colors", return_value=False),
              patch.object(mclog.curses, "curs_set", return_value=None),
              patch.object(mclog.curses, "mousemask", return_value=None),
              patch.object(mclog.AuditReader, "refresh", return_value=([], 0)),
              patch.object(mclog, "draw", side_effect=[
                  (0, 20), (140, 20)
              ]) as drawing,
              patch.object(mclog.time, "sleep", return_value=None) as sleeping):
            mclog.main(screen, Path("/tmp"))
        self.assertEqual(drawing.call_count, 2)
        self.assertEqual(drawing.call_args_list[1].args[5], 140)
        self.assertLessEqual(sleeping.call_count, 1)

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
