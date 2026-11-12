# Owner policy v2 backlog — 2026-11-12

- [x] S03 generic external service log handling with task-specific owner consent.
- [x] S02 external paths: never interpret audit_context by itself as owner approval; enforce AgentWorkspace default in tool docs and actual task workflow.
- [x] S05 accept new SSH host identities without host/profile allowlist, but detect changed fingerprint.

- [x] S03 generic external service logs with redaction/size protections GREEN22.
- [x] S05 SSH identity and unknown host accept-new with OpenSSH changed-key rejection GREEN37.
- [x] S06 inspect browser/GUI/native IPC, bridge and launchd and justify remaining constraints for 143 tools.
- [x] S07 source manifest BETA_SOURCE_MANIFEST.txt must be regenerated after adding files before CI.

- [x] S06 143/143 source+annotation matrix in TOOL_MATRIX.csv / TOOL_COVERAGE.md, reviewed browser/native/ChatBridge/MCP/Watcher boundaries.
- [x] S07 negative parent symlink path tests RED2→GREEN36, preserve canonical root checks.
- [x] S07 full macOS CI, especially long history audit fixture; local batches cannot mark it passed.
- [x] S08 fresh jkmac rollback and two-host install/postflight; no release until CI green.

- [x] S07 CI portability: remove hardcoded Mac Server tempfile directory and canonicalize macOS /private/var paths, patch terminal root mock, regenerate FR025; 27 tests passed locally.
- [x] S07 verify all GitHub macOS CI checks green on updated commit.
- [x] S07 published beta.59 from CI-green SHA 97a12d4 with remote asset verification after merge PR #7; local BETA_SOURCE_MANIFEST tracked inventory 326/326 confirmed.
- [x] S08 Mac Server backup sha-verified under artifacts/backups/mac-control-owner-policy-v2-S08-macserver-20261112T180823Z.
- [x] S08 Mac Server active source-f68421caee1d, 126/126 source match, Watcher/ChatBridge history preserved; no update retries after transient MCP disconnect.
- [x] S08 JKMac-2 separate verified preinstall backup mac-control-owner-policy-v2-S08-jkmac-20261112T181507Z.
- [x] S08 verified both Mac Server and JKMac-2 beta.59 source-f68421caee1d, 126/126 file hashes on each, independent backups, Watcher/ChatBridge data preserved; temporary jkmac ChatBridge 503 resolved itself before successful retry.
- [ ] Operational follow-up (not release gate): run interactive GitHub OAuth browser test separately on both hosts when owner initiates OAuth acceptance.
