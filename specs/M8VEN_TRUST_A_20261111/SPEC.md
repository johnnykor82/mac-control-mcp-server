# M8ven Trust Grade Improvement — SPEC v1.0, 2026-11-11

Approval: The owner approved the overall five-part audit/improvement plan on 2026-11-11, subject to separate architectural review before implementation.

Goal: Improve the independently assessed M8ven grade D toward A through accurate metadata, observable safe behavior, reproducible validation, and internally documented false-positive evidence. A cannot be guaranteed because M8ven also scores reputation, adoption and verification depth.

R1 Exact runtime inventory: all 143 tools, including authenticated-only get_profile, must publish all four explicit Boolean MCP annotation hints: readOnlyHint, destructiveHint, idempotentHint, openWorldHint. No unknown tools or missing flags.
R2 Metadata is truthful to actual handler semantics. Do not change privilege, ownership, audit_context, authorization, operation names, inputs, safety gates or behavior merely to inflate score. Arbitrary terminal_exec remains mutating/non-idempotent.
R3 Every tool has manual semantic review for idempotency/destructive/external effects, with tests on runtime tool listing in stdio and authenticated configurations. Do not treat a provisional algorithm as authoritative.
R4 Review five alleged read-only side effects, three description mismatches and screenshot cleanup with source/contract evidence. Document false positives locally (NO M8ven submissions); do not mislabel safe reads as destructive.
R5 Assess whether gui_screenshot can avoid temporary JPEG files without changing output contract, TCC behavior, max bytes or privacy. Native helper IPC changes require specific architecture approval.
R6 Create a real macOS-only isolated smoke test for MCP initialization, tools/list, harmless read-only calls and failures, without credentials or production user browser profiles; capture repeatable local evidence without contacting M8ven.
R7 Strict SDD: latest verified GitHub base, verified backup, SPEC/ARCH/PLAN/TASKS/ANALYZE before code, RED/GREEN tests, full integration/security/CI, documentation updates, Converge, Git commit, release, backed-up staged rollout on Mac Server and jkmac.
R8 Old BF33 paused state and uncertain Send history must stay immutable; M8ven reports alone never authorize extraneous code changes.
R9 Separate architecture review is a gate before changes to shared tool registration and native screenshot protocol. No source implementation until accepted.
R10 Grade A and public adoption cannot be manufactured; report remaining independent external blockers transparently.

R11 Never contact M8ven: no submissions, appeals, scan requests or owner portal interactions. A public page can be read without interaction.

## A10b-native-protocol — compatibility requirement R12 (2026-11-11)

The approved in-memory JPEG requires both server Python and native GUI helper to
speak the SAME protocol. Both existing Mac Server and jkmac signed owned GUI apps
are CFBundleVersion 1, with no protocol marker; official maccontrol update
reuses installed GUI by default. Activating new Python without GUI refresh would
break gui_screenshot. On standard approved update, only exact owner-managed
legacy helper may be replaced with a checksum-pinned, signed universal GUI app
declaring MacControlCaptureProtocol=jpeg-base64-v1. Preserve previous owned GUI
backup and all TCC checks; refuse untrusted apps. A repeat update must reuse
a compatible helper. Explicit --without-gui with incompatible installed
helper must fail closed rather than silently break screenshot.
