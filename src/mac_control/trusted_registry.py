"""PR-01: fixed operation registry, no workspace imports or dynamic plugins.

Isolated code only. Does not change the running Mac Control MCP.
No second user-consent or confirmation subsystem is implemented.
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .operations import system_info

_REGISTRY_VERSION = 1
_MAX_ARGS_BYTES = 128 * 1024
_NAME = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_TRUSTED_DIR = Path(__file__).resolve().parent


class UnknownOperation(LookupError):
    pass


class InvalidArguments(ValueError):
    pass


class RegistryIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Operation:
    name: str
    handler: Callable[..., Any]
    read_only: bool


def _check_trusted(op: Operation) -> None:
    if not _NAME.fullmatch(op.name):
        raise RegistryIntegrityError("Invalid operation name")
    if not callable(op.handler) or not isinstance(op.read_only, bool):
        raise RegistryIntegrityError("Invalid handler metadata")
    if op.handler.__module__ != "mac_control.operations":
        raise RegistryIntegrityError("Handler does not belong to trusted package")
    origin = inspect.getsourcefile(op.handler)
    if not origin:
        raise RegistryIntegrityError("Handler has no trusted source")
    source = Path(origin)
    if source.is_symlink() or source.resolve(strict=True).parent != _TRUSTED_DIR:
        raise RegistryIntegrityError("Handler source outside trusted package")
    if source.name != "operations.py":
        raise RegistryIntegrityError("Unrecognized trusted module")


def create_registry() -> Mapping[str, Operation]:
    """Build a closed, immutable map of shipped handlers."""
    operations = (Operation("system_info", system_info, True),)
    entries: dict[str, Operation] = {}
    for op in operations:
        _check_trusted(op)
        if op.name in entries:
            raise RegistryIntegrityError("Duplicate operation")
        entries[op.name] = op
    return MappingProxyType(entries)


_REGISTRY = create_registry()


def list_operations() -> list[dict[str, Any]]:
    """Introspect the built-in registry, not a new MCP tool."""
    return [
        {"name": v.name, "read_only": v.read_only,
         "signature": str(inspect.signature(v.handler))}
        for v in _REGISTRY.values()
    ]


def dispatch(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    read_only: bool = True,
    registry_version: int = _REGISTRY_VERSION,
) -> dict[str, Any]:
    """Call a trusted handler; deny unknown IDs/versions without import/eval."""
    if type(registry_version) is not int or registry_version != _REGISTRY_VERSION:
        raise UnknownOperation("Unsupported registry version")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise UnknownOperation("Invalid operation ID")
    op = _REGISTRY.get(name)
    if op is None:
        raise UnknownOperation("Unknown operation")
    if read_only and not op.read_only:
        raise PermissionError("Write-capable operation cannot be called as read-only")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict) or not all(isinstance(k, str) for k in arguments):
        raise InvalidArguments("Arguments must be a JSON object")
    try:
        payload = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidArguments("Arguments must be JSON-serializable") from exc
    if len(payload.encode("utf-8")) > _MAX_ARGS_BYTES:
        raise InvalidArguments("Arguments too large")
    try:
        inspect.signature(op.handler).bind(**arguments)
    except TypeError as exc:
        raise InvalidArguments("Arguments do not match trusted signature") from exc
    _check_trusted(op)
    return {"operation": name, "result": op.handler(**arguments)}
