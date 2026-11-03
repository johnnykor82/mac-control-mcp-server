# FR-025.3 — compatibility matrix for Mac Control MCP arguments

Version 1.1 / 2026-11-03. See the 133-operation regenerated inventory
in TOOL_ARGUMENT_AUDIT_FR025.md for the complete names, required fields
and counts. The 106 frozen direct tool contracts must stay unchanged.
The distinct signatures below are intentional: do not guess parameter
names based on a similarly named operation.

## Known overlapping tool families

| Purpose | Tool | Required parameters | Optional | Workspace path contract |
| --- | --- | --- | --- | --- |
| Write one file | write_file | path, content | expected_sha256 | workspace/projects/x OR projects/x |
| Write one file | fs_write | project, path, content | expected_sha256 | project=workspace AND path=projects/x |
| Read one file | read_file | path | none | workspace/projects/x OR projects/x |
| Read numbered lines | fs_read | project, path | start_line, max_lines | project=workspace AND path=projects/x |
| List workspace | list_workspace | none | path, limit | workspace/ prefix or accepted relative subfolder |
| List approved root | fs_list | none | project, path, limit | project=workspace, relative path |
| Dispatch legacy operation | custom_command | operation | arguments | operation=fs_write, arguments object with project and path |
| Inspect legacy operation | custom_query | none | operation, arguments | consult actual returned operation signature |
| Run local command | terminal_exec | command | project, timeout_seconds | project=workspace is execution workspace; NOT file path |
| Run remote SSH command | ssh_exec | host, command | timeout_seconds | host is SSH alias; NOT local project/path |

Compatibility applies **only** to known workspace subfolders:
projects/, scratch/, artifacts/, downloads/, shared/. A leading
workspace/ prefix remains canonical for maintenance write_file/read_file.
The legacy fs_write(project=workspace, path=projects/...) call is unchanged.

Example of the previously rejected Android audit path:
- write_file(path="projects/android-license-audit/reports/INITIAL_AUDIT.md",
  content="...") now resolves within the approved workspace root.
- Equivalent canonical maintenance spelling:
  write_file(path="workspace/projects/android-license-audit/reports/INITIAL_AUDIT.md",
  content="...").
- Equivalent legacy spelling:
  fs_write(project="workspace",
  path="projects/android-license-audit/reports/INITIAL_AUDIT.md",
  content="...").

**Existing file writes** require expected_sha256 of the current file,
and always use the original atomic write and backup protections. Successful
writes of new files do not need expected_sha256. read_file is text-only;
fs_read offers line ranges. write_file has 256 KiB content limit, fs_write
has 512 KiB; the higher limit must not be silently borrowed.

## Invalid inputs and safety

- WORKSPACE_PATH_FORMAT_INVALID means a *preflight value format error*
  for maintenance read/write. It gives both correct signatures without
  printing the rejected value. A safe corrected path may be resubmitted
  only with the user's existing authorization for the operation.
- Absolute write paths, traversal, hidden/sensitive paths, symlinks,
  outside-workspace roots and ownership failures remain denied. **Never**
  switch tool, rename command or change path to bypass a permission,
  provider or platform safety block.
- A value error after dispatch may have changed state. Inspect
  mclog, fs_stat and actual files before considering a retry.
- Account link_id is an outer ChatGPT routing field, not an argument
  to ssh_exec/terminal_exec/custom_command. Failures at that boundary
  cannot be cured by a maintenance compatibility alias.
- A cached/frozen ChatGPT tool snapshot may differ from the live MCP
  signature; refresh tool definitions in ChatGPT when supported, not
  by inventing tool arguments.

## Reproducible audit and acceptance

- python scripts/audit_tool_argument_contracts.py --format markdown
  renders the full frozen+additional registry and static error inventory.
- tests/integration/test_tool_argument_contract_inventory.py compares
  the generated report against the committed report and all 133 schemas.
- tests/integration/test_tool_schema_fr025.py verifies required fields,
  rejected extra fields and JSON schemas without executing operations.
- tests/integration/test_maintenance_ops.py exercises the exact A08 path
  in isolated workspace fixtures, canonical path, cross-tool content,
  SHA256 CAS, backup and rejected outside/symlink/traversal paths.
