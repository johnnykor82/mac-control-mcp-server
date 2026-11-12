# M8ven Trust Grade — ARCHITECTURE REVIEW v1.0, 2026-11-11

Baseline: GitHub main f4b92c3 (Mac Control beta.56), identical installed release on Mac Server and jkmac. FastMCP server created in scripts/dev_mcp_server.py, and all tool registration passes through mac_control/mandatory_audit_context.install_registration(). Existing 112-handler frozen registry is reused by development operations; remaining tools include native UI, browser, maintenance and get_profile.

Observed in memory without starting a network service: 143 tools (142 without remote-only get_profile); 64 readOnly true and 79 false; missing destructiveHint on 44; missing idempotentHint on 143; readOnlyHint/openWorldHint complete. M8ven static source parser may not understand runtime-generated flags.

Option A — lowest code impact: a single explicit frozen policy keyed by all 143 exact names; the existing central registration wrapper enforces and fills four booleans, fails closed on unknown names or missing policy, preserving full audit_context. Add test for runtime/list parity and behavior. Risk: M8ven may still flag missing literals at decorator sites.

Option B — highest likelihood of static scanner acceptance: authoritative policy with checked/generated literal annotation blocks for each registered tool and CI parity to the policy. More code files changed, but metadata is statically visible and runtime contract is explicit. No handler-body changes. Superseded by owner approval 2026-11-11: implement both canonical policy and explicit source declarations; do not contact M8ven.

Screenshot architectural decision: current Swift native GUI capture writes bounded JPEG to private run/gui-captures; Python gui_screenshot reads then unlinks it. In-memory JPEG must modify Swift -> JSON IPC, image-data bounds and error handling; this is not merely changing one annotation. The owner approved in-memory JPEG instead.

Diagnostic false positives: fixed read-only ps, ssh-add -l and ssh -G do execute a subprocess but do not mutate user data. Preserve truthful semantics, provide exact arguments and mocked tests; never remove useful safe diagnostics to satisfy naive regex.

Dynamic verification: scripts/mac_control_smoke.py exists but performs scratch write/trash and optionally browser actions; unsuitable as no-side-effect trust evidence. Create separate macOS-only read-only smoke using tools/list plus system_info, with audit_context and no real credentials. M8ven externally may not host macOS/Screen Recording; collect local macOS-only evidence without sending it to M8ven.

A06 approved by owner 2026-11-11; code implementation proceeds only on isolated branch with tests; no M8ven outreach.

## Architecture approved by owner — 2026-11-11

Canonical 143-name annotation policy with four explicit booleans at source registration and CI parity; preserve authorization, names, schemas and handlers. Dynamic frozen legacy registrations obtain exact four booleans from immutable name policy. No outreach or disputes sent to M8ven.

The Swift capture operation shall produce in-memory bounded JPEG base64 plus original screen dimensions, preview dimensions and display ID; Python validates base64 and image size under 2 MiB before returning unchanged MCP screenshot schema. Native IPC response remains bounded by 4 MiB; TCC Screen Recording unchanged. The independent capture_window behavior is out of scope.

## A10b-native-protocol — compatible native helper replacement

Signed native app Info.plist advertises MacControlCaptureProtocol
jpeg-base64-v1 and CFBundleVersion 2. The reviewed beta57 portable GUI
release is pinned by version/asset SHA256 in setup_gui_dependency. During
maccontrol update, after verify_owned, ensure_gui compares exact
owner-installed Info.plist marker: compatible -> reuse, legacy -> bounded
stop+backup+replace using verified installer; foreign app -> abort.
Explicit --without-gui for legacy protocols aborts before release activation.
Native artifact must verify identifier, executable, protocol marker, both
architecture slices, and codesign. No generic GUI takeover. Tests first.

A10c CI OPTIONAL MODULES BUG FIXED 2026-11-12: First GitHub macOS CI
run 43155449250 failed two NEW tests ONLY: they assumed 143 remote / 142 stdio
tools in clean runner despite background_browser and background_native both
disabled by default (each module has seven optional tools). No server
functionality/regression defect. Updated annotation integration test to
explicitly patch both enabled() functions ONLY during in-memory registration
and assert the full 143-name policy. Real stdio smoke now verifies exact
core+optional module sets for 128,135,142 without changing runtime feature
flags or calling optional handlers. Clean HOME/macOS unittest: 5 tests PASS,
real stdio test 128 tools PASS; owner runtime enabled mode metadata 6 tests
+419 subtests PASS. Full source regression prior to this test-only patch:
938 integration PASS, 1618 subtests PASS, 1 SKIP, 4 security PASS. Next GitHub
CI for amended commit is the publication gate; beta57 remains draft.
