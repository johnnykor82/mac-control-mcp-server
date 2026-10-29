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
    from .release_preflight import inspect
    from .setup_github_oauth import check as check_oauth, public_origin
except ImportError:  # Allow direct execution: python scripts/setup_network.py
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


def publication_state(executable: str, hostname: str) -> dict:
    """Read both views; accept only an empty or exactly matching publication.

    ServeConfig fields: https://github.com/tailscale/tailscale/blob/main/ipn/serve.go
    Unknown, foreground, service and additional routes require owner review.
    """
    configs = []
    for command in ("funnel", "serve"):
        try:
            result = run([executable, command, "status", "--json"])
            if result.returncode != 0:
                return {"status": "unreadable", "reason": command + " status завершилась с ошибкой"}
            config = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return {"status": "unreadable", "reason": command + " status недоступен или вернул некорректный JSON"}
        if config is None:
            config = {}
        if not isinstance(config, dict):
            return {"status": "unreadable", "reason": command + " status вернул неизвестный формат"}
        # Only documented empty optional maps can be omitted during comparison.
        for key in ("TCP", "Web", "AllowFunnel", "Services", "Foreground"):
            if key in config and config[key] in ({}, None):
                del config[key]
        configs.append(config)
    if json.dumps(configs[0], sort_keys=True) != json.dumps(configs[1], sort_keys=True):
        return {"status": "conflict", "reason": "Конфигурации Funnel и Serve не совпадают"}
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
    return {"status": "conflict", "reason": "Существующие маршруты не соответствуют точно HTTPS для Mac Control на локальном порту 3201"}


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


def guided_network(root: Path, *, network: bool = True, input_fn=input) -> dict:
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
    print("Проверка сети завершена; настройки сети не изменялись.")
    print("Ответ внешнего сервиса определения IP: " + ("получен" if "address" in echo else "недоступен или проверка пропущена"))
    print("Локальный частный IPv4: " + ("обнаружен" if private else "не обнаружен"))
    print("Адрес IPv4 из общего диапазона 100.64.0.0/10: " + ("обнаружен" if shared else "не обнаружен"))
    print("Частные и общие адреса могут указывать на NAT или VPN; они не позволяют подтвердить CGNAT у провайдера.")
    print("Ответ внешнего сервиса с публичным IP не доказывает доступность входящего HTTPS, даже при совпадении с локальным IP.")
    print("Уточните у провайдера наличие белого IP и проверьте входящий HTTPS из другой сети.")
    while True:
        answer = input_fn("У вас есть белый (публичный) IP с доступным входящим HTTPS? [да/нет/не знаю/выход]: ").strip().casefold()
        answer = {"да": "yes", "д": "yes", "нет": "no", "н": "no",
                  "не знаю": "unknown", "выход": "quit", "в": "quit"}.get(answer, answer)
        if answer in ("yes", "y", "no", "n", "unknown", "don't know", "quit", "q"):
            break
        print("Введите «да», «нет», «не знаю» или «выход» (yes/no/unknown/quit также принимаются).")
    if answer in ("quit", "q"):
        return {**report, "status": "cancelled"}
    if answer in ("yes", "y"):
        print("Используйте публичный HTTPS-домен с доверенным TLS-сертификатом.")
        print("После настройки OAuth и проверки анонимного ответа HTTP 401 настройте обратный HTTPS-прокси")
        print("на TCP 443 и проброс TCP 443 к этому прокси на маршрутизаторе, если он используется.")
        print(f"Mac Control должен слушать только 127.0.0.1:{PORT}; проксируйте HTTPS на этот локальный сервис.")
        print("Проксируйте все пути этого HTTPS-домена, включая /mcp, /.well-known/ и /auth/callback.")
        print("TCP 80 нужен только при необходимости HTTP-01 для сертификата или перенаправления HTTP на HTTPS.")
        print(f"Не пробрасывайте TCP {PORT} на маршрутизаторе и не открывайте его на LAN или публичном интерфейсе.")
        while True:
            value = input_fn("Публичный HTTPS-адрес домена (https://control.example.com) или «выход»: ").strip()
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
                    raise ValueError("Укажите HTTPS-домен на TCP 443")
                break
            except ValueError:
                print("Укажите публичный HTTPS-домен на TCP 443, без пути и учётных данных.")
        return {**report, "status": "ready_for_oauth", "route": "direct_https",
                "public_url": origin, "requires_owner_https_setup": True}

    report["route"] = "tailscale_funnel"
    state = _guided_tailscale(base)
    def ready() -> bool:
        return bool(state.get("installed") and state.get("logged_in") and
                    state.get("cli_path") and state.get("interface_verified") and
                    state.get("device_dns_name", "").endswith(".ts.net"))
    if not ready():
        print("Нужны подключённый клиент Tailscale и соответствующий локальный сетевой интерфейс.")
        print("При необходимости вручную установите официальный клиент для macOS:")
        print("https://tailscale.com/docs/install/mac")
        print("Создайте учётную запись Tailscale, если её нет, войдите в неё и подтвердите сетевые разрешения macOS.")
        print("Мастер не изменяет существующие VPN, маршруты по умолчанию и выбор Exit Node.")
    while not ready():
        answer = input_fn("После выполнения этих шагов введите READY или «ГОТОВО» для повторной проверки; Enter — продолжить позже: ").strip().casefold()
        if answer not in ("ready", "готово"):
            return {**report, "tailscale": state}
        state = _guided_tailscale(inspect(network=False))
        if not ready():
            print("Клиент или интерфейс Tailscale пока не подтверждён; проверьте ручные шаги и повторите READY или отложите настройку.")
    existing = publication_state(state["cli_path"], state["device_dns_name"])
    report.update({"tailscale": state, "publication_state": existing})
    if existing["status"] not in ("empty", "existing_matching"):
        print("Нельзя безопасно использовать существующую конфигурацию Funnel/Serve: " + existing["reason"])
        print("Проверьте её вручную; мастер не вносил изменений.")
        return report
    if existing["status"] == "existing_matching":
        print("Существующий маршрут Funnel точно соответствует Mac Control; он будет использован без замены.")
    print("Клиент Tailscale работает, его назначенный IP найден на локальном интерфейсе.")
    print("Это не доказывает доступность из интернета: публичный HTTPS проверяется позже из внешней сети.")
    print("Далее настройте GitHub OAuth для адреса:")
    origin = "https://" + state["device_dns_name"]
    print(origin)
    print("В вашей сети Tailscale могут потребоваться MagicDNS, HTTPS и разрешение владельца на Funnel.")
    print("Для публикации нужны настроенный OAuth, анонимный ответ HTTP 401 и отдельное подтверждение владельца PUBLISH.")
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


def guide() -> None:
    print("Mac Control remote connection (no verified public inbound IP/port):")
    print("1. Confirm whether public IPv4/IPv6 with incoming HTTPS is actually reachable.")
    print("   Public IP echo alone does not prove inbound access; CGNAT may exist.")
    print("2. Use the existing Tailscale app if installed (App Store or Standalone).")
    print("   If absent, install the official macOS client:")
    print("   https://tailscale.com/docs/install/mac")
    print("3. Log in to Tailscale and approve macOS networking permissions.")
    print("   The installer detects the CLI inside Tailscale.app when not in PATH.")
    print("   Existing VPN connections, routes and Exit Node selections are untouched.")
    print("4. Enable MagicDNS / HTTPS and Funnel for this device in your tailnet.")
    print("   Tailscale prompts for web approval as needed (owner performs login).")
    print("5. Configure your own GitHub OAuth App in Mac Control using the resulting")
    print("   HTTPS origin: https://YOUR-DEVICE.YOUR-TAILNET.ts.net")
    print("   callback: https://YOUR-DEVICE.YOUR-TAILNET.ts.net/auth/callback")
    print("6. Start Mac Control's AUTHENTICATED loopback service on 127.0.0.1:3201.")
    print("7. Confirm unauthenticated /mcp requests return HTTP 401.")
    print("8. Run this guide's --enable-funnel with explicit owner consent.")
    print("   Underlying Tailscale CLI command: tailscale funnel --bg 3201")
    print("9. Check tailscale funnel status, external HTTPS and actual GitHub OAuth.")
    print("   Tailscale Serve is tailnet-only; Funnel is public HTTPS.")
    print("   DO NOT expose the unauthenticated DEV preview port 3101.")
    print("Docs: https://tailscale.com/docs/features/tailscale-funnel")
    print("      https://tailscale.com/docs/reference/tailscale-cli/funnel")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _oauth_guard(root: Path) -> dict:
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
        raise RuntimeError("Локальные OAuth metadata недоступны; перенаправления запрещены") from None
    except (OSError, ValueError) as exc:
        raise RuntimeError("Не удалось проверить локальный OAuth issuer и размер metadata") from exc
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
        raise RuntimeError("Локальный сервер Mac Control с авторизацией недоступен") from exc
    if status != 401 or not challenge:
        raise RuntimeError("Публикация запрещена: анонимный запрос к локальному MCP не вернул HTTP 401 с OAuth challenge")
    return configured


def enable_funnel(root: Path, *, input_fn=input) -> dict:
    executable = tailscale_cli()
    ts = tailscale_state()
    if not executable or not ts.get("logged_in"):
        raise RuntimeError("Сначала установите Tailscale и войдите в свою учётную запись")
    hostname = ts.get("device_dns_name", "")
    if not hostname.endswith(".ts.net"):
        raise RuntimeError("Доменное имя устройства Tailscale недоступно; настройте MagicDNS и HTTPS")
    configured = _oauth_guard(root)
    expected = "https://" + hostname
    if configured["public_url"].rstrip("/") != expected:
        raise RuntimeError("HTTPS-адрес в настройках GitHub OAuth не совпадает с адресом устройства Tailscale")
    existing = publication_state(executable, hostname)
    if existing["status"] not in ("empty", "existing_matching"):
        raise RuntimeError("Отказ от изменения существующей конфигурации Funnel/Serve: " + existing["reason"])
    report = {
        "public_url": expected,
        "port": PORT,
        "external_connectivity_verified": False,
        "github_oauth_login_verified": False,
        "next": "Проверьте tailscale funnel status и публичный OAuth из внешнего MCP-клиента",
    }
    if existing["status"] == "existing_matching":
        return {**report, "status": "existing_funnel_reused"}
    if not sys.stdin.isatty():
        raise RuntimeError("Нужно интерактивное подтверждение владельца в Терминале")
    print("ВНИМАНИЕ: Funnel опубликует в интернете HTTP-сервис Mac Control, защищённый авторизацией.")
    print("Публичный HTTPS-адрес:", expected)
    print("ID разрешённых учётных записей:", ", ".join(configured["allowed_github_ids"]))
    if input_fn("Введите PUBLISH, чтобы включить публичный HTTPS через Funnel на этом Mac: ") != "PUBLISH":
        raise RuntimeError("Владелец не подтвердил публикацию в интернете")
    current_oauth = _oauth_guard(root)
    if (current_oauth["public_url"].rstrip("/") != expected or
            set(current_oauth["allowed_github_ids"]) != set(configured["allowed_github_ids"])):
        raise RuntimeError("OAuth origin или разрешённые владельцы изменились за время ожидания; публикация запрещена")
    # The owner may spend time reviewing; do not overwrite routes created then.
    current = publication_state(executable, hostname)
    if current["status"] == "existing_matching":
        return {**report, "status": "existing_funnel_reused"}
    if current["status"] != "empty":
        raise RuntimeError("Конфигурация Funnel/Serve изменилась за время ожидания подтверждения; изменения не внесены")
    outcome = run([executable, "funnel", "--bg", str(PORT)], timeout=50)
    if outcome.returncode != 0:
        raise RuntimeError("Не удалось настроить Tailscale Funnel; проверьте tailscale funnel status")
    verified = publication_state(executable, hostname)
    if verified["status"] != "existing_matching":
        raise RuntimeError("Не удалось проверить конфигурацию Funnel после публикации; проверьте состояние вручную")
    return {**report, "status": "funnel_command_succeeded"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
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
        guide()
    else:
        if args.guided:
            report = guided_network(args.root, network=True)
        else:
            report = enable_funnel(args.root) if args.enable_funnel else diagnose(network=args.network)
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
