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
- Absolute write paths, traversal, symlinks and outside-root paths,
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


## FR-025.4 — full hidden-file READ (2026-11-03)

With explicit owner approval, all *read-only* filesystem operations (`fs_read`,
`fs_list`, `fs_stat`, `fs_search`, maintenance `read_file`, `list_workspace`)
expose hidden names under existing approved project roots, including `.planning`,
`.git`, `.venv`, `.env`, `.ssh` and other dotfiles. Do not assume a hidden name
implies denied reading. This does not grant access outside approved roots or
permit traversal or symlink following. Existing size and text-only limits apply.

**Write permissions did not expand**: `fs_write`, `fs_replace`, `fs_move`,
`fs_trash`, `fs_restore`, `fs_mkdir`, and maintenance `write_file` still
reject protected/hidden targets; CAS hashes and automatic backups remain.
Platform/provider authorization failures never trigger alternate-tool retries.
Regression suite: `tests/integration/test_hidden_read_fr025.py`.


## FR-027 — full hidden file and directory CRUD (2026-11-03)

FR-025.4's read-only hidden-name permission was superseded by the owner's
explicit FR-027 authorization. Every existing filesystem mutation tool now
accepts dotfile and hidden-directory names inside a preapproved project root,
including `.gitignore`, `.planning`, `.git`, `.env` and `.ssh`. The maintenance
`write_file` accepts both `workspace/projects/repo/.gitignore` and
`projects/repo/.gitignore`, plus root `.gitignore`.

`fs_mkdir` creates hidden directories; `fs_write` and `fs_replace` use
existing-file SHA256 CAS and backups; `fs_move` moves files or directories
without overwrite; `fs_trash` recoverably removes either. To delete a
directory, first call `fs_stat` and pass the returned `sha256` to `fs_trash`;
its directory hash covers names and metadata, not file contents. `fs_restore`
accepts the returned backup_id and refuses to overwrite an existing directory.
Directory trash/restore use atomic same-filesystem renames; cross-volume
rename errors leave the original in place. Files continue to use SHA256
content hashes and recoverable backup files. Directory listing and fingerprinting
are limited to 50,000 entries per operation.

Root boundaries, absolute-path / traversal rejection, no symlink traversal,
workspace ownership, size limits and existing-file hash checks remain.
`jkmac-mcp` is the ChatGPT connection name for the same published server when
installed on jkmac; updating that installation supplies this handler.


## FR-026 — pinned managed ChatBridge upgrade (2026-11-03)

The published ChatBridge beta.11 intentionally idled Chrome but did not
implement `POST /v1/browser/verify`. Newer beta.12 does. An explicit
Mac Control installer update first attempts the authenticated verify endpoint;
on 404 only, it invokes `POST /v1/browser/wake` once and then GET `/ready`
to confirm a live authenticated composer. Passive status never starts Chrome.
The managed dependency can be upgraded to the pinned beta.12 release with
SHA256 verification, existing LaunchAgent ownership checks, ChatBridge's own
upgrade and rollback, and retained prior installer source. No foreign
ChatBridge service is modified.
