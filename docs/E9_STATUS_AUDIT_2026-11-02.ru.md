# E9 — аудит состояния и документации (2026-11-02)

**Статус:** INCOMPLETE — это протокол проверки, не решение о готовности релиза.

## Подтверждено через установленный Mac Control MCP

- 2026-11-02: `gui_status` вернул `accessibility_trusted=true`, `screen_capture_trusted=true`, `functional_state=operational`.
- `gui_tree` успешно прочитал AX-дерево приложения «Системные настройки» (реальный тест).
- Восстановление Accessibility потребовало удаления старой записи MacControlMCPServer из системного списка и повторного добавления приложения. Причина утраты доверия после обновления **не установлена**.
- Сохранённый журнал `AgentWorkspace/scratch/maccontrol-e9-suite.log`: `Ran 541 tests in 24.351s`, `OK (skipped=1)`. Это **исторический** результат, а не свежий прогон.
- В рабочем установленном MCP `terminal_capabilities` возвращает `enabled=false`; это состояние установленного экземпляра и не доказывает отсутствие исправления в исходниках релиз-кандидата.

## Несоответствия документов и непроверенные критерии

1. `AgentWorkspace/projects/mac-control-mcp-server-private/PLAN_FULL_CAPABILITY_INSTALLER.ru.md` всё ещё содержит «ожидает утверждения» и E0–E10 «не начаты», что противоречит наличию исходников и журналов тестов E5–E9. Реальные коммиты и статус каждой стадии пока не сверены; автоматически считать их закрытыми нельзя.
2. `SPEC_FULL_CAPABILITY_INSTALLER.ru.md` указывает «реализация не начата»; этот административный статус также требует сверки с историей Git.
3. `docs/PUBLIC_RELEASE_GATES.md` использует дату аудита 2026-10-26, базу 78 тестов и старые открытые gates. Нужна актуализация после проверки релизной ветки; не использовать как подтверждение READY.
4. Не подтверждены на текущей проверке: чистая установка, новый OAuth login, ChatBridge+Watcher E2E, update/rollback, изолированный полный тестовый прогон, `git status`, Git-коммит и source manifest.
5. Регрессионный тест обновления нативного GUI с сохранением TCC доверия отсутствует в текущем протоколе. Нельзя утверждать, что проблема исправлена навсегда.

## Операционный блокер и разрешённый безопасный следующий шаг

- Git-инструмент для `project=workspace` возвращает «Selected project is not a Git repository»; поддерживаемый проект указывает на родительский `AgentWorkspace`, а репозиторий лежит в `workspace/projects/mac-control-mcp-server`.
- `terminal_capabilities.enabled=false`; через `project_task(task=pytest)` тесты не стартуют: «pytest requires the project's .venv/bin/python». Поэтому свежий локальный прогон и проверка коммитов сейчас не выполнены.
- После разрешённого открытия локального терминала: прочитать `.planning` и Git статус, сверить все E0–E9 по реальным коммитам/тестам; внести доказуемые изменения в план, спецификацию (только административный статус без изменения требований), release gates и backlog; выполнить изолированные тесты; сделать Git-коммит. Не изменять установленную production-службу, Funnel, старый MCP, OAuth или TCC без отдельного решения.

**Gate:** E9 не закрыт; E10 и публичный релиз не разрешены этим аудитом.

## Повторная проверка E9 (2026-11-02, актуальнее исходных замечаний выше)

- Источник состояния: приватная .planning/roadmap.md и .planning/progress.md, выведенные владельцем в этот чат. E0–E8 COMPLETE; E9 ACTIVE; E10 PENDING. Подтверждён Git-коммит 8cdba98 на ветке feature/installer-full-capabilities.
- Новый полный тестовый прогон через старый Mac Control: 547 tests, OK (skipped=1), exit_code=0.
- Native GUI в новой установленной версии: Accessibility=true, Screen Recording=true; AX GUI Tree реально прочитан через MCP. Ранее разрешение потребовало удалить и заново добавить запись приложения. Сохранение TCC при следующем upgrade ещё не проверено.
- scripts/release_preflight.py --json прошёл с exit_code=0: ready_for_guided_install=true. Публичную HTTPS-доступность этот preflight не подтверждает.
- Штатный установленный launcher ~/MacControlMCP/bin/maccontrol status работает, exit_code=0. Старый активный релиз source-fad16f1af4ff пока не поддерживает doctor, предусмотренный новой веткой. Ошибка от запуска current/bin/maccontrol не является неисправностью поддерживаемого launcher.
- Source audit (scripts/release_audit.py --strict) заблокирован системой безопасности OpenAI до выполнения; не повторялся. Не считать gate выполненным.
- Старый Watcher доступен через MCP; это не подтверждение полноценного E2E новой связки ChatBridge+Watcher.
- Исторические 541 тест и формулировки «не выполнена проверка Git» выше заменены новыми результатами. Полное E9 ещё открыто: source audit, TCC upgrade, ChatBridge-auth, Watcher E2E, реальный OAuth, upgrade/rollback, RC/package parity.
- Временный каталог unused/ не включать в коммит до выяснения происхождения. Другие службы, Funnel, production и данные OAuth не изменялись.

**Решение:** E9 PARTIAL; E10 не начинать до полного gate и отдельного согласования выпуска.
