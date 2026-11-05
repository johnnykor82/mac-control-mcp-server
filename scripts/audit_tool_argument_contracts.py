"""Offline, non-invasive inventory of actual MCP parameter schemas and errors.

Only tool registration and source AST inspection; never invoke an operation.
Raw caller inputs, environment values and runtime exception text are excluded.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
from collections import Counter
from unittest.mock import patch
from pathlib import Path

from mac_control.legacy_adapter import inspect_existing_handlers
from scripts.dev_mcp_server import make_server
from mac_control import background_browser_ops, background_native_ops


def _raises(fn) -> list[dict[str, str]]:
    try:
        source = textwrap.dedent(inspect.getsource(fn))
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError):
        return []
    errors = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        target = node.exc.func
        kind = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
        if kind not in {"ValueError", "TypeError", "PermissionError", "RuntimeError",
                        "FileNotFoundError"}:
            continue
        first = node.exc.args[0] if node.exc.args else None
        literal = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
        # No dynamic values or runtime exception details. Literal messages
        # come only from checked-in code, never from any user request.
        errors.append({"type": kind, "literal": literal[:120] if literal else ""})
    return sorted({(x["type"], x["literal"]) for x in errors})


def _module_inventory() -> list[dict]:
    """Count static raise sites in shared helpers; not caller-error claims."""
    root = Path(__file__).resolve().parents[1] / "src/mac_control"
    paths = sorted((root / "legacy_handlers").glob("*.py"))
    paths += [root / part for part in (
        "maintenance_ops.py", "background_browser_ops.py",
        "background_native_ops.py")]
    modules = []
    for path in paths:
        kinds = Counter()
        messages = []
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            fun = node.exc.func
            kind = fun.id if isinstance(fun, ast.Name) else getattr(fun, "attr", "")
            if kind not in {"ValueError", "TypeError", "PermissionError", "RuntimeError"}:
                continue
            kinds[kind] += 1
            first = node.exc.args[0] if node.exc.args else None
            if kind == "ValueError" and isinstance(first, ast.Constant) and isinstance(first.value, str):
                messages.append(first.value[:120])
        modules.append({"module": path.name, "exception_sites": dict(kinds),
                        "static_value_errors": sorted(set(messages))})
    return modules


async def audit() -> dict:
    frozen = inspect_existing_handlers()
    # Inventory the full supported set, including opt-in tools, without
    # modifying persistent feature_flags or executing any tool handler.
    with patch.object(background_browser_ops, "enabled", return_value=True), \
         patch.object(background_native_ops, "enabled", return_value=True):
        registered = await make_server(include_mutations=True).list_tools()
    results = []
    for tool in sorted(registered, key=lambda t: t.name):
        is_frozen = tool.name in frozen
        handler = frozen[tool.name].handler if is_frozen else tool.fn
        schema = tool.parameters or {}
        props = schema.get("properties", {})
        issues = [{"type": kind, "literal": literal} for kind, literal in _raises(handler)]
        results.append({
            "name": tool.name,
            "frozen": is_frozen,
            "read_only": frozen[tool.name].read_only if is_frozen else bool(
                getattr(tool.annotations, "read_only_hint", False)),
            "module": handler.__module__,
            "required": sorted(schema.get("required", [])),
            "parameters": sorted(props),
            "exceptions": issues,
        })
    if len(frozen) != 112 or not set(frozen) <= {r["name"] for r in results}:
        raise AssertionError("Frozen operations missing or changed")
    raised = Counter(e["type"] for item in results for e in item["exceptions"])
    return {
        "schema_version": 1,
        "summary": {"tools": len(results), "frozen": len(frozen),
                    "additional": len(results) - len(frozen),
                    "static_exception_sites": dict(raised)},
        "tools": results,
        "module_inventory": _module_inventory(),
    }


def render_markdown(data: dict) -> str:
    from mac_control.argument_guidance import _KNOWN_REASONS

    tools = data["tools"]
    families = Counter(t["name"].split("_", 1)[0] for t in tools)
    counts = Counter()
    unclassified = set()
    for module in data["module_inventory"]:
        counts.update(module["exception_sites"])
        for message in module["static_value_errors"]:
            if (message.lower().startswith((
                    "invalid", "unknown", "unsupported", "missing"))
                    and message not in _KNOWN_REASONS):
                unclassified.add((module["module"], message))
    lines = [
        "# FR-025 — инвентаризация ошибок аргументов Mac Control MCP",
        "",
        "Автоматически воспроизводимый аудит исходников и схем MCP; без вызова",
        "инструментов, доступа к пользовательским аргументам и изменения production.",
        "",
        f"- Всего: **{len(tools)}** инструментов (112 frozen, {len(tools)-112} дополнительных).",
        "- Опциональные background-инструменты зарегистрированы только в памяти.",
        "- Статические исключения из 20 модулей: " + ", ".join(
            f"{name}={count}" for name, count in sorted(counts.items())) + ".",
        f"- Не классифицированных статических сообщений: **{len(unclassified)}**.",
        "- Статические raise-сайты не являются доказательством ошибки параметра;",
        "  ошибки среды, зависимости и после побочного эффекта проверяются отдельно.",
        "",
        "## Семейства",
        "",
        "| Семейство | Инструментов |",
        "| --- | ---: |",
    ]
    lines += [f"| {name} | {size} |" for name, size in sorted(families.items())]
    lines += [
        "", "## Реестр схем MCP", "",
        "| Инструмент | Обязательные поля | Полей всего | Источник |",
        "| --- | --- | ---: | --- |",
    ]
    for item in tools:
        name = item["name"]
        required = ", ".join(item["required"]) or "—"
        lines.append(
            f"| {name} | {required} | {len(item['parameters'])} | "
            + ("frozen" if item["frozen"] else "additional") + " |"
        )
    lines += [
        "", "## Общие валидаторы вызываемых модулей", "",
        "| Модуль | ValueError | PermissionError | RuntimeError | TypeError |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for mod in data["module_inventory"]:
        c = mod["exception_sites"]
        if not any(c.values()):
            continue
        lines.append(
            f"| {mod['module']} | {c.get('ValueError', 0)} | "
            f"{c.get('PermissionError', 0)} | {c.get('RuntimeError', 0)} | "
            f"{c.get('TypeError', 0)} |"
        )
    lines += [
        "", "## Backlog: необходима классификация", "",
        "Не все сообщения являются ошибками аргументов; не предлагать",
        "повтор без оценки этапа выполнения.",
        "", "| Модуль | Сообщение |", "| --- | --- |",
    ]
    for module, message in sorted(unclassified):
        lines.append(f"| {module} | {message.replace('|', ' ')} |")
    return "\n".join(lines) + "\n"


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()
    data = asyncio.run(audit())
    if args.format == "markdown":
        print(render_markdown(data), end="")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
