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
