# GitHub OAuth setup for each Mac Control Mac Control MCP Server installation

Mac Control Mac Control MCP Server uses GitHub **OAuth Apps** and FastMCP OAuthProxy, matching
the existing Stable architecture. It does not require access to repositories.
The user registers their own app, which has its own client ID and client
secret. No shared secret is included in public releases.

## Prerequisite: a public HTTPS origin

First establish a reachable HTTPS hostname, using Tailscale Funnel, a
reverse proxy or another owner-approved approach. The GitHub callback must
match the host exactly. No localhost callback works for an external MCP client.

## Step-by-step onboarding

From a verified Mac Control MCP Server checkout, first install the software. Then run:

    python3 scripts/install_mac_control.py --github-oauth-guide --public-url https://YOUR-HTTPS-HOST

The installer prints a prefilled application name, homepage URL, exact
callback URL and the GitHub registration link:

    https://github.com/settings/applications/new

1. Sign in to GitHub with the account that owns the Mac.
2. Open Developer settings > OAuth Apps > New OAuth App (not GitHub Apps).
3. Fill in the displayed application name, homepage and callback URL.
4. Register the application; copy Client ID and generate a Client Secret.
5. On the same Mac, run:

    python3 scripts/install_mac_control.py --setup-github-oauth --public-url https://YOUR-HTTPS-HOST

If GitHub CLI isn't authenticated, supply --github-login YOUR_USERNAME.
The wizard resolves your numeric GitHub ID, confirms that you approve it,
asks for the Client ID and obtains the secret using a hidden local terminal
prompt. Never paste Client Secret into an AI conversation or command line.

An owner-only file (0600) is created under:

    ~/MacControlMCP/data/remote_auth.json

Containing the client ID, client secret, numeric authorized owner ID,
public URL and randomly generated JWT signing key. Existing secrets are
never silently overwritten. This process does not start the remote server.

Check configuration without exposing credentials:

    python3 scripts/install_mac_control.py --github-oauth-check

## Complete the OAuth sign-in

Start the separate Mac Control MCP Server loopback remote endpoint:

    ~/Library/Application\ Support/MacControl/MCPServer/current/bin/mac-control-remote-mcp.sh

After exposing it via your chosen public HTTPS tunnel, check OAuth
discovery and anonymous HTTP 401 behavior:

    python3 scripts/install_mac_control.py --github-oauth-probe

The installer can also launch an actual interactive browser OAuth login
and call the harmless system_info MCP tool through the public HTTPS URL:

    python3 scripts/install_mac_control.py --github-oauth-login-test

This explicitly opens a browser for GitHub consent, completes the standard
OAuth callback to the local test client and confirms authenticated MCP access.
It does not run arbitrary Mac commands and never prints OAuth credentials.

You may also add https://YOUR-HTTPS-HOST/mcp to another OAuth-capable MCP client.
The client opens GitHub's OAuth consent page; sign in as the authorized
account, complete consent and verify system_info and a disposable write.
Confirm another GitHub account is denied. The installer cannot claim real
sign-in verification before this user-controlled browser OAuth flow happens.

The minimum requested scope is read:user, not repository access. Remember
that successful login grants the authorized agent the configured Mac Control
capabilities. It is not equivalent to permission for every GitHub account.

## Validation and update policy

Changing the OAuth App, hostname, signing key or allowed ID requires an
explicit owner-driven credential rotation. The wizard refuses to overwrite
remote_auth.json and does not modify existing Stable or DEV configuration.
Client secrets should be revoked in GitHub if ever leaked.

Reference: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app