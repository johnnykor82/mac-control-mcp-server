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

Mac Control works without ChatBridge for local filesystem, terminal, Git and native GUI operations. To enable browser features, first install ChatBridge independently, then configure Mac Control to use its API. For a fresh installation, the agent clones the separately published ChatBridge
release into `workspace/projects/chatbridge`; the Mac Control installer may
invoke **ChatBridge's own installer** from that verified checkout. ChatBridge
is not bundled into Mac Control's source or removed with Mac Control.

**ChatBridge source:** [johnnykor82/chatbridge](https://github.com/johnnykor82/chatbridge).
Use a reviewed published release of ChatBridge.

## Installation (macOS)

Requires macOS, Python 3.13 provisioning with [uv](https://docs.astral.sh/uv/) and a compatible MCP client. Review the source first.

```sh
git clone https://github.com/johnnykor82/mac-control-mcp-server.git
cd mac-control-mcp-server
python3 scripts/release_preflight.py --json
python3 scripts/release_audit.py --strict
python3 scripts/install_mac_control.py --plan
python3 scripts/install_mac_control.py --install
python3 scripts/install_mac_control.py --status
```

Connect an already running compatible ChatBridge:

```sh
python3 scripts/install_mac_control.py --update --with-chatbridge
```

Or install it from a separately reviewed ChatBridge release checkout:

```sh
python3 scripts/install_mac_control.py --update --with-chatbridge \
  --chatbridge-source "$HOME/Library/Application Support/MacControl/MCPServer/data/workspace/projects/chatbridge"
```

The default ChatBridge origin is `http://127.0.0.1:8787`. For another local
port add `--chatbridge-url http://127.0.0.1:PORT` to either command.
ChatBridge needs no API key by default. If its owner enables `CHATBRIDGE_API_KEY`,
set the matching `MACCONTROL_CHATBRIDGE_API_KEY` in the install and MCP client
process environments; never paste the key into chat or command arguments.

ChatBridge uses its own installer, profile, LaunchAgent and data directory.
The dependency version must come from ChatBridge's published release; never
download and execute an unverified arbitrary repository.

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
