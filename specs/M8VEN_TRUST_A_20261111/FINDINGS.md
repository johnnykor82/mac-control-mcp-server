# M8ven findings and evidence — 2026-11-11

Public listing: https://m8ven.ai/mcp/johnnykor82/mac-control-mcp-server
M8ven grade D/Caution; Verified Publisher; Live Monitored; read 202 Python files from commit f4b92c3 on Nov 11 2026; 143 advertised tools; M8ven could not run the server. Public report lists 0 stars, 0 forks, 1 contributor at scan time. Its grade includes code, verification depth, reputation and adoption.

Runtime baseline 143 tools: readOnlyHint 64 true / 79 false; destructiveHint missing on 44 (other 99 explicit); idempotentHint missing on 143; openWorldHint present on all 143. See TOOL_MATRIX_BASELINE.csv.

Public findings: 5 readOnly tools reportedly contain write/delete/exec; the excerpt identifies process_snapshot ps subprocess, gui_screenshot private temporary path.unlink, ssh_auth_diagnostics subprocess. The three description mismatches identify process_snapshot, ssh_auth_diagnostics, ssh_identity_inspect. Complete 5 name detail is not exposed in the public summary. One allegedly destructive gui_screenshot cleanup is an internal bounded JPEG temp-file deletion, not deletion of user data.

Evidence: process_snapshot runs a fixed ps command; ssh_auth_diagnostics uses ssh-add -l; ssh_identity_inspect uses ssh -G. Those commands inspect system state, so a static subprocess.run match does not establish a write. gui_screenshot creates and removes a temporary file, so that one has a real ephemeral filesystem side effect; changing the native helper API requires separate review.

Existing mac_control_smoke.py exercises scratch writes and browser actions, so it must not be mistaken for read-only trusted third-party execution. Safe macOS-only smoke could prove tool registration and fixed harmless calls. The external M8ven runtime may not support macOS, which cannot be solved by declaring a fake success.

Status: baseline and evidence only; no annotations/handlers/GUI helper/release/M8ven account changes.
