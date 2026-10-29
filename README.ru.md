[English](README.md) · [**Русский**](README.ru.md)

# Mac Control MCP Server

**Полноценный доступ к macOS для авторизованных ИИ-агентов.** Файлы, терминал, Git, SSH, интерфейс Mac, фоновый браузер через ChatBridge и удалённый MCP.

Mac Control MCP Server — экспериментальный сервер Model Context Protocol (MCP) для автономных задач. Он предоставляет агенту широкие полномочия на Mac владельца, а не ограничивающую песочницу.

> **Подготовка Beta.** Локальные тесты, включая браузерную интеграцию ChatBridge, пройдены. Независимую установку на другом Mac и реальный вход через внешний GitHub OAuth ещё нужно проверить. Это пока не готовый промышленный релиз.




## Возможности

- **Файлы, терминал, Git:** проекты, команды, процессы, службы и разрешённые SSH-подключения.
- **Нативный интерфейс macOS:** отдельный подписанный GUI helper с разрешениями Accessibility и Screen Recording; фоновая работа с окнами там, где это поддерживается.
- **Браузер через ChatBridge:** переходы по страницам, ввод, клики, DOM и скриншоты по HTTP. Mac Control не запускает собственный Chrome.
- **Единый workspace:** проекты, временные файлы, загрузки, журналы и готовые результаты в одном каталоге.
- **Экспериментальный удалённый доступ:** личное GitHub OAuth App и публичный HTTPS через Tailscale Funnel.

## ChatBridge — отдельный продукт

**ChatBridge имеет самостоятельную установку и репозиторий.** Он предоставляет HTTP-доступ к авторизованной браузерной сессии ChatGPT и фоновую автоматизацию браузера. Для его работы Mac Control не нужен.

Стандартный установщик Mac Control переиспользует совместимый ChatBridge или
устанавливает отдельный релиз `v0.2.0-beta.5` с закреплённой SHA256.
Профиль Chrome, LaunchAgent и данные принадлежат ChatBridge; удаление Mac Control
его сохраняет. Для работы без браузера используйте `--without-chatbridge`;
при обновлении этот флаг пропускает настройку и сохраняет прежнюю конфигурацию.

**Исходники ChatBridge:** [johnnykor82/chatbridge](https://github.com/johnnykor82/chatbridge).
Используйте проверенный опубликованный релиз ChatBridge.

По умолчанию ChatBridge доступен по `http://127.0.0.1:8787` без API-ключа.
Для другого локального порта передайте установщику `--chatbridge-url
http://127.0.0.1:PORT`. Если владелец включил `CHATBRIDGE_API_KEY`, задайте
совпадающий `MACCONTROL_CHATBRIDGE_API_KEY` в окружении установщика и процесса
MCP-клиента. Не вставляйте ключ в чат или аргументы команд.

## Установка на macOS

Требуются macOS, Python 3.9+ для bootstrap, Google Chrome и совместимый MCP-клиент. Установщик создаёт изолированный Python 3.13 через [uv](https://docs.astral.sh/uv/). Перед запуском изучите исходники.

```sh
git clone https://github.com/johnnykor82/mac-control-mcp-server.git
cd mac-control-mcp-server
python3 scripts/release_preflight.py --json || [ "$?" -eq 2 ]
python3 scripts/release_audit.py --strict
python3 scripts/install_mac_control.py --plan
python3 scripts/install_mac_control.py --install
python3 scripts/install_mac_control.py --status
```

Запускайте `--install` в Terminal. Установщик сначала проверяет API ChatBridge.
При отсутствии сервиса он скачивает закреплённый релиз, сверяет SHA256 до
распаковки и исполнения и вызывает собственный установщик ChatBridge.
Существующие данные, LaunchAgent, занятый порт, HTTP 401 или несовместимый API
останавливают настройку: сначала восстановите отдельный ChatBridge.
Нужен Google Chrome. Если `uv` отсутствует, ChatBridge предлагает установить его
с согласия владельца; bootstrap работает на Python 3.9+ и создаёт отдельный
Python 3.13. При standalone-установке или переиспользовании сервиса без uv
сначала установите [uv](https://docs.astral.sh/uv/getting-started/installation/).
Preflight возвращает код 2, если uv ещё отсутствует; команда выше допускает этот
результат, чтобы интерактивный bootstrap ChatBridge мог предложить его установку.

`--with-chatbridge` сохранён для совместимости; `--chatbridge-source PATH`
позволяет использовать отдельно проверенные исходники. После новой установки
сначала дождитесь, пока `curl http://127.0.0.1:8787/v1/system/status` покажет
`browser.mode=managed` и `browser.state=running`. Затем вручную войдите в ChatGPT,
открыв **только профиль по умолчанию**:

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir="$HOME/.chatbridge/chrome-profile" --new-window https://chatgpt.com/
```

Для другого расположения профиля следуйте инструкциям ChatBridge. Установка
не оставляет окно входа открытым и не проверяет реальный вход в ChatGPT.
При последующей ошибке Mac Control ChatBridge остаётся отдельно установленным;
повторный запуск использует его совместимый работающий API. Лимит настройки —
30 минут; после таймаута сначала проверьте состояние ChatBridge.

Нативный GUI helper:

```sh
python3 scripts/install_mac_control.py --update --with-gui
```

Разрешения Accessibility и Screen Recording владелец выдаёт в настройках macOS. Доступны `--update`, `--rollback` и `--uninstall` с сохранением пользовательских данных. MCP-клиент запускает установленный `bin/mac-control-stdio-mcp.sh`.

## Рабочий каталог агентов

Новые проекты, временные файлы, клоны репозиториев, загрузки и результаты по умолчанию создаются здесь:

`~/Library/Application Support/MacControl/MCPServer/data/workspace`

Правило находится в инструкциях MCP-сервера и инструменте `workspace_policy`. Запись вне каталога — только по прямому указанию владельца или для необходимых системных настроек. **Это правило для агента, а не системная песочница.**

См. [правила workspace](AGENT_WORKSPACE_POLICY.md) и [состав установки](docs/INSTALL_CONTENTS.md).

## mclog — монитор аудита Mac Control

**`mclog` входит в установочный комплект Mac Control MCP Server.** Это
интерактивная терминальная панель для просмотра вызовов MCP: количества
запросов, ошибок, выполняющихся операций, средней длительности, почасовой
нагрузки и истории вызовов. Клавиша `e` включает фильтр ошибок,
стрелки / PgUp / PgDn прокручивают историю, `q` закрывает монитор.

После установки откройте отдельное окно терминала и запустите:

```sh
"$HOME/Library/Application Support/MacControl/MCPServer/current/bin/mclog"
```

Утилита автоматически читает журнал
`~/Library/Application Support/MacControl/MCPServer/data/logs/audit.jsonl*`.
Для просмотра другого разрешённого каталога есть параметр `--log-dir PATH`.
В целях безопасности релизный MCP сохраняет **названия инструментов, время,
статус и длительность выполнения**, но не аргументы команд, содержимое
файлов, ответы и секреты. ChatBridge для работы `mclog` не нужен.
Подробности: [инструкция mclog](docs/MCLOG.md).

## GitHub OAuth и Tailscale Funnel

Каждый владелец создаёт личное GitHub OAuth App. Мастер выводит callback URL, скрыто принимает Client Secret, генерирует ключ подписи и разрешает вход только нужным GitHub ID.

```sh
python3 scripts/install_mac_control.py --network-diagnose
python3 scripts/install_mac_control.py --network-guide
python3 scripts/install_mac_control.py --github-oauth-guide --public-url https://YOUR-DEVICE.ts.net
python3 scripts/install_mac_control.py --setup-github-oauth --public-url https://YOUR-DEVICE.ts.net
python3 scripts/install_mac_control.py --github-oauth-check
```

Funnel включается после проверки защищённого локального MCP (анонимный HTTP 401) и подтверждения владельца. Установщик не меняет маршруты VPN, WireGuard и Exit Node.

Подробнее: [GitHub OAuth](docs/GITHUB_OAUTH_SETUP.md), [удалённый доступ](docs/REMOTE_ACCESS_GUIDE.md), [инструкция для агента](AGENT_INSTALL.md).

## Риски, статус и лицензия

Агент с доступом к терминалу, GUI и сети способен удалять файлы, раскрывать данные и изменять систему. Mac Control не гарантирует изоляции этих действий песочницей. См. [SECURITY.md](SECURITY.md). ChatBridge — неофициальная интеграция с веб-интерфейсом, а не официальный OpenAI API.

**Лицензия: MIT.** © 2026 Ivan Konstantinov. См. [LICENSE](LICENSE). До публичного релиза необходимо проверить происхождение исходников и провести независимые испытания. См. [критерии релиза](docs/PUBLIC_RELEASE_GATES.md).
