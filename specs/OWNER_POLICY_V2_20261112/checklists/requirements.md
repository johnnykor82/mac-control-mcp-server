# Requirements quality checklist — 2026-11-12
- [x] Owner's default work directory explicitly AgentWorkspace.
- [x] External access only after specific owner/task authorization, not an implicit global grant.
- [x] Distinguish SSH private client keys from remote server host keys.
- [x] New SSH hosts supported without prior alias allowlist, changed server identities detected.
- [x] No artificial allowlist of executable commands, ports, process names.
- [x] Preserve OAuth, macOS TCC, filesystem integrity, Watcher UNKNOWN/ACK semantics.
- [x] 143/143 coverage, deterministic independent tests and CI gates.
- [x] Deployment rollback, old tasks/data preservation and full Converge required.
