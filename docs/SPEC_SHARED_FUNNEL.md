# Shared Tailscale Funnel on HTTPS 443 — specification

Status: approved by owner for implementation and offline testing. Production publication has not been authorized.

## Contract

- On a device with other Funnel HTTPS:443 handlers, Mac Control is mounted under a free, stable path, preferably `/maccontrol`, with external MCP URL `https://<hostname>/maccontrol/mcp`. Existing paths and root `/` remain unchanged.
- Fresh devices may retain root deployment where the Funnel is empty; previously installed devices retain their public URL and OAuth issuer on upgrade. Changing the URL is a separate, explicit migration.
- Tailscale `--set-path` strips its mount point before proxying. Each generated proxy target therefore contains the SAME mount path so that the backend receives its original public URL (see Tailscale ipn/ipnlocal/serve.go `serveWebHandler`). Mac Control serves `/maccontrol/mcp`, `/maccontrol/authorize`, `/maccontrol/token`, `/maccontrol/register`, `/maccontrol/auth/callback` and matching OAuth endpoints locally.
- OAuth authorization-server and protected-resource discovery require additional, narrowly scoped root-level paths such as `/.well-known/oauth-authorization-server/maccontrol` and `/.well-known/oauth-protected-resource/maccontrol/mcp`. Never claim `/` or a generic `/.well-known/` namespace owned by another service.
- Installer reads both `funnel status --json` and `serve status --json`, compares them without treating unrelated routes as conflicts, rejects unknown configurations, paths owned by other services and all unverified situations.
- Publication is opt-in and transactional. Before first mutation check authenticated loopback OAuth issuer and unauthorized MCP `401`; snapshot Tailscale state. For each route use `funnel --bg --yes --https=443 --set-path=<path> http://127.0.0.1:3201<path>`; verify old routes remain byte-for-byte equivalent. On failure, stop only routes added in this transaction, leaving unrelated routes untouched. Never `reset` or overwrite root.
- Existing own routes can be reused without changes. OAuth issuer, callback and resource URLs cannot change implicitly on `maccontrol update`.
- Tests: root compatibility; shared 10-handler config; OAuth issuer and discovery; path collision and shadow routes; idempotency; partial failures; dry-run/no mutating diagnostics; rollback and preserved user services.

## Current deployment

- Server: `macbook-pro-openclaw.tail4b3934.ts.net`, Funnel:443 has ten independently owned handlers, including `/` -> `127.0.0.1:3000` (existing Mac Control).
- New Mac Control backend: `127.0.0.1:3201`; proposed URL `https://macbook-pro-openclaw.tail4b3934.ts.net/maccontrol/mcp`.
- No live Tailscale route modifications until separate owner direction after tests and beta release.
