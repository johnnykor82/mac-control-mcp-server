# SSH/SFTP file transfer — architecture and delivery specification (S1)

Status: **implementation tested; owner accepted best-effort pre-rename SHA-256 checking**
Tracking: [#1](https://github.com/johnnykor82/mac-control-mcp-server/issues/1)  
Priority: high

## Scope and invariants

The agent can create a file from MCP-supplied bytes, push an existing Mac file to a remote host, download remote files, and resume streaming sessions. Neither file contents nor file chunks are inserted into a shell command. No local-path assumption about the ChatGPT runtime is made.

Existing `ssh_exec` (5,000-character command cap), `terminal_exec` (8,000) and `terminal_send` (4,000) stay unchanged. The code runs with the Mac service account's privileges, and remote operations run under the authenticated SSH account.

No remote-filesystem sandbox beyond SSH permissions is introduced. Local transfer cache is private to Mac Control; downloads must be confined to owner-approved local project/workspace roots (unless separately owner-authorized).

## Current architecture (main branch audit)

| Concern | Current implementation | Integration decision |
| --- | --- | --- |
| Managed SSH hosts | `legacy_handlers/ssh_manage_ops.py` uses `DATA_ROOT/ssh_managed_hosts.json`, `_spec(host)`, `_command(host, ...)` | Primary source of `host` for new tools; reuse hostname validation and SSH security options |
| Older SSH diagnostics | `legacy_handlers/ssh_bridge_ops.py` uses **different** `DATA_ROOT/ssh_targets.json` | Preserve it. Introduce explicitly tested adapter or migration from older approved profiles without silently broadening access |
| Existing SSH implementation | System `/usr/bin/ssh`, `BatchMode=yes`, `StrictHostKeyChecking=yes`, `ForwardAgent=no`, alias `~/.ssh/config` incl. ProxyJump | Build SFTP argv from the **same trusted resolved profile**; no `sshpass`, relaxed host-key policy or blind raw subprocess shell |
| Tool composition | `command_plugins.register` calls `ssh_manage_ops.register` | Register new tools via the trusted code path |
| Registry checks | `legacy_adapter._EXPECTED` freezes 102 compatibility operations; 45 read-only. `dev_enabled_operations` validates exact parity | Update both lists/counts and tests when tools are added. Users never manually register tools |
| Dependencies | `requirements/dev-frozen.txt` has no Paramiko/AsyncSSH | Default design uses macOS OpenSSH `sftp` subprocess and fixed SSH remote helpers. No dependency increase unless explicitly approved |
| Auditing | `AuditMiddleware` records metadata, not arguments | Add a bounded file-transfer audit event emitter for host label, paths, byte counts, status, duration and SHA-256, without content or credentials |

## MCP wire contracts

* `ssh_upload(host, local_path, remote_path, overwrite=false, mode=null, expected_remote_sha256=null)` — local source is a regular owner-accessible file. Refuse symlink input and symlink destinations unless explicitly supported in a reviewed path resolution policy. Stream from file descriptor. Return `{status, host, local_path, remote_path, size_bytes, transferred_bytes, sha256, remote_sha256, verified}`.
* `ssh_download(host, remote_path, local_path, overwrite=false, expected_sha256=null)` — `local_path` must be within an approved local root. Download to a private sibling temp, fsync, verify, and atomically commit with no-clobber semantics. Return the same metadata shape with the hash of received bytes.
* `ssh_write_text(host, remote_path, content, encoding="utf-8", overwrite=false, mode=null, expected_remote_sha256=null)` — accept text bytes through MCP arguments; **no heredoc** and no need for an existing Mac path. For initial implementation, support UTF-8 only (reject other encodings instead of silently corrupting). Configurable cap with default at least 128 KiB per call, sufficient for 100-KB Python scripts. Stage bytes into a private local file and reuse the upload pipeline.
* `ssh_transfer_begin(direction, host, remote_path, local_path=null, total_size=null, expected_sha256=null, overwrite=false, mode=null, expected_remote_sha256=null)` — returns `{transfer_id, next_offset, max_chunk_bytes, expires_at, resumable}`. For agent-generated files choose `direction="upload"` without `local_path`.
* `ssh_transfer_chunk(transfer_id, offset, chunk_index, data_base64, chunk_sha256)` — JSON transports binary blocks as base64; **this is MCP input encoding only, never shell base64**. Default decoded chunk max 64 KiB; validate base64, offset, chunk hash and maximum total size. Retry of identical already accepted block returns `already_accepted`; mismatch is a conflict. A transfer may be resumed using the returned `next_offset`.
* `ssh_transfer_finish(transfer_id, expected_sha256=null)` — validates full source SHA-256, uploads via SFTP if upload hasn't completed, verifies remote SHA-256, publishes atomically, returns final status and byte counts. If interrupted, retain recoverable transfer metadata until TTL.
* `ssh_transfer_cancel(transfer_id)` — safely removes owned temporary state locally and remotely; idempotent.

All errors are structured with `code`, `message`, `transfer_id?`, `retryable`, `resumable`, and `next_offset?`. Use explicit codes for `host_not_approved`, `host_key_verification_failed`, `file_exists`, `cas_conflict`, `unsafe_symlink`, `size_limit`, `hash_mismatch`, `ssh_disconnected`, `transfer_expired`.

## Transfer implementation

1. Resolve the registered host before opening local or remote paths. The OpenSSH argv builder must preserve `-F ~/.ssh/config` alias behavior, key selection, strict host verification and batch/no-forwarding constraints.
2. For upload, create a random remote temporary file **in the target directory**, via SFTP. Stream to that path; never expose partially written bytes under the final name. Check complete remote hash before publishing. Remote paths are data, not shell fragments.
3. For download, stream to a private temporary local file and verify before publishing. `overwrite=false` must use an atomic **no-clobber** commit rather than check-then-overwrite. Preserve existing user files on every error.
4. For remote publish, use the fixed server-side commit helper under the existing SSH identity. Verify staged SHA-256 first, then re-read the destination SHA-256 **immediately before** `os.replace`. File contents never enter a shell command. This is a best-effort conflict check, not strict atomic CAS.
5. **Owner's accepted trade-off:** do not create remote per-file lock files, services, backups or coordinated writer protocols. A separate writer may modify the file in the small interval after the last SHA-256 check and before `os.replace`. The owner explicitly accepts this residual risk because concurrent editing of the same remote file is atypical. Preserve atomic file publication and no-clobber by default.
6. Private local session state is stored under `DATA_ROOT/transfers/ssh/` (`0700` dirs, `0600` files). Include host, direction, stage paths, offset, expected hashes, TTL and owner identity; no secrets or contents in JSON metadata. On restart, validate and recover sessions, expire orphan staging files and verify prefix before attempting SFTP resume.
7. Cap total bytes per transfer (configurable, tested with 100 MiB), concurrent sessions, idle TTL, and maximum decoded chunk size. Stream directly from disk; do not buffer 100 MiB in RAM.
8. Audit only metadata. Paths may themselves contain sensitive names and must remain in owner-private audit logs. No credentials, file data, transfer payloads or authentication tokens are ever logged.
9. `ssh_exec` remains available for a **separate** short validation command such as `python3 -m py_compile ...`; it is not used as a file-content transport.

## Test plan and implementation slices

- **S2 basic file operations:** 15 KiB UTF-8; 100 KiB Python; 10 MiB binary; download; Unicode; no-clobber; SHA-256; no partial final file.
- **S3 streaming:** 100 MiB without full-RAM buffering; duplicate chunk retry; out-of-order offset rejection; connection loss; retry/resume; stale cleanup.
- **S4 integration:** tool names in frozen registries; annotations; automatic MCP listing; manifest/install; old SSH/terminal/GUI/Watcher regression tests.
- **S5 live E2E:** submit >10 KiB Python source as MCP `content`, send to a test server, check hashes, run `python3 -m py_compile` via existing `ssh_exec`, download and compare exact bytes without manual `scp`.
- **S6 release:** RU/EN tools and capability docs, README examples, CI passes, Git tag/release only after E2E.

## Gates before merge

- [x] Confirm no-clobber publication and explicitly accept the residual best-effort CAS race (owner decision, 2026-11-01).
- [x] Review alias vs direct vs legacy-profile selection and server key trust.
- [x] Validate MCP input limits for a 100-KiB text call; default chunk 64 KiB decoded, with owner-only policy for limits.
- [x] Verify temporary files are removed on cancellation and opportunistically on expiration; offline host cleanup remains deferred.
- [x] Verify full tool catalog parity, unit tests and live test-server acceptance.
- [x] Preserve production configuration and existing SSH/terminal behavior throughout migration.

## Implementation notes (feature branch)

Implementation uses `/usr/bin/sftp -b -` for file bytes and a fixed Python 3 remote helper (sent via authenticated SSH) for SHA-256 inspection and commit. The remote helper never receives file bytes as an SSH command. Remote no-clobber uses atomic hard-link publication; overwrite verifies the staged SHA-256, then checks the existing destination SHA-256 **directly before** `os.replace`. There is no remote locking subsystem. **Strict CAS is not guaranteed; the owner has explicitly accepted this trade-off.**

`DATA_ROOT/ssh_transfer_policy.json`, when provided by the owner with mode 0600, can configure:
`max_total_bytes` (1 MiB to 1 GiB; default 512 MiB),
`max_chunk_bytes` (1 KiB to 256 KiB; default 64 KiB),
and `ttl_seconds` (300 s to 7 d; default 24 h).
Expired uploads are removed opportunistically when a new transfer starts; if the remote host is unreachable, cleanup is deferred so resumable metadata is retained. `ssh_transfer_begin` can be called with `resume_transfer_id` to recover the saved offset after a reconnect. Repeated identical chunks are idempotent; conflicting offsets/hashes are rejected.

Local file downloads are restricted to approved Mac project roots. Remote paths retain the filesystem permissions of the authorized SSH user. The `ssh_targets.json` diagnostic profile registry is not modified; file-transfer tools use a reviewed adapter to accept both this registry and `ssh_managed_hosts.json`, preserving existing diagnostics. Secrets and contents are never placed in `ssh-transfers.jsonl` audit metadata.

**Observed tests:** 11 dedicated offline transfer tests (15 KiB text, 100 KiB Python, 10 MiB binary, 100 MiB streaming, hash integrity, Unicode, interruption, retry, non-clobber, CAS conflict and download), plus a real localhost SSH/SFTP test through MCP tool registration including `ssh_write_text`, `ssh_exec` Python compilation and `ssh_download`. Full-suite confirmation and GitHub CI gate are recorded in the PR separately.


## Decision record: simplified CAS (2026-11-01)

The owner selected **option 1 — recheck SHA-256 immediately before replacing**.
This supersedes the earlier proposed cooperative remote lock and strict-CAS
release gate. No per-file `flock`, versioned backups, transaction coordinator,
new daemon or remote service is required. Existing transfer-session locking on
the **Mac** is retained solely to keep chunk offsets and local state consistent.

For `overwrite=true`, `expected_remote_sha256` remains an optional guard.
If the remote file changed before the final check, return `cas_conflict`
without replacing the destination. If an unrelated process changes the file
*after* that check but *before* the atomic rename, its changes may be lost.
This is a documented and explicitly accepted residual risk, not a strict
compare-and-swap guarantee.

For `overwrite=false`, atomic hard-link publication still prevents clobbering
an existing destination. The previous filename is never exposed with partial
content, and transfers are still SHA-256-verified.
