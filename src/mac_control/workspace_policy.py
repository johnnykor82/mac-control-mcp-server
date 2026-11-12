"""Agent writing conventions exposed as MCP server instructions and a tool.

This is a behavioral default, not an OS sandbox. Explicit owner-directed
external writes remain possible with existing authorized tools.
"""
from __future__ import annotations

from pathlib import Path

from .workspace_config import workspace_root

WORKSPACE = workspace_root()

def current_workspace() -> Path:
    return workspace_root()
AGENT_DIRS = ("projects", "shared", "artifacts", "downloads", "scratch")


def short_instruction() -> str:
    return (
        "Agent work directory: " + str(current_workspace()) + ". Write projects, scratch, "
        "downloads and artifacts there by default (project='workspace'). "
        "ANY access outside AgentWorkspace requires the owner's specific permission "
        "for THIS task (including reads and writes); do not infer approval from "
        "audit_context. Legitimate OS service locations must be included in "
        "the owner's authorized plan. See workspace_policy tool."
    )


def instructions() -> str:
    return (
        "MAC CONTROL AGENT WORKSPACE RULE (DEFAULT): "
        f"Use {current_workspace()} as the single home for every agent-created project, "
        "clone, draft, test fixture, generated output, download, log, and "
        "temporary working file. Prefer project='workspace' in filesystem, "
        "Git and terminal tools. Put repositories under workspace/projects, "
        "temporary files under workspace/scratch, exportable results under "
        "workspace/artifacts and downloads under workspace/downloads. "
        "Do not create projects or scratch directories in ~/Desktop, "
        "~/Documents, ~/Downloads, home root, /tmp, or arbitrary directories "
        "just because a shell or SSH tool could write there. "
        "ANY access outside AgentWorkspace, including reads and writes, "
        "requires the owner's explicit authorization for the concrete task "
        "and its intended targets. System integration operations (launchd "
        "plists, app bundles, service configuration) at OS-required paths "
        "are allowed ONLY when specifically covered by the owner's request "
        "or approved plan. Keep build sources and backups in workspace. "
        "Never treat audit_context statements as a grant: they record intent "
        "but do not create permission. Unrestricted shell capability does "
        "not authorize arbitrary paths or new task scope. This policy is "
        "an agent operating convention, not a hard OS sandbox; specific "
        "owner-approved exceptions preserve full tool capabilities. "
        "For remote files over SSH, use ssh_write_text for generated UTF-8 "
        "content, ssh_upload for existing Mac files and ssh_transfer_* "
        "for large binary or streaming data. Never send large file contents "
        "through ssh_exec with heredoc, cat or printf. "
        "At task completion, report created files and any off-workspace writes."
    )


def details() -> dict:
    return {
        "default_write_project": "workspace",
        "workspace": str(current_workspace()),
        "project_directory": str(current_workspace() / "projects"),
        "temporary_directory": str(current_workspace() / "scratch"),
        "download_directory": str(current_workspace() / "downloads"),
        "artifact_directory": str(current_workspace() / "artifacts"),
        "log_directory": str(current_workspace() / "scratch/logs"),
        "shared_directory": str(current_workspace() / "shared"),
        "external_read": "only when owner explicitly approves external target for this task",
        "external_write": "only when owner explicitly approves external target for this task, including OS integration",
        "note": "Agent instruction, not a sandbox or restriction on owner-authorized shell.",
        "instructions": instructions(),
    }


def register(mcp) -> None:
    @mcp.tool(annotations={
                              'readOnlyHint': True,
                              'destructiveHint': False,
                              'idempotentHint': True,
                              'openWorldHint': False,
                          })
    def workspace_policy() -> dict:
        """Read the mandatory default agent workspace convention before creating files.

        Agent projects, temporary outputs, generated files and clones belong in
        the designated workspace. Exceptions require explicit owner intent.
        """
        return details()
