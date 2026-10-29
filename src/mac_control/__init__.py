"""Isolated Mac Control core; no production imports or live MCP registration."""
from .trusted_registry import InvalidArguments, UnknownOperation, create_registry, dispatch

__all__ = ("InvalidArguments", "UnknownOperation", "create_registry", "dispatch")
