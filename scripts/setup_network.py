#!/usr/bin/env python3
"""Owner-guided remote connectivity and Tailscale Funnel setup.

All diagnoses and instructions are read-only. Enabling Funnel is a separate
explicit, interactive command; no public endpoint is enabled by installation.
"""
from __future__ import annotations
import argparse
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

try:
    from .setup_language import detect_language, text
    from .release_preflight import inspect
    from .setup_github_oauth import check as check_oauth, public_origin
except ImportError:  # Allow direct execution: python scripts/setup_network.py
    from setup_language import detect_language, text
    from release_preflight import inspect
    from setup_github_oauth import check as check_oauth, public_origin

DEFAULT_ROOT = Path.home() / "Library/Application Support/MacControl/MCPServer"
PORT = 3201


def run(argv: list[str], timeout: int = 12) -> subprocess.CompletedProcess:
    return subprocess.run(argv, text=True, capture_output=True, timeout=timeout,
                          check=False, env={**os.environ, "TAILSCALE_BE_CLI": "1"})


def tailscale_cli() -> str | None:
    """Locate CLI in PATH or inside the official macOS GUI app.

    Both App Store and Standalone variants can expose HTTP ports through
    Funnel. No separate tailscaled daemon or symlink is required.
    """
    executable = shutil.which("tailscale")
    if executable:
        return executable
    for app in (Path("/Applications/Tailscale.app"),
                Path.home() / "Applications/Tailscale.app"):
        embedded = app / "Contents/MacOS/Tailscale"
        if embedded.is_file() and os.access(embedded, os.X_OK):
            return str(embedded)
    return None


def tailscale_state() -> dict:
    executable = tailscale_cli()
    if not executable:
        return {"installed": False, "logged_in": False}
    version = run([executable, "version"])
    status = run([executable, "status", "--json"])
    if status.returncode != 0:
        return {"installed": True, "logged_in": False,
                "version": (version.stdout.splitlines() or ["unknown"])[0]}
    try:
        data = json.loads(status.stdout)
    except ValueError:
        data = {}
    device = data.get("Self") if isinstance(data.get("Self"), dict) else {}
    return {
        "installed": True, "logged_in": data.get("BackendState") == "Running",
        "device_dns_name": str(device.get("DNSName", "")).rstrip("."),
        "backend_state": data.get("BackendState", "unknown"),
        "version": (version.stdout.splitlines() or ["unknown"])[0],
        "cli_path": executable,
        "tailscale_ips": device.get("TailscaleIPs", []),
    }


def publication_state(executable: str, hostname: str, *, language: str = "ru") -> dict:
    """Read both views; accept only an empty or exactly matching publication.

    ServeConfig fields: https://github.com/tailscale/tailscale/blob/main/ipn/serve.go
    Unknown, foreground, service and additional routes require owner review.
    """
    configs = []
    for command in ("funnel", "serve"):
        try:
            result = run([executable, command, "status", "--json"])
            if result.returncode != 0:
                return {"status": "unreadable", "reason": command + text(language, ' status failed', ' status завершилась с ошибкой')}
            config = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return {"status": "unreadable", "reason": command + text(language, ' status is unavailable or returned invalid JSON', ' status недоступен или вернул некорректный JSON')}
        if config is None:
            config = {}
        if not isinstance(config, dict):
            return {"status": "unreadable", "reason": command + text(language, ' status returned an unknown format', ' status вернул неизвестный формат')}
        # Only documented empty optional maps can be omitted during comparison.
        for key in ("TCP", "Web", "AllowFunnel", "Services", "Foreground"):
            if key in config and config[key] in ({}, None):
                del config[key]
        configs.append(config)
    if json.dumps(configs[0], sort_keys=True) != json.dumps(configs[1], sort_keys=True):
        return {"status": "conflict", "reason": text(language, 'Funnel and Serve configurations do not match', 'Конфигурации Funnel и Serve не совпадают')}
    if not configs[0]:
        return {"status": "empty"}
    target = hostname + ":443"
    expected = {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {target: {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{PORT}"}}}},
        "AllowFunnel": {target: True},
    }
    # JSON comparison distinguishes required booleans from numeric 0/1.
    if json.dumps(configs[0], sort_keys=True) == json.dumps(expected, sort_keys=True):
        return {"status": "existing_matching", "public_url": "https://" + hostname}
    return {"status": "conflict", "reason": text(language, 'Existing routes do not exactly match HTTPS for Mac Control on local port 3201', 'Существующие маршруты не соответствуют точно HTTPS для Mac Control на локальном порту 3201')}


def assert_public_route_safe_for_uninstall(root: Path, *, known_remote_service: bool = False,
                                          input_fn=input) -> dict:
    """Keep the owned service alive until its public forwarding is disabled.

    The caller establishes service ownership before setting known_remote_service.
    This guard never changes Tailscale, reverse proxies, routers or launchd.
    """
    config_path = root.expanduser() / "data/remote_auth.json"
    configured = None
    if config_path.exists() or config_path.is_symlink():
        try:
            configured = check_oauth(root)
        except (OSError, ValueError, RuntimeError):
            raise RuntimeError("Не удалось проверить сохранённую OAuth-конфигурацию; перед остановкой сервиса проверьте публичные маршруты вручную") from None
    elif not known_remote_service:
        return {"status": "not_applicable"}
    origin = configured["public_url"].rstrip("/") if configured else ""
    hostname = urlsplit(origin).hostname or ""
    if configured and not hostname.endswith(".ts.net"):
        if not known_remote_service:
            return {"status": "not_applicable"}
        print("Перед остановкой Mac Control отключите его публичный маршрут на HTTPS-прокси.")
        print("Уберите проброс TCP 443 только если им не пользуются другие сайты и сервисы.")
        print(f"Удалите только маршрут {origin} к 127.0.0.1:{PORT}, сохранив чужие сайты и маршруты.")
        print("Иначе после удаления другой процесс на локальном порту 3201 может стать доступен из интернета.")
        if not sys.stdin.isatty():
            raise RuntimeError("Нужно интерактивное подтверждение владельца: публичный proxy/port-forward отключён")
        if input_fn("После отключения этого публичного маршрута введите DISABLED для продолжения удаления: ") != "DISABLED":
            raise RuntimeError("Отключение публичного proxy/port-forward не подтверждено; сервис сохранён")
        return {"status": "owner_confirmed_proxy_disabled"}
    instructions = (
        "Проверьте `tailscale funnel status --json` и `tailscale serve status --json`; "
        f"найдите маршрут {origin or 'Mac Control'} к http://127.0.0.1:{PORT} и вручную отключите только его. "
        "Если оба статуса подтверждают, что это единственный маршрут HTTPS 443, используйте "
        "`tailscale funnel --https=443 off`; при других маршрутах сначала разберите их вручную. "
        "Не выполняйте reset и не удаляйте чужие маршруты. Затем повторите удаление Mac Control."
    )
    executable = tailscale_cli()
    if not executable:
        raise RuntimeError("Tailscale CLI недоступен; отсутствие публичного маршрута не подтверждено. " + instructions)
    state = publication_state(executable, hostname)
    if state["status"] != "empty":
        raise RuntimeError("Остановка/удаление запрещены до отключения публичного маршрута 3201. " + instructions)
    return {"status": "no_active_routes"}


def _guided_tailscale(local: dict) -> dict:
    try:
        state = tailscale_state()
    except (OSError, subprocess.TimeoutExpired, ValueError):
        state = {"installed": False, "logged_in": False,
                 "error": "Tailscale CLI status is unavailable"}
    local_ips = {value for family in ("ipv4", "ipv6")
                 for value in local.get("local_addresses", {}).get(family, [])}
    state["interface_verified"] = bool(local_ips.intersection(state.get("tailscale_ips", [])))
    return state


def guided_network(root: Path, *, network: bool = True, input_fn=input, language: str = "ru") -> dict:
    """Select a remote HTTPS route without changing network or service state.

    A ready_for_oauth result is input for owner-led OAuth setup, not proof of
    incoming connectivity. Publication remains a separate guarded action.
    """
    base = inspect(network=network)
    ipv4 = []
    for value in base.get("local_addresses", {}).get("ipv4", []):
        try:
            ipv4.append(ipaddress.IPv4Address(value))
        except ValueError:
            continue
    private = any(ip in ipaddress.ip_network(cidr) for ip in ipv4
                  for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    shared = any(ip in ipaddress.ip_network("100.64.0.0/10") for ip in ipv4)
    echo = base.get("external_ipv4", {})
    report = {
        "schema": 1, "status": "manual_setup_required",
        "incoming_reachable": "not_tested", "external_connectivity_verified": False,
        "publication_performed": False,
        "ip_signal": {"private_ipv4_present": private, "shared_ipv4_present": shared,
                      "external_ipv4_checked": "address" in echo,
                      "external_ipv6_checked": "address" in base.get("external_ipv6", {})},
    }
    print(text(language, 'Network checks complete; network settings were not changed.', 'Проверка сети завершена; настройки сети не изменялись.'))
    print(text(language, 'External IP lookup response: ', 'Ответ внешнего сервиса определения IP: ') + (text(language, 'received', 'получен') if "address" in echo else text(language, 'unavailable or check skipped', 'недоступен или проверка пропущена')))
    print(text(language, 'Private local IPv4: ', 'Локальный частный IPv4: ') + (text(language, 'detected', 'обнаружен') if private else text(language, 'not detected', 'не обнаружен')))
    print(text(language, 'Shared IPv4 address in 100.64.0.0/10: ', 'Адрес IPv4 из общего диапазона 100.64.0.0/10: ') + (text(language, 'detected', 'обнаружен') if shared else text(language, 'not detected', 'не обнаружен')))
    print(text(language, 'Private and shared addresses can indicate NAT or VPN; they cannot confirm ISP CGNAT.', 'Частные и общие адреса могут указывать на NAT или VPN; они не позволяют подтвердить CGNAT у провайдера.'))
    print(text(language, 'An external public IP response does not prove incoming HTTPS is reachable, even when it matches the local IP.', 'Ответ внешнего сервиса с публичным IP не доказывает доступность входящего HTTPS, даже при совпадении с локальным IP.'))
    print(text(language, 'Ask your ISP about a public IP and check incoming HTTPS from another network.', 'Уточните у провайдера наличие белого IP и проверьте входящий HTTPS из другой сети.'))
    while True:
        answer = input_fn(text(language, 'Do you have a public IP with reachable incoming HTTPS? [yes/no/unknown/quit]: ', 'У вас есть белый (публичный) IP с доступным входящим HTTPS? [да/нет/не знаю/выход]: ')).strip().casefold()
        answer = {"да": "yes", "д": "yes", "нет": "no", "н": "no",
                  "не знаю": "unknown", "выход": "quit", "в": "quit"}.get(answer, answer)
        if answer in ("yes", "y", "no", "n", "unknown", "don't know", "quit", "q"):
            break
        print(text(language, 'Enter yes, no, unknown or quit (Russian equivalents are also accepted).', 'Введите «да», «нет», «не знаю» или «выход» (yes/no/unknown/quit также принимаются).'))
    if answer in ("quit", "q"):
        return {**report, "status": "cancelled"}
    if answer in ("yes", "y"):
        print(text(language, 'Use a public HTTPS domain with a trusted TLS certificate.', 'Используйте публичный HTTPS-домен с доверенным TLS-сертификатом.'))
        print(text(language, 'After configuring OAuth and verifying anonymous HTTP 401 responses, configure an HTTPS reverse proxy', 'После настройки OAuth и проверки анонимного ответа HTTP 401 настройте обратный HTTPS-прокси'))
        print(text(language, 'on TCP 443 and forward TCP 443 to that proxy on your router, if used.', 'на TCP 443 и проброс TCP 443 к этому прокси на маршрутизаторе, если он используется.'))
        print(text(language, f"Mac Control must listen only on 127.0.0.1:{PORT}; proxy HTTPS to this local service.",
                   f"Mac Control должен слушать только 127.0.0.1:{PORT}; проксируйте HTTPS на этот локальный сервис."))
        print(text(language, 'Proxy all paths on this HTTPS domain, including /mcp, /.well-known/ and /auth/callback.', 'Проксируйте все пути этого HTTPS-домена, включая /mcp, /.well-known/ и /auth/callback.'))
        print(text(language, 'TCP 80 is needed only for HTTP-01 certificate validation or HTTP to HTTPS redirects.', 'TCP 80 нужен только при необходимости HTTP-01 для сертификата или перенаправления HTTP на HTTPS.'))
        print(text(language, f"Do not forward TCP {PORT} on the router or expose it on a LAN or public interface.",
                   f"Не пробрасывайте TCP {PORT} на маршрутизаторе и не открывайте его на LAN или публичном интерфейсе."))
        while True:
            value = input_fn(text(language, 'Public HTTPS domain URL (https://control.example.com) or quit: ', 'Публичный HTTPS-адрес домена (https://control.example.com) или «выход»: ')).strip()
            if value.casefold() in ("quit", "q", "выход", "в"):
                return {**report, "status": "cancelled"}
            try:
                origin = public_origin(value)
                parsed = urlsplit(origin)
                host = parsed.hostname or ""
                try:
                    ipaddress.ip_address(host)
                except ValueError:
                    is_domain = "." in host and all(
                        label and len(label) <= 63 and label[0].isalnum() and label[-1].isalnum()
                        and all(c.isascii() and (c.isalnum() or c == "-") for c in label)
                        for label in host.split("."))
                else:
                    is_domain = False
                if not is_domain or parsed.port not in (None, 443):
                    raise ValueError(text(language, 'Provide an HTTPS domain on TCP 443', 'Укажите HTTPS-домен на TCP 443'))
                break
            except ValueError:
                print(text(language, 'Provide a public HTTPS domain on TCP 443, without a path or credentials.', 'Укажите публичный HTTPS-домен на TCP 443, без пути и учётных данных.'))
        return {**report, "status": "ready_for_oauth", "route": "direct_https",
                "public_url": origin, "requires_owner_https_setup": True}

    report["route"] = "tailscale_funnel"
    state = _guided_tailscale(base)
    def ready() -> bool:
        return bool(state.get("installed") and state.get("logged_in") and
                    state.get("cli_path") and state.get("interface_verified") and
                    state.get("device_dns_name", "").endswith(".ts.net"))
    if not ready():
        print(text(language, 'A connected Tailscale client and its matching local network interface are required.', 'Нужны подключённый клиент Tailscale и соответствующий локальный сетевой интерфейс.'))
        print(text(language, 'If needed, manually install the official macOS client:', 'При необходимости вручную установите официальный клиент для macOS:'))
        print("https://tailscale.com/docs/install/mac")
        print(text(language, 'Create a Tailscale account if needed, sign in and approve macOS network permissions.', 'Создайте учётную запись Tailscale, если её нет, войдите в неё и подтвердите сетевые разрешения macOS.'))
        print(text(language, 'The wizard does not change existing VPNs, default routes or Exit Node selection.', 'Мастер не изменяет существующие VPN, маршруты по умолчанию и выбор Exit Node.'))
    while not ready():
        answer = input_fn(text(language, 'After completing these steps, enter READY to check again; Enter to continue later: ', 'После выполнения этих шагов введите READY или «ГОТОВО» для повторной проверки; Enter — продолжить позже: ')).strip().casefold()
        if answer not in ("ready", "готово"):
            return {**report, "tailscale": state}
        state = _guided_tailscale(inspect(network=False))
        if not ready():
            print(text(language, 'The Tailscale client or interface is not verified yet; check the manual steps and enter READY again or defer setup.', 'Клиент или интерфейс Tailscale пока не подтверждён; проверьте ручные шаги и повторите READY или отложите настройку.'))
    existing = publication_state(state["cli_path"], state["device_dns_name"], language=language)
    report.update({"tailscale": state, "publication_state": existing})
    if existing["status"] not in ("empty", "existing_matching"):
        print(text(language, 'The existing Funnel/Serve configuration cannot be safely used: ', 'Нельзя безопасно использовать существующую конфигурацию Funnel/Serve: ') + existing["reason"])
        print(text(language, 'Review it manually; the wizard made no changes.', 'Проверьте её вручную; мастер не вносил изменений.'))
        return report
    if existing["status"] == "existing_matching":
        print(text(language, 'The existing Funnel route exactly matches Mac Control; it will be reused without replacement.', 'Существующий маршрут Funnel точно соответствует Mac Control; он будет использован без замены.'))
    print(text(language, 'The Tailscale client is running and its assigned IP was found on a local interface.', 'Клиент Tailscale работает, его назначенный IP найден на локальном интерфейсе.'))
    print(text(language, 'This does not prove internet reachability: public HTTPS is checked later from an external network.', 'Это не доказывает доступность из интернета: публичный HTTPS проверяется позже из внешней сети.'))
    print(text(language, 'Next, configure GitHub OAuth for this URL:', 'Далее настройте GitHub OAuth для адреса:'))
    origin = "https://" + state["device_dns_name"]
    print(origin)
    print(text(language, 'Your Tailscale network may require MagicDNS, HTTPS and owner authorization for Funnel.', 'В вашей сети Tailscale могут потребоваться MagicDNS, HTTPS и разрешение владельца на Funnel.'))
    print(text(language, 'Publication requires configured OAuth, an anonymous HTTP 401 response and separate owner confirmation with PUBLISH.', 'Для публикации нужны настроенный OAuth, анонимный ответ HTTP 401 и отдельное подтверждение владельца PUBLISH.'))
    print("https://tailscale.com/docs/reference/tailscale-cli/funnel")
    return {**report, "status": "ready_for_oauth", "public_url": origin}


def diagnose(*, network: bool = False) -> dict:
    base = inspect(network=network)
    ts = tailscale_state()
    # Local interface addresses alone cannot prove public inbound access.
    eligible = base.get("locally_global_ip_candidates", [])
    outcome = "verification_required"
    if not eligible:
        outcome = "no_globally_routable_local_interface_address"
    return {
        "schema": 1,
        "incoming_reachable": "not_tested",
        "local_ip_signal": outcome,
        "public_ip_verified": False,
        "public_ipv4_echo": base["external_ipv4"],
        "public_ipv6_echo": base["external_ipv6"],
        "tailscale": ts,
        "recommendation": (
            "Mac Control's supported guided remote deployment is Tailscale Funnel. "
            "It provides public HTTPS without a public IP and does not require "
            "changes to default routes, existing VPN connections, or exit-node settings. "
            "CGNAT and inbound reachability cannot be determined from IP echo alone."
        ),
        "funnel_requires": [
            "Authenticated Tailscale client, MagicDNS and HTTPS on tailnet",
            "Owner authorization for funnel node attribute",
            "Existing Mac Control remote OAuth configuration and anonymous 401",
            "Explicit owner approval before opening a public HTTPS endpoint",
            "External-client test of HTTPS and real GitHub OAuth",
        ],
    }


def guide(*, language: str = "en") -> None:
    print(text(language, 'Mac Control remote connection (no verified public inbound IP/port):', 'Удалённое подключение Mac Control (публичный входящий IP/порт не подтверждён):'))
    print(text(language, '1. Confirm whether public IPv4/IPv6 with incoming HTTPS is actually reachable.', '1. Проверьте доступность публичного IPv4/IPv6 с входящим HTTPS.'))
    print(text(language, '   Public IP echo alone does not prove inbound access; CGNAT may exist.', '   Ответ сервиса определения IP не доказывает входящую доступность; возможен CGNAT.'))
    print(text(language, '2. Use the existing Tailscale app if installed (App Store or Standalone).', '2. Используйте установленное приложение Tailscale (App Store или Standalone).'))
    print(text(language, '   If absent, install the official macOS client:', '   Если его нет, установите официальный клиент для macOS:'))
    print("   https://tailscale.com/docs/install/mac")
    print(text(language, '3. Log in to Tailscale and approve macOS networking permissions.', '3. Войдите в Tailscale и подтвердите сетевые разрешения macOS.'))
    print(text(language, '   The installer detects the CLI inside Tailscale.app when not in PATH.', '   Установщик найдёт CLI внутри Tailscale.app, если его нет в PATH.'))
    print(text(language, '   Existing VPN connections, routes and Exit Node selections are untouched.', '   Существующие VPN, маршруты и выбор Exit Node не изменяются.'))
    print(text(language, '4. Enable MagicDNS / HTTPS and Funnel for this device in your tailnet.', '4. Включите MagicDNS / HTTPS и Funnel для этого устройства в вашей сети Tailscale.'))
    print(text(language, '   Tailscale prompts for web approval as needed (owner performs login).', '   При необходимости Tailscale запросит подтверждение в браузере (владелец входит сам).'))
    print(text(language, '5. Configure your own GitHub OAuth App in Mac Control using the resulting', '5. Настройте своё приложение GitHub OAuth в Mac Control для полученного адреса:'))
    print(text(language, '   HTTPS origin: https://YOUR-DEVICE.YOUR-TAILNET.ts.net', '   HTTPS-адрес: https://YOUR-DEVICE.YOUR-TAILNET.ts.net'))
    print(text(language, '   callback: https://YOUR-DEVICE.YOUR-TAILNET.ts.net/auth/callback', '   Адрес возврата: https://YOUR-DEVICE.YOUR-TAILNET.ts.net/auth/callback'))
    print(text(language, "6. Start Mac Control's AUTHENTICATED loopback service on 127.0.0.1:3201.", '6. Запустите локальный сервис Mac Control С АВТОРИЗАЦИЕЙ на 127.0.0.1:3201.'))
    print(text(language, '7. Confirm unauthenticated /mcp requests return HTTP 401.', '7. Убедитесь, что запросы к /mcp без авторизации возвращают HTTP 401.'))
    print(text(language, "8. Run this guide's --enable-funnel with explicit owner consent.", '8. Запустите этот скрипт с --enable-funnel и явным подтверждением владельца.'))
    print(text(language, '   Underlying Tailscale CLI command: tailscale funnel --bg 3201', '   Используемая команда Tailscale CLI: tailscale funnel --bg 3201'))
    print(text(language, '9. Check tailscale funnel status, external HTTPS and actual GitHub OAuth.', '9. Проверьте tailscale funnel status, HTTPS из внешней сети и вход через GitHub OAuth.'))
    print(text(language, '   Tailscale Serve is tailnet-only; Funnel is public HTTPS.', '   Tailscale Serve доступен только в сети Tailscale; Funnel предоставляет публичный HTTPS.'))
    print(text(language, '   DO NOT expose the unauthenticated DEV preview port 3101.', '   НЕ открывайте доступ к порту DEV-просмотра 3101 без авторизации.'))
    print(text(language, 'Docs: https://tailscale.com/docs/features/tailscale-funnel', 'Документация: https://tailscale.com/docs/features/tailscale-funnel'))
    print("      https://tailscale.com/docs/reference/tailscale-cli/funnel")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def funnel_tls_diagnostics(*, language: str = "ru") -> dict:
    """Check ACME HTTPS from this process without requesting a certificate."""
    directory = "https://acme-v02.api.letsencrypt.org/directory"
    reachable = False
    try:
        # Keep default TLS verification and this process's proxy behavior;
        # neither is evidence of the separate daemon's connectivity.
        opener = urllib.request.build_opener(_NoRedirect())
        request = urllib.request.Request(directory, headers={"Accept": "application/json"})
        with opener.open(request, timeout=8) as response:
            reachable = response.status == 200
    except urllib.error.HTTPError as exc:
        exc.close()
    except (OSError, ValueError):
        # Proxy/transport exceptions can contain credentials; never display them.
        pass
    print(text(language,
        "Let's Encrypt ACME HTTPS is reachable from the setup process." if reachable else
        "The setup process could not reach Let's Encrypt ACME HTTPS.",
        "HTTPS Let's Encrypt ACME доступен из процесса настройки." if reachable else
        "Из процесса настройки не удалось проверить доступ к HTTPS Let's Encrypt ACME."))
    print(text(language,
        "Tailscale may use a different network or proxy; this check does not verify daemon connectivity or certificate issuance.",
        "Tailscale может использовать другую сеть или прокси; эта проверка не подтверждает доступ из демона или выдачу сертификата."))
    print(text(language,
        "Check Tailscale logs for ACME/certificate errors and its TLS certificate status in the admin console. Verify daemon access to " + directory + ", then retry --setup.",
        "Проверьте журнал Tailscale на ошибки ACME/сертификата и статус TLS-сертификата в консоли администратора. Проверьте доступ демона к " + directory + ", затем повторите --setup."))
    print(text(language,
        "No certificate was requested and network settings were not changed.",
        "Сертификат не запрашивался, настройки сети не изменялись."))
    return {"status": "acme_reachable_from_setup" if reachable else "acme_unreachable_from_setup",
            "daemon_connectivity_verified": False}


def _oauth_guard(root: Path, *, language: str = "ru") -> dict:
    configured = check_oauth(root)
    # Probe this Mac directly: inherited proxy settings and redirects must not
    # substitute a remote issuer or authentication challenge for the loopback app.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    local = f"http://127.0.0.1:{PORT}"
    metadata_request = urllib.request.Request(
        local + "/.well-known/oauth-authorization-server",
        headers={"Accept": "application/json"},
    )
    try:
        with opener.open(metadata_request, timeout=5) as response:
            payload = response.read(65537)
        if len(payload) > 65536:
            raise ValueError("OAuth metadata exceeds size limit")
        metadata = json.loads(payload)
        issuer = metadata.get("issuer") if isinstance(metadata, dict) else None
        # FastMCP serializes an origin issuer with a terminal slash. Normalize
        # that slash only; paths, queries and different origins remain unequal.
        if not isinstance(issuer, str) or issuer.rstrip("/") != configured["public_url"].rstrip("/"):
            raise ValueError("OAuth issuer does not match configured origin")
    except urllib.error.HTTPError as exc:
        exc.close()
        raise RuntimeError(text(language, 'Local OAuth metadata is unavailable; redirects are forbidden', 'Локальные OAuth metadata недоступны; перенаправления запрещены')) from None
    except (OSError, ValueError) as exc:
        raise RuntimeError(text(language, 'Could not verify the local OAuth issuer and metadata size', 'Не удалось проверить локальный OAuth issuer и размер metadata')) from exc
    request = urllib.request.Request(
        local + "/mcp", method="POST",
        headers={"Content-Type": "application/json"},
        data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
    )
    try:
        with opener.open(request, timeout=5) as response:
            status = response.status
            challenge = bool(response.headers.get("WWW-Authenticate"))
    except urllib.error.HTTPError as exc:
        try:
            status = exc.code
            challenge = bool(exc.headers.get("WWW-Authenticate"))
        finally:
            exc.close()
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(text(language, 'The authenticated local Mac Control server is unavailable', 'Локальный сервер Mac Control с авторизацией недоступен')) from exc
    if status != 401 or not challenge:
        raise RuntimeError(text(language, 'Publication blocked: the anonymous local MCP request did not return HTTP 401 with an OAuth challenge', 'Публикация запрещена: анонимный запрос к локальному MCP не вернул HTTP 401 с OAuth challenge'))
    return configured


def enable_funnel(root: Path, *, input_fn=input, language: str = "ru") -> dict:
    executable = tailscale_cli()
    ts = tailscale_state()
    if not executable or not ts.get("logged_in"):
        raise RuntimeError(text(language, 'Install Tailscale and sign in to your account first', 'Сначала установите Tailscale и войдите в свою учётную запись'))
    hostname = ts.get("device_dns_name", "")
    if not hostname.endswith(".ts.net"):
        raise RuntimeError(text(language, 'The Tailscale device domain name is unavailable; configure MagicDNS and HTTPS', 'Доменное имя устройства Tailscale недоступно; настройте MagicDNS и HTTPS'))
    configured = _oauth_guard(root, language=language)
    expected = "https://" + hostname
    if configured["public_url"].rstrip("/") != expected:
        raise RuntimeError(text(language, 'The GitHub OAuth HTTPS URL does not match the Tailscale device URL', 'HTTPS-адрес в настройках GitHub OAuth не совпадает с адресом устройства Tailscale'))
    existing = publication_state(executable, hostname, language=language)
    if existing["status"] not in ("empty", "existing_matching"):
        raise RuntimeError(text(language, 'Refusing to change the existing Funnel/Serve configuration: ', 'Отказ от изменения существующей конфигурации Funnel/Serve: ') + existing["reason"])
    report = {
        "public_url": expected,
        "port": PORT,
        "external_connectivity_verified": False,
        "github_oauth_login_verified": False,
        "next": text(language, 'Check tailscale funnel status and public OAuth from an external MCP client', 'Проверьте tailscale funnel status и публичный OAuth из внешнего MCP-клиента'),
    }
    if existing["status"] == "existing_matching":
        return {**report, "status": "existing_funnel_reused"}
    if not sys.stdin.isatty():
        raise RuntimeError(text(language, 'Interactive owner confirmation in Terminal is required', 'Нужно интерактивное подтверждение владельца в Терминале'))
    print(text(language, 'WARNING: Funnel will publish the authenticated Mac Control HTTP service on the internet.', 'ВНИМАНИЕ: Funnel опубликует в интернете HTTP-сервис Mac Control, защищённый авторизацией.'))
    print(text(language, 'Public HTTPS URL:', 'Публичный HTTPS-адрес:'), expected)
    print(text(language, 'Allowed account IDs:', 'ID разрешённых учётных записей:'), ", ".join(configured["allowed_github_ids"]))
    if input_fn(text(language, 'Enter PUBLISH to enable public HTTPS through Funnel on this Mac: ', 'Введите PUBLISH, чтобы включить публичный HTTPS через Funnel на этом Mac: ')) != "PUBLISH":
        raise RuntimeError(text(language, 'The owner did not confirm internet publication', 'Владелец не подтвердил публикацию в интернете'))
    current_oauth = _oauth_guard(root, language=language)
    if (current_oauth["public_url"].rstrip("/") != expected or
            set(current_oauth["allowed_github_ids"]) != set(configured["allowed_github_ids"])):
        raise RuntimeError(text(language, 'The OAuth origin or allowed owners changed while waiting; publication is blocked', 'OAuth origin или разрешённые владельцы изменились за время ожидания; публикация запрещена'))
    # The owner may spend time reviewing; do not overwrite routes created then.
    current = publication_state(executable, hostname, language=language)
    if current["status"] == "existing_matching":
        return {**report, "status": "existing_funnel_reused"}
    if current["status"] != "empty":
        raise RuntimeError(text(language, 'The Funnel/Serve configuration changed while waiting for confirmation; no changes were made', 'Конфигурация Funnel/Serve изменилась за время ожидания подтверждения; изменения не внесены'))
    outcome = run([executable, "funnel", "--bg", str(PORT)], timeout=50)
    if outcome.returncode != 0:
        raise RuntimeError(text(language, 'Could not configure Tailscale Funnel; check tailscale funnel status', 'Не удалось настроить Tailscale Funnel; проверьте tailscale funnel status'))
    verified = publication_state(executable, hostname, language=language)
    if verified["status"] != "existing_matching":
        raise RuntimeError(text(language, 'Could not verify the Funnel configuration after publication; check its status manually', 'Не удалось проверить конфигурацию Funnel после публикации; проверьте состояние вручную'))
    return {**report, "status": "funnel_command_succeeded"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--language", choices=("en", "ru"), default=detect_language(),
                        help="Language for interactive setup (defaults to system language)")
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--diagnose", action="store_true")
    choices.add_argument("--guide", action="store_true")
    choices.add_argument("--guided", action="store_true",
                         help="Interactive read-only remote HTTPS selection and Tailscale checks")
    choices.add_argument("--enable-funnel", action="store_true")
    parser.add_argument("--network", action="store_true",
                        help="Opt in to external IP echo lookups for diagnostics")
    args = parser.parse_args()
    if args.guide:
        guide(language=args.language)
    else:
        if args.guided:
            report = guided_network(args.root, network=True, language=args.language)
        else:
            report = enable_funnel(args.root, language=args.language) if args.enable_funnel else diagnose(network=args.network)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("Mac Control network setup failed:", type(exc).__name__,
              str(exc) if isinstance(exc, (RuntimeError, ValueError)) else "",
              file=sys.stderr)
        raise SystemExit(1)
