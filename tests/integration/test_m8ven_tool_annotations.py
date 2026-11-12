"""M8ven trust metadata: verify the actual registered FastMCP schema, not guesses."""
from __future__ import annotations

import ast
import asyncio
import csv
from pathlib import Path
from unittest import TestCase

from mac_control import account_profile
from mac_control.mandatory_audit_context import install_registration
from scripts.dev_mcp_server import make_server

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "specs/M8VEN_TRUST_A_20261111/TOOL_MATRIX_BASELINE.csv"
FIELDS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
SNAKE = ("read_only_hint", "destructive_hint", "idempotent_hint", "open_world_hint")


def registered_tools():
    server = make_server(include_mutations=True)
    account_profile.register(server)
    return asyncio.run(server.list_tools(run_middleware=False))


class ToolAnnotationTrustTests(TestCase):
    def test_exact_143_policy_declares_all_four_boolean_hints(self):
        from mac_control.tool_annotation_policy import TOOL_ANNOTATIONS
        with BASELINE.open(newline="") as stream:
            names = {item["name"] for item in csv.DictReader(stream)}
        self.assertEqual(set(TOOL_ANNOTATIONS), names)
        self.assertEqual(len(names), 143)
        for name, policy in TOOL_ANNOTATIONS.items():
            with self.subTest(name=name):
                self.assertEqual(set(policy), set(FIELDS))
                self.assertTrue(all(type(policy[key]) is bool for key in FIELDS))
        self.assertEqual(TOOL_ANNOTATIONS["terminal_exec"]["readOnlyHint"], False)
        self.assertEqual(TOOL_ANNOTATIONS["terminal_exec"]["idempotentHint"], False)
        self.assertEqual(TOOL_ANNOTATIONS["chat_marker_issue"]["idempotentHint"], False)
        self.assertEqual(TOOL_ANNOTATIONS["gui_screenshot"]["readOnlyHint"], True)
        self.assertEqual(TOOL_ANNOTATIONS["gui_screenshot"]["destructiveHint"], False)

    def test_registered_tools_publish_complete_annotations_and_keep_audit_context(self):
        from mac_control.tool_annotation_policy import TOOL_ANNOTATIONS
        tools = registered_tools()
        self.assertEqual(len(tools), 143)
        for tool in tools:
            with self.subTest(tool=tool.name):
                data = tool.annotations.model_dump(exclude_none=True)
                self.assertTrue(all(type(data.get(name)) is bool for name in SNAKE), tool.name)
                expected = TOOL_ANNOTATIONS[tool.name]
                self.assertEqual({k: data[s] for k, s in zip(FIELDS, SNAKE)}, dict(expected))
                self.assertIn("audit_context", tool.parameters["properties"])

    def test_registration_rejects_unknown_policy_tool(self):
        from fastmcp import FastMCP
        server = FastMCP("fixture")
        install_registration(server, enforce_policy=True)
        with self.assertRaisesRegex((ValueError, KeyError, RuntimeError), "unknown|Unknown|policy|registered"):
            @server.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
            def unexpected_for_policy() -> str:
                return "should not register"

    def test_existing_static_source_annotations_are_complete(self):
        """At registration sites, all four explicit named fields must be visible."""
        from mac_control.tool_annotation_policy import TOOL_ANNOTATIONS
        paths = [ROOT / "scripts/dev_mcp_server.py", *sorted((ROOT / "src/mac_control").rglob("*.py"))]
        found = 0
        for path in paths:
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fun = node.func
                if not ((isinstance(fun, ast.Attribute) and fun.attr == "tool")
                        or (isinstance(fun, ast.Name) and fun.id == "gui_tool")):
                    continue
                args = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                if "annotations" not in args:
                    continue
                ann = args["annotations"]
                if not isinstance(ann, ast.Dict):
                    continue
                keys = {key.value for key in ann.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
                with self.subTest(file=str(path.relative_to(ROOT)), line=node.lineno):
                    self.assertTrue(set(FIELDS).issubset(keys), f"Missing static flags: {set(FIELDS)-keys}")
                found += 1
        self.assertGreaterEqual(found, 133)
        self.assertEqual(len(TOOL_ANNOTATIONS), 143)


def test_published_release_manifest_contains_strict_tool_policy():
    from io import BytesIO
    from tarfile import open as tar_open

    from scripts.release_payload_audit import build_archive
    manifest = (ROOT / "scripts/install_manifest.txt").read_text().splitlines()
    name = "src/mac_control/tool_annotation_policy.py"
    assert name in manifest
    with tar_open(fileobj=BytesIO(build_archive(ROOT)), mode="r:gz") as archive:
        assert name in archive.getnames()
        assert archive.extractfile(name).read() == (ROOT / name).read_bytes()
