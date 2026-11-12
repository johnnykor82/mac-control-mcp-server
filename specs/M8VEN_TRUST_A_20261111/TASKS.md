# M8ven Trust Grade TASKS v1.0 — 2026-11-11

- [x] A01 Read latest GitHub Spec Kit methodology directly online.
- [x] A02 Verify M8ven's current source SHA and public grade/finding inventory.
- [x] A03 Count 143 exact tool annotations at FastMCP runtime and create CSV.
- [x] A04 Backup Git bundle/SQLite/plists and create isolated latest-main worktree.
- [x] A05 Verified 7 SDD files, SPEC R1-R10, PLAN/TASKS A01-A11, 143-tool matrix and rollback SHA; Analyze PASS on 2026-11-11.
- [x] A06 Owner approved 143-name canonical registry, explicit source hints and in-memory JPEG; no M8ven contact (2026-11-11).
- [x] A07 RED tests proved missing 143 metadata and file-backed screenshot; corrected test fixture.
- [x] A08 Canonical 143-entry registry, 133 explicit source dictionaries, in-memory Swift/Python JPEG; new tests 9+419 PASS, native isolated GUI signed/compiled. Full suite remains A10.
- [x] A09 Isolated read-only macOS STDIO smoke validated 142 local tools and system_info, no M8ven contact.
- [ ] A10 TESTS VERIFIED (932+1616, security4, native build, Ruff critical, payload audit); Converge docs, Git commit, GitHub release/CI and host rollout still OPEN.
- [ ] A11 Verify both host versions, optionally read current public grade without contacting M8ven or requesting scans.

- [ ] A10b-native-protocol: RED/assess legacy GUI reuse mismatch, pin matching
  beta57 universal native artifact, owner-only auto-refresh and explicit opt-out
  fail-closed; rerun full regression/security, Converge before release.

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
