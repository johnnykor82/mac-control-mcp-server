# Converge preflight — owner capability policy v2, 2026-11-12

This is a PRE-RELEASE Converge review, **not final acceptance**. All implementation changes live only in the isolated AgentWorkspace worktree. Source history BF33/UNKNOWN remains untouched. No production upgrade has occurred.

| Requirement | Source/test evidence | Status |
|---|---|---|
| R01 Artificial hard-coded allowlists removed from targeted tools | TOOL_MATRIX.csv, source diff, test batches | PASS |
| R02 AgentWorkspace remains mandatory default, external access requires owner instruction for particular task | workspace_policy.py, EN/RU docs, workspace policy tests | PASS |
| R03 Authorization statement not fabricated from audit_context; no persistent blanket grant | spec, architecture, workspace instructions | PASS (behavioral, not OS sandbox) |
| R04 Any accessible client SSH key and owner-approved new host, changed key rejected | SSH RED/GREEN, StrictHostKeyChecking=accept-new | PASS |
| R05 Any loopback TCP port, GET/HEAD/no redirects and bounded response | core RED3/GREEN42 | PASS |
| R06 All process names, project shell-free commands, scrubbed generic logs | core/logs unit tests, source | PASS |
| R07 Files/Git/terminal absolute task-target paths; no traversal, symlink, or SHA/CAS regression | external project tests, maintenance23, negative symlink RED→GREEN36 | PASS |
| R08 SSH transfer/diagnostics new host/identity and SHA verification | SSH regressions37, SFTP33, arbitrary diag destructive classification | PASS |
| R09 Homebrew formula/cask/tap, other owner-approved package manager via terminal | package mocked RED4→GREEN4, no actual install | PASS |
| R10 Browser/GUI/bridge/launchd more flexible where technical backend allows; TCC/session safety retained | launchd21, GUI2, code review of browser/native/bridge boundaries | PASS |
| R11 Watcher ACK, Supervisor independent review, UNKNOWN no blind resend, old historical tasks untouched | watcher_ops unchanged; BF20 pytest29, targeted pass | PASS local |
| R12 143/143 tools reviewed with exact source and safety classification | TOOL_MATRIX.csv, MCP in-memory metadata136 standard/143 native | PASS |
| R13 Full tests+CI+commit+release+dual Mac postflight | 811 ordinary unittest cases (1 skipped), BF20 29; full-history audit too slow for terminal; CI/deployment pending | PENDING |

Local evidence (untracked logs retained ONLY in AgentWorkspace): S07-BATCH-01-PINNED.log, S07-BATCH-02A-GREEN.log, S07-BATCH-02B1-FAST.log, S07-BATCH-02B2.log, S07-BATCH-03.log, S07-BATCH-04-GREEN.log, S07-BATCH-05-GREEN.log, S07-BF20-PYTEST.log, S07-STATIC-AUDIT.log, S07-SOURCE-PAYLOAD.json.

Risk: An authenticated arbitrary shell operating as macOS user cannot have its external accesses cryptographically constrained by tool docstrings. Task-specific owner authorization is an agent instruction and review rule, NOT enforced by audit_context alone. User asked to remove mandatory filesystem root binding while keeping this explicit behavioral rule. Do not advertise an invented grant mechanism.

Gate: source CI macOS green, Git commit+merge/release, independent SHA verification, jkmac and Mac Server fresh backups and deployment smoke, final Converge update and Git commit before declaring DONE.
