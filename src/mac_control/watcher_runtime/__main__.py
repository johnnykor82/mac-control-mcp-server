"""Run state commands or the HTTP-only delivery daemon."""
import json
import sys
from . import multi_project_watcher as core

def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] in ("run", "once", "dry-run", "poll-once"):
            if sys.argv[1] == "poll-once":
                sys.argv[1] = "once"
            from .watcher_http_adapter import main as run_http
            run_http()
        else:
            core.main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__,
                          "error": "Watcher operation failed; check its state and supplied parameters"}))
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
