"""Consistent, late-bound tmux discovery across MCP capability tools."""
from __future__ import annotations

import os
from pathlib import Path
import shutil


def locate() -> str | None:
    """Prefer standard Homebrew locations even when launchd's PATH is minimal."""
    for candidate in ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux",
                      shutil.which("tmux")):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None
