# A10b-native-protocol / Bug Fixing Assess → Fix → Test

Assess (2026-11-11): Mac Server and jkmac both have owner-managed, verified
MacControlMCPServer.app CFBundleVersion 1 with old capture-to-private-file
protocol. New Python gui_screenshot calls capture expecting in-memory base64,
and default maccontrol update executes ensure_gui(...replace=False), which
reuses existing app. Without coordination, screenshots break after rollout.

Fix: install SHA-pinned, signed universal beta57 GUI with
MacControlCaptureProtocol=jpeg-base64-v1. Versioned native metadata and
strict payload validation; only exact owner-controlled legacy app may be
stopped/replaced through existing reversible backup installer. Reuse already
compatible helper. Explicit --without-gui refuses mismatch. No TCC bypass.

Test: failing RED tests for protocol marker, automatic legacy-to-current
replacement, current reuse, malformed signed/marker payload rejection and
explicit opt-out; then GREEN all relevant GUI installer/security/remote
tests and full integration. Verify original GUI backup before activation,
plus independent host checks after install. No M8ven outreach.
