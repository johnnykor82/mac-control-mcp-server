"""Read-only discovery of optional installer tools."""
from __future__ import annotations

import os
from pathlib import Path
import shutil


def find_uv() -> str | None:
    """Find uv after standalone installation even before a shell PATH refresh."""
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (Path.home() / ".local/bin/uv",
                      Path("/opt/homebrew/bin/uv"), Path("/usr/local/bin/uv")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None
