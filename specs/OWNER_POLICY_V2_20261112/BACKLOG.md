# Owner policy v2 backlog — 2026-11-12

- [ ] S03 generic external service log handling with task-specific owner consent.
- [ ] S02 external paths: never interpret audit_context by itself as owner approval; enforce AgentWorkspace default in tool docs and actual task workflow.
- [ ] S05 accept new SSH host identities without host/profile allowlist, but detect changed fingerprint.

- [x] S03 generic external service logs with redaction/size protections GREEN22.
- [x] S05 SSH identity and unknown host accept-new with OpenSSH changed-key rejection GREEN37.
- [ ] S06 inspect browser/GUI/native IPC, bridge and launchd and justify remaining constraints for 143 tools.
- [ ] S07 source manifest BETA_SOURCE_MANIFEST.txt must be regenerated after adding files before CI.

- [x] S06 143/143 source+annotation matrix in TOOL_MATRIX.csv / TOOL_COVERAGE.md, reviewed browser/native/ChatBridge/MCP/Watcher boundaries.
- [x] S07 negative parent symlink path tests RED2→GREEN36, preserve canonical root checks.
- [ ] S07 full macOS CI, especially long history audit fixture; local batches cannot mark it passed.
- [ ] S08 fresh jkmac rollback and two-host install/postflight; no release until CI green.

- [x] S07 CI portability: remove hardcoded Mac Server tempfile directory and canonicalize macOS /private/var paths, patch terminal root mock, regenerate FR025; 27 tests passed locally.
- [ ] S07 verify all GitHub macOS CI checks green on updated commit.
