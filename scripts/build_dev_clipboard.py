"""Build the internal Dev Unicode paste helper (not an MCP command)."""
from pathlib import Path
import hashlib
import os
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"scripts/gui_clipboard_paste.swift"
DEST=ROOT/"build/gui_clipboard_paste"


def build() -> Path:
    if not SRC.is_file() or SRC.is_symlink() or ROOT.is_symlink():
        raise RuntimeError("Untrusted Dev clipboard source path")
    DEST.parent.mkdir(parents=True,exist_ok=True)
    if DEST.is_symlink():
        raise RuntimeError("Clipboard executable cannot be a symlink")
    fd,tmp=tempfile.mkstemp(prefix="gui-clipboard-build-",dir=DEST.parent)
    os.close(fd)
    try:
        command=["/usr/bin/swiftc","-swift-version","5","-O",str(SRC),"-o",tmp]
        subprocess.run(command,check=True,capture_output=True,text=True,timeout=90)
        os.chmod(tmp,0o700)
        os.replace(tmp,DEST)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    print("DEV_UNICODE_PASTE_HELPER_BUILT",hashlib.sha256(DEST.read_bytes()).hexdigest())
    return DEST


if __name__=="__main__":
    build()
