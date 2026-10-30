#!/bin/sh
# Explicit owner-authorized remote HTTP. Listens on loopback only; tunnel separately.
set -eu
BIN=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
ROOT=$(CDPATH='' cd -- "$BIN/.." && pwd -P)
DATA=$(CDPATH='' cd -- "$ROOT/../../data" && pwd -P)
unset PYTHONHOME PYTHONPATH
export PYTHONPATH="$ROOT/src"
export MAC_CONTROL_DATA_ROOT="$DATA"
export MAC_CONTROL_GUI_APP="$DATA/../apps/MacControlMCPServer.app"
if [ -f "$DATA/chatbridge_connection.txt" ]; then
    IFS= read -r MACCONTROL_CHATBRIDGE_URL < "$DATA/chatbridge_connection.txt" || true
    export MACCONTROL_CHATBRIDGE_URL
fi
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
exec "$ROOT/.venv/bin/python" -P -B "$ROOT/scripts/dev_mcp_server.py" --remote --port "${MAC_CONTROL_REMOTE_PORT:-3201}"
