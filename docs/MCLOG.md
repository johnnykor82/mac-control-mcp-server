# mclog — Mac Control MCP Server audit monitor

A bundled, **read-only** curses dashboard for observing locally authorized MCP tool calls. It is installed with the Mac Control MCP Server core release and does not require ChatBridge, GUI permissions, GitHub OAuth or Tailscale.

## Start / Запуск

Open a separate terminal on the Mac with Mac Control installed:

```sh
mclog
```

The installer registers `mclog` (and `maccontrol`) in `~/.local/bin`, creating an owner-only launcher.
If needed, it adds `~/.local/bin` to the login shell `PATH` through an idempotent `~/.zprofile` block.
Start a new Terminal or run `source ~/.zprofile` to activate the change.
Without a PATH entry, use `~/MacControlMCP/current/bin/mclog`. Uninstall removes only owned launchers.

The launcher follows the currently activated version and automatically reads:

```text
~/MacControlMCP/data/logs/audit.jsonl*
```

For a custom root, invoke that installation's `current/bin/mclog`. The viewer also supports `--log-dir /path/to/logs` for explicitly permitted logs.

## What it displays / Что показывает

- Recent requests, errors and running operations / Запросы, ошибки и выполняющиеся операции.
- Average duration and hourly activity / Средняя длительность и почасовая нагрузка.
- Scrollable history of tool names, timestamps and statuses / История инструментов, времени и статусов.
- Historical audit files across log rotation / Данные из ротируемого архива журналов.
- Columns / Столбцы: ВРЕМЯ, КОМАНДА, АРГУМЕНТЫ, ИТОГ; optional ЧАТ on sufficiently wide terminals when ChatGPT supplies a conversation reference. The empty КЛИЕНТ column remains removed.
- New tool calls show their **actual arguments** from the owner-only audit, with viewer-side truncation and display redaction; nested `custom_command`/`custom_query` parameters are supported.
- A chat marker such as `Чат 01234567` is a repeatable, anonymized **conversation identifier**, not the conversation title. If ChatGPT omits `_meta["openai/session"]`, no chat attribution is shown.

### Keyboard / Клавиши

| Key | Action / Действие |
| --- | --- |
| `↑`, `↓`, `j`, `k` | Scroll / Прокрутка |
| `PgUp`, `PgDn` | Scroll by page / Страницами |
| `g`, `End` | Latest events / Последние вызовы |
| `e` | Errors only / Только ошибки |
| `q`, `Esc` | Quit / Выход |

## Security and data handling / Безопасность

The local Mac Control audit is the diagnostic **source of truth**: new
`tool_start` records preserve the actually supplied MCP argument JSON, including
shell command texts, paths and nested parameters. A bounded snapshot limits
individual fields, depth and total record size; truncated content keeps a
preview, original length and SHA-256. The log also retains the time,
tool/request ID, status, and duration. It never logs tool response bodies.
Because arguments can contain credentials and private data, the raw JSONL
should be treated as private owner data; the viewer masks common credential
fields and inline token patterns **only in its terminal presentation**.

To correlate calls from a single ChatGPT conversation, the server hashes the
optional client-supplied `_meta["openai/session"]` into a stable short
`chat_ref`. This is **not** an authorization identity, actual conversation
title, browser tab title or guarantee of provenance. It may be absent for
other clients or ChatGPT versions.

Remote `audit_tail` and `audit_search` intentionally project only metadata:
raw arguments are available in the local owner-only file, not automatically
in remote tool responses. For a complete forensic inspection, read the local
JSONL with user-owned tools.
The installed data directory and log files are private to the macOS account (directories `0700`, files `0600`). Daily rotation retains up to seven archived files. Uninstall preserves the owner data directory and audit history.

### Limitations / Ограничения

Historical records from older MCP versions that contain no parameters
show `—`, and explicit empty arguments show `нет`. The original legacy
Mac Control logs that already contain actual `arguments` remain supported,
as do the intermediate `argument_info` records from FR-021 v1.
After updating the running MCP, only **future** requests gain complete
audit records; previous calls cannot be reconstructed.

The screen intentionally removes the empty `КЛИЕНТ` column. Its optional
`ЧАТ` column is shown only when a recognizable ChatGPT conversation
reference is recorded and the terminal is wide enough. Chat names are not
sent by the ChatGPT MCP client.
**No automatic telemetry or external reporting.** All inspection is local.
