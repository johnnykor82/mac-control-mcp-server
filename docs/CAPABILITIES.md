[English](CAPABILITIES.md) · [Русский](CAPABILITIES.ru.md) · [README](../README.md)

# Mac Control capabilities: modules and practical workflows

Mac Control MCP Server connects an authorized AI assistant to the owner's Mac.
It combines project files, Git, terminal sessions, SSH, native macOS GUI tools,
browser automation through ChatBridge, and persistent Watcher coordination.
This guide describes the beta.17 product, including the conditions under which
its modules become usable. Tool availability does not prove that a dependency,
account login, permission, or external connection has been configured.

For exact arguments, see the [tool reference](TOOLS.md). For installation and
connection, start with the [README](../README.md). For a complete coordinator and
executor example, use the [Watcher guide](WATCHER_GUIDE.md).

## What a normal installation prepares

| Module | Normal installation | Additional owner action or dependency |
|---|---|---|
| Files, Git, diagnostics, maintenance | Shipped with the core server | Configure additional project roots; Git repositories and credentials remain yours. |
| Agent workspace and audit viewer | Created/provisioned automatically | Connect an MCP client; open `mclog` when desired. |
| Terminal and package tools | Tool implementations are included | Enable terminal access explicitly; install Homebrew or tmux where needed. |
| Native GUI helper | Installed or verified and reused by default | Grant Accessibility and Screen Recording in macOS. |
| ChatBridge integration | Reuses a compatible service or installs a pinned independent release | Google Chrome, supported provider APIs, and any required account login. |
| Watcher | Provisioned with default ChatBridge setup | Sign in to ChatGPT; register projects and tasks. |
| Remote MCP | Setup tools are included | Owner GitHub OAuth App, trusted public HTTPS, and real client authorization. |
| SSH and downstream MCP connections | Client tools are included | Owner-specific hosts, identities, known hosts, and target configuration. |

The experimental `background_native` module is not enabled by the normal product
installation. Historical DEV documents describe additional experiments; they do
not expand the supported default toolset. GUI tools in the standard product use
the separately installed native helper.

## One place for agent-created work

The default workspace is:

```text
~/Library/Application Support/MacControl/MCPServer/data/workspace
```

It contains `projects`, `scratch`, `scratch/tmp`, `artifacts`, `downloads`, and
`logs` folders. The server's instructions and `workspace_policy` tool tell agents
to put generated projects, clones, tests, downloads, and outputs there.
Additional destinations require specific owner direction or necessary OS setup.
This is a working convention, not an operating-system sandbox.

**Example request:** “Create a research folder in the agent workspace, keep the
source notes separate from the final report, and show me the resulting files.”
The workspace is a useful default for projects you want an agent to own without
mixing temporary artifacts into your Desktop or existing repositories.

## Project files, search, and safe text edits

`project_roots` lists configured roots. The workspace is available as `workspace`;
additional roots come from the owner's `allowed_projects.json` configuration.
`fs_list`, `fs_stat`, `fs_read`, and `fs_search` inspect approved project content.
The text tools have size/output bounds; ordinary text file reads and writes are
limited to 512 KiB. A metadata/media reference does not inline arbitrary binaries.

`fs_write` creates or replaces UTF-8 text, while `fs_replace` changes exactly one
matching span. Existing content requires its current SHA256. This compare-and-swap
check prevents an agent from silently overwriting a file changed since its read.
On a conflict, read the current file, reconcile the intended edit, and retry.
Python text written through these tools is syntax-checked before replacement.

```text
fs_read(project="workspace", path="projects/demo/notes.md")
fs_replace(project="workspace", path="projects/demo/notes.md",
           old="Draft", new="Reviewed", expected_sha256="<hash from read>")
```

The dedicated file API rejects traversal, symlinks, and sensitive/generated paths
such as `.ssh`, `.env*`, `.git`, and `node_modules`. These checks apply to that API;
an enabled shell or GUI has the Mac account's broader access.

## Recovery copies, moves, and deletion

Replacing an existing file through the file tools creates a recovery copy under
`data/backups/fs_recovery`. `fs_restore` restores a selected backup with the
relevant destination checks. `fs_mkdir` and `fs_move` handle project organization.
`fs_trash` requires the expected hash and saves a recoverable file copy before
removal. It is not a general-purpose recursive directory deletion interface.

**Example request:** “Update this configuration using its current hash. Keep the
returned backup identifier in the work report so I can restore the previous file.”
Recovery copies are local and can contain the original private content. They are
not an independent disaster-recovery backup or a guarantee against disk failure.

## Git changes with explicit scope

Git tools inspect status, diffs, history, and branches; create a branch; stage
specific paths; commit; fetch; pull with fast-forward-only behavior; and push.
The selected project root must be the repository root. Staging takes explicit
paths rather than an unrestricted `git add -A` operation.
Git operations disable repository hooks and interactive credential prompting.
Existing remote access and Git identity still need to work for the service user.

**Example request:** “Inspect the approved repository, fix the documented issue,
show the diff and test results, then commit only those changed files.”
Use `git_diff(staged=true)` to review what a commit will contain. A successful
local commit does not establish that a push or a remote CI workflow succeeded.
Arbitrary Git commands remain possible through an explicitly enabled terminal.

## Terminal: one command or an ongoing session

Terminal access starts disabled unless its private policy explicitly enables it.
`terminal_capabilities` reports that state. `terminal_access_configure` changes the
opt-in setting; enabling it authorizes shell execution as the Mac service account.
A working directory restricts where a command starts, not what the shell can read.

`terminal_exec` runs a bounded noninteractive zsh command and returns captured
output. The persistent session tools open, read, send input to, resize, list, and
close tmux-backed terminals. They are useful for long-running builds and commands
that need several exchanges. Interactive sessions require tmux.
Temporary/cache environment defaults point into the agent workspace.

**Example request:** “Run the approved project's build. If it needs an ongoing
terminal, retain the session and report its current output and exit status.”
A terminal that still exists is not proof that its task is finished. Commands,
including those launched from project scripts, run with the account's privileges.

## Approved commands, test runners, and Homebrew

For narrower automation, `approved_commands` and `execute_approved` use exact
owner-configured argument lists from `allowed_commands.json`, without a caller
supplying a shell string. `project_task` provides specific runners for Python
compilation, pytest, npm tests, and npm builds in an approved project.
Project tests and build scripts can themselves execute code and contact networks.

The package tools report Homebrew availability and installed formulae, start a
formula installation, and poll its background job status and log tail.
`package_install` accepts a simple formula name, not an arbitrary installer URL,
cask, tap, or sudo command. Homebrew must already be available.
Installing a formula can execute package installation scripts as the Mac user.

**Example request:** “Check whether tmux is available. If I authorize installation,
install the formula, wait for the package job result, and recheck availability.”
A queued package job is a starting state; inspect `package_job_status` for its end.

## SSH profiles, remote commands, and authentication checks

There are two SSH use patterns: fixed diagnostics for locally configured targets,
and managed SSH profiles for remote shell commands and persistent PTY sessions.
`ssh_targets` and `ssh_diagnostic` use `ssh_targets.json` and named diagnostic
commands. Managed profile tools inventory SSH aliases and register/approve profiles;
`ssh_exec` runs a remote command and `ssh_pty_open` opens an interactive session.
Interactive SSH shares the terminal session tools and requires terminal opt-in.

SSH uses the owner's identities and strict host-key checking. A new server must
have a trusted known-host entry; the tools do not make an unknown host trusted
just because its address appears in a prompt. Remote commands have the remote
login user's permissions, which may be extensive.
`ssh_auth_diagnostics` and `ssh_identity_inspect` inspect authentication metadata,
file names/permissions, and agent/configuration state without reading private keys.

**Example request:** “Use the already approved staging profile to check disk
space and the service status. Report findings before changing anything.”
No SSH credentials or production host inventory is supplied by installation.

## Native macOS GUI and screenshots

The helper exposes displays, windows, Accessibility trees, screenshots, app
opening/focus, mouse actions, scrolling, key presses, text input, and title waits.
These are useful when a desktop application has no suitable API or CLI.
The helper is installed under `~/Applications/MacControlMCPServer.app` by default.
Its normal prebuilt installation does not require compiling Swift locally.

macOS Accessibility and Screen Recording permissions are separate owner grants.
`gui_status` reports permission and helper connectivity information;
`gui_request_permissions` requests the system's permission flow. A prompt may not
appear, and an agent cannot grant TCC permissions on the owner's behalf.
Screen captures and Accessibility content may expose any visible private data.

**Example request:** “Open the document editor, inspect the current window, and
make the requested change. Ask before sending or publishing the document.”
Foreground GUI actions can affect the application the owner is using. Do not
assume that a global key press or typing command is a background operation.

## Browser sessions through the independent ChatBridge application

`background_browser_*` tools create capability-protected browser sessions, navigate
and act on pages, inspect snapshots, capture images, list authorized sessions,
and close or reopen sessions. Actions include click, fill, press, scroll, and tab
operations supported by ChatBridge. A session capability is private access material.

Mac Control sends HTTP requests to ChatBridge; ChatBridge owns Chrome and its
profiles. Mac Control does not run a separate Playwright browser or attach to CDP.
The background API does not silently fall back to foreground GUI input. A website's
login, UI structure, rate limits, or access challenge can still prevent a task.
An uncertain action result needs reconciliation before another click or submission.

**Example request:** “Read these three public product pages in background browser
sessions and save a comparison in the workspace. Do not submit any forms.”
A missing/incompatible ChatBridge API produces an error, not a second browser.
See the [browser integration notes](CHATBRIDGE_BROWSER_MIGRATION.md); dated DEV
status statements in older design documents are historical, not current guarantees.

## ChatGPT conversation tools and orchestrator compatibility

The retained `chrome_chat_*` and `chrome_orchestrator_*` names have a different
purpose from general web browsing: they manage ChatGPT task/conversation mappings
through ChatBridge's Sessions API. They can create/adopt a task chat, send a prompt,
read or wait for a result, save a report, and maintain compatibility task state.
`chrome_orchestrator_launch` checks the gateway rather than launching Chrome.
Cleanup/archive operations follow the adapter's supported semantics, not arbitrary
browser tab ownership. Use exact tool descriptions for their current behavior.

This integration uses an authorized ChatGPT web session. It is unofficial and
is not the official OpenAI API. A ChatGPT subscription, account permissions, model
availability, or rate-limit capacity is not supplied by Mac Control.

## Watcher: file reports and browser completion

Watcher keeps project/task state in private SQLite and addresses notifications to
the registered coordinator conversation. New installations start with empty state.
It is a scheduler and delivery service, not an additional AI model or compute pool.

File mode uses `watcher_register_file_task` and revisioned reports submitted through
`watcher_submit_report`. Separate capabilities authorize submission and resumption.
Reports are immutable, SHA256-checked UTF-8 files, up to 80 KiB each.
`checkpoint` records progress; `needs_input`, `blocked`, and `completed` notify the
coordinator. The coordinator reads the report, validates it, and acknowledges it.
A blocked/input-needed file task resumes explicitly in the same executor chat.

Browser mode uses `watcher_register_task` and ChatBridge's provider completion
information. After a result is verified and acknowledged,
`watcher_followup_browser_task` continues the same executor with a stable request
key and preserved earlier reports. Exact session/chat identities are checked.
An unknown delivery must not be blindly resent. See the [full guide](WATCHER_GUIDE.md).

## Delayed checks, pause, and availability

`watcher_schedule_wakeup` stores a delayed check for one verified conversation.
An exact chat URL or verified `WATCHER-CHAT-<32 lowercase hex>` marker identifies
the destination. A marker is a locator, not permission to perform arbitrary work.
Use list/get/cancel/ack tools to manage checks and explicit project pause/resume
to control monitoring. One delayed check does not create a recurring automation.

**Example request:** “In fifteen minutes, check this task's real result and report
in this same conversation. Do not assume success from the executor's last message.”
The Mac must be awake, logged in, and connected for browser delivery. SQLite state
survives restarts; busy chats, provider cooldowns, or offline periods delay work.
Idle Watcher iterations are local; ChatBridge alone performs browser operations.

## Downstream MCP connections and local diagnostics

`mcp_targets` lists owner-configured downstream servers. `mcp_bridge_list`,
`mcp_bridge_read`, and `mcp_bridge_call` inspect/call approved local HTTP or stdio
MCP targets. Read calls require a read-only annotation from the downstream tool;
that annotation is a declaration, not independent verification of its behavior.
Media support follows configured target roots and transport bounds.

`system_info`, `machine_health`, `network_listeners`, and `process_snapshot` help
inspect the Mac. `local_http_probe` covers specified local ports, not arbitrary
network scanning. `launchd_status`/`launchd_restart` use the configured service
allowlist. Availability of a diagnostic does not authorize a repair or restart.

## Remote access, maintenance, logs, and lifecycle

Local MCP uses the installed stdio launcher. Remote setup uses an owner-created
GitHub OAuth App and owner verification, with MCP bound to loopback behind public
HTTPS. Choose an owner-managed domain/TLS/reverse proxy or optional Tailscale
Funnel. Funnel publication requires explicit owner confirmation; setup does not
reconfigure the existing VPN or prove inbound HTTPS from an IP-echo result.
See [OAuth](GITHUB_OAUTH_SETUP.md) and [remote access](REMOTE_ACCESS_GUIDE.md).

Maintenance tools inspect diagnostics and service logs, search audit metadata,
read shipped source or workspace files, write only within their defined workspace
scope, and restart the verified owned remote service. `custom_query` and
`custom_command` dispatch shipped handlers with the same feature gates; they do
not load arbitrary new workspace plugins into the running server.

`mclog` is the bundled read-only terminal audit dashboard. Public audit records
contain tool names, times, status, and duration, not arguments or response bodies.
This does not mean all local data is content-free: reports, backups, browser
profiles, terminal output, and package/service logs can contain private material.
See [mclog](MCLOG.md), [security](../SECURITY.md), and [installation contents](INSTALL_CONTENTS.md).

The installer supports plan/install/setup/update/status/rollback/uninstall.
Versioned releases and `current`/`previous` pointers support rollback; user data is
preserved. Updates reuse a verified GUI helper by default to preserve its TCC
identity. ChatBridge remains independently installed. The software is experimental;
check actual results, account access, and permissions before depending on a workflow.
