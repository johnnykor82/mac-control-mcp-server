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
| Installer lifecycle: plan/install/update/rollback/status/uninstall | install_mac_control.py | Test-verified |
| Read-only public IP and transport capability diagnosis | setup_network.py | Tests; not external connectivity proof |
| Owner-guided GitHub OAuth App creation and authorization checks | setup_github_oauth.py / test_github_oauth_login.py | Unit-tested, public E2E pending |
| Tailscale Funnel guide and explicitly authorized enable action | setup_network.py | Guarded tests, external validation pending |
| Smoke test for installed MCP file ops and optional browser | mac_control_smoke.py | Tested |

The installer copies only files listed in `scripts/install_manifest.txt`; local
untracked files and symlinks are excluded or rejected.

The package does **not** copy the developer's private source tree or
active user credentials by design. The MIT LICENSE has been added; a final
public source export and provenance review remain prerequisites.

## Optional installation or external prerequisite

| Component | Scope / owner action |
| --- | --- |
| Native GUI helper (.app) | Optional --with-gui; separately signed and installed under ~/Applications. Owner must approve Accessibility/Screen Recording in macOS Settings |
| ChatBridge HTTP Browser API | **Independent external product**. Default setup reuses a compatible service or installs the checksum-pinned published release using ChatBridge's own installer. --without-chatbridge skips setup; --chatbridge-source selects owner-reviewed sources. ChatBridge is not bundled or removed by Mac Control. |
| GitHub OAuth App | Owner creates an app in own GitHub Developer settings; enters Client Secret privately in local Terminal |
| Public HTTPS route | Tailscale Funnel to authenticated local port 3201; no public IP required |
| Tailscale GUI app, account and MagicDNS/Funnel approval | External; reuse an existing App Store or Standalone install, leave VPN/Exit Node unchanged |
| Watcher, downstream SSH and other adapters | Owner-specific integration; not assumed to be installed in a clean Mac Control MCP Server environment |

## Not part of current one-command automatic provisioning

The Mac Control MCP Server installer currently does **not** ensure persistent launchd
autostart of the remote server or Tailscale app, issue a public
release URL, register a GitHub OAuth App behind the owner's back, migrate
preexisting scattered files, download an unverified ChatBridge release
without owner selection, or grant macOS TCC permissions. The installation agent guides the owner
through these actions and verifies them when possible.

Tailscale Funnel is the supported guided remote access mechanism.
The installer never changes the user's VPN routing or Exit Node selection.

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
