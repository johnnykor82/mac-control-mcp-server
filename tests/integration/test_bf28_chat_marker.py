"""BF28: stable optional per-chat marker flows through audit and MClog."""
import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from mac_control.audit_middleware import AuditMiddleware, extract_audit_context
from mac_control.mandatory_audit_context import AuditContext
from scripts import mclog

SHORT = "WC9d4f8a2c7b61e305"
OTHER = "WC0102030405060708"
LEGACY = "WATCHER-CHAT-" + "a" * 32
CTX = {
    "task_id": "BF28-02",
    "action": "Read harmless metadata only for this test",
    "authorization_basis": "Owner authorized BF28 on 2026-11-07",
}


@pytest.mark.parametrize("marker", [SHORT, LEGACY])
def test_accepted_chat_markers_are_optional_and_stable(marker):
    assert AuditContext.model_validate(CTX).chat_marker is None
    assert AuditContext.model_validate({**CTX, "chat_marker": marker}).chat_marker == marker


@pytest.mark.parametrize("bad", [
    "WC", "WC123456789012345", "WC12345678901234567",
    "wc9d4f8a2c7b61e305", SHORT.upper(), SHORT+"-tail", "Bearer X",
])
def test_invalid_chat_marker_fails_closed(bad):
    with pytest.raises(ValidationError):
        AuditContext.model_validate({**CTX, "chat_marker": bad})


def test_chat_marker_issuer_returns_cryptographic_compact_id():
    from mac_control.chat_identity import generate_chat_marker
    items = {generate_chat_marker() for _ in range(50)}
    assert len(items) == 50
    assert all(len(s) == 18 and AuditContext.model_validate({
        **CTX, "chat_marker": s
    }).chat_marker == s for s in items)


def test_middleware_carries_marker_and_preserves_original_three_fields(tmp_path):
    assert extract_audit_context({"audit_context": {**CTX, "chat_marker": SHORT}}) == {
        **CTX, "chat_marker": SHORT
    }
    recorder = AuditMiddleware(tmp_path / "owner-only")
    msg = SimpleNamespace(message=SimpleNamespace(
        name="system_info", arguments={"audit_context": {**CTX, "chat_marker": SHORT}},
        meta={},
    ))
    async def done(_):
        return SimpleNamespace(is_error=False)
    asyncio.run(recorder.on_call_tool(msg, done))
    records = [json.loads(s) for s in
               (tmp_path / "owner-only/audit.jsonl").read_text().splitlines()]
    assert records[0]["chat_marker"] == SHORT
    assert records[0]["audit_context"]["chat_marker"] == SHORT
    assert records[1]["status"] == "ok"
    assert "chat_marker" not in extract_audit_context({"audit_context": CTX})
    assert "chat_marker" not in extract_audit_context({
        "audit_context": {**CTX, "chat_marker": "INVALID"}
    })


def test_mclog_groups_events_by_chat_and_not_by_task():
    now = dt.datetime.now(dt.UTC)
    rows = [
        {"id": "a", "started": now, "chat_marker": SHORT,
         "audit_context": {**CTX, "chat_marker": SHORT}, "tool": "system_info"},
        {"id": "b", "started": now, "audit_context": {**CTX, "chat_marker": SHORT},
         "tool": "terminal_exec"},
        {"id": "c", "started": now, "chat_marker": OTHER,
         "audit_context": {**CTX, "chat_marker": OTHER}, "tool": "fs_read"},
        {"id": "d", "started": now, "tool": "fs_read"},
        {"id": "e", "started": now, "chat_ref": "ref0123456", "tool": "fs_read"},
    ]
    assert mclog.event_chat_marker(rows[0]) == SHORT
    assert mclog.event_chat_marker(rows[1]) == SHORT
    assert [r["id"] for r in mclog.filter_by_chat(rows, SHORT)] == ["a", "b"]
    assert [r["id"] for r in mclog.filter_by_chat(rows, OTHER)] == ["c"]
    assert mclog.chat_groups(rows)[0] == (SHORT, 2)
    assert ("Без метки", 1) in mclog.chat_groups(rows)
    assert mclog.event_chat_marker(rows[4]) == "ref0123456"


def test_mclog_audit_arguments_still_redacted_after_marker():
    event = {"tool": "terminal_exec", "audit_context": {**CTX, "chat_marker": SHORT},
             "arguments": {"password": "BF28_SECRET_TEST", "audit_context":
                           {**CTX, "chat_marker": SHORT}}}
    assert SHORT in mclog.display_args(event, 2000)
    assert "BF28_SECRET_TEST" not in mclog.display_args(event, 2000)
    assert "BF28_SECRET_TEST" not in "|".join(mclog.audit_fields(event))


def test_mclog_draw_selected_chat_keeps_only_that_chat():
    from pathlib import Path
    from unittest.mock import patch

    class Screen:
        def __init__(self):
            self.rows = {}
        def getmaxyx(self):
            return 27, 135
        def erase(self):
            self.rows = {}
        def addnstr(self, y, x, value, n, style=0):
            old = self.rows.get(y, "").ljust(x)
            part = value[:n]
            self.rows[y] = old[:x] + part + old[x+len(part):]
        def refresh(self):
            pass

    now = dt.datetime.now(dt.UTC)
    rows = [
        {"started": now, "tool": "system_info", "status": "ok",
         "chat_marker": SHORT, "arguments": {"command": "echo targeted"}},
        {"started": now, "tool": "fs_read", "status": "ok",
         "chat_marker": OTHER, "arguments": {"command": "echo unrelated"}},
    ]
    scr = Screen()
    with patch.object(mclog.curses, "color_pair", return_value=0):
        mclog.draw(scr, rows, 0, Path("/tmp"), now, 0, chat_filter=SHORT)
    all_text = "\n".join(scr.rows.values())
    assert SHORT in all_text
    assert "targeted" in all_text
    assert "unrelated" not in all_text
    assert "ЧАТ" in all_text
    assert "ЧАТОВ" in all_text


def test_mclog_chat_selector_cycles_existing_labels_without_new_markers():
    labels = [SHORT, OTHER, "ref0123456"]
    assert mclog.next_chat_filter(None, labels) == SHORT
    assert mclog.next_chat_filter(SHORT, labels) == OTHER
    assert mclog.next_chat_filter(labels[-1], labels) is None


def test_chat_marker_round_trip_from_audit_jsonl_to_cli_group(tmp_path):
    import subprocess
    from pathlib import Path

    from mac_control.audit_middleware import AuditMiddleware

    async def run_one(tool_name, task):
        writer = AuditMiddleware(tmp_path / "logs")
        ctx = {**CTX, "task_id": task, "chat_marker": SHORT}
        msg = SimpleNamespace(message=SimpleNamespace(
            name=tool_name, arguments={"audit_context": ctx}, meta={},
        ))
        async def done(_):
            return SimpleNamespace(is_error=False)
        await writer.on_call_tool(msg, done)

    asyncio.run(run_one("system_info", "BF28-STAGE-1"))
    asyncio.run(run_one("fs_read", "BF28-STAGE-2"))
    entries, malformed = mclog.load(tmp_path / "logs")
    assert malformed == 0
    assert mclog.chat_groups(entries) == [(SHORT, 2)]
    assert {e["audit_context"]["task_id"] for e in entries} == {
        "BF28-STAGE-1", "BF28-STAGE-2",
    }
    cli = subprocess.run(
        ["/usr/bin/python3", str(Path(mclog.__file__)),
         "--log-dir", str(tmp_path / "logs"), "--list-chats"],
        capture_output=True, text=True, timeout=10, check=True,
    )
    assert SHORT in cli.stdout
    assert "2 calls" in cli.stdout
