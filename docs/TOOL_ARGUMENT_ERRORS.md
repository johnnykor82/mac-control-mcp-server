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
