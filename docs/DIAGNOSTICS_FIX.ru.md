# Диагностика Mac Control — beta.23

## Исправленные инструменты

- `mcp_diagnostics`: корректно находит собственный модуль
  `scripts/setup_remote_service.py` из установленного релиза, даже если
  текущий каталог и `PYTHONPATH` не содержат `scripts`. Не исполняет файлы
  с совпадающим именем из чужого проекта. Возвращает состояние LaunchAgent,
  PID, собственный PID MCP-процесса и размеры разрешённых журналов.
- `launchd_status()`: проверяет `org.maccontrol.mcpserver.remote`.
  Для Watcher используйте
  `launchd_status(label="org.maccontrol.mcpserver.watcher")`.
  Старые метки удалены из автоматического allowlist. Дополнительные
  сервисы разрешаются отдельно локальной конфигурацией.
- `local_http_probe()`: проверяет штатный порт из установленного релиза
  (сейчас 3201). Пример: `local_http_probe(path="/.well-known/oauth-authorization-server")`.
  Разрешены только GET и HEAD на 127.0.0.1, без редиректов.
- `terminal_capabilities` и `terminal_list`: если `tmux` отсутствует,
  возвращают `TMUX_NOT_INSTALLED` и инструкцию, не бросая исключение.
  Для установки можно выполнить `maccontrol update --install-tmux` —
  это явное разрешение на `brew install tmux` через Homebrew. При
  интерактивной обычной установке будет предложен выбор.
- `gui_status`: после успешной связи с GUI Helper сообщает
  `functional_state=operational`, `ipc.service_state=responsive`,
  а наблюдаемость PID — отдельно. Для работы через запуск по требованию
  PID может быть недоступен; это не ошибка самого GUI.

## Проверки

После обновления `maccontrol update` перезапустите MCP-клиент, чтобы
новый код инструментов загрузился. Проверьте `mcp_diagnostics`,
`launchd_status`, `local_http_probe` и `gui_status`.
Проверка интерактивного терминала требует установленного `tmux`
и разрешённого владельцем доступа к терминалу.

Обновление не перенастраивает Tailscale Funnel, OAuth, ChatBridge,
Watcher и не переносит пользовательские проекты. Если Funnel уже
настроен иначе, мастер не затирает существующие маршруты.
