# Owner Policy v2 — all 143 tools, 2026-11-12

Full canonical tool policy, installed-source AST and independently saved prior 143-tool audit match: **143/143** names, no missing/duplicate entries.

Workspace is default; external reads/writes require specific owner task authorization. Audit metadata is NOT a grant.
Some implementation-bound restrictions intentionally remain: TCC, signed GUI Swift command vocabulary, browser capability/scoped sessions, MCP read-only hint, Watcher ACK vs approval and UNKNOWN no resend, technical resource limits.

| Tool | Source | Effect / remaining safeguard |
| --- | --- | --- |
| audit_search | maintenance_ops.py:319 | any authorized OS-readable log and file, all processes; dynamic actions via terminal/MCP; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| audit_tail | maintenance_ops.py:306 | any authorized OS-readable log and file, all processes; dynamic actions via terminal/MCP; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| background_app_action | background_native_ops.py:188 | valid signed app session required; no global input takeover; Security: optional feature, TCC and app/PID/window bound token |
| background_app_capture | background_native_ops.py:203 | valid signed app session required; no global input takeover; Security: optional feature, TCC and app/PID/window bound token |
| background_app_close | background_native_ops.py:220 | valid signed app session required; no global input takeover; Security: optional feature, TCC and app/PID/window bound token |
| background_app_create | background_native_ops.py:161 | valid signed app session required; no global input takeover; Security: optional feature, TCC and app/PID/window bound token |
| background_app_elements | background_native_ops.py:179 | valid signed app session required; no global input takeover; Security: optional feature, TCC and app/PID/window bound token |
| background_app_list | background_native_ops.py:152 | valid signed app session required; no global input takeover; Security: optional feature, TCC and app/PID/window bound token |
| background_app_windows | background_native_ops.py:170 | valid signed app session required; no global input takeover; Security: optional feature, TCC and app/PID/window bound token |
| background_browser_action | background_browser_ops.py:274 | Owner-session scoped browser actions, use GUI for foreground; Technical: session capability, no foreground, bounded bridge responses |
| background_browser_capture | background_browser_ops.py:306 | create/action/snapshot/capture any URL in owned browser session; use GUI tools for foreground; Technical: session capability, no foreground, bounded bridge responses |
| background_browser_close | background_browser_ops.py:326 | create/action/snapshot/capture any URL in owned browser session; use GUI tools for foreground; Technical: session capability, no foreground, bounded bridge responses |
| background_browser_create | background_browser_ops.py:264 | create/action/snapshot/capture any URL in owned browser session; use GUI tools for foreground; Technical: session capability, no foreground, bounded bridge responses |
| background_browser_list | background_browser_ops.py:316 | create/action/snapshot/capture any URL in owned browser session; use GUI tools for foreground; Technical: session capability, no foreground, bounded bridge responses |
| background_browser_reopen | background_browser_ops.py:336 | create/action/snapshot/capture any URL in owned browser session; use GUI tools for foreground; Technical: session capability, no foreground, bounded bridge responses |
| background_browser_snapshot | background_browser_ops.py:296 | create/action/snapshot/capture any URL in owned browser session; use GUI tools for foreground; Technical: session capability, no foreground, bounded bridge responses |
| chat_marker_issue | maintenance_ops.py:287 | any authorized OS-readable log and file, all processes; dynamic actions via terminal/MCP; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| chrome_chat_adopt | legacy_handlers/chrome_orchestrator_ops.py:206 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_chat_archive | legacy_handlers/chrome_orchestrator_ops.py:274 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_chat_cleanup | legacy_handlers/chrome_orchestrator_ops.py:288 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_chat_new | legacy_handlers/chrome_orchestrator_ops.py:196 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_chat_read | legacy_handlers/chrome_orchestrator_ops.py:240 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_chat_restore | legacy_handlers/chrome_orchestrator_ops.py:298 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_chat_save | legacy_handlers/chrome_orchestrator_ops.py:250 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_chat_send | legacy_handlers/chrome_orchestrator_ops.py:230 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_chat_switch | legacy_handlers/chrome_orchestrator_ops.py:218 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_chat_ui_status | legacy_handlers/chrome_orchestrator_ops.py:167 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_chat_wait | legacy_handlers/chrome_orchestrator_ops.py:313 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_orchestrator_launch | legacy_handlers/chrome_orchestrator_ops.py:178 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| chrome_orchestrator_status | legacy_handlers/chrome_orchestrator_ops.py:155 | unmanaged browser navigation belongs in background_browser_* or gui_*; no uncertain send replay; Security: owner-managed ChatBridge task identity and delivery |
| custom_command | maintenance_ops.py:570 | Frozen trusted dispatcher (not arbitrary Python plugin); terminal_exec/mcp_bridge_call support unrestricted authorized actions; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| custom_query | maintenance_ops.py:565 | any authorized OS-readable log and file, all processes; dynamic actions via terminal/MCP; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| fs_list | legacy_handlers/fs_ops.py:193 | default workspace, authorized absolute project path without persistent allowlist; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| fs_mkdir | legacy_handlers/fs_ops.py:334 | default workspace, authorized absolute project path without persistent allowlist; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| fs_move | legacy_handlers/fs_ops.py:348 | default workspace, authorized absolute project path without persistent allowlist; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| fs_read | legacy_handlers/fs_ops.py:248 | default workspace, authorized absolute project path without persistent allowlist; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| fs_replace | legacy_handlers/fs_ops.py:293 | default workspace, authorized absolute project path without persistent allowlist; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| fs_restore | legacy_handlers/fs_ops.py:437 | default workspace, authorized absolute project path without persistent allowlist; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| fs_search | legacy_handlers/fs_ops.py:396 | default workspace, authorized absolute project path without persistent allowlist; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| fs_stat | legacy_handlers/fs_ops.py:219 | default workspace, authorized absolute project path without persistent allowlist; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| fs_trash | legacy_handlers/fs_ops.py:369 | default workspace, authorized absolute project path without persistent allowlist; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| fs_write | legacy_handlers/fs_ops.py:267 | default workspace, authorized absolute project path without persistent allowlist; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| get_profile | account_profile.py:62 | get_profile only after authenticated owner; Security: authenticated GitHub subject |
| git_branches | legacy_handlers/git_ops.py:99 | any owner-task-approved absolute repo, arbitrary remote, explicit staged paths; Safety: no force, hooks disabled, bounded output |
| git_commit | legacy_handlers/git_ops.py:127 | any owner-task-approved absolute repo, arbitrary remote, explicit staged paths; Safety: no force, hooks disabled, bounded output |
| git_create_branch | legacy_handlers/git_ops.py:140 | any owner-task-approved absolute repo, arbitrary remote, explicit staged paths; Safety: no force, hooks disabled, bounded output |
| git_diff | legacy_handlers/git_ops.py:71 | any owner-task-approved absolute repo, arbitrary remote, explicit staged paths; Safety: no force, hooks disabled, bounded output |
| git_fetch | legacy_handlers/git_ops.py:157 | Remote alias/URL parameter (default origin) not forced origin; Safety: no force, hooks disabled, bounded output |
| git_history | legacy_handlers/git_ops.py:87 | any owner-task-approved absolute repo, arbitrary remote, explicit staged paths; Safety: no force, hooks disabled, bounded output |
| git_pull_ff | legacy_handlers/git_ops.py:167 | Remote alias/URL parameter; ff-only preserved; Safety: no force, hooks disabled, bounded output |
| git_push | legacy_handlers/git_ops.py:181 | Remote alias/URL parameter; no force; Safety: no force, hooks disabled, bounded output |
| git_stage | legacy_handlers/git_ops.py:109 | Removed 20-path cap, bounded argv bytes and explicit selection; Safety: no force, hooks disabled, bounded output |
| git_status | legacy_handlers/git_ops.py:59 | any owner-task-approved absolute repo, arbitrary remote, explicit staged paths; Safety: no force, hooks disabled, bounded output |
| gui_displays | legacy_handlers/gui_ops.py:119 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_focus | legacy_handlers/gui_ops.py:313 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_mouse | legacy_handlers/gui_ops.py:217 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_open_app | legacy_handlers/gui_ops.py:325 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_press | legacy_handlers/gui_ops.py:244 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_request_permissions | legacy_handlers/gui_ops.py:203 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_screenshot | legacy_handlers/gui_ops.py:167 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_scroll | legacy_handlers/gui_ops.py:234 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_status | legacy_handlers/gui_ops.py:96 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_tree | legacy_handlers/gui_ops.py:139 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_type | legacy_handlers/gui_ops.py:254 | Removed 1500-char cap; 32768-char/128KiB bound and clipboard restore; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_wait_title | legacy_handlers/gui_ops.py:343 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| gui_windows | legacy_handlers/gui_ops.py:129 | any owner-task-approved app; 32768 char/128KiB paste, native actions per installed signed binary; Security+technical: macOS TCC, signed GUI protocol and IPC bounds |
| launchd_restart | legacy_handlers/system_ops.py:180 | Supports user/gui/system by exact label and UID, no shell; Safety: localhost-only/no redirect GET/HEAD, validated launchd labels/UID/domain |
| launchd_status | legacy_handlers/system_ops.py:149 | Supports current GUI, other UID GUI/user, and system daemon within OS rights; Safety: localhost-only/no redirect GET/HEAD, validated launchd labels/UID/domain |
| list_workspace | maintenance_ops.py:346 | Removed workspace-only browse restriction for explicit absolute folder; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| local_http_probe | legacy_handlers/system_ops.py:107 | Removed hardcoded TCP port list; any 1–65535 on loopback GET/HEAD; Safety: localhost-only/no redirect GET/HEAD, validated launchd labels/UID/domain |
| machine_health | legacy_handlers/system_ops.py:71 | any loopback port, arbitrary project argv, system/user/GUI services in OS rights; Safety: localhost-only/no redirect GET/HEAD, validated launchd labels/UID/domain |
| mcp_bridge_call | legacy_handlers/mcp_bridge_ops.py:246 | saved or explicit HTTP(S)/stdio target_spec without fixed list; Security: readOnlyHint required by read path; separate bridge_call for mutations |
| mcp_bridge_list | legacy_handlers/mcp_bridge_ops.py:223 | saved or explicit HTTP(S)/stdio target_spec without fixed list; Security: readOnlyHint required by read path; separate bridge_call for mutations |
| mcp_bridge_read | legacy_handlers/mcp_bridge_ops.py:233 | Read only when downstream readOnlyHint is true; mutations through bridge_call; Security: readOnlyHint required by read path; separate bridge_call for mutations |
| mcp_diagnostics | maintenance_ops.py:415 | Added task-authorized log_paths metadata; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| mcp_targets | legacy_handlers/mcp_bridge_ops.py:211 | saved or explicit HTTP(S)/stdio target_spec without fixed list; Security: readOnlyHint required by read path; separate bridge_call for mutations |
| network_listeners | legacy_handlers/system_ops.py:92 | any loopback port, arbitrary project argv, system/user/GUI services in OS rights; Safety: localhost-only/no redirect GET/HEAD, validated launchd labels/UID/domain |
| package_capabilities | legacy_handlers/package_ops.py:128 | Reports formula+cask+tap support; Safety: subprocess argv/no shell; bounded async jobs |
| package_install | legacy_handlers/package_ops.py:167 | Homebrew formula/cask/tap by validated kind; Safety: subprocess argv/no shell; bounded async jobs |
| package_installed | legacy_handlers/package_ops.py:147 | Homebrew formula/cask/tap query; Safety: subprocess argv/no shell; bounded async jobs |
| package_job_status | legacy_handlers/package_ops.py:208 | Homebrew formula/cask/tap; other installed managers via owner-authorized terminal; Safety: subprocess argv/no shell; bounded async jobs |
| process_snapshot | maintenance_ops.py:374 | Removed six-name executable filter; all process names and resource metrics; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| project_roots | legacy_handlers/fs_ops.py:179 | Workspace default; no pre-registration for explicit approved absolute project; Safety: OS permission, traversal/symlink and SHA/CAS/backup |
| project_task | legacy_handlers/system_ops.py:200 | Removed four-command-only list; supports arbitrary shell-free argv; Safety: localhost-only/no redirect GET/HEAD, validated launchd labels/UID/domain |
| read_file | maintenance_ops.py:451 | Removed workspace-root-only paths; any owner-task-authorized OS-readable file; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| read_service_log | maintenance_ops.py:391 | Removed three-log-name-only list; arbitrary user-authorized path with scrubbing; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| restart_server | maintenance_ops.py:504 | any authorized OS-readable log and file, all processes; dynamic actions via terminal/MCP; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| self_update_start | maintenance_ops.py:493 | any authorized OS-readable log and file, all processes; dynamic actions via terminal/MCP; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| self_update_status | maintenance_ops.py:487 | any authorized OS-readable log and file, all processes; dynamic actions via terminal/MCP; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |
| ssh_auth_diagnostics | legacy_handlers/ssh_auth_diag.py:13 | inspect metadata and owner-managed host authentication without echoing secrets; Security: no private key contents |
| ssh_diagnostic | legacy_handlers/ssh_bridge_ops.py:113 | Arbitrary task-authorized remote command, classified destructive; Safety: first-contact OpenSSH accept-new, changed fingerprints rejected |
| ssh_download | legacy_handlers/ssh_file_transfer.py:718 | Task-authorized absolute local file, staging SHA/overwrite protection; Safety: symlinks, SHA256/CAS, staging/size/recovery |
| ssh_exec | legacy_handlers/ssh_manage_ops.py:203 | Any owner-approved host, any OS-readable key, no profile registration; Safety: host key authenticity, no agent forwarding/password prompts |
| ssh_identity_inspect | legacy_handlers/ssh_auth_diag.py:53 | inspect metadata and owner-managed host authentication without echoing secrets; Security: no private key contents |
| ssh_open | legacy_handlers/ssh_bridge_ops.py:66 | New hosts via OpenSSH with TOFU, no pre-approved diagnostics list; Safety: first-contact OpenSSH accept-new, changed fingerprints rejected |
| ssh_profile_approve_alias | legacy_handlers/ssh_manage_ops.py:154 | direct user@host/IP, any readable regular identity; saved profile optional; Safety: host key authenticity, no agent forwarding/password prompts |
| ssh_profile_inventory | legacy_handlers/ssh_manage_ops.py:140 | direct user@host/IP, any readable regular identity; saved profile optional; Safety: host key authenticity, no agent forwarding/password prompts |
| ssh_profile_register | legacy_handlers/ssh_manage_ops.py:171 | Existing owner-readable identity key anywhere; shortcut optional; Safety: host key authenticity, no agent forwarding/password prompts |
| ssh_pty_open | legacy_handlers/ssh_manage_ops.py:252 | Any owner-approved host and key; signed tmux session; Safety: host key authenticity, no agent forwarding/password prompts |
| ssh_targets | legacy_handlers/ssh_bridge_ops.py:49 | any owner-task host; ssh_diagnostic arbitrary but correctly destructive; Safety: first-contact OpenSSH accept-new, changed fingerprints rejected |
| ssh_transfer_begin | legacy_handlers/ssh_file_transfer.py:743 | Absolute owner-approved local path; resumes identity-checked; Safety: symlinks, SHA256/CAS, staging/size/recovery |
| ssh_transfer_cancel | legacy_handlers/ssh_file_transfer.py:783 | any task-approved local absolute path, relative defaults to workspace; Safety: symlinks, SHA256/CAS, staging/size/recovery |
| ssh_transfer_chunk | legacy_handlers/ssh_file_transfer.py:760 | any task-approved local absolute path, relative defaults to workspace; Safety: symlinks, SHA256/CAS, staging/size/recovery |
| ssh_transfer_finish | legacy_handlers/ssh_file_transfer.py:772 | any task-approved local absolute path, relative defaults to workspace; Safety: symlinks, SHA256/CAS, staging/size/recovery |
| ssh_upload | legacy_handlers/ssh_file_transfer.py:706 | Task-authorized absolute local file, staging SHA/overwrite protection; Safety: symlinks, SHA256/CAS, staging/size/recovery |
| ssh_write_text | legacy_handlers/ssh_file_transfer.py:730 | any task-approved local absolute path, relative defaults to workspace; Safety: symlinks, SHA256/CAS, staging/size/recovery |
| system_info | operations.py:4 | no arbitrary commands needed; Safety: static non-sensitive facts |
| terminal_capabilities | legacy_handlers/command_plugins.py:142 | default workspace, owner-approved external absolute working directory; arbitrary shell command; Safety: time/size/tmux session isolation |
| terminal_close | legacy_handlers/command_plugins.py:363 | default workspace, owner-approved external absolute working directory; arbitrary shell command; Safety: time/size/tmux session isolation |
| terminal_exec | legacy_handlers/command_plugins.py:160 | Any command, cwd may be specifically approved absolute path, >8000 => fs_write fallback; Safety: time/size/tmux session isolation |
| terminal_list | legacy_handlers/command_plugins.py:338 | default workspace, owner-approved external absolute working directory; arbitrary shell command; Safety: time/size/tmux session isolation |
| terminal_open | legacy_handlers/command_plugins.py:234 | Approved absolute project cwd without persistent registry; Safety: time/size/tmux session isolation |
| terminal_read | legacy_handlers/command_plugins.py:259 | default workspace, owner-approved external absolute working directory; arbitrary shell command; Safety: time/size/tmux session isolation |
| terminal_resize | legacy_handlers/command_plugins.py:319 | default workspace, owner-approved external absolute working directory; arbitrary shell command; Safety: time/size/tmux session isolation |
| terminal_send | legacy_handlers/command_plugins.py:272 | default workspace, owner-approved external absolute working directory; arbitrary shell command; Safety: time/size/tmux session isolation |
| watcher_ack_delivery | legacy_handlers/watcher_ops.py:489 | Receipt only after delivered; does not approve goal; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_ack_wakeup | legacy_handlers/watcher_ops.py:359 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_approve_goal | legacy_handlers/watcher_ops.py:225 | Owner review/decision separate from ACK; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_cancel_wakeup | legacy_handlers/watcher_ops.py:349 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_dispatch_browser_task | legacy_handlers/watcher_ops.py:263 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_error_status | legacy_handlers/watcher_ops.py:507 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_followup_browser_task | legacy_handlers/watcher_ops.py:439 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_get_wakeup | legacy_handlers/watcher_ops.py:329 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_guide | legacy_handlers/watcher_ops.py:75 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_list_wakeups | legacy_handlers/watcher_ops.py:339 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_pause_project | legacy_handlers/watcher_ops.py:469 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_read_report | legacy_handlers/watcher_ops.py:411 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_read_result | legacy_handlers/watcher_ops.py:542 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_reconcile_goal_review | legacy_handlers/watcher_ops.py:203 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_register_browser_project | legacy_handlers/watcher_ops.py:148 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_register_file_task | legacy_handlers/watcher_ops.py:379 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_register_project | legacy_handlers/watcher_ops.py:133 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_register_task | legacy_handlers/watcher_ops.py:288 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_resolve_current_chat | legacy_handlers/watcher_ops.py:316 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_resume_project | legacy_handlers/watcher_ops.py:479 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_resume_task | legacy_handlers/watcher_ops.py:422 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_return_for_rework | legacy_handlers/watcher_ops.py:245 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_schedule_wakeup | legacy_handlers/watcher_ops.py:298 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_spawn_subagent | legacy_handlers/watcher_ops.py:168 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_status | legacy_handlers/watcher_ops.py:369 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| watcher_submit_report | legacy_handlers/watcher_ops.py:393 | no arbitrary messaging outside verified owner workflows; Security+reliability: verified identities, UNKNOWN no retries, separate ACK/approval |
| workspace_policy | workspace_policy.py:85 | AgentWorkspace remains default, no implicit global external scope; Owner policy: external access requires specific task permission |
| write_file | maintenance_ops.py:466 | Removed workspace-root-only paths; owner-task external write with SHA/CAS; Safety: owned self-update, SHA/CAS/backup, redaction, frozen dispatcher |

Testing: S02 external roots 47 tests, S03 core 42 and logs 22, S04 Git4/maintenance23, S05 SSH37, S06 packages4/launchd21/GUI2. Full suite and CI pending.
