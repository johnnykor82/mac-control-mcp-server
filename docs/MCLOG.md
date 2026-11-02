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
- Columns / Столбцы: ВРЕМЯ, КОМАНДА, АРГУМЕНТЫ, ИТОГ. The empty client column has been removed / Пустой столбец «Клиент» удалён.
- New tool calls show bounded *safe argument metadata* / Новые вызовы показывают ограниченное безопасное описание аргументов.

### Keyboard / Клавиши

| Key | Action / Действие |
| --- | --- |
| `↑`, `↓`, `j`, `k` | Scroll / Прокрутка |
| `PgUp`, `PgDn` | Scroll by page / Страницами |
| `g`, `End` | Latest events / Последние вызовы |
| `e` | Errors only / Только ошибки |
| `q`, `Esc` | Quit / Выход |

## Security and data handling / Безопасность

The public Mac Control MCP Server produces an owner-only audit log with **tool name, start/end times, outcome, duration and a bounded, redacted argument description** for new calls. The argument summary records only approved enum names, safe numerical settings, value type and length or hidden markers; it never stores raw shell command text, arbitrary string values, file paths or content, typed messages, screenshots, response bodies or credentials. Secret-bearing parameter names are masked. This is a deliberately non-reversible summary, not an argument-replay log. Older installations may use different policies.

The installed data directory and log files are private to the macOS account (directories `0700`, files `0600`). Daily rotation retains up to seven archived files. Uninstall preserves the owner data directory and audit history.

### Limitations / Ограничения

Before this change, tool parameters were never written, so historical rows show «—» (no stored argument information). New calls with no parameters show «нет», and new calls with parameters display only a redacted structural summary (for example: `command=[команда: 48 симв.], project=workspace`). The word `null` is not displayed for missing parameters.

The MCP server does not receive a verified ChatGPT conversation title in tool-call metadata, so the client column is removed rather than presenting a guessed identity. This release does not map ChatBridge browser tabs to unrelated MCP calls.

**No automatic telemetry or external reporting.** All inspection is local.
