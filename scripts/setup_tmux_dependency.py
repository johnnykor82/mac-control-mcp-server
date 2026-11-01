"""Optional owner-approved Homebrew provisioning for interactive PTY sessions.

This module makes no changes on import or without explicit owner consent.
The installer itself remains usable when Homebrew or tmux is unavailable.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

_ERROR_LIMIT = 4000
_SENSITIVE = re.compile(
    r"(?i)(password|passwd|authorization|secret|bearer\s|"
    r"api[ _-]?key|access[ _-]?token|private[ _-]?key|"
    r"github_pat_|gh[pousr]_|sk-[A-Za-z0-9_-]+)"
)


def locate():
    for value in ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux",
                  shutil.which("tmux")):
        if value and Path(value).is_file() and os.access(value, os.X_OK):
            return value
    return None


def _homebrew():
    for value in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew",
                  shutil.which("brew")):
        if value and Path(value).is_file() and os.access(value, os.X_OK):
            return value
    return None


def _environment(brew: str):
    # Homebrew needs the caller's locale, USER, LOGNAME, TMPDIR, proxy/cert
    # and other valid environment configuration. A minimal HOME/PATH-only
    # environment caused opaque failures on real user installations.
    environment = dict(os.environ)
    environment.setdefault("HOME", str(Path.home()))
    base_path = environment.get("PATH", "")
    extra = ":".join((str(Path(brew).parent), "/opt/homebrew/bin",
                      "/usr/local/bin", "/usr/bin", "/bin"))
    environment["PATH"] = extra + (":" + base_path if base_path else "")
    environment["HOMEBREW_NO_AUTO_UPDATE"] = "1"
    environment["HOMEBREW_NO_ANALYTICS"] = "1"
    return environment


def _excerpt(value):
    # Homebrew errors can include externally-supplied URLs and credentials.
    # Report only bounded diagnostic lines, never full command output.
    lines = str(value or "").splitlines()[-40:]
    safe = ["[REDACTED sensitive diagnostic line]" if _SENSITIVE.search(line)
            else line[:800] for line in lines]
    return "\n".join(safe)[-_ERROR_LIMIT:]


def ensure(*, approved=False, interactive=False, input_fn=input):
    executable = locate()
    if executable:
        return {"status": "ready", "available": True, "tmux_path": executable}
    brew = _homebrew()
    if brew is None:
        return {"status": "missing_homebrew", "available": False,
                "remedy": "Install Homebrew, then run brew install tmux"}
    if not approved and interactive:
        answer = input_fn(
            "Interactive terminal requires tmux. Install with Homebrew? [y/N] ")
        approved = answer.strip().lower() in ("y", "yes", "да", "д")
    if not approved:
        return {"status": "needs_owner_approval", "available": False,
                "remedy": "Run maccontrol update --install-tmux or brew install tmux"}
    try:
        result = subprocess.run(
            [brew, "install", "tmux"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=360, env=_environment(brew))
    except subprocess.TimeoutExpired as error:
        return {"status": "install_failed", "available": False,
                "error_code": "HOMEBREW_TIMEOUT",
                "stderr_tail": _excerpt(error.stderr),
                "stdout_tail": _excerpt(error.stdout),
                "remedy": "Run brew install tmux in Terminal and check Homebrew errors"}
    except OSError as error:
        return {"status": "install_failed", "available": False,
                "error_code": "HOMEBREW_EXEC_ERROR", "detail": _excerpt(error),
                "remedy": "Check Homebrew path and execution permissions"}
    executable = locate()
    if result.returncode or executable is None:
        return {
            "status": "install_failed", "available": False,
            "error_code": ("HOMEBREW_INSTALL_FAILED" if result.returncode
                           else "TMUX_BINARY_NOT_FOUND"),
            "exit_code": result.returncode, "brew_path": brew,
            "stderr_tail": _excerpt(result.stderr),
            "stdout_tail": _excerpt(result.stdout),
            "remedy": "Check the Homebrew output; run brew install tmux in Terminal"}
    return {"status": "installed", "available": True, "tmux_path": executable}
