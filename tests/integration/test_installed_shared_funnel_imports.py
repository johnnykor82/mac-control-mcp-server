"""Simulate direct execution/imports in the installed CLI without a 'scripts' package.

Regression: guided_setup.py imports setup_network as a top-level module;
inside _enable_shared_funnel, 'from scripts.shared_funnel_routes ...' failed.
This invokes both functions with no GitHub credentials or network changes.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class InstalledSharedFunnelImportTests(unittest.TestCase):
    def test_direct_script_import_can_inspect_and_reuse_shared_routes(self):
        scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
        code = textwrap.dedent("""
            import json, subprocess, sys
            from unittest.mock import patch
            sys.path.insert(0, sys.argv[1])
            import setup_network
            from shared_funnel_routes import route_paths, backend_for
            assert setup_network.__package__ == ''
            hostname = "test-device.ts.net"
            key = hostname + ":443"
            handlers = {"/": {"Proxy": "http://127.0.0.1:3000"}}
            state = {"TCP": {"443": {"HTTPS": True}},
                     "Web": {key: {"Handlers": handlers}},
                     "AllowFunnel": {key: True}}
            def fake_run(args, timeout=12):
                assert args[1:3] in (["funnel", "status"], ["serve", "status"])
                return subprocess.CompletedProcess(args, 0, json.dumps(state), "")
            with patch.object(setup_network, "run", side_effect=fake_run):
                proposed = setup_network.publication_state("tailscale", hostname)
            assert proposed["status"] == "shared_available", proposed
            assert proposed["prefix"] == "/maccontrol", proposed
            for path in route_paths("/maccontrol"):
                handlers[path] = {"Proxy": backend_for(path)}
            auth = {"public_url": "https://" + hostname + "/maccontrol",
                    "allowed_github_ids": ["42"]}
            with patch.object(setup_network, "run", side_effect=fake_run):
                result = setup_network._enable_shared_funnel(
                    "tailscale", hostname, "/maccontrol", None, auth)
            assert result["status"] == "existing_shared_funnel_reused", result
            print("DIRECT_INSTALL_STYLE_OK")
        """)
        with tempfile.TemporaryDirectory() as tmp:
            # Avoid repository directory on sys.path and any inherited PYTHONPATH.
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            process = subprocess.run(
                [sys.executable, "-P", "-B", "-c", code, str(scripts_dir)],
                cwd=tmp, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0,
                         process.stdout + "\n" + process.stderr)
        self.assertIn("DIRECT_INSTALL_STYLE_OK", process.stdout)


if __name__ == "__main__":
    unittest.main()
