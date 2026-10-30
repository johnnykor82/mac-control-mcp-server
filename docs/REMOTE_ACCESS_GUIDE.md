# Experimental standalone remote OAuth (not yet a certified public installation)

This mode does not use the owner's existing Stable MCP bridge. It has a
write-capable tool catalogue behind FastMCP's GitHub OAuth proxy. The service
listens **only on 127.0.0.1:3201**; a user-managed HTTPS reverse tunnel can
make it reachable by an external MCP client.

Tested so far: OAuth config validation, owner-only file permissions, full
FastMCP tool registration and unauthenticated ASGI requests returning HTTP
401 with an auth challenge. A real GitHub OAuth login, external tunnel
verification and end-to-end authorized remote write are still OPEN gates.

## Local installation

From a reviewed repository checkout, after a successful preflight:

    python3 scripts/install_mac_control.py --plan
    python3 scripts/install_mac_control.py --install --with-chatbridge
    python3 scripts/install_mac_control.py --status

The local installer deploys a versioned Python 3.13 environment with pinned
dependencies, switches a private MCPServer/current symlink only after the
smoke test succeeds, and keeps older releases for rollback. Browser access
is provided by an independently installed ChatBridge, never a separate
Mac Control Chrome instance. Existing Stable
and MCP-Dev services are not changed. Native background GUI support needs
its own signed TCC helper and is not covered by this command.

To enable browser tools after ChatBridge Browser API v1 is available, run
the installer with --with-chatbridge. This checks the upstream capabilities
endpoint, then enables HTTP proxy tools; it never downloads Chromium.

## Prepare GitHub OAuth

Use the guided installer rather than manually editing credentials. See
[GITHUB_OAUTH_SETUP.md](GITHUB_OAUTH_SETUP.md) for the complete workflow:

    python3 scripts/install_mac_control.py --github-oauth-guide --public-url https://YOUR-HTTPS-HOST
    python3 scripts/install_mac_control.py --setup-github-oauth --public-url https://YOUR-HTTPS-HOST
    python3 scripts/install_mac_control.py --github-oauth-check

After remote HTTPS is reachable and authenticated MCP is running:

    python3 scripts/install_mac_control.py --github-oauth-probe

The probe checks anonymous denial and discovery; full GitHub sign-in must
still be completed by the owner's OAuth-capable MCP client.

The manual configuration below is reference material, not the default path.


1. Set up an OAuth App under your own GitHub account.
2. Set **Authorization callback URL** to
   https://YOUR-HTTPS-HOST/auth/callback (default FastMCP OAuthProxy path).
3. Choose your final public HTTPS hostname before configuring the app.
4. Obtain the **numeric** GitHub user ID(s) authorized to use this Mac.
5. Generate a strong signing key locally and keep it private.
6. Create the file below under
   ~/MacControlMCP/data/remote_auth.json
   with owner-only permissions (0600). Do not put this file in Git.

Example JSON **with deliberately invalid placeholder values**:

```json
{
  "github_client_id": "SET_YOUR_GITHUB_OAUTH_CLIENT_ID",
  "github_client_secret": "SET_YOUR_GITHUB_OAUTH_CLIENT_SECRET",
  "github_allowed_ids": ["12345678"],
  "public_url": "https://YOUR-HTTPS-HOST",
  "jwt_signing_key": "REPLACE_WITH_A_LONG_RANDOM_SECRET_FROM_YOUR_MAC"
}
```

Do not send OAuth secrets, signing keys or session credentials to the agent
through chat. Use local Terminal or a credential manager. Use
chmod 600 on the JSON file.

## Start the local authenticated endpoint

    ~/Library/Application\ Support/MacControl/MCPServer/current/bin/mac-control-remote-mcp.sh

A launchd service can be added after testing on a clean machine; the current
script is foreground-only. It never listens on all interfaces by default.

The remote HTTP MCP path is /mcp. Auth metadata and callback routes must
remain reachable through the HTTPS tunnel. Check service logs locally.

## No public IP: Tailscale Funnel

Mac Control's guided remote deployment uses Tailscale Funnel exclusively.
It does not require a routable inbound public IP or router port forwarding.

    python3 scripts/install_mac_control.py --network-diagnose
    python3 scripts/install_mac_control.py --network-guide

Re-use Tailscale if already installed. Both Standalone and App Store
macOS client variants can publish local HTTP ports through Funnel.
If the `tailscale` CLI is absent from PATH, the installer uses
`/Applications/Tailscale.app/Contents/MacOS/Tailscale` with
`TAILSCALE_BE_CLI=1`. It does not silently install a second client,
change VPN routes, modify a selected Exit Node, or interfere with WireGuard.

On a new computer, install the official Tailscale macOS client,
authorize the user and obtain its `*.ts.net` HTTPS name. Register the
GitHub OAuth App with that hostname and the exact callback
`https://HOST.ts.net/auth/callback`.

After configuring OAuth, start authenticated MCP on
`127.0.0.1:3201` and confirm anonymous MCP requests receive HTTP
401 with an authorization challenge. Only then offer Funnel:

    python3 scripts/install_mac_control.py --enable-funnel

This command requires the owner to type PUBLISH. If Funnel already has
other published routes, the installer refuses to replace them
automatically. It never exposes the unauthenticated DEV preview port.

Finally verify the public HTTPS URL from an external client and
complete real GitHub OAuth login. Tailscale Serve is tailnet-only,
not the public Funnel used for remote MCP.
