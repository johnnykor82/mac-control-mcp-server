"""Mac native STDIO protocol check with no owner writes and no external services."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase, skipUnless

ROOT = Path(__file__).resolve().parents[2]


@skipUnless(sys.platform == "darwin", "macOS native-only smoke")
class SafeNativeMCPTests(TestCase):
    def test_real_stdio_protocol_and_complete_annotation_schema(self):
        proc = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/m8ven_safe_smoke.py")],
            cwd=ROOT,
            env={**os.environ, "MAC_CONTROL_DATA_ROOT": "", "PYTHONPATH":
                 os.pathsep.join((str(ROOT / "src"), str(ROOT)))},
            timeout=42,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        self.assertRegex(
            proc.stdout, r"M8VEN_MACOS_MCP_READONLY_SMOKE_PASS (128|135|142) tools"
        )
