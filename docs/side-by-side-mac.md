# Future installed runtime: code/data separation

The isolated H1 package uses `mac_control.runtime_paths.DATA_ROOT` as the
owner-specific **Dev** runtime data root:

`~/Library/Application Support/MacControl/MCP-Dev`

This directory is distinct from the Python installation tree, the existing
production `~/chatgpt-mcp` root and the Chrome profile directory
`~/Library/Application Support/MacControl/ChromeProfiles`.
Importing the package does **not** create the directory.

The frozen handlers that previously resolved their configuration, runtime,
backups or scripts from `__file__` now point to this data root.
Legacy Chrome/Watcher private handlers remain **not exposed** in the new
core: their scripts, profile and lifecycle require separate packaging work.

The installer must later provision this directory, migrate or initialize
configuration under explicit user-approved steps, and arrange the existing
ChatGPT OAuth/authorization connector. No credentials, production settings
or profile data were copied during this development task.

The live Dev HTTP preview is read-only. A separate stdio subprocess,
started through the approved Stable MCP bridge, exposes only existing
Dev-scoped filesystem/Git mutations. Most other handlers remain disabled
pending integration testing. There is no independent consent UI.

## Reproducible developer bundle

`python3 -P -B scripts/build_dev_bundle.py` creates
`dist/mac-control-h1-dev.zip` offline with a SHA256 inventory. Only package
source, compatibility contract, minimal developer shell check and documentation
are included; no production configs, credentials, logs, browser profiles or
backups. This archive is **not an installer**, contains untested legacy
operations and must not be installed as a service or distributed as a release.


## Isolated Dev terminal operations — 2026-10-20

After GUI regression verification, a subset of the **original** Mac Control
terminal operations was enabled in local stdio only: `terminal_exec`,
`terminal_open`, `terminal_send`, `terminal_resize`, `terminal_close`
plus `terminal_read` and `terminal_list`. These are not wrappers and
were already included in the original 95-operation contract.

Owner-only Dev configuration:
`~/Library/Application Support/MacControl/MCP-Dev/terminal_policy.json`
is mode 0600 with `{"enabled": true}`. The old Stable configuration and
terminal socket remain untouched. Dev tmux exclusively uses:
`~/Library/Application Support/MacControl/MCP-Dev/run/tmux.sock`.

Real invocation through **Stable `mcp_bridge_call`**:

- `terminal_exec` ran `printf 'DEV_TERMINAL_BRIDGE_OK\n'; pwd`
  with exit_code 0 and returned the Dev workspace path.
- `terminal_open` created an isolated tmux session.
- `terminal_send` ran a harmless `printf` inside it.
- `terminal_read` showed the expected output.
- `terminal_resize` succeeded, `terminal_list` showed only Dev sessions,
  and `terminal_close` terminated the test session.

The HTTP target stays restricted to 20 read-only tools. The local stdio
target presents 49 existing operations: 28 read-only and 21 write-capable.

**Security limitation:** project-root choice is only a working-directory
selection; Dev terminal is **not an OS sandbox**. It runs as the same Mac
service user. ChatGPT's own tool approvals and platform security controls
govern MCP command requests; this implementation adds no separate approvals.
Avoid exposing the local stdio target on a public endpoint.

No network Git operations, SSH execution, package installation, watcher
management or production migration have been enabled in Dev.


## Existing downstream MCP bridge integrated in Dev — 2026-10-20

Three original operations `mcp_bridge_list`, `mcp_bridge_read` and
`mcp_bridge_call` are available through Dev's local stdio only. No new
MCP commands were invented. Dev reads only its owner-only
`~/Library/Application Support/MacControl/MCP-Dev/mcp_targets.json`,
which currently has **no configured downstream targets** and does not
inherit any of Stable's connector tokens, target lists or credentials.

Self-connection protection in Dev now rejects both Mac Control MCP ports
3000 and 3101. A disposable stdio MCP target was used for an isolated test:
tool discovery returned one read and one write operation; a read-only call
succeeded; trying the write through read-only bridge was denied; an explicitly
write-capable downstream call created only a disposable fixture file. FastMCP
v4 property deprecation warnings were also removed in Dev code.

Dev stays on port 3101 for 20 read-only tools, and supports 49 existing
operations (28 read, 21 write) through the owner-local stdio bridge.

See `docs/bridge-gate.md`.

## Approved Stable media upgrade (2026-10-20)

Supersedes earlier claims that Stable source is untouched. With explicit
owner permission Stable Python bridge and dispatcher were changed and the
Python service restarted; GUI, OAuth, Watcher, TCC and tool names remain
unchanged. Dev was then synchronized. See docs/media-transport-gate.md.
