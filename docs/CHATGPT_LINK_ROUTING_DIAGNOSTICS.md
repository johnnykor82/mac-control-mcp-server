# Mac Control MCP — ChatGPT account routing, link_id and blocked SSH calls

FR-025.1 / 2026-11-03. The ChatGPT connector and the local FastMCP server
are distinct layers. Local fixes cannot override platform safety or change
ChatGPT connection eligibility.

## Verified boundary

- ChatGPT's connected-tool wrapper selects an eligible account using
  link_id. The local ssh_exec schema accepts host, command,
  timeout_seconds; terminal_exec accepts command, project,
  timeout_seconds; custom_command accepts operation, arguments.
  None of these server-side schemas accepts link_id.
- Only use the account currently offered by the invoking connector.
  Do not copy an old link_id from a previous conversation or put this
  wrapper field in a nested tool argument.
- An "eligible linked account" error is account routing upstream of
  the Mac Control handler. An "unexpected link_id" error is consistent
  with a wrapper-only field crossing into a FastMCP parameter schema;
  exact layer must be established from the invoking tool call trace.
- An OpenAI safety rejection is a separate upstream policy gate.
  Owner consent does not guarantee that a blocked tool call is allowed.
  Never split/rephrase the blocked request or use another tool/SSH
  server to evade the decision.
- Local audit tool_start proves the invocation reached the Mac.
  Local tool_end with status=ok proves only that the handler returned,
  not that an embedded terminal or remote SSH command exited with 0.

## Observations, 2026-11-03

The installed remote server and Watcher were running. Read-only calls to
terminal_exec, mcp_diagnostics and ssh_profile_inventory succeeded with
the current linked Mac Control MCP account. The actual local schemas
contain no link_id. The owner-only audit includes two terminal_exec
invocations starting with SSH and referring to client_traffics at
07:14:44 and 07:59:09 UTC, both ended status=ok on MCP; remote exit
status was not recorded in that metadata. No separate direct ssh_exec
call with this query was observed. No corresponding eligibility error
was found in the server stderr. This does not prove which other attempt
was blocked at the platform layer.

## Troubleshooting for the agent and owner

1. On linked-account eligibility failure, stop that call. Use the tool
   wrapper's currently advertised linked accounts, selecting the
   specifically connected Mac Control MCP account when it is eligible.
   Do not manually inject link_id into the handler payload. If no
   eligible connection is available, the owner should inspect the
   connection in ChatGPT Settings > Plugins and reconnect or reauthorize
   if needed. Do not fall back to the old service without permission.
2. On extra-field schema failure, inspect the exact invocation layer
   and its parameters. The direct local ssh_exec tool has no link_id.
   Do not relax the server schema to conceal a routing error.
3. On an OpenAI safety block, STOP. Do not retry with an alternate
   command format or tool. Record the blocked step and platform error.
4. When a call reached the server, use safe read-only diagnostics
   (mcp_diagnostics, ssh_profile_inventory, owner-only mclog).
   For shell/SSH, inspect the returned exit_code; audit status=ok
   alone does not establish that the remote command succeeded.
5. For recurring platform failures, send the integration maintainer
   UTC timestamp, tool name, selected connection label, error text
   and platform correlation ID if provided. Do not expose credentials,
   SSH private keys or entire command bodies.

Mac Control cannot fix external connection-eligibility denial by
inventing link aliases, modifying SSH keys or bypassing policy checks.
