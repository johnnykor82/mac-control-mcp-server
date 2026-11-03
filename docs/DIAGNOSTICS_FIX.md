# Installed Mac Control diagnostics — beta.23

`mcp_diagnostics` imports its lifecycle helper exclusively from the
active release. `launchd_status()` uses the current remote service label;
the Watcher LaunchAgent is an explicitly recognized read-only diagnostic
target. `local_http_probe()` obtains the configured local port from the
shipped service module and probes only localhost, with GET/HEAD and no redirects.

Interactive sessions require Homebrew `tmux`. The installer detects this
dependency and asks for approval if running in a Terminal, while
`maccontrol update --install-tmux` explicitly approves its installation.
When missing, terminal tools return a structured `TMUX_NOT_INSTALLED`
diagnostic, leaving the rest of Mac Control functional. The terminal
execution permission policy remains unchanged.

`gui_status` reports responsive GUI IPC separately from the ability to
identify its PID using `ps`. On-demand helpers can be responsive without
an observable PID. Failures still return structured IPC diagnostics.

The update does not reset existing Funnel/Serve routes, migrate workspace,
alter OAuth/ChatBridge identities, or silently grant macOS TCC permissions.
For a live post-update check, reconnect the MCP client and invoke the four
diagnostic tools; interactive terminal open/read/send/close additionally needs
an installed tmux and owner-enabled terminal access.

## beta.24: tmux/Homebrew failure reporting

The beta.23 installer suppressed Homebrew's stderr/stdout when an
owner-authorized `brew install tmux` failed. The beta.24 installer preserves
the user's Homebrew-relevant environment (locale, TMPDIR, username, network
proxy settings and PATH), emits bounded redacted diagnostics with the precise
exit code, and reports timeouts or an unlocatable post-install binary.
No automatic retry or package installation is performed without consent.
If the failure persists, use `brew install tmux` in Terminal to inspect
the complete error message.

**Observed on JKMac-2:** tmux 3.8 is already installed and a real MCP PTY
session was opened, sent a command, read and closed successfully. A Homebrew
exit code 1 may follow a successful installation; beta.24 now checks the
resulting executable via `tmux -V` and returns `installed_with_warnings`
with `available=true` if functional, preserving the Homebrew diagnostics.
The historical Homebrew error text was not captured in beta.23, so its exact
cause is unknown.


### ChatBridge idle readiness and Mac Control installer (FR-024)

Managed ChatBridge can intentionally idle-close Chrome after five minutes.
Passive GET /ready returns 503 with reason=browser_idle and
chatgpt_authenticated=null. This is **not** a login failure. The owner
install/update flow issues POST /v1/browser/verify only when this precise
reason is reported and accepts success only after a real editor is verified.
Normal status polling never reopens Chrome. If not verified, inspect the
ChatBridge managed profile and endpoint, not general Chrome login.
