# M8VEN-A Backlog — approved plan v1.0, 2026-11-11

DONE: source/backup/143-tool inventory, SDD/Analyze, owner architecture approval, canonical registry + 133 static decorator groups, native JPEG without temporary file, 9 local regression tests +419 subtests, signed native GUI build, isolated 142-tool MCP STDIO smoke.
DONE (A10 test gate): BETA_SOURCE_MANIFEST synced; 114 integration modules 932 pass/1616 subtests/1 skipped, security4, new-files full Ruff, changed-files critical Ruff, native code signature, strict source audit, 126-file payload pass. Derived screenshot error report fixed (6 tests pass). OPEN: final source Converge/Git commit, GitHub CI and immutable release.
OPEN (A11): verify refreshed backup each Mac, official maccontrol update Mac Server then jkmac, current code SHA/health and no BF33/UNKNOWN impact; report current public grade without contacting or requesting any M8ven rescan.
EXTERNAL: M8ven false-positive subprocess flags, native macOS scanner compatibility, independent reputation/forks/stars are not directly solvable by truthful code changes. Do not manipulate reputation.

A10b-native-protocol BLOCKER discovered in deployment preflight: old
CFBundleVersion1 GUI on both Macs cannot answer new screenshot JSON/base64.
Do not publish/activate until paired native helper release is pinned and
owner-only legacy refresh is RED/GREEN verified.

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
