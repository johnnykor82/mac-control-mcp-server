#!/usr/bin/env python3
"""Interactive, owner-led GitHub OAuth App onboarding for Mac Control.

No GitHub app is created behind the owner's back. GitHub OAuth Apps are
registered by the owner in GitHub Developer Settings. The setup writes
owner-only credentials locally and NEVER prints the Client Secret or JWT key.
"""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

try:
    from scripts.setup_language import choose_language, detect_language, text
except ImportError:
    from setup_language import choose_language, detect_language, text


DEFAULT_ROOT = Path.home() / "MacControlMCP"
GITHUB_NEW_APP_URL = "https://github.com/settings/applications/new"
GITHUB_USER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]{8,128}$")


def public_origin(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Provide a public HTTPS origin")
    parsed = urlsplit(value.strip())
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or
            parsed.path not in ("", "/")):
        raise ValueError("Public URL must be an HTTPS origin, without paths or credentials")
    if parsed.hostname in ("localhost", "127.0.0.1", "::1") or parsed.hostname.endswith(".local"):
        raise ValueError("OAuth callback must use a publicly reachable HTTPS host")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        if not ip.is_global:
            raise ValueError("Public callback cannot use a private/reserved IP")
    return value.strip().rstrip("/")


def github_account(login: str | None, *, allow_gh: bool = True) -> tuple[str, str, str]:
    """Resolve GitHub account ID. gh auth gives stronger owner-account evidence."""
    if allow_gh and shutil.which("gh"):
        result = subprocess.run(
            ["gh", "api", "user", "--jq", "{login: .login, id: .id}"],
            check=False, capture_output=True, timeout=12, text=True,
        )
        if result.returncode == 0:
            value = json.loads(result.stdout)
            if (isinstance(value, dict) and isinstance(value.get("login"), str)
                    and isinstance(value.get("id"), int) and value["id"] > 0):
                found_login = value["login"]
                if login is None or found_login.casefold() == login.casefold():
                    return found_login, str(value["id"]), "authenticated_github_cli"
                raise ValueError("Requested login does not match authenticated GitHub CLI account")
    if not login or not GITHUB_USER_PATTERN.fullmatch(login):
        raise ValueError("Supply --github-login or authenticate GitHub CLI with gh auth login")
    request = urllib.request.Request(
        "https://api.github.com/users/" + login,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "MacControlMac Control MCP ServerOAuthInstaller/1.0"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        value = json.load(response)
    if not isinstance(value, dict) or not isinstance(value.get("id"), int):
        raise RuntimeError("Cannot resolve GitHub numeric account ID")
    actual = value.get("login")
    if not isinstance(actual, str) or actual.casefold() != login.casefold():
        raise ValueError("GitHub returned a different account")
    return actual, str(value["id"]), "public_profile_unverified"


def guide(url: str, login: str | None, language=None) -> None:
    language = language or detect_language()
    if language == "ru":
        print("\nMac Control MCP Server — настройка GitHub OAuth App")
        print("1. Проверьте публичный HTTPS-адрес и сетевой туннель.")
        print("2. Войдите в GitHub как владелец этого Mac и откройте:")
        print("   " + GITHUB_NEW_APP_URL)
        print("3. В настройках разработчика GitHub откройте OAuth Apps → New OAuth App и заполните:")
        print("   Нужен OAuth App. GitHub App — другой тип приложения.")
        print("   Срок действия токенов пользователя — отдельная настройка, не Client Secret.")
        print("   При желании отключите их истечение в настройках GitHub; длительный срок повышает риск при утечке.")
        print("   Application name: Mac Control MCP Server (имя вашего компьютера)")
        print("   Homepage URL: " + url)
        print("   Authorization callback URL: " + url + "/auth/callback")
        print("   Enable Device Flow: не включать (для MCP OAuth-прокси не требуется)")
        print("4. Нажмите Register application и скопируйте Client ID.")
        print("5. На странице настроек приложения создайте Client Secret.")
        print("6. Введите Client ID и Client Secret локально. Ввод секрета будет скрыт.")
        if login:
            print("   Разрешённый аккаунт GitHub: @" + login)
        print("   Приложение запрашивает только read:user; доступ к репозиториям не требуется.")
        print("   Не отправляйте Client Secret, токены или ключи подписи в чат с ИИ.")
        print("7. После настройки запустите локальный удалённый сервер Mac Control MCP Server,")
        print("   опубликуйте его через HTTPS под вашим управлением и войдите через MCP-клиент")
        print("   с поддержкой OAuth. Проверьте, что другим аккаунтам GitHub отказано в доступе.\n")
        return
    print("\nMac Control MCP Server — GitHub OAuth App setup guide")
    print("1. First verify your public HTTPS address and network tunnel.")
    print("2. Sign in to GitHub as the owner of this Mac, then open:")
    print("   " + GITHUB_NEW_APP_URL)
    print("3. In GitHub Developer settings > OAuth Apps > New OAuth App, enter:")
    print("   Use an OAuth App. GitHub App is a different application type.")
    print("   User token expiration is a separate setting; it is not the Client Secret.")
    print("   You may disable expiration in GitHub settings; long-lived tokens increase the impact of a leak.")
    print("   Application name: Mac Control MCP Server (your machine nickname)")
    print("   Homepage URL: " + url)
    print("   Authorization callback URL: " + url + "/auth/callback")
    print("   Enable Device Flow: no (not required for MCP OAuth proxy)")
    print("4. Register application; copy its Client ID.")
    print("5. On the application's settings page, generate a Client Secret.")
    print("6. Run the configure command locally and enter the Client Secret hidden.")
    if login:
        print("   GitHub account to authorize: @" + login)
    print("   The application requests read:user only; it does not need repository access.")
    print("   Never send Client Secret, tokens or signing keys through an AI chat.")
    print("7. Once configured, start Mac Control MCP Server's loopback remote server,")
    print("   expose it through owner-controlled HTTPS, and sign in with an")
    print("   OAuth-capable MCP client. Check that other GitHub accounts are denied.\n")


def destination(root: Path) -> Path:
    expanded = root.expanduser()
    if expanded.is_symlink() or (expanded / "data").is_symlink():
        raise RuntimeError("Install/data root must not be a symlink")
    root = expanded.resolve()
    data = root / "data"
    if root.is_symlink() or data.is_symlink():
        raise RuntimeError("Install/data root must not be a symlink")
    if not root.is_dir() or not (root / ".mac-control-installer-owned").is_file():
        raise RuntimeError("Install Mac Control MCP Server before configuring OAuth")
    if not data.is_dir():
        raise RuntimeError("MCP Server data directory missing")
    if data.stat().st_mode & 0o077:
        raise PermissionError("MCP Server data directory must be owner-only (0700)")
    if hasattr(os, "getuid") and data.stat().st_uid != os.getuid():
        raise PermissionError("MCP Server data directory not owned by current user")
    return data / "remote_auth.json"


def save_new_config(path: Path, config: dict) -> None:
    """Atomically create credentials without overwrite, leaks or world-readable temp."""
    if path.is_symlink() or path.exists():
        raise FileExistsError("OAuth credentials already exist: no changes made")
    content = (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    temp = path.with_name(".remote_auth." + secrets.token_hex(8) + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temp, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        # Avoid overwriting secrets from concurrent installation. hard-link
        # is atomic and does not replace an existing destination.
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def configure(root: Path, url: str, login: str | None, *, input_fn=input,
              secret_fn=getpass.getpass, language=None) -> dict:
    language = language or detect_language()
    tr = lambda en, ru: text(language, en, ru)
    path = destination(root)
    if path.exists() or path.is_symlink():
        raise FileExistsError("OAuth credentials already exist; use --check instead")
    username, uid, method = github_account(login)
    print(tr("Resolved GitHub account: @", "Найден аккаунт GitHub: @") + username + tr(" (numeric ID ", " (числовой ID ") + uid + ")")
    if method == "public_profile_unverified":
        print(tr("WARNING: public profile lookup does not prove ownership. Only", "ВНИМАНИЕ: публичный профиль не подтверждает владение аккаунтом. Только"))
        print(tr("the specified account will pass subsequent GitHub OAuth verification.", "указанный аккаунт сможет пройти последующую проверку GitHub OAuth."))
    confirmation = input_fn(tr("Authorize ONLY this GitHub account to control your Mac? Type YES: ", "Разрешить ТОЛЬКО этому аккаунту GitHub управлять вашим Mac? Введите YES: "))
    if confirmation != "YES":
        raise RuntimeError("Owner did not authorize this GitHub account")
    client_id = input_fn(tr("GitHub OAuth App Client ID: ", "Client ID приложения GitHub OAuth: ")).strip()
    if not CLIENT_ID_PATTERN.fullmatch(client_id):
        raise ValueError("Invalid GitHub OAuth Client ID")
    client_secret = secret_fn(tr("GitHub Client Secret (hidden; never pasted into chat): ", "GitHub Client Secret (ввод скрыт; не отправляйте в чат): ")).strip()
    if len(client_secret) < 20 or any(c.isspace() for c in client_secret):
        raise ValueError("Invalid Client Secret")
    config = {"github_client_id": client_id,
              "github_client_secret": client_secret,
              "github_allowed_ids": [uid],
              "public_url": public_origin(url),
              "jwt_signing_key": secrets.token_urlsafe(64)}
    save_new_config(path, config)
    return {
        "status": "configured",
        "github_owner": username,
        "allowed_github_id": uid,
        "owner_id_method": method,
        "public_url": public_origin(url),
        "callback_url": public_origin(url) + "/auth/callback",
        "configuration_path": str(path),
        "configuration_mode": "0600",
        "secret_values": "not_displayed",
        "server_started": False,
        "oauth_login_verified": False,
        "next": "Start authenticated MCP endpoint and complete real GitHub OAuth login",
    }


def check(root: Path) -> dict:
    path = destination(root)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("OAuth config missing; run --configure")
    metadata = path.stat()
    if metadata.st_mode & 0o077 or (hasattr(os, "getuid") and metadata.st_uid != os.getuid()):
        raise PermissionError("OAuth config must be owner-only (0600)")
    # Standard-library validation works before FastMCP is installed. The
    # runtime repeats these checks when the authenticated service starts.
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("OAuth config must be a JSON object")
    ids = loaded.get("github_allowed_ids")
    if not isinstance(ids, list) or not ids or any(
        not isinstance(value, str) or not value.isdecimal() for value in ids
    ) or len(set(ids)) != len(ids):
        raise ValueError("Invalid GitHub account allowlist")
    if (not isinstance(loaded.get("github_client_id"), str) or
            not CLIENT_ID_PATTERN.fullmatch(loaded["github_client_id"])):
        raise ValueError("Invalid OAuth Client ID")
    if (not isinstance(loaded.get("github_client_secret"), str) or
            len(loaded["github_client_secret"]) < 20 or
            not isinstance(loaded.get("jwt_signing_key"), str) or
            len(loaded["jwt_signing_key"]) < 32):
        raise ValueError("Incomplete OAuth credentials")
    public_origin(loaded.get("public_url"))
    return {"status": "config_valid", "path": str(path),
            "allowed_github_ids": loaded["github_allowed_ids"],
            "public_url": loaded["public_url"],
            "callback_url": loaded["public_url"].rstrip("/") + "/auth/callback",
            "secret_values": "not_displayed", "oauth_login_verified": False}


def probe(origin: str) -> dict:
    """Read-only remote reachability checks; never sends credentials."""
    origin = public_origin(origin)
    request = urllib.request.Request(
        origin + "/.well-known/oauth-authorization-server",
        headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            metadata = json.load(response)
        metadata_ok = (isinstance(metadata, dict) and
                       str(metadata.get("issuer", "")).rstrip("/") == origin and
                       metadata.get("authorization_endpoint") and
                       metadata.get("token_endpoint"))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, OSError):
        metadata_ok = False
    request = urllib.request.Request(
        origin + "/mcp", method="POST",
        data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            status = response.status
            challenge = bool(response.headers.get("WWW-Authenticate"))
    except urllib.error.HTTPError as err:
        status = err.code
        challenge = bool(err.headers.get("WWW-Authenticate"))
    except (urllib.error.URLError, OSError, ValueError):
        status = None
        challenge = False
    success = bool(metadata_ok and status == 401 and challenge)
    return {"status": "public_oauth_preflight_pass" if success else "public_oauth_preflight_failed",
            "oauth_metadata_valid": bool(metadata_ok),
            "anonymous_mcp_http_status": status,
            "anonymous_auth_challenge": challenge,
            "oauth_login_verified": False,
            "next": "Complete GitHub OAuth in your MCP client; probe cannot authenticate on your behalf"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--language", choices=("en", "ru"))
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--guide", action="store_true", help="Print owner instructions, no changes")
    commands.add_argument("--configure", action="store_true", help="Interactive owner-approved credential setup")
    commands.add_argument("--check", action="store_true", help="Validate existing config without displaying secrets")
    commands.add_argument("--probe", action="store_true", help="Check public HTTPS OAuth discovery and deny-anonymous behavior")
    parser.add_argument("--public-url", help="Externally reachable HTTPS origin, no path (e.g. https://mac.example.com)")
    parser.add_argument("--github-login", help="GitHub login; otherwise use already-authenticated gh CLI")
    args = parser.parse_args(argv)
    if args.check:
        report = check(args.root)
    elif args.probe:
        existing = check(args.root)
        report = probe(existing["public_url"])
    else:
        if not args.public_url:
            parser.error("--public-url is required with --guide or --configure")
        origin = public_origin(args.public_url)
        language = args.language
        if args.guide:
            guide(origin, args.github_login, language)
            return 0
        if not sys.stdin.isatty():
            raise RuntimeError("Interactive Terminal required to enter Client Secret without echo")
        language = choose_language(language=language)
        guide(origin, args.github_login, language)
        report = configure(args.root, origin, args.github_login, language=language)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError,
            json.JSONDecodeError) as error:
        # Avoid printing arbitrary exception contents from external requests,
        # subprocesses or responses that could include secrets.
        print("GitHub OAuth setup failed:", type(error).__name__,
              str(error) if isinstance(error, (ValueError, RuntimeError, FileExistsError,
                                                PermissionError, FileNotFoundError))
              else "Check setup and retry", file=sys.stderr)
        raise SystemExit(1)
