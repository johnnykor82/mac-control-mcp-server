# M8ven Trust Grade — ARCHITECTURE REVIEW v1.0, 2026-11-11

Baseline: GitHub main f4b92c3 (Mac Control beta.56), identical installed release on Mac Server and jkmac. FastMCP server created in scripts/dev_mcp_server.py, and all tool registration passes through mac_control/mandatory_audit_context.install_registration(). Existing 112-handler frozen registry is reused by development operations; remaining tools include native UI, browser, maintenance and get_profile.

Observed in memory without starting a network service: 143 tools (142 without remote-only get_profile); 64 readOnly true and 79 false; missing destructiveHint on 44; missing idempotentHint on 143; readOnlyHint/openWorldHint complete. M8ven static source parser may not understand runtime-generated flags.

Option A — lowest code impact: a single explicit frozen policy keyed by all 143 exact names; the existing central registration wrapper enforces and fills four booleans, fails closed on unknown names or missing policy, preserving full audit_context. Add test for runtime/list parity and behavior. Risk: M8ven may still flag missing literals at decorator sites.

Option B — highest likelihood of static scanner acceptance: authoritative policy with checked/generated literal annotation blocks for each registered tool and CI parity to the policy. More code files changed, but metadata is statically visible and runtime contract is explicit. No handler-body changes. Recommend starting with a narrowly tested Option A plus M8ven developer confirmation of scanner behavior, switching to B only if evidence shows A invisible.

Screenshot architectural decision: current Swift native GUI capture writes bounded JPEG to private run/gui-captures; Python gui_screenshot reads then unlinks it. In-memory JPEG must modify Swift -> JSON IPC, image-data bounds and error handling; this is not merely changing one annotation. Alternatively retain private ephemeral capture and dispute the false claim of destructive user-data deletion. Separate owner decision required.

Diagnostic false positives: fixed read-only ps, ssh-add -l and ssh -G do execute a subprocess but do not mutate user data. Preserve truthful semantics, provide exact arguments and mocked tests; never remove useful safe diagnostics to satisfy naive regex.

Dynamic verification: scripts/mac_control_smoke.py exists but performs scratch write/trash and optionally browser actions; unsuitable as no-side-effect trust evidence. Create separate macOS-only read-only smoke using tools/list plus system_info, with audit_context and no real credentials. M8ven externally may not host macOS/Screen Recording; request their review of a macOS runner artifact rather than misrepresenting container support.

Review gate A06: choose A or B for annotations, and approve/disapprove native in-memory screenshot protocol. No changes to existing code, release, service or remote repository until reviewed.
