# Release lifecycle and version parity

Owner-approved operational policy, 2026-11-11. This applies to Mac Control MCP, its Watcher, and the owned ChatBridge dependency on the primary and secondary managed Mac installations.

## Source of truth
- The latest *verified stable release* (published Git commit/tag and immutable versioned deployment) is authoritative, **not** an untested new commit.
- Before starting any feature or bug fix, compare remote `main`, local source, active release, loaded Python module origin and both hosts' installed SHA. Start from the current verified source; reconcile divergence first.
- Never run production Watcher/ChatBridge using `PYTHONPATH` pointing into a mutable Git worktree. LaunchAgents must use only the immutable installed release. An installer that generates `current/src` rather than `AgentWorkspace/projects/*/src` is the intended route.
- Treat the installed Mac Control and ChatBridge SHAs as **one version pair**; record both along with the Watcher source SHA, owner gateway health, and deployment status.

## Stage gates
1. Specify → Architecture/Plan → Tasks → Analyze. For fixes, Assess → Fix → Test. Read the current GitHub Spec Kit methodology before development.
2. RED/GREEN focused tests for changed behavior; full integration/security suites for all affected services, static checks, source inventory validation, and source Converge.
3. Git commit on an isolated branch; verify remote `main` has not moved unexpectedly. Publish a release only once all checks pass. Do not accidentally commit unrelated changes.
4. Snapshot SQLite online and store owned LaunchAgent plists; verify SHA256 and integrity. Preserve an immutable previous release and a tested rollback that **never overwrites newer live SQLite**.
5. Deploy to the primary host using the versioned installer, check actual Python module origins against released SHA, service health, Watcher ACK/receipt invariants and independent gateway. Stage the secondary host with its own independently verified backup before switching to exactly the same version pair.
6. Mark the release complete only after **all targeted hosts** pass deployment evidence; if a host is unreachable, mark pending/unsynced and do not claim parity. Use only owner-approved management paths and transports.
7. Update PLAN/TASKS/CONVERGE and backlog at every milestone, record Git SHA, release paths, test results and any open blockers. Do not start the next change atop an incomplete release.

## Fail closed
- Provider `queued` is not `delivered`; source-bound HTTP2xx and provider user-message identity are stronger than local IDs. Never repeat `Send` after `unknown` or an uncertain attempt. Orchestrator notification ACK is separate from goal approval.
- Preserve all historic paused projects and already-uncertain requests unless a separate owner-approved operation targets them.
- M8ven automatically monitors new GitHub commits. Read and report its findings; **do not apply code/config changes solely on an M8ven warning without discussion with the owner**.
- Failed upgrade: verify health, rollback service plist/release pointer only, keep newer state DB, report and correct, then revalidate before proceeding.
