"""BF27: compact WC markers are default; persisted legacy markers stay valid."""
from __future__ import annotations

import sqlite3

import pytest

from mac_control.watcher_runtime import watcher_autonomous as autonomous
from mac_control.watcher_runtime import watcher_chat_resolver as resolver

SHORT = "WC4f9e8c16d7a23b50"
LEGACY = "WATCHER-CHAT-" + "b" * 32
URL = "https://chatgpt.com/c/11111111-1111-4111-8111-111111111111"
PROMPT = "Return exactly SHORT_MARKER_OK for this isolated Watcher test."


@pytest.mark.parametrize("marker", [SHORT, "WC" + "0" * 16, LEGACY])
def test_compact_default_and_existing_legacy_markers_accepted(marker):
    assert resolver.MARKER.fullmatch(marker)
    assert autonomous._validate(
        "bf27-pilot", "agent-a", marker, PROMPT, "bf27-short-task-0001", "123"
    )


@pytest.mark.parametrize("invalid", [
    "WC4f9e8c16d7a23b5",  # truncated
    "WC4f9e8c16d7a23b500",  # too long
    "wc4f9e8c16d7a23b50",  # wrong case
    "WC4F9E8C16D7A23B50",  # uppercase hex
    "WC4f9e8c16d7a23b5g",  # invalid hex
    "prefix WC4f9e8c16d7a23b50",
    "WC4f9e8c16d7a23b50 suffix",
    "WATCHER-CHAT-" + "b" * 31,
])
def test_reject_nonexact_or_malformed_markers_without_enqueue(invalid):
    assert not resolver.MARKER.fullmatch(invalid)
    with pytest.raises(ValueError):
        autonomous._validate(
            "bf27-pilot", "agent-a", invalid, PROMPT, "bf27-short-task-0001", "123"
        )


@pytest.mark.parametrize("marker", [SHORT, LEGACY])
def test_verified_assistant_resolves_once_and_reuses_registry(marker):
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    calls = []

    def transport(method, path, payload):
        calls.append((method, path, payload))
        return {
            "chat_url": URL,
            "evidence_verified": True,
            "verification": "assistant_message",
            "matches": 1,
        }

    try:
        first = resolver.resolve(marker, db=db, transport=transport)
        second = resolver.resolve(marker, db=db, transport=transport)
        assert first["cached"] is False
        assert second["cached"] is True
        assert first["chat_url"] == URL
        assert calls == [("POST", "/v1/chats/resolve-marker", {"marker": marker})]
        assert db.execute(
            "SELECT source FROM chat_marker_registry WHERE marker=?", (marker,)
        ).fetchone()[0] == "chatbridge_verified_assistant_message"
    finally:
        db.close()


def test_ambiguous_compact_marker_does_not_enter_registry():
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        with pytest.raises(ValueError, match="uniquely"):
            resolver.resolve(SHORT, db=db, transport=lambda *_: {
                "chat_url": URL, "evidence_verified": True,
                "verification": "assistant_message", "matches": 2,
            })
        assert db.execute("SELECT COUNT(*) FROM chat_marker_registry").fetchone()[0] == 0
    finally:
        db.close()


def test_error_message_guides_new_compact_format():
    with pytest.raises(ValueError, match=r"WC"):
        autonomous._validate(
            "bf27-pilot", "agent-a", "invalid", PROMPT, "bf27-short-task-0001", "123"
        )
