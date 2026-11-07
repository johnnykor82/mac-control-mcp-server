"""Non-authorizing, owner-visible correlation labels for existing ChatGPT chats.

Chat identifiers are supplied by the assistant, not inferred from IP/transport.
"""
from __future__ import annotations

import re
import secrets

CHAT_MARKER = re.compile(r"(?:WC[a-f0-9]{16}|WATCHER-CHAT-[a-f0-9]{32})\Z")


def valid_chat_marker(value: object) -> bool:
    """Only exact compact or previously issued legacy labels are accepted."""
    return isinstance(value, str) and CHAT_MARKER.fullmatch(value) is not None


def generate_chat_marker() -> str:
    """Issue a one-time 64-bit random label; caller must publish and reuse it."""
    return "WC" + secrets.token_hex(8)
