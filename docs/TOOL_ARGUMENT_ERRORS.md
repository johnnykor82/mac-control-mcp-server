# Mac Control MCP argument errors / Ошибки аргументов

FR-023 provides non-authorization guidance for all 106 frozen direct MCP
handlers and the custom_query / custom_command compatibility dispatcher.

## Response classes

- VALIDATION_ERROR: recognized bad argument shape or value. Error gives tool
  name, expected parameter names, bounded cause and existing diagnostic tools.
  The compatibility dispatcher retains TypeError for wrong signatures.
- TOOL_VALUE_ERROR: unclassified ValueError, potentially raised after a side
  effect. Inspect the local mclog audit and actual state before any retry.
- SSH_COMMAND_TOO_LONG / SSH_COMMAND_INVALID keep exact byte counts and
  remedies (ssh_write_text or ssh_upload then a short ssh_exec).
- PermissionError, authorization and policy denial are not rewritten and must
  not be bypassed. RuntimeError and dependency failures remain distinct.

Direct FastMCP calls missing typed parameters are rejected at the framework
schema boundary before entering the handler. Pydantic names the missing/
mistyped field; inspect the published tool schema and relevant capability tool.

## Alternatives

| Operation | Recovery |
| --- | --- |
| ssh_* | ssh_profile_inventory; large files via ssh_write_text / ssh_upload |
| terminal_* | terminal_capabilities, terminal_list |
| gui_* | gui_status, gui_windows |
| fs_* / git_* | project_roots, fs_stat, git_status |
| watcher_* | watcher_guide, watcher_status |
| chrome_* | chrome_chat_ui_status, chrome_orchestrator_status |
| mcp_* | mcp_targets, mcp_bridge_list |
| package_* | package_capabilities |

The guidance never copies raw parameter values, shell commands, credentials
or source exception bodies into the displayed error. The local owner-only
JSONL audit, specified by FR-021 v2, is separate and records bounded actual
input arguments. The old Mac Control service is untouched.

## FR-025: exact semantic validation contracts (candidate)

The offline source inventory is in TOOL_ARGUMENT_AUDIT_FR025.md in Git
(not shipped as a runtime diagnostics endpoint). It covers all 133
registered MCP tools, including 27 optional/maintenance tools and shared
validator modules. Source raise-site counts are not all caller errors.

| Tool | Actionable response |
| --- | --- |
| terminal_exec | TERMINAL_COMMAND_INVALID for empty/NUL/non-string; TERMINAL_COMMAND_TOO_LONG with actual characters and 8000-character limit. For generated source use fs_write(project, path, content), then short terminal_exec. |
| terminal_send | TERMINAL_TEXT_TOO_LONG: 4000-character limit; TERMINAL_TEXT_INVALID, TERMINAL_KEY_INVALID (supported key names), TERMINAL_SEND_EMPTY. Session IDs via terminal_list. |
| terminal_read/send/close | TERMINAL_SESSION_INVALID requires mc- plus 16 lowercase hex; TERMINAL_SESSION_NOT_FOUND means expired/absent, inspect terminal_list. |
| watcher_* | WATCHER_ID_INVALID: 2–56 lowercase letters/digits/underscore/hyphen, starting lowercase letter/digit. Inspect watcher_status and watcher_guide. |
| gui_mouse | GUI_MOUSE_ACTION_INVALID enumerates move/left_click/right_click/double_click/drag without contacting the helper. |
| git_create_branch | GIT_BRANCH_NAME_INVALID explains 1–80-character precheck; native Git can still reject other invalid refs. |
| background_browser_* | Structured INVALID_ARGUMENT includes exact input shape for session_token/client_request_id/session_tokens; ChatBridge config errors use CHATBRIDGE_CONFIGURATION_ERROR. Malformed provider replies use INVALID_PROVIDER_RESPONSE with an explicit no-automatic-retry warning. |

Do not treat a post-dispatch or uncertain error as proof of no side effects.
Structured API codes remain compatible with the previous browser adapter
where bad capabilities returned INVALID_ARGUMENT. Raw audit is owner-only.

## FR-025.1 — ChatGPT connected-tool link_id

link_id is selected by the ChatGPT connector, not by Mac Control's
ssh_exec, terminal_exec or custom_command handler. See
CHATGPT_LINK_ROUTING_DIAGNOSTICS.md for account-eligibility,
unexpected-field and safety-block troubleshooting; none is a reason
to retry a blocked SSH request via another tool.

## FR-025.3 — cross-tool path compatibility

The maintenance write_file and read_file accept both canonical
workspace/projects/... and the common workspace-relative projects/...
form. fs_write and fs_read retain project=workspace + path=projects/...
schemas. No migration of unrelated approved project roots and no
privilege widening. A missing or ambiguous workspace path returns
WORKSPACE_PATH_FORMAT_INVALID before dispatch; true policy/permission
denials are not rewritten or retried via alternate tools.

See TOOL_ARGUMENT_COMPATIBILITY_FR025.md for the overlap matrix,
explicit A08 examples and validation vs policy boundary.


## FR-025.4 — hidden paths are readable (owner-approved)

Read-only fs and maintenance tools expose hidden files and directories inside
approved project roots. A hidden name alone is no longer a PermissionError.
For mutation tools, sensitive/hidden name denial remains unchanged.
Root containment, relative fs paths, symlink and traversal checks remain.
Do not treat read permission as authorization to write or to bypass an
upstream tool/platform block.
