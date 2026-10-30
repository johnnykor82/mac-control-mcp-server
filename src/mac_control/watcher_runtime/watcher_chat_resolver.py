"""Durable mapping of user-posted conversation markers to verified ChatGPT URLs.

Watcher never attaches to the Chrome browser. On cache miss it asks the
ChatBridge owner to search in the normal ChatGPT UI and to verify the exact
marker in a user message. A failed/ambiguous lookup cannot poison the cache.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

MARKER = re.compile(r"WATCHER-CHAT-[a-f0-9]{32}\Z")


def choose(matches):
    urls = set(matches)
    if len(urls) != 1:
        raise ValueError("Conversation cannot be uniquely identified from evidence")
    return urls.pop()


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS chat_marker_registry (
        marker TEXT PRIMARY KEY,
        chat_url TEXT NOT NULL,
        verified_at TEXT NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('chatbridge_verified_user_message','chatbridge_verified_assistant_message'))
    )""")
    schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='chat_marker_registry'").fetchone()[0]
    if "chatbridge_verified_assistant_message" not in schema:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""CREATE TABLE chat_marker_registry_new (
                marker TEXT PRIMARY KEY, chat_url TEXT NOT NULL,
                verified_at TEXT NOT NULL,
                source TEXT NOT NULL CHECK(source IN
                ('chatbridge_verified_user_message','chatbridge_verified_assistant_message'))
            )""")
            db.execute("INSERT INTO chat_marker_registry_new SELECT * FROM chat_marker_registry")
            db.execute("DROP TABLE chat_marker_registry")
            db.execute("ALTER TABLE chat_marker_registry_new RENAME TO chat_marker_registry")
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
    db.execute("CREATE INDEX IF NOT EXISTS idx_chat_marker_url ON chat_marker_registry(chat_url)")


def resolve(evidence_text, allow_search=True, db=None):
    """Cache-first exact match. Never invent a target from current browser tab."""
    if not isinstance(evidence_text, str) or not MARKER.fullmatch(evidence_text):
        raise ValueError("Provide a dedicated WATCHER-CHAT-<32 lowercase hex> user-message marker")
    if db is None:
        from .multi_project_watcher import connect
        with connect() as connection:
            return resolve(evidence_text, allow_search=allow_search, db=connection)
    setup(db)
    from .multi_project_watcher import canonical_url
    known = db.execute(
        "SELECT chat_url,verified_at FROM chat_marker_registry WHERE marker=?",
        (evidence_text,),
    ).fetchone()
    if known:
        return {"chat_url": canonical_url(known["chat_url"]),
                "evidence_verified": True, "matches": 1,
                "cached": True, "verified_at": known["verified_at"]}
    if not allow_search:
        raise LookupError("Marker is not registered")
    # The only browser owner is ChatBridge; use its localhost HTTP API.
    from .watcher_http_adapter import api
    remote = api("POST", "/v1/chats/resolve-marker", {"marker": evidence_text})
    role = remote.get("verification")
    if remote.get("evidence_verified") is not True or role not in ("user_message", "assistant_message"):
        raise ValueError("ChatBridge did not verify the marker in a message")
    target = canonical_url(remote.get("chat_url"))
    if remote.get("matches") != 1:
        raise ValueError("ChatBridge did not uniquely identify the conversation")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Two concurrent lookups must never overwrite different verified targets.
    db.execute("""INSERT OR IGNORE INTO chat_marker_registry
        (marker,chat_url,verified_at,source) VALUES(?,?,?,?)""",
        (evidence_text, target, now, "chatbridge_verified_" + role),
    )
    stored = db.execute(
        "SELECT chat_url,verified_at FROM chat_marker_registry WHERE marker=?",
        (evidence_text,),
    ).fetchone()
    if not stored or canonical_url(stored["chat_url"]) != target:
        raise ValueError("Conflicting marker registration: manual investigation required")
    return {"chat_url": target, "evidence_verified": True, "matches": 1,
            "cached": False, "verified_at": stored["verified_at"]}
