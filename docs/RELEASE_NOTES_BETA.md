# Mac Control MCP Server — draft GitHub Beta release description

**Language:** [English](#english) · [Русский](#русский)

## English

**Switch language:** [Русский](#русский)

Mac Control MCP Server gives an owner-authorized AI agent broad capabilities on macOS through MCP: filesystem, terminal, Git, SSH, native GUI automation, service control, and background browser operations through **ChatBridge**.

- **Workspace-first:** one default directory for agent-created projects, logs, temporary files and results.
- **Native GUI:** separate optional GUI helper with owner-approved macOS permissions.
- **Independent ChatBridge dependency:** Mac Control uses ChatBridge's HTTP Browser API, never owns Chrome. ChatBridge must be published separately **first**; Mac Control can install it from a reviewed standalone release checkout.
- **Remote access:** individual GitHub OAuth Apps, Tailscale Funnel, HTTPS and explicit owner authorization.
- **Safe lifecycle:** versioned installation, update, rollback and removal preserving data.
- **Open source:** MIT License, copyright © 2026 Ivan Konstantinov.

**Beta acceptance still required:** independent installation on an unrelated Mac, real GitHub OAuth sign-in, external Funnel access, macOS Accessibility/Screen Recording permissions and final public source-provenance review. This is not a production certification.

## Русский

**Переключить язык:** [English](#english)

Mac Control MCP Server предоставляет авторизованному ИИ-агенту широкие возможности управления macOS через MCP: файлы, терминал, Git, SSH, нативный интерфейс, службы и браузерные операции через **ChatBridge**.

- **Единая рабочая директория:** проекты, временные файлы, логи и результаты агентов хранятся в одном каталоге.
- **Нативный GUI:** дополнительное приложение-помощник с разрешениями macOS, выдаваемыми владельцем.
- **Отдельный ChatBridge:** Mac Control использует его HTTP Browser API и не запускает собственный Chrome. ChatBridge публикуется **раньше** и может устанавливаться из проверенного отдельного релиза.
- **Удалённый доступ:** личное GitHub OAuth App, Tailscale Funnel, HTTPS и явное разрешение владельца.
- **Установка и обслуживание:** версии, обновление, откат, удаление с сохранением данных.
- **Открытые исходники:** MIT License, © 2026 Ivan Konstantinov.

**Что ещё проверить перед Beta:** независимую чистую установку на другом Mac, GitHub Actions для соответствующего исходного коммита, зависимости и права распространения. Публичный GitHub OAuth, Funnel, Accessibility/Screen Recording, ChatBridge/Watcher и откат подтверждены на текущем Mac в рамках E9. Это пока не подтверждение готовности публичного выпуска.

## v0.1.0-beta.16 — production tool parity and portable Watcher

- Port maintenance tools and the static compatibility dispatcher, retaining workspace and CAS restrictions.
- Include current Watcher file reports, marker-based chat resolution, scheduled checks and browser-task followups through ChatBridge HTTP.
- Provision the owned Watcher login service with default installation; stop/restart it safely on update, rollback and uninstall.
- Preserve metadata-only audit logging and separate all runtime state from release code.
- Live ChatGPT delivery on the upgraded Mac is a separate beta acceptance step; automated tests do not sign in or send real messages.

## v0.1.0-beta.17 — bilingual module and Watcher guides

- Expand English/Russian README, module overview, complete 122-tool catalog, practical Watcher guide and FAQ; include the guides in installed releases.
- Fix packaged interactive SSH imports. Local identity inspection no longer targets a developer's fixed host; effective SSH configuration is inspected only for an explicitly supplied approved profile.
- Watcher runtime remains as introduced in beta.16. Real notification delivery on the upgraded target Mac remains the next acceptance step.

## v0.1.0-beta.18 — consolidated, self-updating Mac Control

- All Mac Control-managed code, versions, GUI helper, data and workspaces now reside in `~/MacControlMCP`.
- New `~/MacControlMCP/bin/maccontrol` CLI updates from the latest complete published GitHub beta, verifies SHA256SUMS, and supports status, rollback and uninstall from any directory.
- `uninstall --all` performs confirmed complete deletion of Mac Control-owned files and services, preserving the independent ChatBridge installation.
- Legacy roots are deliberately not migrated automatically. A clean reinstall is supported after uninstalling the old instance.

## v0.1.0-beta.19 — automatically managed ChatBridge dependency

- Fresh Mac Control installation detects ChatBridge and, if absent, downloads the SHA256-pinned release and installs its service, Chrome profile, SQLite and retained installer source under `~/MacControlMCP/deps/`.
- Existing ChatBridge services outside this root are rejected to avoid silently breaking the consolidated deployment.
- Confirmed `maccontrol uninstall --all` invokes the owned ChatBridge uninstaller and stops its LaunchAgent before deleting the Mac Control tree. Tailscale is not changed.
- The system LaunchAgent registration and any global tools, including `uv`, remain managed separately by macOS/tool installers.

## v0.1.0-beta.20 — mclog CLI registration

- Install, update and reinstalls register `mclog` and `maccontrol` as user-scoped commands under `~/.local/bin`, with no sudo.
- `mclog` runs the active `~/MacControlMCP/current/bin/mclog` release and continues to work after update/rollback.
- On Macs without `~/.local/bin` in PATH, add an idempotent PATH block in `~/.zprofile`; open a new Terminal or source it.
- Existing user executables and symlinks are preserved without overwrite. Both commands and the exact PATH block are removed during uninstall.
- Regression tests cover PATH invocation, idempotence, cleanup, foreign commands, unsafe symlinks and spaces in installation paths.


## v0.1.0-beta.21 — SSH/SFTP file transfer and resumable uploads

- Seven new MCP tools: `ssh_upload`, `ssh_download`, `ssh_write_text`,
  `ssh_transfer_begin`, `ssh_transfer_chunk`, `ssh_transfer_finish`,
  `ssh_transfer_cancel`. File contents travel through authenticated SFTP,
  not `ssh_exec` shell strings; MCP-supplied text and base64 JSON chunks work
  without a pre-existing file on the Mac.
- SHA-256 verification, atomic staging, resumable upload chunks, offsets and
  idempotent retry; transfer TTL, size and chunk bounds configurable through
  owner-only `ssh_transfer_policy.json`.
- Supports the managed SSH profile store and existing legacy diagnostic hosts.
  Strict SSH known-host checking and existing keys remain unchanged.
- Localhost SFTP E2E: Python script generated via MCP tools, uploaded, compiled
  with the unchanged `ssh_exec`, downloaded and hash-verified; 100 MiB
  streaming test also passed.
- **Accepted concurrency trade-off (2026-11-01):** overwrite rechecks the
  destination SHA-256 immediately before atomic rename, without remote locks,
  services, backups or strict CAS. An unrelated writer in the tiny check-to-rename
  interval may still lose an update; the owner has accepted this risk. The
  default no-overwrite path remains atomically no-clobber.

## v0.1.0-beta.22 — independent AgentWorkspace (P0)

- Projects, agent-created sources and user artifacts default to `~/AgentWorkspace/`
  (projects/shared/artifacts/downloads/scratch), **outside** `~/MacControlMCP/`.
  Development uses a distinct workspace. Custom installation prefixes use a
  sibling workspace rather than their internal data folder.
- One owner-owned `workspace_root` configuration at
  `data/config/workspace.json`. `maccontrol workspace status` and
  `maccontrol workspace set /absolute/path` update the location without
  moving existing files; external drives are supported and disconnection
  fails closed.
- File, Git, terminal temp/cache, SFTP local file transfer and user-originated
  streaming staging resolve the active user workspace dynamically. Watcher
  user-facing reports and browser results now go under `artifacts/watcher-reports`
  and `artifacts/watcher-results`; Watcher service SQLite stays product-owned.
  Historical indexed reports remain readable at their original locations.
  Agent instructions and workspace tool metadata expose the current path.
- Install, update, rollback and uninstall do not move/delete user projects.
  Full removal never touches the external workspace and refuses to purge a
  populated legacy `data/workspace`. Downgrading to a release that cannot
  understand external workspaces is blocked, avoiding hidden user projects.
- Existing populated legacy workspace remains in place until the user
  explicitly migrates; no automatic migration or service rewrites.
- `maccontrol workspace inventory --from OLD` and
  `maccontrol workspace migrate --from OLD --name NAME` (dry-run) inspect
  sources without changes. `--execute --yes` creates a separately located,
  verified copy while preserving source files, modes and symlinks; live SQLite
  databases use SQLite backup and integrity checks. Old processes and
  LaunchAgents are **never** modified by migration.
- Documentation: [English](WORKSPACE_MIGRATION.md) and
  [Russian](WORKSPACE_MIGRATION.ru.md). No production projects or services
  were changed to prepare this release.

## v0.1.0-beta.23 — installed MCP diagnostics and interactive terminal

- Fixed `mcp_diagnostics` under the installed release: the remote service
  helper and its OAuth dependencies load exclusively from that release,
  independent of the current working directory or ambient Python sys.path.
  Reject symlinked/foreign helpers. The tool now reports the actual owned
  LaunchAgent state, PID, effective process PID, and file sizes for permitted
  redacted log files.
- `launchd_status()` defaults to `org.maccontrol.mcpserver.remote`.
  `org.maccontrol.mcpserver.watcher` is also read-only approved. Historic
  service labels are not enabled by default; an owner may still configure
  specific names in the local `allowed_services.txt`. No restart permissions
  were broadened.
- `local_http_probe()` defaults to the MCP service's declared loopback port
  (3201 in beta.23), obtained from the verified installed lifecycle module.
  OAuth metadata paths are supported; GET/HEAD only, no redirects, no proxy,
  no external hosts or state-changing HTTP methods.
- The installer and updater check for `tmux` and offer owner-approved
  Homebrew installation when run interactively. The explicit
  `maccontrol update --install-tmux` option grants permission from the
  command line. Missing `tmux` no longer makes terminal_list/open/read/
  send/resize/close raise an exception; they return `TMUX_NOT_INSTALLED`
  with remediation. Unrelated MCP tools continue working.
- `gui_status` separately reports functional IPC responsiveness and
  process-list visibility. If GUI IPC succeeds but LaunchServices hides its
  process argv, the state is `responsive` (on-demand), not
  `not_running`. Actual IPC errors remain structured and actionable.
- No Funnel, Tailscale, OAuth, ChatBridge, Watcher service state or user
  workspace migration is performed by this feature. Installation still
  requires manual macOS TCC consent where needed.

## v0.1.0-beta.24 — Homebrew tmux installation diagnostics

- On JKMac-2, beta.23 installed successfully but owner-approved `brew install tmux`
  returned exit code 1. Its stdout and stderr were captured but discarded,
  making the actual failure impossible to diagnose from the installation log.
- The installer now retains the user's Homebrew-relevant environment (including
  `USER`, `LOGNAME`, `TMPDIR`, locale, PATH, proxy and certificate settings),
  rather than replacing it with a minimal `HOME`/`PATH` dictionary.
  Homebrew auto-update and analytics are still disabled for this operation.
- Failures return `error_code`, exit status, the resolved Homebrew path and
  bounded, redacted stderr/stdout excerpts, which are printed to the Terminal
  and included in the structured `tmux` result. Timeouts and missing
  post-install binaries also return structured errors rather than exceptions.
- Homebrew installation remains conditional on the owner's explicit `y`
  at the interactive prompt or `maccontrol update --install-tmux`; no
  unintended package installs or retries. If the Mac-specific cause persists,
  run `brew install tmux` in Terminal and inspect the error message.
- If Homebrew returns exit code 1 after successfully installing tmux
  (as observed on JKMac-2), the installer now verifies the actual binary with
  `tmux -V` and reports `installed_with_warnings` / available=true rather
  than falsely reporting a missing terminal. Real tmux 3.8 terminal
  open/send/read/close was verified via the installed JKMac-2 MCP server.
- No changes to existing Tailscale Funnel routes, OAuth/ChatBridge credentials,
  Watcher, GUI permissions or user workspace paths. All other MCP tools work
  independently of the optional tmux installation.

## v0.1.0-beta.25 — consistent tmux discovery and automatic release retention

- `package_capabilities.tmux_path` and `terminal_capabilities.tmux_path`
  now use the same live executable resolver, checking `/opt/homebrew/bin/tmux`
  and `/usr/local/bin/tmux` before the service's minimal `PATH`.
  A newly installed tmux is discovered without restarting Mac Control;
  non-executable binaries are not reported.
- Installer release garbage collection runs **after** successful release
  activation and post-install setup. It protects both `current` and
  `previous` for one-step rollback and deletes only validated,
  installer-owned, unreferenced older snapshots under
  `~/MacControlMCP/releases`. Unknown directory names, symlinks,
  unexpected top-level files, missing ownership metadata and incomplete
  activation are skipped/refused.
- Read-only preview: `maccontrol releases cleanup --dry-run`.
  Explicit cleanup: `maccontrol releases cleanup --yes`. The preview
  lists protected releases, candidates and estimated reclaimable bytes;
  deletion results include reclaimed bytes and errors.
- User projects in `~/AgentWorkspace`, `data/` (OAuth/Watcher/service
  configuration and logs), ChatBridge, GUI, Tailscale/Funnel and other
  non-release paths are never targets of release cleanup.
- Release retention is covered by dedicated tests of rollback protection,
  dry-run, unrecognized folders, symlinks, dangling pointers, interrupted
  activation, missing ownership markers and new tmux detection.

## Next beta — automatic, non-destructive shared Funnel on HTTPS:443

- Adds safe subpath deployment under /maccontrol/mcp when other services already own / on the same HTTPS:443 host. If /maccontrol is taken, select /maccontrol-2 ... /maccontrol-9 without touching existing routes.
- FastMCP OAuth issuer, callback, token and MCP resource URL use the selected prefix. Dedicated path-aware RFC 8414 and RFC 9728 metadata routes are published separately to avoid overwriting an existing root-level OAuth server.
- Reads both Tailscale funnel/serve configuration views before every publish step. Requires local authenticated issuer metadata, an anonymous 401 challenge and owner confirmation PUBLISH. Adds only 3 scoped handlers, verifies their destinations and hashes all unrelated routes. On partial failure rolls back only handlers installed by that transaction; unknown ownership fails closed.
- Tailscale strips --set-path. The proxy backend target includes the same mount path, preserving the expected FastMCP URL. Never runs tailscale funnel reset, deletes foreign handlers or replaces the root route.
- Previously installed root URLs and saved OAuth configurations remain unchanged on routine updates. Existing /maccontrol-N installations keep their chosen prefix.
- No production Funnel modification by publishing this source beta: owner must run the guided setup and explicitly confirm publication.

## v0.1.0-beta.27 — updates must preserve independent browser services

- Fixed `maccontrol update` failing when another application owns port 8787.
  In the reported case, Hermes WebUI was listening on 127.0.0.1:8787
  and correctly responded HTTP 404 to the unrelated ChatBridge API probe.
- **Updates now skip ChatBridge provisioning by default**, leaving an existing
  ChatBridge, Hermes WebUI, browser credentials, service process, port,
  database and Mac Control browser configuration untouched. The standalone
  `--update` entrypoint also defaults to skip, including when invoked by
  a previous version's updater without any explicit ChatBridge option.
- **Fresh `--install` behavior is unchanged**: the ChatBridge dependency
  is installed or verified unless `--without-chatbridge` was selected.
- Explicit opt-in: `maccontrol update --with-chatbridge`, or invoke the
  installer with `--update --with-chatbridge`. The existing strict
  ownership and API guards still prevent adopting or replacing other services.
- HTTP API conflicts now identify the local port and response status without
  exposing secrets or silently changing the existing service.
- Added regression tests for default update, old updater compatibility,
  first install, explicit opt-in/opt-out and a foreign HTTP 404.
- This release has no automatic Funnel or service changes at publication time.

## v0.1.0-beta.28 — direct-installed wizard imports

- Fixed a `ModuleNotFoundError: No module named 'scripts'` after GitHub OAuth
  onboarding when `guided_setup.py` calls `_enable_shared_funnel`.
- Both `setup_network` and `shared_funnel_routes` now import consistently
  in Python package mode and standalone installed-script mode, without
  requiring a special `PYTHONPATH`, editable checkout or source edits.
- Added subprocess regression test that simulates the installed script:
  run from an unrelated directory with no inherited `PYTHONPATH`;
  detect existing shared routes and reuse an existing `/maccontrol` route.
- No OAuth secrets, live Funnel routes or active Mac services changed as
  part of developing this fix. Existing owner OAuth configuration is retained
  by the installer and is read when setup resumes.


## Local full-capability installer candidate (unreleased)

This worktree remains local; it is not a published release. The candidate
includes native OpenSSH aliases for SSH/SFTP, an authenticated terminal with
automatic tmux provisioning, dynamic MCP targets, ChatBridge login readiness,
ChatBridge+Watcher bundle gates, GUI/TCC guided setup, unchanged visibility
of shipped tools, owner-approved mclog migration, and `maccontrol doctor`.

The tool inventory is 106 compatibility handlers, 126 local MCP tools with
background browser enabled. Previously documented 109/129 counts applied
before the removal of retired command-allowlist tools.

**Acceptance is not complete** until real browser login, macOS TCC approval,
GitHub OAuth MCP authentication, owned Watcher browser delivery, and a fully
green isolated install/update/rollback have been verified. Internal planning
and approval documents remain outside the source checkout.


## FR-021 v2 — owner-only forensic audit and ChatGPT conversation correlation (candidate)

- `mclog` reads full local tool-invocation argument snapshots rather than
  only irreversible type/length summaries. Only the terminal presentation
  masks known secret-looking keys/values. Long inputs have SHA-256 digests,
  lengths and bounded previews; tool response bodies remain unlogged.
- A client-provided MCP `_meta["openai/session"]` can produce a stable
  anonymized `chat_ref` and an optional «ЧАТ» column. This identifies
  the ChatGPT conversation **when the client sends metadata**; it is not
  a title, identity proof, or permission factor.
- The local source JSONL remains 0600 (directory 0700; daily 7-day
  rotation). Remote `audit_tail`/`audit_search` remain metadata-only.
- Versioned source candidate only; active MCP/legacy service and OAuth
  credentials are not changed by testing or publication of source.


## FR-022 — actionable SSH argument validation (candidate)

- The old 5000-character ssh_exec validator rejected a 5027-character
  heredoc (verified in owner legacy audit) with only "Invalid remote command".
- New ssh_exec accepts up to 65536 UTF-8 bytes; longer inputs return
  SSH_COMMAND_TOO_LONG with actual byte count and next steps:
  ssh_write_text or ssh_upload followed by short ssh_exec.
- Empty or non-string commands return SSH_COMMAND_INVALID with guidance.
  Invalid calls do not contact SSH and never echo command contents in errors.
- The change is to the new Mac Control MCP only; old Mac Control and remote
  VPN hosts are not modified.

## FR-023 — guided parameter errors (candidate)

- Guide arguments for 106 frozen handlers, plus custom_command/custom_query.
- Preserve TypeError for nested signature errors and specific SSH error codes.
- Unclassified ValueError may follow side effects: inspect state before retry.
- Policy/runtime failures are not rewritten and live services are unchanged.


## FR-024 — fix false ChatBridge login_required on idle Chrome (candidate)

- Passive /ready HTTP 503 browser_idle means the managed Chrome was closed
  after 300s inactivity; the user may still be authenticated.
- Read-only status reports browser_idle without waking the browser. Only
  owner-initiated install/update calls explicit POST /v1/browser/verify and
  requires live ready=true and chatgpt_authenticated=true.
- Generic HTTP 503, browser unavailable, provider cooldown and an
  unverified login are distinct. No weakened Watcher readiness gate.
- Requires ChatBridge local release with POST /v1/browser/verify; older
  versions display an upgrade instruction rather than claiming a logout.

## FR-025 — MCP input contract audit and actionable errors (candidate)

- Inventory all 133 actual tool schemas (106 frozen + 27 maintenance or
  optional), plus 20 shared-handler modules and ambiguous error backlog.
  Schema and report regeneration have offline tests without execution.
- Replace opaque local terminal and PTY errors with exact length/format limits
  and safe, actual alternative tool names. No shell/PTY side effects from
  invalid input and no expanded command limits.
- Watcher IDs, Git branch names and GUI mouse actions now explain accepted
  syntax or enumerated choices before dispatch.
- Background ChatBridge Browser API distinguishes malformed arguments from
  service configuration and invalid upstream responses, preserving prior
  INVALID_ARGUMENT code for caller input and no-retry for uncertain outcomes.
- Existing authorization, workspace policy and service lifecycle unchanged.

## FR-025.1 — ChatGPT linked-account routing triage (candidate)

- Document and test that link_id is owned by ChatGPT's connection wrapper,
  not the FastMCP server schemas for ssh_exec, terminal_exec or custom_command.
- Distinguish platform eligibility and safety rejections from server argument
  validation and SSH execution. Do not retry a platform-blocked command
  with another tool or interpret MCP status=ok as SSH exit_code=0.
- Include the operator runbook CHATGPT_LINK_ROUTING_DIAGNOSTICS.md in the
  immutable release payload alongside TOOL_ARGUMENT_ERRORS.md.
- Improve mcp_bridge target-name, missing-target and URL diagnostics with
  exact safe alternatives and no leaked caller argument values.
- No platform eligibility or OpenAI safety policy can be changed by this
  local Mac Control update. Production remains unchanged in this candidate.
- Document optional refresh of the app's published/frozen MCP tool snapshot
  where supported, since stale approved schemas can produce parameter
  mismatches even while local FastMCP schemas are correct.

## FR-025.2 — GitHub OAuth profile identity for multi-account ChatGPT (candidate)

- Add an authenticated, remote-only, read-only get_profile tool with
  OpenAI profile metadata and an explicit structured output schema.
- Stable id is the authenticated, immutable GitHub provider subject,
  not a session token, mutable GitHub login or MCP client_id.
- Missing or unauthorized subject fails closed. Local anonymous MCP
  tool schemas and existing OAuth settings are unchanged.
- This helps ChatGPT identify existing linked accounts after reconnect;
  historical duplicate connection records remain managed by ChatGPT.

## FR-025.3 — compatible Mac Control workspace arguments (candidate)

- write_file/read_file now accept familiar projects/<file> (and other
  known workspace subfolders) as equivalent to workspace/projects/<file>.
- fs_write(project, path) and all 106 frozen operation schemas stay
  unchanged; invalid ambiguous file paths receive safe preflight guidance.
- SHA256 CAS, atomic backup, 256 KiB maintenance limit, sensitive-path,
  traversal, symlink and external-root restrictions are preserved.
- Regression tests cover the exact jkmac A08 path without touching
  any Android audit project or its user files.


## v0.1.0-beta.29 — mclog, compatibility and OAuth profile (release candidate)

- Complete FR-021–FR-025 candidate: owner-only mclog actual call
  parameters, detailed MCP tool errors, workspace-relative path
  compatibility for write_file/read_file, and stable authenticated
  GitHub get_profile for ChatGPT linked-account recognition.
- Exact native GUI release is pinned to the beta.29 universal package,
  SHA256 7c1e99163d3c765492f3b035daf609b43092c28ea1380f4c4886b655fdf156ad.
  Source and prebuilt native GUI are packaged separately; the native
  archive contains ad-hoc signed arm64/x86_64 app and clipboard helper.
  Ad-hoc signature validates integrity, not publisher notarization.
- Existing owned GUI is reused by default, without resetting macOS
  Accessibility or Screen Recording permissions. Fresh install still
  requires explicit owner TCC authorization.
- Source and GUI binaries are candidates until the complete GitHub
  macOS CI, security/provenance review, and actual release assets have
  been published with verified SHA256SUMS. A GitHub tag alone is not a
  complete installable update.

- The candidate `BETA_SOURCE_MANIFEST.txt` now matches the Git-tracked source
  inventory. Standalone source tarballs contain no `.git` history: the one
  history-dependent fixture test explicitly skips there, while full-history
  security scanning remains mandatory in Git checkout/CI.


## v0.1.0-beta.30 — full hidden path read/write/delete

- Owner-approved FR-027 removes the hidden-basename restriction for already
  approved workspace and project roots; supports .gitignore, .planning, .git,
  .venv, .env and nested dotfiles with existing MCP file tools.
- Directory fs_stat now returns bounded metadata SHA256, fs_move handles
  directories, fs_trash moves directories into private recoverable storage
  after CAS, and fs_restore recovers them without overwriting an existing path.
- Root, symlink, traversal and file-level CAS guards remain enforced.
- On jkmac, jkmac-mcp is the connection name to this server installation;
  maccontrol update refreshes its server code. It does not update legacy Mac Control.


## beta.30 installer correction and managed ChatBridge updates

- When ChatBridge beta.11 returns HTTP 404 for POST /v1/browser/verify,
  Mac Control invokes its supported POST /v1/browser/wake once and requires
  a successful real GET /ready afterward. Browser wake alone never proves login.
- Publish and pin ChatBridge v0.2.0-beta.12 with verified SHA256 for both new
  installs and owner-managed dependency refreshes; beta.12 exposes /verify.
- `maccontrol update` defaults to refreshing owner-managed ChatBridge using
  its own rollback-safe upgrade installer. Unknown/foreign instances are untouched;
  `--without-chatbridge` opts out. The first transition from beta.29 requires
  `maccontrol update --with-chatbridge` because that older CLI defaults to opt-out.


## beta.31 — urgent BF-14: current-user LaunchAgent allowlist bugfix

- Fixed `launchd_status` unexpectedly rejecting existing ChatBridge labels such as
  `net.chatbridge.gateway` and `net.chatbridge.gateway.maccontrol` as not locally approved.
- Explicit `launchd_restart` now accepts valid current-user LaunchAgent labels
  without an extra `allowed_services.txt` gate. Neither command runs automatically.
- Both still use `launchctl` in `gui/<current-uid>`, validate labels, and use
  `restart_server` for Mac Control's own service. macOS permissions and OAuth remain.
- No live LaunchAgent, Chrome profile or SQLite state is modified by updating source.


## beta.32 — urgent BF-15: stale managed ChatBridge LaunchAgent alias recovery

- `maccontrol update --with-chatbridge` now handles a verified **unloaded**
  `net.chatbridge.gateway` LaunchAgent that mistakenly references the exact same
  Mac Control-owned SQLite database and Chrome profile as the managed
  `net.chatbridge.gateway.maccontrol` service.
- To prevent Chrome/SQLite concurrent writers, **active**, foreign or unknown
  LaunchAgents remain protected. No service is stopped automatically.
- The stale plist is moved to a private, verified backup/quarantine; failed
  ChatBridge provisioning or upgrade restores the original plist. Backup is
  retained after success for manual rollback. Neither SQLite nor Chrome profile
  files are modified by this migration.
- Standalone ChatBridge's own shared-state protection is unchanged.
- If both services are active on the same data, the installer still stops with
  a recoverable error. Stop/migrate that live service only under a separate
  owner-approved transition.


## beta.33 — BF-16: agent-controlled safe self-update with detached watchdog

- Added authenticated `self_update_start(with_chatbridge=false)` and read-only `self_update_status`. The start call returns a job ID before the independent worker updates the running server. Default leaves ChatBridge untouched; setting `with_chatbridge=true` explicitly also upgrades it.
- The worker is executed from the prior immutable, owner-verified release, holds a cross-process lifecycle lock and records bounded, 0600-private progress under `data/run/self-update/`. It uses the existing SHA256-verified GitHub beta manager; users cannot pass shell commands, URLs or arbitrary source directories.
- Following installation, the worker checks an owned running LaunchAgent and the authenticated OAuth challenge on loopback MCP. If a changed release fails, it calls the previous release's official rollback installer, verifies recovery, and marks `rolled_back` or `rollback_failed`. An interrupted/missing watchdog is reported as `worker_missing`, never as success.
- A hard machine reboot or SIGKILL of the independent process can interrupt recovery; this beta detects a missing worker but does not yet install an always-on external OS-level recovery daemon. For existing installations without these tools, bootstrap once with the standard `maccontrol update` command.
- Updating a service intentionally disconnects the current MCP request; reconnect and call `self_update_status`. This feature is not invoked automatically and never touches a live service merely by being installed.


## beta.34 — BF-17: upgrade owner-managed active historical ChatBridge label

- `maccontrol update` accepts existing `net.chatbridge.gateway` services if the active service is demonstrably owned under the same `~/MacControlMCP/deps/chatbridge` release root and persistent data/profile as Mac Control, and `net.chatbridge.gateway.maccontrol` is absent.
- Preserves that service's current LaunchAgent label, port, Chrome profile, SQLite, credentials and settings. Applies the pinned ChatBridge upgrade **to the existing label** using standalone ChatBridge's own idle check, prior plist backup and failed-upgrade rollback. No new second service or profile is created.
- Foreign ChatBridge services and ambiguous launchctl/ownership remain protected; BF-15 inactive duplicate quarantine is unchanged. New installations still use `net.chatbridge.gateway.maccontrol`; no standalone ChatBridge installer changes.
- After a successful ordinary `maccontrol update`, inspect LaunchAgent status, ChatBridge source version and browser readiness; request activity can delay the safe upgrade until the service is idle.


## beta.35 — BF-17 installed-payload fix and validated ChatBridge joint upgrade

- Corrected the **installed release** manifest to include `src/mac_control/self_update.py` and `scripts/self_update_watchdog.py`. Beta.33 and beta.34 contained these files in GitHub source archives but omitted them from the installer-copied runtime payload; `self_update_start` was registered but unavailable at runtime.
- Added a regression that calls actual `copy_source()` and imports the self-update supervisor modules from the isolated installed copy.
- Includes beta.34's strict owner-verified historical running `net.chatbridge.gateway` label support. The Mac Control updater can now refresh an owner-managed ChatBridge b11→b12 without creating a conflicting `.maccontrol` service.
- On previously installed beta.33, bootstrap with `maccontrol update --without-chatbridge` to receive the corrected installed self-update modules; then run `maccontrol update` to upgrade owner-managed ChatBridge under the historical label. Maintain independent verified backup and live idle preflight.


## beta.36 — BF-18: Mac Control-only update survives owned ChatBridge provider cooldown

- `maccontrol update --without-chatbridge` now correctly distinguishes a managed ChatBridge `/ready` HTTP 503 `error.code=provider_rate_limited` from a real `login_required`. No provider cooldown is treated as authenticated.
- On existing installations only, Mac Control may activate its release during cooldown when its configured ChatBridge URL exactly matches a running installer-owned service and its **already running** owned Watcher. Owner marker, release roots, both SQLite and Chrome paths, LaunchAgent label/program/PID, port, and loaded launchd state must match. Returns `readiness_deferred=provider_cooldown`; actual authentication remains unverified until provider recovery.
- Unknown/foreign/legacy endpoints, missing Watcher, mismatch of data/profile, true logout and other 503 failures retain the fail-closed readiness gate. A `--with-chatbridge` upgrade still requires full ChatGPT login readiness.
- The independent Legacy ChatBridge and the managed Mac Control ChatBridge keep their own ports/profiles/databases; neither service is started/stopped or modified during `--without-chatbridge`. The Watcher and MCP may restart on Mac Control release activation.
- Diagnoses an openclaw server with legacy 8788 and managed 59496: rate-limit on managed 59496 had blocked beta35 activation despite both instances running.

## beta.37 — BF-19 Watcher file-dispatch observability and scoped recovery

- Retains up to 100 recent immutable, credential-free dispatch transition events across failed-send recovery and serializes duplicate request keys using SQLite transactions.
- Records file-task registration separately from actual ChatBridge dispatch confirmation; adds durable metadata-only `file_task_dispatch` with request-key/idempotency and distinct `registered`/`prepared`/`queued`/`failed`/`uncertain`/`reported` status. An unacknowledged prepared send is displayed as uncertain after 300 seconds without automatic retry.
- `watcher_status` now redacts submission/resume capability hashes. For the local Mac owner, added explicit CLI dispatch receipts and a guarded early-failure reset that rotates both credentials only when no report/revision/delivery exists. No existing report files are overwritten.
- Two-executor fixture tests cover report integrity, SHA256, delivery/ACK and SQLite restart persistence. Does not circumvent any platform-blocked ChatBridge call or claim that cross-chat credential handoff was verified; real multi-agent E2E remains an external acceptance gate.
- No change to ChatBridge ownership, browser logic, Watcher background tasks or independent Legacy services.

## beta.38 — BF-21 GitHub OAuth validation resilience (2026-11-04)

- A verified GitHub owner identity is cached on the Mac for up to **24 hours from its last successful online verification**. Normal authorized MCP requests use the local cache rather than waiting for GitHub API latency.
- The Mac runs an hourly background revalidation for active tokens. Successful checks renew the 24-hour window; temporary GitHub/network failures (timeout, HTTP 403/429/5xx) never reset or extend that window. An explicit upstream HTTP 401 or a confirmed owner/permission mismatch revokes the cached result immediately. Unknown/expired tokens require a fresh online verification; after 24h offline, authentication fails closed.
- Owner-only Fernet-encrypted, atomically written 0600 snapshot stores token HMAC fingerprints, allowed numeric identity/scopes, and timestamps, **not bearer tokens**. Cached confirmation can survive a Mac Control restart; the hourly background worker resumes when a token is presented. Configuration edits or signing-key changes fail closed. Auth metrics contain counters only and never credential material.
- The OAuthProxy, GitHub OAuth App, original ChatGPT client JWT/refresh lifecycle, provider URLs, Watcher, managed/Legacy ChatBridge and browser profiles are unchanged. Client-side token expiration, unstable HTTPS/Tailscale routing and provider revocations can still require reauthorization; this update does not bypass OAuth or guarantee never reconnecting.
- Regression tests cover offline grace, revocation, clock rollback, concurrency, snapshot corruption, permissions, multi-token isolation and live GitHub response-code classification with mocked HTTP; no real token is used in tests.

## beta.39 — BF-20 owner-bound tokenless Watcher browser dispatch (2026-11-04)

- A verified GitHub OAuth owner can register a **new browser-mode project** and submit an initial task into its executor ChatGPT conversation without handing credentials/capability tokens to that executor. Durable ChatBridge persistent session, request and assistant-turn bindings protect delivery and report provenance.
- The Watcher prepares tasks before network POST, suppresses duplicate sends, quarantines uncertain 429/503/timeout outcomes, treats explicit HTTP 401/403 as blocking and uses existing immutable SHA256 reports and ACK-gated browser continuation.
- Fix release-installation manifest to **include `watcher_browser_dispatch.py`** in the installed runtime payload, verified by a red-to-green packaging regression test and independent 120-file deterministic install-source audit.
- Preserve existing file-mode Watcher tasks, independent ChatBridge and Legacy services, remote OAuth configuration, and user profile state. Normal upgrade command: `maccontrol update --without-chatbridge`; obtain verified backup first.
- **Early public beta release by explicit owner decision:** GitHub macOS CI run `41858680685` ended without executing tests (runner job cancelled). Full pinned local regression: 738 passed (1 skipped); 26 additional BF-20 focused tests passed and deterministic payload audited. Live two-executor ChatGPT-to-ChatGPT acceptance is **not yet verified**; the owner approved publishing this beta before CI and performing a pilot on JKMac-2, with a later bugfix release if needed.

## beta.40 — BF-23 Watcher marker lookup timeout fix (2026-11-04)

- Increase **only** the local Watcher→ChatBridge `POST /v1/chats/resolve-marker` HTTP timeout from 30 seconds to **180 seconds**, and the `watcher_resolve_current_chat` subprocess timeout from 45 seconds to **210 seconds**. All other HTTP and MCP CLI timeouts remain unchanged.
- Add TDD RED→GREEN tests for the two timeout budgets and unchanged default limits. Six focused tests passed, and the full pinned source regression passed **738 tests (1 skipped)**. Deterministic installed-source package contains 120 files; source and Git-history audits found zero critical issues.
- **Real provider lookup remains unverified:** an old duplicate marker produced HTTP 409, a new current-turn marker HTTP 404, and a newly created ChatBridge test conversation could not send its first prompt due to a separate `[data-reasoning-slider]` locator timeout. No prompt was retried. This release does not fix that independent ChatBridge browser UI issue or claim fully functional autonomous orchestration.
- The existing ChatBridge/Legacy instances and historic Watcher tasks must not be modified by a Mac Control-only update (`maccontrol update --without-chatbridge`). Verify host backup and rollback before upgrade.

## beta.41 — BF-23 autonomous subagents and BF-22 model Supervisor (2026-11-05)

- Introduce owner-authenticated `watcher_spawn_subagent`: given an orchestrator's assistant-message marker and a task, Watcher durably resolves the exact orchestrator URL via ChatBridge, creates a new persistent executor session without manual URLs, and binds the actual conversation only after verifying the completed provider request. Each worker belongs to one orchestrator; retries, lost acknowledgements, rate limits, crashes and duplicates fail closed rather than creating another untracked request.
- Add optional BF-22 Goal Supervisor using a separate ChatGPT model conversation. Its structured decision controls bounded continuation or forwarding a review-ready report; Watcher enforces transport/security limits **without grading tests, files, or deliverable quality**. An ACK only confirms delivery. Authenticated `watcher_approve_goal` closes the goal and `watcher_return_for_rework` continues the original worker session after an orchestrator review. Review notices explicitly require the orchestrator to verify the result.
- Retain BF-19 file mode, BF-20 explicit-URL mode, persistent SQLite records and pre-existing tasks. The installation manifest includes both new runtime modules and their tests. ChatBridge beta.13 is required for the verified first-message model-picker fix; Mac Control-only upgrades must not replace ChatBridge.
- Verification before public candidate: 738 frozen unittest tests passed (1 skipped); 788 integration pytest tests passed (1 skipped); BF-23/BF-22 specific 23 tests passed. Release source audit found zero critical issues; frozen MCP inventory totals 140 tools (111 historical handlers, 29 additional). **Real assistant-marker two-worker ChatGPT E2E, successful Supervisor review-to-orchestrator delivery, rollout and hosted CI have not been verified yet**. They remain acceptance gates; these tests alone do not establish a production-ready orchestration system.


## beta.42 — Supervisor UI envelope recovery (2026-11-05)

- Repair BF-22 handling of real ChatBridge Supervisor answers returned as one literal `<escape>{...}</escape>` UI envelope. Only an entire exact envelope is removed; JSON schema, allowed decisions, source assistant-turn provenance, credential checks and strict rejection of mixed/invalid output remain enforced.
- Add owner-authenticated `watcher_reconcile_goal_review(project_id,task_id)` to recover a **previously completed** blocked Supervisor review. It verifies stored request/session/conversation/source IDs using GET only, performs one atomic `blocked`→`supervisor_recovering` state transition, then the existing Watcher tick re-polls that SAME completed review. No new Executor or Supervisor model POST is made. Already completed evidence can be delivered after the original elapsed-time budget; no new model generation is permitted by this exception.
- The frozen MCP catalogue becomes 112 operations / 141 total tools; historical browser/file-mode tools unchanged. BF-19/BF-20 and old user tasks remain untouched. Upgrade with `maccontrol update --without-chatbridge` only after verified backup; leave ChatBridge beta.13 and Chrome profile intact.
- Tests: 16 BF22 Supervisor tests incl. real-format envelope, malformed/foreign/credential rejection, owner/duplicate and elapsed deadline, full pinned 738 unittest PASS (1 skipped), 795 full integration pytest PASS (1 skipped), source and history audits 0 critical. Live recovery and return-to-orchestrator are *still separate acceptance gates*, not established by these offline tests.


## beta.43 — receipt-bound Watcher delivery recovery (2026-11-05)

- Repair stalled delivery of prior ChatBridge notification where request remains `thinking` (or becomes `unknown` on restart) although provider-assigned `user_message_id` and exact user message are durably present. Watcher verifies linked request/session/client key/conversation and the **entire exact immutable user-message payload** using only local ChatBridge GET endpoints. A confirmed receipt is marked delivered with `receipt_confirmed` status; no duplicate message is sent.
- Modern ChatBridge `completed` records with inconsistent/missing local receipt cannot be silently promoted to delivered: fail closed as `delivery_uncertain`. Legacy status-only test fixture compatibility preserved.
- Paired with ChatBridge **beta.14**, which releases its global model slot immediately after confirmed delivery of Watcher-only notifications rather than waiting up to 30 minutes for an unneeded assistant reply. Other chat messages retain normal completion semantics. Prior BF22/23 reports, ACK, orchestrator approval and owner checks unchanged.
- TDD RED→GREEN 12 new Watcher proof cases (thinking/unknown/completed and forged/tampered evidence); full regression and exact package audit required before publishing. The live A/B queue, ACK and approval remain pending acceptance until tested on JKMac-2.


## beta.44 — safe recovery of already-uncertain notification (2026-11-06)

- Completes beta.43 by handling existing `delivery_uncertain` records whose **exact** stored error is `ChatBridge unknown: request_id=<same persisted request_id>`. Watcher automatically performs bounded GET-only verification of original project, target chat/session, source request/client key, provider user-message ID and **entire immutable delivery text**, then atomically marks delivered without another POST. Other uncertain reasons remain blocked.
- Affected project `bf23-live-20261105/agent-a` had already advanced to unknown after old 30-minute model wait, while the user-visible user message persisted; beta.44 specifically handles that state. ChatBridge beta.14 releases the model slot after true receipt for future notifications.
- 18 focused source tests, full 813 integration pytest PASS (1 skipped), 738 unittest PASS (1 skipped), 248 tracked-source manifest and source/history audit 0 critical. Exact beta.44 release archive and JKMac live recovery must still pass before claiming completion.
