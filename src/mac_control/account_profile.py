"""Stable authenticated GitHub account identity for OpenAI MCP multi-account UI.

The provider numeric GitHub user ID is an immutable opaque provider identifier.
Never derive an identity from the OAuth client registration, token, email,
untrusted tool arguments, or an arbitrarily selected local allowlist entry.
"""
from __future__ import annotations

from fastmcp.server.dependencies import get_access_token

from .remote_auth import load_config

OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "minLength": 1,
            "pattern": r"\S",
            "description": (
                "Immutable, opaque GitHub provider profile identifier. "
                "Stable across reconnection and token refresh."
            ),
        }
    },
    "required": ["id"],
    "additionalProperties": False,
}


def authenticated_profile() -> dict[str, str]:
    """Resolve exactly the GitHub subject represented by verified credentials."""
    token = get_access_token()
    subject = getattr(token, "subject", None)
    if not isinstance(subject, str) or not subject.isascii() or not subject.isdecimal():
        raise PermissionError("Authenticated GitHub profile identity unavailable")
    allowed = load_config()["github_allowed_ids"]
    if subject not in allowed:
        raise PermissionError("Authenticated GitHub profile not approved")
    return {"id": subject}


def register(mcp) -> None:
    """Expose only on authenticated remote MCP, not local anonymous preview."""
    @mcp.tool(
        name="get_profile",
        description=(
            "Return the GitHub profile represented by this request's verified "
            "OAuth credentials. Its opaque ID stays constant across reconnection "
            "and token refresh."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": False,
        },
        output_schema=OUTPUT_SCHEMA,
        meta={"openai/profile": True},
    )
    def get_profile() -> dict[str, str]:
        return authenticated_profile()
