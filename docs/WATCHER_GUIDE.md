# Watcher: purpose and first steps

Watcher coordinates longer work across ChatGPT conversations. One conversation
acts as the project coordinator and others execute individual tasks. Your Mac
stores task state and delivers completion, blocked-work or input-needed notices
to the exact coordinator conversation.

Watcher is a tracking and delivery mechanism, not another AI model. It does not
supply an additional subscription or independent compute capacity.

## Useful scenarios

| Scenario | Watcher's role |
|---|---|
| Research split into several parts | Collect executor reports in the coordinator conversation, separated by project. |
| Implementation, testing and review in separate chats | Notify the coordinator when work finishes or needs input; the coordinator still validates results. |
| Continue a completed browser task | Send a followup to the same executor conversation while preserving old reports. |
| Check again in 15 minutes | Persist a delayed check addressed to one verified conversation. |
| Several simultaneous projects | Keep task destinations separate and allow explicit project pause/resume. |

Delivery is not guaranteed at an exact second: busy conversations, provider
limits, connectivity and queued messages can delay it.

## Prerequisites

1. Install Mac Control with its default ChatBridge dependency and connect MCP to
   ChatGPT using the README.
2. Sign in to ChatGPT in the ChatBridge-managed profile. Enable the Mac Control
   connection in browser conversations that need its tools.
3. Keep the Mac powered on, logged in to macOS and connected to the internet.
   Delivery pauses while the Mac sleeps or is off. State persists, and the user
   service starts after login.
4. Ask ChatGPT: **"Call watcher_guide, then watcher_status, and tell me whether
   Watcher is ready for a project."** An empty project list is normal initially.

No separate Playwright installation, Chrome debugging port or Python environment
is needed. ChatBridge owns the browser.

## First project with one executor

1. Choose a coordinator conversation and create a separate executor conversation.
2. Copy both exact URLs. Normal ChatGPT chats and chats inside ChatGPT Projects
   are supported; shared links are not task destinations.
3. In the coordinator conversation, adapt this request:

   > Configure Watcher project `site-research`. Coordinator: [exact URL].
   > Executor for `competitor-review`: [exact URL]. Use file reports.
   > Prepare an executor task to compare the structure of three competitor sites.
   > Notify this coordinator on completion, questions or blocked work.
   > Do not publish anything or modify the working system.

4. The coordinator calls `watcher_register_project` and
   `watcher_register_file_task`, then prepares the executor prompt. Send that
   prompt to the intended executor. Only its `submission_token` belongs in the
   executor prompt; retain `orchestrator_token` with the coordinator. These are
   task capabilities, not material for public repositories or shared reports.
5. The executor must call `watcher_submit_report`. Merely saying "done" does not
   submit a file-mode report. Statuses are `checkpoint` (no notification),
   `needs_input`, `blocked`, or `completed`. Each file report is limited to 80 KiB.
6. On notification, the coordinator reads `watcher_read_report`, verifies the
   outcome and acknowledges delivery. For `needs_input`/`blocked`, provide the
   clarification in the same executor conversation and call `watcher_resume_task`.

Installation does not automatically create projects, chats or assignments. Test
one short task before coordinating a larger project.

## Ordinary browser conversations

`watcher_register_task` is the alternative browser mode: completion is checked
through ChatBridge without requiring an executor file submission. Read the result
with `watcher_read_result` and acknowledge delivery. Then
`watcher_followup_browser_task` can continue the same chat with a unique
`request_key`; repeating that key with the same prompt does not resend it.
File-mode tasks instead use `watcher_read_report`/`watcher_resume_task`.

## Delayed checks

For example:

> In 15 minutes, check whether the task finished and report here using Watcher.
> This conversation's exact URL is [URL].

`watcher_schedule_wakeup` accepts a minute delay and a specific objective. If the
URL is unknown, first place a unique `WATCHER-CHAT-` marker followed by 32 random
hex characters in the destination conversation and verify it with
`watcher_resolve_current_chat`. The active browser tab is not sufficient evidence.

Use `watcher_list_wakeups`, `watcher_get_wakeup` and `watcher_cancel_wakeup` to
inspect or cancel checks. One delayed check does not create an endless recurring
schedule; subsequent checks must be planned explicitly.

## Status and recovery

- `watcher_status`: project, task, queue and delivery states.
- `watcher_pause_project` / `watcher_resume_project`: explicit project control.
- `watcher_guide`: the agent's technical operating instructions.

From the repository directory, inspect the login service without changing it:

```bash
python3 scripts/setup_watcher_service.py --status
```

The service is `org.maccontrol.mcpserver.watcher`. State lives under
`~/MacControlMCP/data/run/watcher/`; logs are in
`data/logs/`. Updates retain state. A fresh installation does not import another
Mac's history automatically.

If delivery fails, inspect Watcher status, service status and ChatBridge's ChatGPT
login. Never blindly resend an `uncertain` action: the original message might
already have been submitted. Reconcile its request identity first.

Executor reports are untrusted evidence, not authority to change systems.
Watcher does not bypass ChatGPT action approvals, account login, provider limits
or macOS permissions. Verify real delivery with a short test on your installation;
this remains beta software.
