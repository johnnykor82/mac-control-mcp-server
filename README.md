[**English**](README.md) · [Русский](README.ru.md)

# Mac Control MCP Server

**Full macOS access for owner-authorized AI agents.** Files, terminal, Git, SSH, native GUI, background browser operations through ChatBridge, and remote MCP.

Mac Control MCP Server is an experimental Model Context Protocol (MCP) server designed for autonomous tasks. It offers powerful control of the owner's Mac, not a restrictive sandbox.

> **Beta preparation.** Local tests pass, including a working ChatBridge browser adapter. An independent clean-Mac installation and real public OAuth login still require acceptance tests. This is not a production-certified release.




## Capabilities

- **Files, terminal and Git:** manage projects, shell commands, services, processes and approved SSH targets.
- **Native macOS GUI:** separate native helper installed by default using Accessibility and Screen Recording permissions, with background window operations where supported.
- **Browser through ChatBridge:** navigate, click, fill forms, inspect the DOM and take screenshots using ChatBridge HTTP; Mac Control never owns Chrome.
- **Agent workspace:** store generated projects, tests, downloads, logs and artifacts under one default working directory.
- **Experimental remote access:** each owner configures a GitHub OAuth App and optionally publishes the authenticated MCP endpoint using Tailscale Funnel.

## ChatBridge is independent

**ChatBridge is a separate application and repository.** It exposes an authorized ChatGPT web session and browser automation through HTTP. It works without Mac Control.

The standard Mac Control installer reuses a compatible ChatBridge service or
installs ChatBridge's independent, checksum-pinned `v0.2.0-beta.11` release.
ChatBridge owns its Chrome profile, LaunchAgent and data; uninstalling Mac Control
preserves ChatBridge. Use `--without-chatbridge` for standalone filesystem,
terminal, Git and GUI use; on update this skips setup and preserves existing
browser configuration.

**ChatBridge source:** [johnnykor82/chatbridge](https://github.com/johnnykor82/chatbridge).
Use a reviewed published release of ChatBridge.

## Installation (macOS)

Requires macOS, Python 3.9+ for bootstrap, Google Chrome and a compatible MCP client. Native helpers require macOS 14+ on Apple Silicon or Intel. The installer provisions isolated Python 3.13 using [uv](https://docs.astral.sh/uv/). Review the source first.

```sh
git clone https://github.com/johnnykor82/mac-control-mcp-server.git
cd mac-control-mcp-server
python3 scripts/release_preflight.py --json || [ "$?" -eq 2 ]
python3 scripts/release_audit.py --strict
python3 scripts/install_mac_control.py --plan
python3 scripts/install_mac_control.py --install
python3 scripts/install_mac_control.py --status
```

Run `--install` in Terminal. It checks the local ChatBridge API first. If absent,
it downloads the pinned release, checks SHA256 before extracting or executing,
and runs ChatBridge's own installer. Existing state, LaunchAgent, occupied port,
HTTP 401 or incompatible API stop setup for independent recovery; nothing is
silently overwritten. ChatBridge requires Google Chrome. If `uv` is absent, its
installer offers the official standalone installation without Homebrew, with your consent; if Astral is unavailable, it tries the official GitHub release. It selects uv for the Mac's architecture; Python 3.9+ bootstraps the
isolated Python 3.13 runtime. For standalone mode or a reused service without uv,
install [uv](https://docs.astral.sh/uv/getting-started/installation/) first.
Preflight reports missing uv until it is installed; this does not prevent the
default interactive ChatBridge bootstrap from offering it.

Default origin: `http://127.0.0.1:8787`; use `--chatbridge-url http://127.0.0.1:PORT`
for another local port. `--with-chatbridge` remains accepted; advanced owners can
provide `--chatbridge-source PATH` for a separately reviewed checkout.
No API key is required by default. If ChatBridge has `CHATBRIDGE_API_KEY`, set a
matching `MACCONTROL_CHATBRIDGE_API_KEY` in installer and MCP client environments.
Never paste keys into chat or command arguments.

After an interactive installation, ChatBridge checks the saved ChatGPT session
once the browser is ready. If it cannot confirm the session, it offers to open
the managed profile for a manual check. If you skip
the offer, first run `curl -fsS -X POST http://127.0.0.1:8787/v1/browser/wake`,
then wait until `curl http://127.0.0.1:8787/v1/system/status` reports
`browser.mode=managed` and `browser.state=running`, then open the **default profile only**:

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir="$HOME/.chatbridge/chrome-profile" --new-window https://chatgpt.com/
```

For custom profile locations follow ChatBridge's instructions. Opening a login
window does not verify a real ChatGPT login. If Mac Control
fails later, ChatBridge remains installed independently; rerunning reuses its
working compatible API. The dependency setup timeout is 30 minutes; after timeout
inspect ChatBridge status before retrying.

After five minutes without browser operations, ChatBridge stops its own Chrome;
the next browser operation starts it again. Profile data is preserved.
During idle, `/ready` returns HTTP 503 with `reason=browser_idle` without waking
Chrome. If API authentication is enabled, use an authenticated client for wake
and status checks.

Default `--install` installs the GUI helper under
`~/Applications/MacControlMCPServer.app`, or reuses the verified helper owned by
this installation. It downloads prebuilt universal GUI and Unicode clipboard
helpers from the pinned release and verifies SHA256 before extraction. Normal
installation does not compile helpers or require Apple Command Line Tools.
The binaries are ad hoc signed, without a Developer ID signature or Apple
notarization; the signature verifies integrity, not publisher identity.
Manual developer builds with `scripts/build_mac_control_gui.py` or
`scripts/package_gui_release.py` still require Apple developer tools and Swift.

After local installation, the interactive setup starts the helper and requests
missing Accessibility and Screen Recording permissions in order, checking each
grant before proceeding. A system popup is not guaranteed; use the Settings
instructions if it does not appear. Only the owner grants these macOS permissions.
It continues through public HTTPS selection, GitHub
OAuth, owner login autostart and public endpoint checks. The owner manually
adds the plugin in ChatGPT and completes real OAuth login. Noninteractive
installation reports `pending_owner_interaction`.

Resume setup in Terminal:

```sh
python3 scripts/install_mac_control.py --setup
```
Interactive installation and setup offer English or Russian and suggest the macOS language. Use `--language en` or `--language ru` to select explicitly. Third-party installer output may remain in its original language.


`--update` reuses the verified GUI app without replacing it, preserving its TCC
identity; it does not rerun the wizard. Resume with `--setup` as needed.
`--with-gui` explicitly replaces the verified owner-managed app from the pinned
prebuilt release and may require new TCC approval. `--without-gui` skips new GUI installation and
the wizard's TCC step; an already enabled GUI remains configured and its
clipboard helper is prepared in the new release. After choosing this option, resume with `--setup --without-gui`. Unknown apps are never
replaced. `--rollback` and `--uninstall` preserve user data. A local MCP client
runs the installed `bin/mac-control-stdio-mcp.sh` launcher.

## Dedicated agent workspace

Agent-created files, clones, temporary outputs, downloads and artifacts belong in:

`~/Library/Application Support/MacControl/MCPServer/data/workspace`

This is conveyed by MCP server instructions and the `workspace_policy` tool. Writing elsewhere requires an explicit owner instruction or necessary OS-specific service setup. **It is a behavioral convention, not an OS-enforced sandbox.**

See [workspace rules](AGENT_WORKSPACE_POLICY.md) and [installation contents](docs/INSTALL_CONTENTS.md).

## mclog — live audit monitor

**`mclog` ships with Mac Control MCP Server.** It is a read-only,
interactive terminal dashboard for MCP tool invocations: requests, errors,
running calls, average execution time, hourly activity and a scrollable
history. Press `e` to filter errors, arrows / Page Up / Page Down to
scroll, and `q` to exit.

After installing Mac Control, launch it from a separate terminal:

```sh
"$HOME/Library/Application Support/MacControl/MCPServer/current/bin/mclog"
```

The bundled executable automatically reads
`~/Library/Application Support/MacControl/MCPServer/data/logs/audit.jsonl*`.
Use `--log-dir PATH` to inspect another authorized audit directory.
For privacy, the public installer stores **tool names, times, statuses and
execution durations only**, not command arguments, file contents, responses
or credentials. The standalone viewer needs no connection to ChatBridge.
See [mclog usage](docs/MCLOG.md).

## GitHub OAuth and public HTTPS

The [ChatGPT setup guide](docs/CHATGPT_SETUP.ru.md) is available in Russian.

The `--setup` wizard requests TCC, checks network signals and asks whether the
owner has a public IP with incoming HTTPS. Direct access requires a domain,
trusted TLS certificate, external TCP 443 and an owner-configured reverse proxy
to `127.0.0.1:3201`. Never expose port 3201 externally. IP echo cannot prove
inbound reachability; verify HTTPS from another network. Without a known public
IP, the wizard offers Tailscale Funnel and reuses an existing client. The owner
completes login, macOS networking and tailnet approvals.

Once the final HTTPS origin is selected, the owner creates a personal GitHub
OAuth App and enters its Client Secret through hidden local input. The wizard
installs the owner-scoped `org.maccontrol.mcpserver.remote` LaunchAgent for
login autostart, starts authenticated MCP, and checks the local 401 and issuer.
Funnel requires separate `PUBLISH` confirmation and preserves unrelated
published routes. A public probe follows. VPN, WireGuard and Exit Node routing
are not changed.

A passing probe does not verify real OAuth or ChatGPT connectivity. Live
GitHub OAuth and ChatGPT E2E remain unverified release gates.
See [OAuth setup](docs/GITHUB_OAUTH_SETUP.md), [network setup](docs/REMOTE_ACCESS_GUIDE.md) and [agent instructions](AGENT_INSTALL.md).

## Security, status and license

An agent authorized to use shell, GUI and network tools can delete or disclose data and make consequential changes. It is not isolated by a security sandbox. See [SECURITY.md](SECURITY.md). ChatBridge is unofficial and depends on a changing web UI, not the official OpenAI API.

**License: MIT.** Copyright © 2026 Ivan Konstantinov. See [LICENSE](LICENSE). A final source-provenance review and independent acceptance test remain prerequisites for public publication. See [release gates](docs/PUBLIC_RELEASE_GATES.md).

## Watcher and maintenance tools (beta.16)

Default installation with ChatBridge now provisions Watcher and its user login
LaunchAgent `org.maccontrol.mcpserver.watcher`. It reuses the installed Mac Control
Python; ChatBridge is the sole browser owner. Watcher does not contact ChatGPT
while idle. Delivery requires signing in to ChatGPT in the ChatBridge profile.
New installations start with no projects, tasks or migrated credentials.

After connecting MCP, call `watcher_guide` and `watcher_status`. Use exact project
and executor chat URLs; the guide explains file reports, continuation in the same
chat, and scheduled checks. State remains under the private Mac Control data root.

```bash
# Existing standard installation
git pull --ff-only
python3 scripts/install_mac_control.py --update
# Read-only service check
python3 scripts/setup_watcher_service.py --status
```

`--without-watcher` skips provisioning and stops its owned service;
`--without-chatbridge` preserves existing configuration without provisioning Watcher.
Updates restart only owned services. Uninstall preserves state. Rolling back to
pre-beta.16 stops Watcher because that release has no runtime.

Maintenance tools include `audit_tail`, `audit_search`, `list_workspace`,
`process_snapshot`, `read_service_log`, `mcp_diagnostics`, `read_file`, `write_file`,
`restart_server`, `custom_query`, and `custom_command`. Dispatch is limited to
shipped operations; workspace Python is never dynamically imported. File aliases
are workspace-scoped; explicitly listed shipped sources are read-only. Replacing
files requires their current SHA256. Audit logs retain metadata only.

An older customized server requires a separate configuration migration. Never
publish its secrets, Watcher database or browser profiles.
