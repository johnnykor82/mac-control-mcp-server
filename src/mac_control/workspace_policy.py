"""Agent writing conventions exposed as MCP server instructions and a tool.

This is a behavioral default, not an OS sandbox. Explicit owner-directed
external writes remain possible with existing authorized tools.
"""
from __future__ import annotations

from pathlib import Path

from .runtime_paths import DATA_ROOT

WORKSPACE = DATA_ROOT / "workspace"
AGENT_DIRS = ("projects", "scratch", "artifacts", "downloads", "logs")


def short_instruction() -> str:
    return (
        "Agent work directory: " + str(WORKSPACE) + ". Write projects, scratch, "
        "downloads and artifacts there by default (project='workspace'). "
        "External writes require a specific owner instruction or a necessary "
        "OS service/application integration. See workspace_policy tool."
    )


def instructions() -> str:
    return (
        "MAC CONTROL AGENT WORKSPACE RULE (DEFAULT): "
        f"Use {WORKSPACE} as the single home for every agent-created project, "
        "clone, draft, test fixture, generated output, download, log, and "
        "temporary working file. Prefer project='workspace' in filesystem, "
        "Git and terminal tools. Put repositories under workspace/projects, "
        "temporary files under workspace/scratch, exportable results under "
        "workspace/artifacts and downloads under workspace/downloads. "
        "Do not create projects or scratch directories in ~/Desktop, "
        "~/Documents, ~/Downloads, home root, /tmp, or arbitrary directories "
        "just because a shell or SSH tool could write there. "
        "Reading outside workspace and inspecting the machine is permitted "
        "by the owner's existing authorizations. System integration writes "
        "(launchd plists, app bundles, permissions, service configuration) "
        "may take place at the OS-required locations when genuinely necessary "
        "for the owner's requested task; keep build sources and backups in "
        "workspace. Other writes outside workspace require the owner's "
        "direct, specific instruction naming the intended destination and "
        "purpose. The ability to execute unrestricted shell commands is not "
        "permission to use arbitrary write paths. Do not treat this policy "
        "as a hard filesystem sandbox; it is the operating convention for "
        "agents, and owner-approved exceptions preserve full capabilities. "
        "At task completion, report created files and any off-workspace writes."
    )


def details() -> dict:
    return {
        "default_write_project": "workspace",
        "workspace": str(WORKSPACE),
        "project_directory": str(WORKSPACE / "projects"),
        "temporary_directory": str(WORKSPACE / "scratch"),
        "download_directory": str(WORKSPACE / "downloads"),
        "artifact_directory": str(WORKSPACE / "artifacts"),
        "log_directory": str(WORKSPACE / "logs"),
        "external_read": "allowed by owner-granted tools",
        "external_write": "only owner-specified destination, or necessary OS service/config integration",
        "note": "Agent instruction, not a sandbox or restriction on owner-authorized shell.",
        "instructions": instructions(),
    }


def register(mcp) -> None:
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def workspace_policy() -> dict:
        """Read the mandatory default agent workspace convention before creating files.

        Agent projects, temporary outputs, generated files and clones belong in
        the designated workspace. Exceptions require explicit owner intent.
        """
        return details()
