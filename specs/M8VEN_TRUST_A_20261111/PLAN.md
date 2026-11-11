# M8ven Trust Grade PLAN v1.0 — 2026-11-11

Overall scope approved by the owner on 2026-11-11. Architecture changes require a separate review before implementation.

Verified rollback baseline: /Users/openclaw/AgentWorkspace/artifacts/backups/m8ven-a-20261111. Complete Git bundle SHA256 7dcff1cb0aaa82edd77cbeca5816efe12ea3b52df4ad0b81cc1a9ea58905df68, git bundle verify PASS; online SQLite snapshots of Mac Server Watcher and owned ChatBridge both integrity_check ok; existing owner Watcher and ChatBridge LaunchAgent plists saved with SHA256. Prior immutable installed beta.56 releases on Mac Server/jkmac preserved. Before deployment refresh owner-specific backups. On rollback restore release/plists, NEVER overwrite newer SQLite. Preserve BF33/UNKNOWN.

A01 DONE 2026-11-11: official current GitHub Spec Kit Agentic SDD and Evolving Specs consulted via internet (not Mac/local docs).
A02 DONE: M8ven public current commit f4b92c3 (D/Caution), 143 tools, no successful third-party live execution. Read key findings.
A03 DONE: in-memory FastMCP enumeration and current hint inventory; verified 143-row CSV with SHA256 09b964b7a249db91cd6e469c422a543520e779a8cfa2e40bf17e2d3132489160.
A04 DONE: verified backup and isolated Git worktree branch m8ven-a-20261111 based on exact remote GitHub f4b92c3; original main and installed releases unmodified.
A05 DONE/VERIFIED 2026-11-11: seven SDD/baseline artifacts created; strict Analyze script checked 10 requirements, 11 planned stages, 143 unique MCP tools, read-only/missing annotation counts and exact verified Git bundle SHA; PASS. No source/runtime code edits. A06 separate owner architecture review is the next blocking gate.
A06 ARCHITECTURAL REVIEW GATE: separately approve canonical runtime policy only versus explicit static decorator literals, and decide whether native in-memory screenshot protocol should be changed. Stop coding until approved.
A07 Write RED tests for exact 143 full hints, immutable policy, safety semantics, role-specific get_profile, unchanged audit_context/call schemas and failure on tool inventory drift.
A08 Implement ONLY approved metadata design and approved screenshot alternative; GREEN tests and update docs/backlog after each stage.
A09 Add macOS-only harmless live smoke and separate proof/dispute packet for M8ven including the false positive evidence.
A10 Run full MacControl integration/security, native and dependency CI checks, Converge; Git commit, recheck remote main, publish verified immutable GitHub beta and update Mac Server then jkmac via maccontrol update after per-host backup.
A11 Verify both hosts exact source SHA/health, run latest M8ven audit, report actual grade and residual external reputation / third-party runtime limits. No fake grade claims.
