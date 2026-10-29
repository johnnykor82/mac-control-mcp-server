[**English**](README.md) · [Русский](README.ru.md)

# Mac Control MCP Server

**Full macOS access for owner-authorized AI agents.** Files, terminal, Git, SSH, native GUI, background browser operations through ChatBridge, and remote MCP.

Mac Control MCP Server is an experimental Model Context Protocol (MCP) server designed for autonomous tasks. It offers powerful control of the owner's Mac, not a restrictive sandbox.

> **Beta preparation.** Local tests pass, including a working ChatBridge browser adapter. An independent clean-Mac installation and real public OAuth login still require acceptance tests. This is not a production-certified release.




## Capabilities

- **Files, terminal and Git:** manage projects, shell commands, services, processes and approved SSH targets.
- **Native macOS GUI:** optional separate signed helper using Accessibility and Screen Recording permissions, with background window operations where supported.
- **Browser through ChatBridge:** navigate, click, fill forms, inspect the DOM and take screenshots using ChatBridge HTTP; Mac Control never owns Chrome.
- **Agent workspace:** store generated projects, tests, downloads, logs and artifacts under one default working directory.
- **Experimental remote access:** each owner configures a GitHub OAuth App and optionally publishes the authenticated MCP endpoint using Tailscale Funnel.

## ChatBridge is independent

**ChatBridge is a separate application and repository.** It exposes an authorized ChatGPT web session and browser automation through HTTP. It works without Mac Control.

The standard Mac Control installer reuses a compatible ChatBridge service or
installs ChatBridge's independent, checksum-pinned `v0.2.0-beta.6` release.
ChatBridge owns its Chrome profile, LaunchAgent and data; uninstalling Mac Control
preserves ChatBridge. Use `--without-chatbridge` for standalone filesystem,
terminal, Git and GUI use; on update this skips setup and preserves existing
browser configuration.

**ChatBridge source:** [johnnykor82/chatbridge](https://github.com/johnnykor82/chatbridge).
Use a reviewed published release of ChatBridge.

## Installation (macOS)

Requires macOS, Python 3.9+ for bootstrap, Google Chrome and a compatible MCP client. The installer provisions isolated Python 3.13 using [uv](https://docs.astral.sh/uv/). Review the source first.

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
installer offers the official standalone installation without Homebrew, with your consent; Python 3.9+ bootstraps the
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

After a new installation, wait until `curl http://127.0.0.1:8787/v1/system/status`
reports `browser.mode=managed` and `browser.state=running`. Then manually sign in
using the **default profile only**:

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir="$HOME/.chatbridge/chrome-profile" --new-window https://chatgpt.com/
```

For custom profile locations follow ChatBridge's instructions. Installation does
not leave a login window open or verify a real ChatGPT login. If Mac Control
fails later, ChatBridge remains installed independently; rerunning reuses its
working compatible API. The dependency setup timeout is 30 minutes; after timeout
inspect ChatBridge status before retrying.

Optional native GUI:

```sh
python3 scripts/install_mac_control.py --update --with-gui
```

The owner grants Accessibility and Screen Recording permissions in macOS Settings. The installer supports `--update`, `--rollback` and `--uninstall` while preserving user data. Configure your MCP client to run the installed `bin/mac-control-stdio-mcp.sh` launcher.

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

## GitHub OAuth + Tailscale Funnel

Each owner creates a personal GitHub OAuth App. The wizard shows the callback URL, privately collects the Client Secret, generates a signing key and restricts authorized users by numeric GitHub account ID.

```sh
python3 scripts/install_mac_control.py --network-diagnose
python3 scripts/install_mac_control.py --network-guide
python3 scripts/install_mac_control.py --github-oauth-guide --public-url https://YOUR-DEVICE.ts.net
python3 scripts/install_mac_control.py --setup-github-oauth --public-url https://YOUR-DEVICE.ts.net
python3 scripts/install_mac_control.py --github-oauth-check
```

The owner explicitly approves Funnel after the authenticated local endpoint passes an anonymous HTTP 401 check. The installer does not modify VPN routes, WireGuard or Exit Node.

See [OAuth setup](docs/GITHUB_OAUTH_SETUP.md), [network setup](docs/REMOTE_ACCESS_GUIDE.md) and [agent install guide](AGENT_INSTALL.md).

## Security, status and license

An agent authorized to use shell, GUI and network tools can delete or disclose data and make consequential changes. It is not isolated by a security sandbox. See [SECURITY.md](SECURITY.md). ChatBridge is unofficial and depends on a changing web UI, not the official OpenAI API.

**License: MIT.** Copyright © 2026 Ivan Konstantinov. See [LICENSE](LICENSE). A final source-provenance review and independent acceptance test remain prerequisites for public publication. See [release gates](docs/PUBLIC_RELEASE_GATES.md).
