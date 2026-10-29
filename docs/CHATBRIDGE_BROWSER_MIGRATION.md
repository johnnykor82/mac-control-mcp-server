# Mac Control DEV → ChatBridge-only browser migration

**Owner decision, 2026-10-27:** ChatBridge is the only browser owner.
Mac Control DEV must not launch Chrome, connect to CDP, or operate Playwright.
Mac Control's native macOS Accessibility/ScreenCaptureKit backend remains
independent because it does not own a browser.

## Implementation state

- Legacy chrome_chat_* and chrome_orchestrator_* tools route via ChatBridge
  HTTP Sessions API (based on working Stable adapter; no direct CDP).
- background_browser_* now routes to the planned ChatBridge Browser API.
  MCP operation names and arguments are preserved for existing callers.
- Direct DEV browser worker, launch, soak and legacy provision scripts
  have been removed from this release branch. Their historical test
  evidence remains in dated documentation and Git history only.
- Mac Control MCP Server installer no longer provisions Playwright or Chromium.
  The optional browser feature flag means **ChatBridge integration**,
  not private browser ownership.
- The user-facing ChatBridge Browser API is not yet available on the
  locally running gateway (GET /v1/browser/capabilities returned HTTP 404
  on 2026-10-27). Therefore browser MCP calls in this release branch
  intentionally report CHATBRIDGE_API_MISSING instead of silently
  launching standalone Chrome.
- The private working Stable and existing installed DEV have not been
  switched to this release branch. Only the isolated Git worktree changed.

## Proposed ChatBridge Browser API v1

The final shape is subject to coordination with the ChatBridge developer.
It must be versioned and tested before promoting this release.

| MCP operation | ChatBridge HTTP operation |
| --- | --- |
| background_browser_create | POST /v1/browser/sessions |
| background_browser_action | POST /v1/browser/sessions/{id}/actions |
| background_browser_snapshot | GET /v1/browser/sessions/{id}/snapshot |
| background_browser_capture | GET /v1/browser/sessions/{id}/screenshot |
| background_browser_list | GET /v1/browser/sessions |
| background_browser_close | DELETE /v1/browser/sessions/{id} |
| background_browser_reopen | POST /v1/browser/sessions/{id}/reopen |

Session creation must return an opaque session capability in its result,
plus a stable session ID. Mac Control passes the **session ID** in the
URL and the full capability in the X-ChatBridge-Session-Capability header;
never leak a secret token through HTTP access logs or URL query strings.
The client may additionally authenticate via MACCONTROL_CHATBRIDGE_API_KEY.

GET /v1/browser/capabilities should report the supported operations,
actual background execution modes, response sizes, concurrency limits,
and API version. GET /v1/system/status is already implemented but does
not prove the new browser API exists.

Browser operations must not activate Chrome, inject global input or
change the macOS frontmost application. ChatBridge may own more than one
Chrome process if that is its deliberate internal implementation, but
Mac Control must not create or own any.

Actual screenshot binary transport, signed capabilities, downstream
authorization, operation-idempotency, and failure reconciliation must be
specified jointly with the ChatBridge implementation. Do not accept a
solution merely because a mock server returned JSON.

## Failure semantics

- API route not available: CHATBRIDGE_API_MISSING.
- Unauthorized client/session: CHATBRIDGE_UNAUTHORIZED.
- HTTP 429: CHATBRIDGE_RATE_LIMITED.
- Invalid session capability: INVALID_ARGUMENT.
- Transport failure on mutating request after submission:
  UNKNOWN_RESULT; do **not** blindly repeat click/submit.
- No implicit foreground fallback.

## Release acceptance gates

- [x] Legacy ChatGPT browser tools now use HTTP-only adapter source.
- [x] Background browser tools use HTTP-only adapter source.
- [x] Tests cover HTTP requests, session capability header, binary
      screenshot preservation, missing provider, and no direct fallback.
- [x] Mac Control MCP Server installer no longer downloads a private Chromium.
- [ ] ChatBridge developer implements and releases Browser API v1.
- [ ] Real local DEV/ChatBridge E2E: two sessions, DOM/click/fill/screenshot.
- [ ] User works in another foreground app during browser operations.
- [ ] Crash/restart and ambiguous-action recovery tests across HTTP.
- [ ] Clean Mac installs ChatBridge and Mac Control using AGENT_INSTALL.
- [ ] Browser uploads/downloads and native MCP binary image delivery.
- [ ] Independent code audit, licensing decision, public GitHub publication.

Older docs describing DEV's original standalone Playwright backend
are historical engineering reports, not statements about current
release architecture.
