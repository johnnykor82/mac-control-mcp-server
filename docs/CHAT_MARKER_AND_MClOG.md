# ChatGPT chat markers and MClog grouping

Owner-approved BF28, 2026-11-07.

Current ChatGPT clients do not supply an authoritative conversation_id in the MCP request metadata. Mac Control cannot silently publish messages in the current ChatGPT conversation. The user and assistant must cooperate: on first Mac Control use, issue ONE WC marker followed by 16 lowercase hexadecimal characters and display it in an assistant reply. Reuse an existing marker from this same chat if there is one. Do not generate a new marker for every task or turn. Do not create a new ChatGPT chat for orchestration.

The read-only chat_marker_issue MCP tool generates a fresh cryptographically random marker for a chat that has none. Include it as audit_context.chat_marker on each subsequent Mac Control call, keeping the mandatory task_id, action and authorization_basis unchanged. The marker is for correlation, NOT authentication. The initial issuance call may be uncorrelated unless the caller had already chosen the marker. Missing markers do not prevent older clients from using Mac Control but those records remain ungrouped.

MClog console usage:
- mclog --list-chats: list discovered WC chat groups and request counts.
- mclog --chat WC9d4f8a2c7b61e305: filter the live audit TUI to one conversation.
- Inside MClog press c to cycle existing chat groups and a to show all; 1/2/3 and m still switch detail modes, e still filters errors. All task IDs sharing one chat marker belong to the same group. Existing chat_ref hashed transport metadata still works if supplied; unmarked older events show as uncorrelated.
- Logs are local owner-only redacted metadata; they do not contain full ChatGPT conversations.
- Do not use a chat marker as proof of owner authorization or as a substitute for unique ChatBridge assistant-message verification.

ChatBridge dependency:
- Fresh Mac Control install or maccontrol update with ChatBridge management resolves the newest compatible official release, requires GitHub TLS plus exact SHA256SUMS, and refuses downgrade or foreign/active-service overwrite.
- maccontrol update --without-chatbridge preserves a standalone independently installed service.
- The MCP self-update tool also supports explicit with_chatbridge=true; its default false remains for backward-compatible, non-disruptive updates.
- Release discovery is an installation/update-time operation, not an always-running updater. There is no implied automatic update between Mac Control releases.
- Existing ChatBridge authentication, profile and SQLite are preserved by the official installer. On verification failure leave the prior working service intact.
