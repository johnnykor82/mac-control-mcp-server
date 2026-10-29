"""Read-only discovery of optional installer tools."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Optional


def _apple_silicon() -> bool:
    if platform.system() != "Darwin":
        return False
    if platform.machine() == "arm64":
        return True
    # Under Rosetta platform.machine() reports x86_64; query the hardware.
    try:
        result = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=5, check=False)
        return result.returncode == 0 and result.stdout.strip() == "1"
    except (OSError, subprocess.TimeoutExpired):
        return False


def find_uv() -> Optional[str]:
    """Find uv without a PATH refresh; require native uv on Apple Silicon."""
    native = _apple_silicon()
    found = shutil.which("uv")
    if found and not native:
        return found
    candidates = ([Path(found)] if found else []) + [
        Path.home() / ".local/bin/uv", Path("/opt/homebrew/bin/uv"),
        Path("/usr/local/bin/uv"),
    ]
    if platform.system() == "Darwin":
        target = "aarch64-apple-darwin" if native else "x86_64-apple-darwin"
        candidates.append(Path.home() / ".local/share/chatbridge/tools/uv" / target / "uv")
    for candidate in dict.fromkeys(candidates):
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        if native:
            # An actual native launch also checks universal binaries and broken uv.
            # Use fixed argv, never a shell or an installer, for this read-only probe.
            try:
                result = subprocess.run(["/usr/bin/arch", "-arm64", str(candidate), "--version"],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=5, check=False)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode != 0:
                continue
        return str(candidate)
    return None
