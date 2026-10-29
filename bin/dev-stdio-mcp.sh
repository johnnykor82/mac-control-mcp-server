#!/bin/sh
# Trusted fixed-path launcher for Stable's stdio MCP bridge.
# No network listener, no inherited Python module search path or user startup.
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
unset PYTHONHOME PYTHONPATH
export PYTHONPATH="$ROOT/src" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
exec "$ROOT/.venv/bin/python" -P -B "$ROOT/scripts/dev_mcp_server.py" --stdio
