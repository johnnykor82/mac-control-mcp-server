# Mac Control MCP Server — installation contents and ownership

Release candidate scope, 2026-10-27. This is **not** a publication claim.
The portable second Mac is the intended independent acceptance-test host.

## Automatically installed by the core installer

| Component | Destination | Status |
| --- | --- | --- |
| Pinned Python 3.13 runtime and dependencies | MCPServer/releases/<version>/.venv | Tested on developer's Mac |
| Mac Control MCP local stdio server, tools and library | MCPServer/releases/<version> | Tested |
| MCPServer/current and previous pointers | Mac Control MCP Server root | Tested update/rollback |
| Agent workspace | MCPServer/data/workspace | Created at install |
| Workspace subdirectories: projects, scratch, scratch/tmp, artifacts, downloads, logs | MCPServer/data/workspace | Created at install |
| mclog read-only terminal audit viewer and launcher | releases/<version>/scripts/mclog.py and bin/mclog | Tested |
| Owner-only metadata audit JSONL (7 daily backups) | MCPServer/data/logs/audit.jsonl* | Tested |
| MCP server instructions and workspace_policy tool | MCP initialization/tool catalogue | Source and test verified |
| Shell temp/cache defaults inside workspace | terminal environment | Source and test verified |
| Owner data/configuration and recoverable backups | MCPServer/data | Preserved on uninstall |
| Installer lifecycle: plan/install/setup/update/rollback/status/uninstall | install_mac_control.py | Test-verified |
| Read-only public IP and transport capability diagnosis | setup_network.py | Tests; not external connectivity proof |
| Owner-guided GitHub OAuth App creation and authorization checks | setup_github_oauth.py / test_github_oauth_login.py | Unit-tested, public E2E pending |
| Tailscale Funnel guide and explicitly authorized enable action | setup_network.py | Guarded tests, external validation pending |
| Default signed native GUI helper | ~/Applications/MacControlMCPServer.app | Install if absent, reuse verified owner-managed app; TCC owner approval required |
| Interactive connection wizard | guided_setup.py | TCC, network selection, OAuth, service and public checks; ChatGPT manual |
| Remote MCP owner login autostart | ~/Library/LaunchAgents/org.maccontrol.mcpserver.remote.plist | Configured after OAuth by setup; live remote E2E pending |
| Smoke test for installed MCP file ops and optional browser | mac_control_smoke.py | Tested |

The installer copies only files listed in `scripts/install_manifest.txt`; local
untracked files and symlinks are excluded or rejected.

The package does **not** copy the developer's private source tree or
active user credentials by design. The MIT LICENSE has been added; a final
public source export and provenance review remain prerequisites.

## Optional installation or external prerequisite

| Component | Scope / owner action |
| --- | --- |
| GUI permissions and build tools | Apple Command Line Tools for Swift/clipboard compilation; if absent run xcode-select --install and approve Apple installation manually. Setup starts the helper and requests TCC; owner grants Accessibility/Screen Recording. |
| ChatBridge HTTP Browser API | **Independent external product**. Default setup reuses a compatible service or installs the checksum-pinned published release using ChatBridge's own installer. --without-chatbridge skips setup; --chatbridge-source selects owner-reviewed sources. ChatBridge is not bundled or removed by Mac Control. |
| GitHub OAuth App | Owner creates an app in own GitHub Developer settings; enters Client Secret privately in local Terminal |
| Public HTTPS route | Direct public domain with trusted TLS and TCP 443 reverse proxy to 127.0.0.1:3201, or Tailscale Funnel without public IP. Owner configures direct DNS/TLS/proxy/router and verifies inbound HTTPS. Never expose port 3201 externally. |
| Tailscale GUI app, account and MagicDNS/Funnel approval | External; reuse an existing App Store or Standalone install, leave VPN/Exit Node unchanged |
| Watcher, downstream SSH and other adapters | Owner-specific integration; not assumed to be installed in a clean Mac Control MCP Server environment |

## Interactive setup and owner responsibilities

Default `--install` installs/reuses the GUI helper, then runs interactive setup:
TCC request and status checks, public-IP question, direct HTTPS or Tailscale,
GitHub OAuth, owner-scoped remote MCP LaunchAgent, local 401/issuer checks,
explicit Funnel `PUBLISH` when needed, and public discovery/authentication probe.
The owner manually adds the server in ChatGPT and completes OAuth. Public probes
do not establish real OAuth or ChatGPT E2E; those release checks remain pending.

`--update` reuses the verified app without replacement; `--with-gui` explicitly
rebuilds it and can require new TCC approval. `--without-gui` skips a new app and
the wizard TCC step; an already enabled GUI is preserved and its clipboard
helper is provisioned in the active release. Unknown apps are not overwritten.
`--setup` resumes pending setup; after `--without-gui`, use `--setup --without-gui`. Noninteractive installation reports
`pending_owner_interaction`; it does not silently grant permissions or publish.

Setup configures remote MCP autostart for the logged-in owner, not a system
service before login. It does not install Tailscale automatically, grant TCC,
create GitHub OAuth Apps on behalf of the owner, complete account logins,
configure a direct HTTPS proxy or router, or verify inbound reachability from
an IP echo. Direct access needs a domain and trusted TLS on external TCP 443;
MCP stays bound to loopback 3201. Check HTTPS from another network.
Tailscale routes and the user's VPN/Exit Node selection remain unchanged.

## Default folder layout

```text
~/Library/Application Support/MacControl/MCPServer/
├── current -> releases/<version>
├── previous -> releases/<older-version>
├── releases/
│   └── <version>/
│       ├── .venv/
│       ├── src/
│       ├── scripts/
│       ├── bin/
│       └── requirements/
└── data/
    ├── workspace/
    │   ├── projects/
    │   ├── scratch/tmp/
    │   ├── artifacts/
    │   ├── downloads/
    │   └── logs/
    ├── backups/
    ├── run/
    └── remote_auth.json        # created only after user-guided setup
```

**Policy:** ordinary agent-written content stays in workspace. OS-required
service configuration and explicitly owner-authorized destinations are
exceptions, not a sign of failure. This is an agent convention, not a
kernel-enforced sandbox.

## Second Mac acceptance

Perform an independent installation on the owner's portable Mac, with a
fresh repository checkout, separate account and a genuinely unrelated
data directory. Test local stdio, filesystem, terminal opt-in, native GUI
permissions, external GitHub OAuth, ChatBridge integration when ChatBridge
is present and a tunnel that does not disrupt the user's existing VPN.
Keep the primary server Mac's Stable/DEV and ChatBridge unchanged.
