# Browser Background MCP API — Dev experimental

> Historical DEV design; superseded by [ChatBridge Browser API integration](CHATBRIDGE_BROWSER_MIGRATION.md). Current public installations use the independent ChatBridge service, not the Chrome/profile implementation described below.

Enabled by `{"background_browser":true}` in private `~/Library/Application Support/MacControl/MCP-Dev/feature_flags.json`. Only available over local `mac_control_dev_local` stdio. All operations return `{ok:true,result:{...}}` or `{ok:false,error:{code,message}}`.

- `background_browser_create(persist_profile=false,url="about:blank")` returns a secret `session_token`, session ID, PID and background status.
- `background_browser_action(session_token,action,tab_id="",url="",selector="",text="",dx=0,dy=0)` accepts `navigate`, `click`, `fill`, `press`, `scroll`, `new_tab`, `close_tab`, `tabs`. URL navigation accepts HTTP(S); selector is Playwright-compatible. Empty `tab_id` chooses the first tab.
- `background_browser_snapshot(session_token,tab_id="",max_chars=12000)` returns ARIA/body snapshot, title, URL and tab IDs.
- `background_browser_capture(session_token,tab_id="",quality=65)` returns JPEG `image_data` in base64, capped at 700 KB.
- `background_browser_list(session_tokens)` lists status only for sessions with supplied valid capabilities.
- `background_browser_close(session_token)` closes the owned browser, retaining the profile only if explicitly persistent.
- `background_browser_reopen(session_token)` restarts a previously closed persistent session.

Errors include `INVALID_SESSION`, `SESSION_NOT_FOUND`, `NOT_AUTHORIZED`, `STALE_TAB`, `INVALID_URL`, `BROWSER_START_FAILED`, `BROWSER_OPERATION_FAILED`, `DEPENDENCY_MISSING`, `WORKER_UNAVAILABLE` and `SESSION_CLOSED`. A crash may leave an orphan process; independent garbage collection is not implemented.

## Native AX tools (experimental)

Enable with `"background_native":true` in Dev's owner-only feature flags. These tools are also local stdio only: `background_app_list`, `background_app_create(bundle_id)`, `background_app_windows(session_token)`, `background_app_elements(session_token,window_ref,max_depth,max_nodes)`, `background_app_action(session_token,window_ref,element_path,expected_role,expected_title,action,text)`, `background_app_capture(session_token,window_ref)`, and `background_app_close(session_token)`. Native sessions are capability-protected, bound to PID and application launch date, with seven-day validity; closing revokes the capability but never terminates the app. Direct AX operations require exact expected role/title and matching window fingerprint. Supported actions are direct `set_value` on settable non-secure text fields/areas/comboboxes, or a supported AX action name. No macOS global input, focus activation or clipboard mutation is used. A standalone native CLI has no Screen Recording permission. `background_app_capture` instead validates the live AX window under the session and calls `capture_window` on the authorized Dev GUI application via its owner-only Unix socket. The GUI matches PID, title, and geometry to one ScreenCaptureKit window, then captures it without activation. New ad-hoc GUI signatures may require the owner to reauthorize Screen Recording.

`background_browser_action` and `background_app_action` accept `mode="background"|"auto"|"foreground"`. `background` and `auto` always use true background methods; `auto` never silently switches focus. Explicit `foreground` returns `REQUIRES_FOREGROUND` because legacy GUI tools must be selected separately. Invalid modes return `INVALID_MODE`.

### Large native screenshots

On success, `background_app_capture` emits a native MCP `ImageContent` block rather than placing JPEG base64 in JSON. `structured_content.result` contains only metadata (`image_bytes`, `mime_type`, `window_ref`, `capture_mode`). Error responses remain structured JSON with `ok=false`. Clients must process MCP image content; converting it back to a giant text field may trigger generic bridge truncation. Source-level verification is complete; live bridge acceptance remains a separate gate.
