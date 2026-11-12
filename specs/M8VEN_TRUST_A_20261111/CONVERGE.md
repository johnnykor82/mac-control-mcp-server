# M8VEN TRUST A / Converge v1.0 — 2026-11-11

Owner-approved architecture: full 143-name canonical registry, four explicit
source metadata hints, bounded JPEG in memory via Swift/Python, and NO
contact/submission/rescan request to M8ven.

Requirements R1/R3: 143 authenticated remote registrations, 142 local stdio,
133 explicit annotation dictionaries; immutable 143-entry policy, unknown-name
fail-closed in production while BF26 standalone fixtures remain supported.
All required audit_context schemas unchanged. GREEN tests 5+419 subtests.
R2: existing readOnly/openWorld values preserved, seven previously unspecified
mutation destructiveness classifications documented in tool_annotation_policy;
chat_marker_issue uniquely non-idempotent read-only generator. No handler
behavior change except approved screenshot.
R4: internal evidence records fixed ps/ssh-add -l/ssh -G as inspections, no
M8ven communication. Third-party false positives/reputation are external.
R5: gui_screenshot no private temporary file; Swift ImageIO in-memory JPEG,
Python strict base64/JPEG size checks, 2MiB image/4MiB IPC guard, TCC preserved.
Three screenshot tests green; native app compiles/signs, not installed.
R6: isolated macOS MCP stdio real initialize/tools/list (142) and
system_info read-only PASS, no browser/user secrets.
R7/R8/R9/R11: backup bundle+SQLite+plists verified, branch isolated, BF33
paused/UNKNOWN untouched, no M8ven outreach. Real release update still pending.
R10: A grade cannot be guaranteed by source changes.

Complete offline integration: 114 test modules, 932 tests PASS, 1616
subtests PASS, 1 SKIP. Security 4 PASS, full Ruff 5 new files PASS,
changed-files critical Ruff PASS (26 files), compileall PASS,
strict release audit critical0 (41 heuristic warnings), deterministic
installer payload includes 126 files, native Swift signed, stdout MCP smoke
PASS. Source argument contract report was regenerated only for newly
introduced screenshot error messages; 6 tests PASS.

Current verdict: SOURCE/TEST CONVERGED; GITHUB PUBLISH / PUBLIC CI / TWO-HOST
DEPLOYMENT NOT YET CONVERGED. After remote CI success, use the official
versioned updater on Mac Server and jkmac with fresh per-host backups, confirm
actual code SHA/health and original BF33 frozen state, and record final status.
No benchmark or third-party grade claim without independent proof.

A10b-native-protocol NEW HIGH-SEVERITY GAP: in-memory screenshot code
requires a matching updated native GUI; default installer currently reuses
old CFBundleVersion1 on both machines. Prior SOURCE/TEST convergence is
conditional; runtime/rollout is NOT CONVERGED until native pin and safe upgrade
are implemented/tested. No release publication performed.

A10b 2026-11-12 NATIVE STAGE VERIFIED: separate signed universal arm64+x86_64 beta57 archive
/Users/openclaw/AgentWorkspace/artifacts/releases/m8ven-a-20261112/mac-control-native-v0.1.0-beta.57-universal.tar.gz,
SHA256 35f8b056554f534f305ddb571ead2bdb916a6558086f12665a667eba1d599265;
source RELEASE_URL and hash pinned to beta57. Bundle CFBundleVersion2
MacControlCaptureProtocol jpeg-base64-v1; two signed Mach-O verified by native
bounded extractor, security and codesign. 26 GUI/pin/screenshot/security tests
PASS, 298 subtests PASS. Owner-only legacy GUI auto-refresh, matching reuse,
wrong protocol reject and explicit --without-gui fail-closed tests GREEN.
Native archive not yet published; do not activate Python-only release.
Rollback: preserve original signed owned GUI .app and prior immutable Python
release; the installed GUI replacement backs up exact owner app. Never restore
old Watcher/ChatBridge SQLite over new transactions.

FULL A10b FINAL regression verified 2026-11-12: all 114 integration modules
ran in 8 independent pytest processes after fixing only the GUI installer mock
signature/protocol metadata (4 false failures under monolithic combination).
Results: 938 integration tests PASS, 1618 subtests PASS, 1 SKIP; security
4 tests PASS. Core native helper signed universal beta57 archive SHA256
35f8b056554f534f305ddb571ead2bdb916a6558086f12665a667eba1d599265.
Strict source manifest includes 297 tracked files, no untracked fixture
included, installer deterministic payload verified. Native protocol upgrade
tested, original BF33/UNKNOWN unchanged. GitHub publish/CI and two-host
installation are still OPEN; no M8ven outreach permitted.
