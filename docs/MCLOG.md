# mclog — Mac Control MCP Server audit monitor

A bundled, **read-only** curses dashboard for observing locally authorized MCP tool calls. It is installed with the Mac Control MCP Server core release and does not require ChatBridge, GUI permissions, GitHub OAuth or Tailscale.

## Start / Запуск

Open a separate terminal on the Mac with Mac Control installed:

```sh
"$HOME/Library/Application Support/MacControl/MCPServer/current/bin/mclog"
```

The launcher follows the currently activated version and automatically reads:

```text
~/Library/Application Support/MacControl/MCPServer/data/logs/audit.jsonl*
```

For a custom root, invoke that installation's `current/bin/mclog`. The viewer also supports `--log-dir /path/to/logs` for explicitly permitted logs.

## What it displays / Что показывает

- Recent requests, errors and running operations / Запросы, ошибки и выполняющиеся операции.
- Average duration and hourly activity / Средняя длительность и почасовая нагрузка.
- Scrollable history of tool names, timestamps and statuses / История инструментов, времени и статусов.
- Historical audit files across log rotation / Данные из ротируемого архива журналов.
- The name of the calling client **only when the server supplies verified attribution** / Имя клиента только при наличии достоверного идентификатора.

### Keyboard / Клавиши

| Key | Action / Действие |
| --- | --- |
| `↑`, `↓`, `j`, `k` | Scroll / Прокрутка |
| `PgUp`, `PgDn` | Scroll by page / Страницами |
| `g`, `End` | Latest events / Последние вызовы |
| `e` | Errors only / Только ошибки |
| `q`, `Esc` | Quit / Выход |

## Security and data handling / Безопасность

The public Mac Control MCP Server produces a minimal audit log containing **tool name, start/end times, outcome and duration**. It does not retain tool arguments, typed text, file contents, screenshots, response bodies or credentials. These restrictions are intentional. Older owner-specific Mac Control installations may have a different logging policy: do not infer their retention settings from this release.

The installed data directory and log files are private to the macOS account (directories `0700`, files `0600`). Daily rotation retains up to seven archived files. Uninstall preserves the owner data directory and audit history.

### Limitations / Ограничения

The packaged viewer keeps the original read-only display conventions. Because this public release does **not** record tool parameters, the arguments column will normally be empty. A blank client identity means the server did not record a verified caller identifier. Those are not errors.

**No automatic telemetry or external reporting.** All inspection is local.
