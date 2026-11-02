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
