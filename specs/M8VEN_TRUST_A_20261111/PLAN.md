# M8ven Trust Grade PLAN v1.0 — 2026-11-11

Overall scope approved by the owner on 2026-11-11. Architecture changes require a separate review before implementation.

Verified rollback baseline: /Users/openclaw/AgentWorkspace/artifacts/backups/m8ven-a-20261111. Complete Git bundle SHA256 7dcff1cb0aaa82edd77cbeca5816efe12ea3b52df4ad0b81cc1a9ea58905df68, git bundle verify PASS; online SQLite snapshots of Mac Server Watcher and owned ChatBridge both integrity_check ok; existing owner Watcher and ChatBridge LaunchAgent plists saved with SHA256. Prior immutable installed beta.56 releases on Mac Server/jkmac preserved. Before deployment refresh owner-specific backups. On rollback restore release/plists, NEVER overwrite newer SQLite. Preserve BF33/UNKNOWN.

A01 DONE 2026-11-11: official current GitHub Spec Kit Agentic SDD and Evolving Specs consulted via internet (not Mac/local docs).
A02 DONE: M8ven public current commit f4b92c3 (D/Caution), 143 tools, no successful third-party live execution. Read key findings.
A03 DONE: in-memory FastMCP enumeration and current hint inventory; verified 143-row CSV with SHA256 09b964b7a249db91cd6e469c422a543520e779a8cfa2e40bf17e2d3132489160.
A04 DONE: verified backup and isolated Git worktree branch m8ven-a-20261111 based on exact remote GitHub f4b92c3; original main and installed releases unmodified.
A05 DONE/VERIFIED 2026-11-11: seven SDD/baseline artifacts created; strict Analyze script checked 10 requirements, 11 planned stages, 143 unique MCP tools, read-only/missing annotation counts and exact verified Git bundle SHA; PASS. No source/runtime code edits. A06 separate owner architecture review is the next blocking gate.
A06 DONE/APPROVED 2026-11-11: one canonical 143-name registry plus explicit source metadata and in-memory Swift/Python JPEG; no outreach/requests to M8ven. Preserve 2 MiB raw JPEG, 4 MiB IPC bound, TCC, and screenshot output.
A07 DONE: 7 RED failures proved absent canonical policy, missing hints and native file-backed screenshots. One test fixture corrected; no production action.
A08 IMPLEMENTED/GREEN: 143-name explicit four-boolean immutable policy, strict production registration with legacy BF26 fixture compatibility; 133 static source annotation dicts updated, 5 policy tests+419 subtests PASS. In-memory Swift+Python capture with 2MiB JPEG/4MiB IPC, no temp-file unlink, 3 screenshot tests PASS. Isolated GUI binary compiled/ad-hoc signed and codesign verified, not installed or started. New policy included in strict installer manifest. Full regression still OPEN.
A09 DONE (internal only): actual macOS STDIO protocol initialized 142 local tools with four hints and called safe system_info; isolated regression PASS, no credentials or browser/Watcher calls. Fixed ps/ssh-add -l/ssh -G classified local read-only; no messages/submissions to M8ven.
A10 TESTS DONE/VERIFIED 2026-11-11: 114 integration modules in isolated batches 932 passed, 1616 subtests passed, 1 skipped; 4 security tests passed; source-critical Ruff (26 changed Python files), full Ruff all new files, compileall, strict release audit (0 critical), deterministic 126-file installer payload and signed Swift native GUI PASS. A derived argument audit Markdown difference was limited to expected JPEG error types (142 tools and all names/schemas unchanged); regenerated and 6 tests PASS. Tests left one zero-byte fixture lock, moved reversibly to verified backup. Remaining A10: Converge documentation, Git commit, GitHub remote CI and immutable beta release. Then A11 independent host backups+rollout.
A11 Verify both hosts exact source SHA/health; read the public M8ven grade only (no rescan request or contact); state residual independent factors. No fake grade claims.

A10b-native-protocol OPEN / fail-closed release gate: Both installed native
GUI helpers CFBundleVersion1 lack in-memory protocol marker. Default updater
reuses them; shipping current code alone would break gui_screenshot.
Before release: RED tests of matching vs legacy helper and protocol marker,
versioned signed universal beta57 artifact+SHA256 pin, limited owner-only
auto-refresh in setup_gui_dependency.ensure on ordinary update, explicit
--without-gui mismatch rejection, GREEN unit/security + full regressions,
Converge and Git commit. No production changes until all pass. Old GUI app
backup created by built-in gui.install and rollback; do not modify TCC grants.

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
