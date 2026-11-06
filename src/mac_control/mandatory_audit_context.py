"""Mandatory owner-visible task context for every externally exposed MCP tool.

Context documents intent and the owner's stated authorization. It is NOT
authorization: underlying tool and OAuth security checks remain unchanged.
"""
from __future__ import annotations

from functools import wraps
import inspect

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
