# Mac Control MCP Server — draft GitHub Beta release description

**Language:** [English](#english) · [Русский](#русский)

## English

**Switch language:** [Русский](#русский)

Mac Control MCP Server gives an owner-authorized AI agent broad capabilities on macOS through MCP: filesystem, terminal, Git, SSH, native GUI automation, service control, and background browser operations through **ChatBridge**.

- **Workspace-first:** one default directory for agent-created projects, logs, temporary files and results.
- **Native GUI:** separate optional GUI helper with owner-approved macOS permissions.
- **Independent ChatBridge dependency:** Mac Control uses ChatBridge's HTTP Browser API, never owns Chrome. ChatBridge must be published separately **first**; Mac Control can install it from a reviewed standalone release checkout.
- **Remote access:** individual GitHub OAuth Apps, Tailscale Funnel, HTTPS and explicit owner authorization.
- **Safe lifecycle:** versioned installation, update, rollback and removal preserving data.
- **Open source:** MIT License, copyright © 2026 Ivan Konstantinov.

**Beta acceptance still required:** independent installation on an unrelated Mac, real GitHub OAuth sign-in, external Funnel access, macOS Accessibility/Screen Recording permissions and final public source-provenance review. This is not a production certification.

## Русский

**Переключить язык:** [English](#english)

Mac Control MCP Server предоставляет авторизованному ИИ-агенту широкие возможности управления macOS через MCP: файлы, терминал, Git, SSH, нативный интерфейс, службы и браузерные операции через **ChatBridge**.

- **Единая рабочая директория:** проекты, временные файлы, логи и результаты агентов хранятся в одном каталоге.
- **Нативный GUI:** дополнительное приложение-помощник с разрешениями macOS, выдаваемыми владельцем.
- **Отдельный ChatBridge:** Mac Control использует его HTTP Browser API и не запускает собственный Chrome. ChatBridge публикуется **раньше** и может устанавливаться из проверенного отдельного релиза.
- **Удалённый доступ:** личное GitHub OAuth App, Tailscale Funnel, HTTPS и явное разрешение владельца.
- **Установка и обслуживание:** версии, обновление, откат, удаление с сохранением данных.
- **Открытые исходники:** MIT License, © 2026 Ivan Konstantinov.

**Что ещё проверить перед Beta:** независимую установку на другом Mac, реальный вход через GitHub OAuth, внешний Funnel, разрешения Accessibility/Screen Recording и чистоту публичного Git-репозитория. Это пока не подтверждение промышленной готовности.

## v0.1.0-beta.16 — production tool parity and portable Watcher

- Port maintenance tools and the static compatibility dispatcher, retaining workspace and CAS restrictions.
- Include current Watcher file reports, marker-based chat resolution, scheduled checks and browser-task followups through ChatBridge HTTP.
- Provision the owned Watcher login service with default installation; stop/restart it safely on update, rollback and uninstall.
- Preserve metadata-only audit logging and separate all runtime state from release code.
- Live ChatGPT delivery on the upgraded Mac is a separate beta acceptance step; automated tests do not sign in or send real messages.
