"""Standard macOS data location for an isolated future Mac Control install.

No directories are created on import. No production path or credentials used.
The installer, not the MCP request, provisions this owner-scoped location.
"""
import os
from pathlib import Path

DEFAULT_DATA_ROOT = Path.home() / "Library" / "Application Support" / "MacControl" / "MCP-Dev"
_override = os.environ.get("MAC_CONTROL_DATA_ROOT", "").strip()
if _override:
    proposed = Path(_override).expanduser()
    if not proposed.is_absolute():
        raise ValueError("MAC_CONTROL_DATA_ROOT must be an absolute path")
    DATA_ROOT = proposed
else:
    DATA_ROOT = DEFAULT_DATA_ROOT
