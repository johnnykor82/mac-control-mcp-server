"""BF26: all externally registered MCP tools require structured owner-visible context."""
import asyncio

import pytest
from fastmcp import FastMCP

from scripts.dev_mcp_server import make_server

CTX = {
    "task_id": "BF26-P03",
    "action": "Inspect registered tool metadata without changing host state",
    "authorization_basis": "User approved BF26 implementation on 2026-11-06",
}
FIELDS = {"task_id", "action", "authorization_basis"}


def test_all_registered_tools_have_required_audit_context():
    tools = asyncio.run(make_server(include_mutations=True).list_tools())
    assert len(tools) >= 125
    for tool in tools:
        params = tool.parameters
        assert "audit_context" in params.get("properties", {}), tool.name
        assert "audit_context" in params.get("required", []), tool.name
        inner = params["properties"]["audit_context"]
        assert FIELDS == set(inner.get("required", [])), tool.name
        assert FIELDS.issubset(inner.get("properties", {})), tool.name
        assert "audit_context" in tool.description, tool.name


def test_missing_and_invalid_context_rejected_before_system_info():
    server = make_server(include_mutations=True)
    with pytest.raises(Exception, match="audit_context"):
        asyncio.run(server.call_tool("system_info", {}))
    with pytest.raises(Exception, match="task_id"):
        asyncio.run(server.call_tool("system_info", {
            "audit_context": {"task_id": "", "action": CTX["action"],
                              "authorization_basis": CTX["authorization_basis"]}
        }))
    with pytest.raises(Exception, match="authorization_basis"):
        asyncio.run(server.call_tool("system_info", {"audit_context": {
            **CTX, "authorization_basis": "          "
        }}))
    response = asyncio.run(server.call_tool("system_info", {"audit_context": CTX}))
    assert not response.is_error


def test_async_and_sync_wrapped_handlers_keep_original_args():
    from mac_control.mandatory_audit_context import install_registration
    app = FastMCP("BF26 isolated registration")
    install_registration(app)
    seen = []
    @app.tool
    async def async_handler(value: int):
        seen.append(("async", value))
        return value + 1
    @app.tool()
    def sync_handler(value: int = 2):
        seen.append(("sync", value))
        return value + 1
    for name, args in (("async_handler", {"value": 5}), ("sync_handler", {})):
        with pytest.raises(Exception, match="audit_context"):
            asyncio.run(app.call_tool(name, args))
    for name, args in (("async_handler", {"value": 5}), ("sync_handler", {})):
        response = asyncio.run(app.call_tool(name, {**args, "audit_context": CTX}))
        assert not response.is_error
    assert seen == [("async", 5), ("sync", 2)]


def test_middleware_persists_context_in_own_record(tmp_path):
    import json
    from types import SimpleNamespace
    from mac_control.audit_middleware import AuditMiddleware
    audit = AuditMiddleware(tmp_path / "logs")
    context = SimpleNamespace(message=SimpleNamespace(
        name="system_info", arguments={"audit_context": CTX}
    ))
    async def next_call(_):
        return SimpleNamespace(is_error=False)
    asyncio.run(audit.on_call_tool(context, next_call))
    records = [json.loads(line) for line in
               (tmp_path / "logs/audit.jsonl").read_text().splitlines()]
    assert records[0]["audit_context"] == CTX
    assert records[0]["arguments"]["audit_context"] == CTX
    assert records[1]["status"] == "ok"


def test_mclog_displays_separate_task_action_and_basis():
    from scripts import mclog
    event = {"tool": "system_info", "arguments": {"audit_context": CTX}}
    line = mclog.display_args(event, 1200)
    assert "BF26-P03" in line
    assert CTX["action"] in line
    assert CTX["authorization_basis"] in line
    assert "Задача:" in line
