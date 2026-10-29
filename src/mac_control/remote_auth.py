"""Owner-configured OAuth for standalone remote Mac Control.

No public endpoint is enabled by default. Credentials live outside Git, in
the owner-only data directory. This is an internet-facing execution service:
authorize only intentional GitHub identities and verify the external URL.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastmcp.server.auth import OAuthProxy
from fastmcp.server.auth.providers.github import GitHubTokenVerifier

from .runtime_paths import DATA_ROOT


class AllowedGitHubUsersVerifier(GitHubTokenVerifier):
    def __init__(self, allowed_ids: set[str]):
        super().__init__(required_scopes=["read:user"])
        self._allowed_ids = allowed_ids

    async def verify_token(self, token: str):
        verified = await super().verify_token(token)
        if verified is None or str(verified.subject) not in self._allowed_ids:
            return None
        return verified


def _read_config(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Remote OAuth config must be a regular file")
    meta = path.stat()
    if hasattr(os, "getuid") and meta.st_uid != os.getuid():
        raise PermissionError("Remote OAuth config must be owned by the service user")
    if meta.st_mode & 0o077:
        raise PermissionError("Remote OAuth config must have permissions 0600")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Remote OAuth config must be a JSON object")
    return data


def load_config(path: Path | None = None) -> dict:
    config = _read_config(path or (DATA_ROOT / "remote_auth.json"))
    required = ("github_client_id", "github_client_secret",
                "public_url", "jwt_signing_key")
    if any(not config.get(k) for k in required):
        raise RuntimeError("Remote OAuth config is missing required fields")
    ids = config.get("github_allowed_ids")
    if not isinstance(ids, list) or not ids or any(
        not isinstance(value, str) or not value.isdecimal() for value in ids
    ):
        raise ValueError("github_allowed_ids must be a list of numeric GitHub account IDs")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate GitHub account ID")
    if not isinstance(config["github_client_id"], str) or not isinstance(
        config["github_client_secret"], str
    ):
        raise ValueError("Invalid OAuth client configuration")
    if not isinstance(config["jwt_signing_key"], str) or len(config["jwt_signing_key"]) < 32:
        raise ValueError("JWT signing key must be at least 32 characters")
    raw_url = config["public_url"]
    if not isinstance(raw_url, str):
        raise ValueError("Public URL must be HTTPS")
    parsed = urlsplit(raw_url)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("Public URL must be an HTTPS origin, without path/query/credentials")
    return config


def build_auth(path: Path | None = None) -> OAuthProxy:
    config = load_config(path)
    return OAuthProxy(
        upstream_authorization_endpoint="https://github.com/login/oauth/authorize",
        upstream_token_endpoint="https://github.com/login/oauth/access_token",
        upstream_client_id=config["github_client_id"],
        upstream_client_secret=config["github_client_secret"],
        token_verifier=AllowedGitHubUsersVerifier(set(config["github_allowed_ids"])),
        base_url=config["public_url"].rstrip("/"),
        jwt_signing_key=config["jwt_signing_key"],
        require_authorization_consent=True,
    )
