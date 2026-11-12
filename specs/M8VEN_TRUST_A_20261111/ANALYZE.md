# M8ven Trust Grade ANALYZE v1.0 — 2026-11-11

Traceability: R1->A03/A07/A08; R2->A06/A07/A08; R3->A03/A07/A10; R4->A02/A09/A11; R5->A06/A07/A08; R6->A09/A10; R7->A01/A04/A05/A07/A10/A11; R8->all; R9->A06; R10->A11. No uncovered requirement.

Verified observations (not guesses): 143 tools from in-memory FastMCP list_tools, including remote-only get_profile; 64 read-only and 79 mutating. 44 missing destructiveHint and 143 missing idempotentHint, zero missing readOnlyHint or openWorldHint. 44 tools have only 2 fields and 99 have 3. TOOL_MATRIX_BASELINE.csv is evidence with PROVISIONAL values, not an approved security policy.

Known ambiguity: installing metadata centrally via install_registration may not be visible to M8ven's static scanner. The tradeoff between runtime policy and explicit literal decorators is a genuine architecture decision. Native screenshot in-memory output modifies Swift IPC and must not be assumed trivial. Public M8ven listing truncates some of the 5 alleged read-only offenders; obtain owner expanded audit or dispute record instead of inventing names.

Preimplementation gate: SPEC/PLAN/TASKS cover requirements; backup/isolated branch present; no code changes. A06 separately approved design is mandatory before RED tests and implementation. Final grade A also depends on independent reputation and verification factors; do not promise grade uplift absent new scan.

R11->A09/A11. Approved A06 architecture 2026-11-11: explicit policy/source flags, in-memory Swift/Python JPEG, no M8ven outreach. RED→GREEN achieved on isolated branch; 143 policy, 133 full source decorators, in-memory JPEG and real 142-tool STDIO smoke; native Swift compiled/signed. Implementation stages PASS, full regression/release gates still OPEN.

## Post-implementation interim consistency — 2026-11-11

R1-R3: 143 registered tools, all 4 explicit Boolean hints (static 133 dictionaries + remaining frozen/dynamic entries under strict canonical policy), get_profile remote-only, audit_context unchanged. RED→GREEN verified.
R4: unchanged fixed diagnostic subprocesses; no fake mutation claims or M8ven appeals.
R5: Python/Swift in-memory bounded JPEG, original metadata and TCC; mocked test and isolated codesign compile PASS, no private real screenshot taken.
R6: native isolated MCP STDIO handshake/tools-list with 142 tools and system_info PASS; no browser/SSH/Watcher call.
R7-R11: backups verified, branch isolated, docs and backlog updated. A10 full regression/Converge/GitHub release and A11 two-host deployment/grade observation still OPEN.


## Full regression convergence evidence — 2026-11-11

114 integration modules: 932 passed, 1616 subtests passed, 1 skipped.
Security: 4 passed. Full Ruff on all 5 newly created Python modules PASS;
critical Ruff E9/F821/F822/F823 on 26 changed Python modules PASS.
A separate pre-existing F821 in UNTOUCHED watcher_runtime/multi_project_watcher.py
is an independent project issue, not modified under the approved M8ven scope.
Compiler: isolated Swift GUI binary built, ad-hoc signed and codesign verified,
not launched and no production TCC changes. MCP native stdio smoke: 142 tools,
four hints, safe system_info PASS. Release installer manifest: 126 files with
new policy/smoke, payload audit and strict release history scan: zero critical.
Derived docs/TOOL_ARGUMENT_AUDIT_FR025.md updated solely for expected new JPEG
validation errors; 6 matching report tests PASS. No actual user screenshot
captured; mock/compiled evidence does not prove live owner-TCC image rendering.
Release publication, remote CI and two-host parity still OPEN.

A10b-native-protocol Analyze: R12 maps to source marker, pinned universal
package + SHA, exact-owner old-app upgrade, opt-out guard, tests and staged
rollout. Necessary dependency of already-approved R5/R7, not optional
third-party grading. Current code is NOT safe to deploy because old native
GUI would be reused. No untrusted app takeover or M8ven outreach. Analyze PASS.

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
