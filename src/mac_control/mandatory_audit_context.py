"""Mandatory owner-visible task context for every externally exposed MCP tool.

Context documents intent and the owner's stated authorization. It is NOT
authorization: underlying tool and OAuth security checks remain unchanged.
"""
from __future__ import annotations

from functools import wraps
import inspect

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .chat_identity import valid_chat_marker


class AuditContext(BaseModel):
    """Structured per-call intent, recorded in the owner-only MCP audit."""

    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(
        min_length=3, max_length=96,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$",
        description="Stable task/plan step ID; use the same ID across related operations.",
    )
    action: str = Field(
        min_length=8, max_length=512,
        description="Precisely what the tool will do, the target(s) it affects, "
                    "and the expected outcome. Do not include credentials.",
    )
    authorization_basis: str = Field(
        min_length=8, max_length=512,
        description="User permission or pre-approved PLAN reference, including "
                    "approval date. An assertion is not permission to bypass MCP policy.",
    )

    chat_marker: str | None = Field(
        default=None,
        max_length=45,
        description=(
            "Optional stable ChatGPT conversation marker: WC plus 16 lowercase "
            "hex characters. Reuse the same marker on EVERY call in this chat "
            "regardless of task_id. Publish it once in an assistant reply when "
            "first issuing; do not create a new chat. Legacy long markers accepted. "
            "Not an authorization credential."
        ),
    )

    @field_validator("chat_marker")
    @classmethod
    def require_exact_marker(cls, value: str | None) -> str | None:
        if value is not None and not valid_chat_marker(value):
            raise ValueError("Expected WC plus 16 lowercase hex characters")
        return value

    @field_validator("action", "authorization_basis")
    @classmethod
    def require_meaningful_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Audit context field cannot be blank")
        return value


def _wrapped_handler(handler):
    """Add one required keyword-only argument without changing handler input."""
    original = inspect.signature(handler)
    if "audit_context" in original.parameters:
        raise RuntimeError("Handler already defines reserved audit_context")
    parameters = list(original.parameters.values())
    location = next(
        (i for i, param in enumerate(parameters)
         if param.kind == inspect.Parameter.VAR_KEYWORD),
        len(parameters),
    )
    parameters.insert(location, inspect.Parameter(
        "audit_context", kind=inspect.Parameter.KEYWORD_ONLY,
        annotation=AuditContext,
    ))
    signature = original.replace(parameters=parameters)

    if inspect.iscoroutinefunction(handler):
        @wraps(handler)
        async def guard(*args, **kwargs):
            # FastMCP validates the Pydantic field before invocation.
            context = kwargs.pop("audit_context")
            AuditContext.model_validate(context)
            return await handler(*args, **kwargs)
    else:
        @wraps(handler)
        def guard(*args, **kwargs):
            context = kwargs.pop("audit_context")
            AuditContext.model_validate(context)
            return handler(*args, **kwargs)
    guard.__doc__ = (
        (handler.__doc__ or handler.__name__).strip()
        + "\n\nEvery MCP invocation requires audit_context: task_id (stable plan step),"
        " action (operation, affected targets and expected outcome), and"
        " authorization_basis (user consent or approved plan and date)."
        " This is an audit record, never permission to bypass tool security."
        "\nChat identity: on FIRST Mac Control use in a new ChatGPT conversation,"
        " call chat_marker_issue once if no WC marker is present; publish the"
        " returned WC marker in your next assistant reply. Reuse the SAME"
        " audit_context.chat_marker for EVERY subsequent call in that chat,"
        " including different tasks/turns. Never create a new ChatGPT chat"
        " to get an ID. Marker is correlation only, NOT authorization."
    )
    guard.__signature__ = signature
    guard.__annotations__ = {**getattr(handler, "__annotations__", {}),
                             "audit_context": AuditContext}
    return guard


def install_registration(server) -> None:
    """Decorate registration for ALL tools, including system/profile/extensions."""
    underlying = server.tool

    def tool_with_context(name_or_fn=None, **options):
        if isinstance(options.get("description"), str):
            options["description"] += (
                "\n\nSupply required audit_context(task_id, action, authorization_basis)"
                " describing the task, action/targets/outcome and user's dated consent."
                " Metadata is not permission to bypass authorization."
            )
        if callable(name_or_fn):
            return underlying(_wrapped_handler(name_or_fn), **options)
        decorator = underlying(name_or_fn, **options)

        def register(handler):
            return decorator(_wrapped_handler(handler))
        return register

    server.tool = tool_with_context
