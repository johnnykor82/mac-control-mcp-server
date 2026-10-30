# Mac Control tool catalog

[Русская версия](TOOLS.ru.md) · [Installation](../README.md) · [Agent workspace convention](../AGENT_WORKSPACE_POLICY.md)

Mac Control connects an assistant to a Mac through MCP. Its tools cover files, repositories, commands, native apps, SSH, downstream MCP servers, ChatBridge browser sessions, and persistent Watcher tasks. This catalog explains the **122 tool names** in the full supported configuration: 102 compatibility handlers, 11 maintenance tools, system information, workspace guidance, and 7 background-browser tools.

The catalog describes the available product surface, not a promise that every tool works immediately after installation. Installed feature flags, local configuration, dependency availability, macOS permissions, and the selected MCP connection determine which tools are advertised and usable. The experimental background-native module is excluded from this count.

## How to read the catalog

**R** means the tool declares `readOnlyHint=true`; **W** means it can change state and declares `readOnlyHint=false`. These are MCP hints, not a separate authorization system. An R tool can still contact a service or read private information. Use both kinds only within the owner's requested scope.

The input column gives representative named arguments, not a complete JSON schema. Omitted optional arguments use their defaults; the connected server supplies the authoritative schema. Names such as `returned_session_token`, `current_sha256`, `event_id`, and `submission_token` mean values returned by earlier calls. Never paste real credentials or task capabilities into documentation or logs.

Agent-created projects, downloads, scratch work and exports belong under the designated workspace by default. The installed workspace is normally `~/MacControlMCP/data/workspace`; an owner-selected data root can change it. This convention is not an operating-system sandbox. Additional project roots require local owner configuration.

A practical first pass is `workspace_policy` → `project_roots` → the relevant capability/status tool. Inspect the current file before replacing it, inspect a proposed Git diff before committing it, and read a Watcher report before acknowledging its notification.

## Workspace orientation — 2 tools

These calls explain the environment before an assistant creates files or chooses a module. They do not install dependencies or change macOS permissions.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `system_info` | R | Report non-sensitive operating-system and Python version information. | No arguments. |
| `workspace_policy` | R | Return the default agent work directory, suggested subdirectories, and rules for writes elsewhere. | No arguments; consult before creating files. |

## Approved project files — 11 tools

Use `project="workspace"` for ordinary agent work. Other aliases must appear in `allowed_projects.json` under the data root. Paths are relative to the selected root. Sensitive/hidden/generated paths, traversal and symlinks are rejected; this is not unrestricted disk access. Text reads/writes are limited to 512 KiB. Overwriting/replacing existing text and recoverable deletion require the current SHA256; replacement backups support recovery.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `project_roots` | R | List approved project aliases, their roots, and the workspace policy. | No arguments; select an advertised alias. |
| `fs_list` | R | List permitted files and directories under one project root. | `project="workspace", path="projects", limit=100` |
| `fs_stat` | R | Inspect size, modification time, mode and available hash; optionally return an approved media-file reference. | `project="workspace", path="artifacts/report.txt"` |
| `fs_read` | R | Read numbered UTF-8 lines and obtain the file's SHA256. | `project="workspace", path="artifacts/report.txt", start_line=1, max_lines=100` |
| `fs_search` | R | Find a literal substring in a bounded scan of permitted UTF-8 files. | `project="workspace", pattern="TODO", path="projects"` |
| `fs_write` | W | Create text, or atomically replace an existing file after checking its SHA256. Python source receives a syntax check. | `project="workspace", path="artifacts/note.txt", content="Review notes"`; add `expected_sha256=current_sha256` when replacing. |
| `fs_replace` | W | Replace exactly one occurrence of a text span, with a required current SHA256. | `project="workspace", path="artifacts/note.txt", old="Review", new="Final", expected_sha256=current_sha256` |
| `fs_mkdir` | W | Create a directory inside an approved project. | `project="workspace", path="artifacts"` |
| `fs_move` | W | Move a permitted file inside the same project without overwriting its destination. | `project="workspace", source="scratch/note.txt", destination="artifacts/note.txt"` |
| `fs_trash` | W | Move one file into private recoverable backup storage; no recursive directory deletion. | `project="workspace", path="scratch/old.txt", expected_sha256=current_sha256` |
| `fs_restore` | W | Restore a retained backup, checking the current destination hash when applicable. | `project="workspace", path="artifacts/note.txt", backup_id=returned_backup_id, expected_sha256=current_sha256` |

## Git repositories — 10 tools

The selected project alias must point to the repository root itself. For example, an owner can approve alias `repo` for a repository under `workspace/projects`. Git tools disable hooks and return bounded output; remote operations still require valid Git credentials and network access. They do not initialize a repository or silently authorize publication.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `git_status` | R | Show the current branch and changed/untracked files. | `project="repo"` |
| `git_diff` | R | Read unstaged or staged changes, optionally for one permitted file. | `project="repo", path="README.md", staged=false` |
| `git_history` | R | Read recent local commits without contacting a remote. | `project="repo", count=12` |
| `git_branches` | R | List local branches and their commit references. | `project="repo"` |
| `git_stage` | W | Stage 1–20 explicit permitted paths. | `project="repo", paths=["README.md"]` |
| `git_commit` | W | Commit already staged changes; hooks and commit signing are disabled by this operation. | `project="repo", message="Document setup"` |
| `git_create_branch` | W | Create a local branch without switching to it. | `project="repo", name="docs-update"` |
| `git_fetch` | W | Fetch references from `origin` without merging them. | `project="repo"` |
| `git_pull_ff` | W | Pull the current branch from `origin` only when a fast-forward is possible. | `project="repo"` |
| `git_push` | W | Push the current branch to the corresponding branch on `origin`. | `project="repo"`; use only when the owner requested publication. |

## Machine diagnostics and approved jobs — 8 tools

Machine diagnostics need no ChatGPT browser login. Approved commands come from owner-managed `allowed_commands.json`; an empty list means no such commands are configured. `project_task` may execute repository test/build code. Service inspection/restart uses a separate local label allowlist; the legacy default label may not describe this installation, so use `mcp_diagnostics` for Mac Control itself.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `machine_health` | R | Report disk capacity, uptime and memory pressure. | No arguments. |
| `network_listeners` | R | List listening TCP processes and ports without making network requests. | `limit=50` |
| `local_http_probe` | R | Probe an approved loopback HTTP port with GET/HEAD, without credentials or redirects. | `port=8000, path="/health", method="GET"` |
| `approved_commands` | R | List IDs for exact command argument lists configured locally by the owner. | No arguments. |
| `execute_approved` | W | Run one configured command ID in an approved project; no caller-supplied shell or extra arguments. | `project="repo", command_id="lint"` after that ID is configured. |
| `project_task` | W | Run `python_compile`, `pytest`, `npm_test` or `npm_build`; pytest uses the project's `.venv/bin/python`. | `project="workspace", task="python_compile", path="projects/demo/main.py"` |
| `launchd_status` | R | Inspect a locally permitted user LaunchAgent label. | `label=owner_approved_label` |
| `launchd_restart` | W | Restart an explicitly allowlisted user LaunchAgent. Use the dedicated maintenance restart for Mac Control. | `label=owner_approved_label` |

## Local shell and persistent terminals — 9 tools

Shell access is disabled until explicitly enabled through the terminal policy. Noninteractive commands run as the service user; choosing a project is a working-directory choice, not a sandbox. Interactive sessions require `tmux`. Commands and keystrokes can have broad effects, so supply them only for the owner's authorized task.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `terminal_capabilities` | R | Inspect shell availability, terminal policy and interactive-session prerequisites. | No arguments. |
| `terminal_access_configure` | W | Explicitly enable or disable shell/interactive terminal access. | `enabled=true` only when the owner requests shell access. |
| `terminal_exec` | W | Run a bounded noninteractive zsh command in an approved project. | `command="pwd", project="workspace", timeout_seconds=25` |
| `terminal_open` | W | Create a persistent tmux terminal and return its session ID. | `project="workspace", width=120, height=36` |
| `terminal_list` | R | List active managed terminal sessions. | No arguments. |
| `terminal_read` | R | Read a managed terminal's screen and recent scrollback. | `session=returned_session_id, lines=100` |
| `terminal_send` | W | Send literal text or a supported key to a managed terminal. | `session=returned_session_id, text="pwd", key="Enter"` |
| `terminal_resize` | W | Change a managed terminal's character dimensions. | `session=returned_session_id, width=140, height=40` |
| `terminal_close` | W | Terminate one explicitly identified managed terminal. | `session=returned_session_id` |

## Package support — 4 tools

These tools use an existing Homebrew installation. Installing a formula can execute upstream installation scripts as the Mac user. Names are restricted to simple formula identifiers; casks, taps, arbitrary URLs and sudo are not offered by this interface. A package installation is asynchronous: save its job ID and inspect the job rather than resubmitting it.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `package_capabilities` | R | Check Homebrew and tmux availability. | No arguments. |
| `package_installed` | R | Check whether a formula and its version are installed. | `formula="tmux"` |
| `package_install` | W | Start installation of one validated Homebrew formula. | `formula="tmux"`; retain the returned job ID. |
| `package_job_status` | R | Read a package job's state, bounded log tail and available exit code. | `job_id=returned_job_id` |

## SSH hosts and remote work — 10 tools

SSH requires an approved host/profile, existing key or agent authentication, and established `known_hosts` trust. No tool returns private-key contents. Fixed diagnostics are separate from arbitrary remote shell execution. Interactive SSH additionally requires local terminal opt-in and tmux; a local Mac workspace convention does not restrict the remote shell's filesystem.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `ssh_targets` | R | List owner-configured hosts and available fixed diagnostic command names. | No arguments. |
| `ssh_profile_inventory` | R | Inspect SSH config aliases and approved profile metadata. | No arguments. |
| `ssh_identity_inspect` | R | Read local SSH file/account/agent metadata without a subprocess by default; optionally inspect an approved host's effective settings without connecting. | No arguments for local metadata; optional `host="demo"` must name an approved diagnostic host. |
| `ssh_auth_diagnostics` | R | Diagnose SSH identity/agent availability. | No arguments. |
| `ssh_profile_approve_alias` | W | Approve an existing SSH config alias for later use. | `name="demo"` after the owner configures that alias. |
| `ssh_profile_register` | W | Register a host profile; this does not establish host trust or create a working key. | `name="demo", host="server.example", user="operator", port=22` |
| `ssh_diagnostic` | R | Run one fixed read-only diagnostic on an approved host. | `host="demo", command="uptime"` |
| `ssh_exec` | W | Execute a bounded arbitrary remote shell command on a registered host. | `host="demo", command="pwd", timeout_seconds=30` |
| `ssh_open` | W | Open an interactive SSH terminal using a host from the diagnostic allowlist. | `host="demo"`; then use the terminal tools. |
| `ssh_pty_open` | W | Open persistent interactive SSH using an approved profile. | `host="demo"`; retain the returned terminal session ID. |

## Native macOS app and desktop control — 13 tools

This module requires the installed GUI helper and the relevant macOS Screen Recording/Accessibility permissions. Permission prompts require action by the Mac owner. Native GUI tools can activate apps and operate the shared desktop; they are different from ChatBridge's independent background browser. A fresh installation may hide these tools until its GUI feature/helper is enabled.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `gui_status` | R | Inspect permissions, the active app and display information. | No arguments. |
| `gui_displays` | R | List display IDs, global coordinates and pixel dimensions. | No arguments; use the actual display geometry. |
| `gui_windows` | R | List onscreen windows, app names and coordinates. | No arguments. |
| `gui_tree` | R | Read a bounded Accessibility tree for the active app or a specific process. | `pid=0, max_depth=4, max_nodes=120` |
| `gui_screenshot` | R | Capture a display as a reduced JPEG image. | `display_id=0, max_width=1200` |
| `gui_wait_title` | R | Wait briefly for an Accessibility element with an exact requested title. | `title="Save", timeout_seconds=8` |
| `gui_request_permissions` | W | Ask macOS to show the supported privacy-permission prompts. | No arguments; the owner grants permissions in macOS. |
| `gui_open_app` | W | Launch an installed app by name. | `name="TextEdit"` |
| `gui_focus` | W | Activate an already running app by exact bundle ID. | `bundle_id="com.apple.TextEdit"` |
| `gui_mouse` | W | Move, click, double-click, right-click or drag in global screen coordinates. | `action="left_click", x=observed_x, y=observed_y` after inspecting the screen. |
| `gui_press` | W | Press a supported key with optional keyboard modifiers. | `key="s", modifiers=["cmd"]` |
| `gui_type` | W | Paste Unicode text into the focused control while preserving the user's clipboard. | `text="Draft notes"` after identifying the destination. |
| `gui_scroll` | W | Scroll at the current pointer location. | `dx=0, dy=3` |

## Downstream MCP services — 4 tools

Configure approved targets locally in `mcp_targets.json`. Each downstream server has its own authentication, permissions and tool schema. Read discovery first; a tool can be called through the read wrapper only if the downstream metadata explicitly marks it read-only. Optional media arguments use the configured, scoped media mechanism rather than arbitrary file access.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `mcp_targets` | R | List configured downstream MCP target names and transport types. | No arguments. |
| `mcp_bridge_list` | R | Discover a target's tool names, schemas and read-only declarations. | `target="demo"` after local target configuration. |
| `mcp_bridge_read` | R | Invoke a downstream tool explicitly declared read-only. | `target="demo", tool=discovered_read_tool, arguments={}` |
| `mcp_bridge_call` | W | Invoke an approved downstream tool through the write-capable wrapper. | `target="demo", tool=discovered_tool, arguments=validated_arguments` |

## ChatGPT conversations through ChatBridge — 13 tools

The legacy `chrome_*` names now use ChatBridge HTTP. ChatBridge exclusively owns its browser, profile and tabs; Mac Control does not connect directly to CDP. This family requires the relevant installed feature, a configured local ChatBridge endpoint and a signed-in ChatGPT profile. Use stable `task_id` values to keep separate work mapped to separate sessions.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `chrome_orchestrator_status` | R | Inspect the owning ChatBridge service's browser status. | No arguments. |
| `chrome_orchestrator_launch` | W | Ask the owning ChatBridge gateway to check/wake its browser. | No arguments; follow its login guidance when needed. |
| `chrome_chat_ui_status` | R | Read gateway/browser health through HTTP. | No arguments. |
| `chrome_chat_new` | W | Create or reuse a logical ChatBridge session for a named task. | `task_id="review-one", reuse=true` |
| `chrome_chat_adopt` | W | Look up an existing compatibility task's session; does not transfer physical tabs. | `task_id="review-one"` |
| `chrome_chat_switch` | W | Select an existing logical task/session without switching desktop tabs. | `task_id="review-one"` |
| `chrome_chat_send` | W | Queue a prompt, or load one from the scoped agent-prompts directory. | `task_id="review-one", prompt="Review the attached task requirements."` |
| `chrome_chat_wait` | R | Wait for the task's queued gateway request. | `task_id="review-one", wait_seconds=15` |
| `chrome_chat_read` | R | Read the task's available answer and attachment information. | `task_id="review-one", max_chars=16000` |
| `chrome_chat_save` | W | Save a completed answer under workspace/agent-results. | `task_id="review-one", result_filename="review-one.md"` |
| `chrome_chat_archive` | W | Archive the local logical task mapping, not the remote ChatGPT conversation. | `task_id="review-one"` |
| `chrome_chat_restore` | W | Restore an archived logical mapping without navigating a browser. | `task_id="review-one"` |
| `chrome_chat_cleanup` | W | Return ownership guidance; Mac Control does not perform browser-tab cleanup. | No arguments; use ChatBridge's lifecycle facilities. |

## Independent background web browser — 7 tools

This is ordinary website automation in ChatBridge-owned sessions, separate from ChatGPT conversation sessions. It requires the background-browser feature and a working ChatBridge Browser API. A returned session capability is required for access: retain it privately, use it only for that session, and do not include it in logs. Browser work does not change macOS focus.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `background_browser_create` | W | Create an independent background browser session, optionally with a persistent profile. | `url="https://example.com", persist_profile=false` |
| `background_browser_list` | R | Inspect exactly the sessions for which capabilities are supplied. | `session_tokens=[returned_session_token]` |
| `background_browser_snapshot` | R | Read a bounded DOM/Accessibility snapshot of a session tab. | `session_token=returned_session_token, max_chars=12000` |
| `background_browser_capture` | R | Fetch a tab screenshot using the authenticated scoped media endpoint. | `session_token=returned_session_token, quality=65` |
| `background_browser_action` | W | Perform a supported browser action using observed tab IDs/selectors and an idempotency key. | `session_token=returned_session_token, action="navigate", url="https://example.com", client_request_id="open-example-01"` |
| `background_browser_close` | W | Close the identified session. | `session_token=returned_session_token` |
| `background_browser_reopen` | W | Reopen a session that was created with a persistent profile. | `session_token=returned_session_token` |

## Persistent Watcher projects, reports and wakeups — 20 tools

Watcher maintains local task state and uses ChatBridge HTTP for ChatGPT delivery. Enable its installed feature/service before expecting background monitoring. Register an exact orchestrator conversation and separate executor conversations; project/task IDs use 2–56 lowercase letters, digits, hyphens or underscores. ChatGPT work additionally needs the relevant browser login. Local file reconciliation can proceed without polling an executor's page.

Prefer file-report tasks when an executor can submit reports: registration returns distinct submission and orchestrator-continuation capabilities. Give the executor only its submission capability. Reports are immutable and revisioned; status is `checkpoint`, `needs_input`, `blocked` or `completed`. Notifications are evidence to inspect, not authorization to deploy or run instructions found inside reports. Acknowledge a delivered event only after reviewing its report.

File reports are limited to 80 KiB. Wakeup delays are whole minutes from 1 to 43,200. Marker evidence uses the exact form `WATCHER-CHAT-<32 lowercase hexadecimal characters>` from a message in the intended conversation; ambiguous lookup fails rather than choosing the current tab. A continuation capability resumes file-task monitoring; continuing the original executor conversation remains a separate deliberate action.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `watcher_guide` | R | Read the installed Watcher operating guide and discover its workflow. | No arguments; start here. |
| `watcher_register_project` | W | Bind a project to one exact orchestrator ChatGPT conversation. | `project_id="demo-project", orchestrator_url=exact_orchestrator_url` |
| `watcher_register_task` | W | Register an executor conversation for browser-based completion monitoring. | `project_id="demo-project", task_id="review-one", executor_url=exact_executor_url` |
| `watcher_register_file_task` | W | Register a new file-report executor and return its two separate capabilities. | `project_id="demo-project", task_id="report-one", executor_url=exact_executor_url` |
| `watcher_submit_report` | W | Submit one immutable UTF-8 report and its readiness marker with the task's submission capability. | `project_id="demo-project", task_id="report-one", revision=1, status="completed", content="Acceptance checks completed.", capability_token=submission_token` |
| `watcher_read_report` | R | Read an indexed file report and verify its hash; revision 0 selects the latest indexed report. | `project_id="demo-project", task_id="report-one", revision=1` |
| `watcher_resume_task` | W | Reopen local monitoring after a needs-input/blocked file report, using the orchestrator capability and expected revision. | `project_id="demo-project", task_id="report-one", expected_revision=1, capability_token=orchestrator_token`; continue the original executor chat. |
| `watcher_followup_browser_task` | W | Queue a new revision in a completed browser executor's original chat after the previous result is delivered and acknowledged. | `project_id="demo-project", task_id="review-one", prompt="Review the remaining acceptance criteria and report the result.", request_key="review-followup-01"` |
| `watcher_status` | R | Inspect project/task/delivery states, followups and local diagnostics. | `project_id="demo-project"`; omit it for all projects. |
| `watcher_read_result` | R | Read a completed browser executor result, including its current followup revision, with hash verification. | `project_id="demo-project", task_id="review-one", max_chars=65000` |
| `watcher_ack_delivery` | W | Acknowledge one reviewed, delivered event for the exact project. | `project_id="demo-project", event_id=verified_delivery_id` |
| `watcher_pause_project` | W | Pause a project while preserving its state/history. | `project_id="demo-project"` |
| `watcher_resume_project` | W | Resume monitoring/delivery for a registered paused project. | `project_id="demo-project"` |
| `watcher_error_status` | R | Inspect aggregated MCP exceptions and queued diagnostic alerts; metadata-only exceptions do not trigger severe alerts by themselves. | `limit=20` |
| `watcher_resolve_current_chat` | W | Resolve/cache an exact high-entropy conversation marker using verified ChatBridge message evidence. | `evidence_text=exact_WATCHER_CHAT_marker` from the intended conversation. |
| `watcher_schedule_wakeup` | W | Persist a delayed check for the exact conversation using verified marker evidence or its exact URL. | `delay_minutes=30, objective="Verify the report is available", evidence_text=exact_WATCHER_CHAT_marker, request_key="report-check-01"` |
| `watcher_get_wakeup` | R | Verify a saved wakeup's target, identity and delivery state. | `wakeup_id=returned_wakeup_id` |
| `watcher_list_wakeups` | R | List saved wakeups, optionally scoped to one exact conversation. | `chat_url=exact_orchestrator_url` |
| `watcher_cancel_wakeup` | W | Cancel a wakeup that has not been sent or entered an attempt. | `wakeup_id=returned_wakeup_id` |
| `watcher_ack_wakeup` | W | Acknowledge a verified delivered wakeup. | `wakeup_id=verified_wakeup_id` |

## Maintenance, logs and compatibility dispatch — 11 tools

These tools are offered on the full local/authorized remote server, not the restricted read-only HTTP preview. Maintenance text reads/writes have a 256 KiB limit. The file alias writes only inside workspace; approved shipped source is read-only. There is no editable executable extension/plugin hot-reload system. Audit responses expose invocation metadata rather than prompts, tool arguments or answers; service logs are scrubbed diagnostic tails.

Approved source reads are `scripts/dev_mcp_server.py`, `scripts/setup_remote_service.py`, `src/mac_control/maintenance_ops.py` and `src/mac_control/audit_middleware.py`. Log reads are bounded to 8 MiB per file; audit search scans at most 50,000 lines and follows the audit's seven-day retention. Compatibility dispatch accepts at most 128 KiB of JSON arguments and cannot add new executable handlers from workspace.

| Tool | Mode | Purpose | Typical inputs / next step |
| --- | --- | --- | --- |
| `audit_tail` | R | Read the latest valid metadata-only tool audit events. | `limit=20` |
| `audit_search` | R | Search retained audit metadata by tool, status and literal text, with bounded scanning. | `tool="fs_write", status="exception", limit=30` |
| `list_workspace` | R | List non-sensitive workspace entries using workspace-relative paths. | `path="workspace/artifacts", limit=100` |
| `process_snapshot` | R | Inspect selected service executable names and resource usage without command arguments. | `limit=40` |
| `read_service_log` | R | Read a scrubbed tail of one allowlisted service log. | `name="stderr", lines=25`; allowed names: stdout, stderr, restart. |
| `mcp_diagnostics` | R | Inspect the owned remote agent's state, current PID and allowlisted log sizes. | No arguments. |
| `read_file` | R | Read small workspace text or an explicitly approved shipped source path, returning SHA256. | `path="workspace/artifacts/note.txt"` |
| `write_file` | W | Atomically write workspace text; existing files require their current hash and receive a backup. | `path="workspace/artifacts/note.txt", content="Revised note", expected_sha256=current_sha256` |
| `restart_server` | W | Schedule a delayed restart of this installation's verified, loaded remote LaunchAgent. | No arguments; `restart_scheduled` does not prove the restart succeeded. |
| `custom_query` | R | Call an enabled frozen shipped read-only operation, or list the operation catalog. | `operation="help"`; then `operation="fs_list", arguments={"project":"workspace","path":"."}` |
| `custom_command` | W | Call an enabled frozen shipped operation through JSON arguments and the same feature gates. | `operation="fs_mkdir", arguments={"project":"workspace","path":"artifacts"}` |

## Choosing the right workflow

For document/code work, use the filesystem and Git families, then a project test/build when requested. Use a terminal only when structured tools do not cover the task and shell access is authorized. For another machine, inspect SSH profiles and diagnostics before remote commands.

For native application work, check GUI status and inspect the actual window/tree before input. For ordinary websites, use an independent background-browser session. For ChatGPT conversations, use the ChatBridge compatibility family; for persistent handoffs, use Watcher projects and reports. These are distinct session types and their IDs/capabilities are not interchangeable.

When an operation reports an uncertain outcome, inspect its durable request/job/event state before repeating a modifying action. SHA256 conflicts require rereading and reconciling the current file. A missing feature, target alias, permission or login requires that prerequisite to be completed; registering a tool name does not bypass it.
