"""Optional owner-approved Homebrew provisioning for required PTY dependency.

No actions on import. Missing tmux does not block other MCP capabilities.
"""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import sys


def locate():
    for value in ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux",
                  shutil.which("tmux")):
        if value and Path(value).is_file() and os.access(value, os.X_OK):
            return value
    return None


def ensure(*, approved=False, interactive=False, input_fn=input):
    binary=locate()
    if binary:
        return {"status":"ready","available":True,"tmux_path":binary}
    brew=next((p for p in ("/opt/homebrew/bin/brew","/usr/local/bin/brew",
                          ) if p and Path(p).is_file()
               and os.access(p, os.X_OK)),None)
    if brew is None:
        return {"status":"missing_homebrew","available":False,
                "remedy":"Install Homebrew, then run brew install tmux"}
    if not approved and interactive:
        response=input_fn("Interactive terminal requires tmux. Install with Homebrew? [y/N] ")
        approved=response.strip().lower() in ("y","yes","да","д")
    if not approved:
        return {"status":"needs_owner_approval","available":False,
                "remedy":"Run maccontrol update --install-tmux or brew install tmux"}
    result=subprocess.run([brew,"install","tmux"],stdin=subprocess.DEVNULL,
                          capture_output=True,text=True,timeout=360,
                          env={"HOME":str(Path.home()),
                               "PATH":"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                               "HOMEBREW_NO_AUTO_UPDATE":"1"})
    binary=locate()
    if result.returncode or binary is None:
        return {"status":"install_failed","available":False,
                "exit_code":result.returncode,
                "remedy":"Check Homebrew installation and install tmux manually"}
    return {"status":"installed","available":True,"tmux_path":binary}
