"""Standalone, read-only smoke check for the isolated registry (not an MCP tool)."""
import json

from .trusted_registry import list_operations

if __name__ == "__main__":
    print(json.dumps({"registry_version": 1, "operations": list_operations()}))
