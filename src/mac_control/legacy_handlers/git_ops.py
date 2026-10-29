"""Bounded Git operations for allowlisted project roots."""
import re
import subprocess
from pathlib import Path
from .fs_ops import roots, target_for

OUTPUT_LIMIT = 24000

def repo(project):
    available = roots()
    if project not in available:
        raise ValueError("Project is not approved")
    base = available[project]
    test = subprocess.run(
        ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=8,
    )
    if test.returncode:
        raise ValueError("Selected project is not a Git repository")
    git_root = Path(test.stdout.strip()).resolve()
    if git_root != base.resolve():
        raise PermissionError("Project root must be repository root")
    return git_root

def git(project, args, timeout=15):
    root = repo(project)
    cmd = ["git", "-c", "core.hooksPath=/dev/null",
           "-C", str(root), "--no-pager", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL,
                          env={"PATH": "/opt/homebrew/bin:/usr/bin:/bin",
                               "HOME": str(Path.home()),
                               "GIT_TERMINAL_PROMPT": "0"})
    return {"exit_code": proc.returncode,
            "stdout": proc.stdout[:OUTPUT_LIMIT],
            "stderr": proc.stderr[:4000],
            "truncated": len(proc.stdout) > OUTPUT_LIMIT}

def checked_path(project, path):
    root, full = target_for(project, path)
    if full == root:
        raise ValueError("Specify a concrete path")
    return str(full.relative_to(root))

def register(mcp):
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def git_status(project: str, limit: int = 12000) -> dict:
        """Git porcelain status and current branch for one approved repository."""
        result = git(project, ["status", "--short", "--branch", "--untracked-files=normal"])
        result["stdout"] = result["stdout"][:max(500, min(limit, OUTPUT_LIMIT))]
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def git_diff(project: str, path: str | None = None,
                 staged: bool = False) -> dict:
        """Read bounded Git diff, optionally one allowed file."""
        args = ["diff", "--no-ext-diff", "--no-color", "--unified=3"]
        if staged:
            args.append("--cached")
        if path is not None:
            args.extend(["--", checked_path(project, path)])
        return git(project, args)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def git_history(project: str, count: int = 12) -> dict:
        """Read recent local commits without accessing remotes."""
        n = max(1, min(int(count), 40))
        return git(project, ["log", f"-{n}", "--format=%h %ad %s",
                             "--date=iso-strict"])

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def git_branches(project: str) -> dict:
        """Read local branches and their current commit references."""
        return git(project, ["branch", "-vv", "--no-color"])

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def git_stage(project: str, paths: list[str]) -> dict:
        """Stage up to 20 explicit allowlisted paths; never use add -A or wildcard."""
        if not 1 <= len(paths) <= 20:
            raise ValueError("Supply 1–20 explicit paths")
        checked = [checked_path(project, p) for p in paths]
        return git(project, ["add", "--", *checked])

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def git_commit(project: str, message: str) -> dict:
        """Commit already staged changes with hooks disabled and explicit approval."""
        if not 1 <= len(message) <= 300 or any(x in message for x in ("\x00", "\r")):
            raise ValueError("Commit message must be 1–300 chars")
        return git(project, ["-c", "commit.gpgsign=false",
                             "commit", "--no-verify", "-m", message], timeout=30)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def git_create_branch(project: str, name: str) -> dict:
        """Create a new local branch; does not switch worktree or contact remote."""
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_./-]{0,79}", name):
            raise ValueError("Invalid branch name")
        return git(project, ["branch", name])

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def git_fetch(project: str) -> dict:
        """Fetch refs only from origin with Git hooks disabled; does not merge."""
        return git(project, ["fetch", "--no-tags", "origin"], timeout=45)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def git_pull_ff(project: str) -> dict:
        """Fast-forward current branch from origin; refuses merges and overwrites."""
        branch = git(project, ["branch", "--show-current"])
        if branch["exit_code"] or not branch["stdout"].strip():
            raise ValueError("No active branch")
        name = branch["stdout"].strip()
        return git(project, ["pull", "--ff-only", "origin", name], timeout=45)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
    def git_push(project: str) -> dict:
        """Push current local branch to origin (explicit write authorization required)."""
        branch = git(project, ["branch", "--show-current"])
        if branch["exit_code"] or not branch["stdout"].strip():
            raise ValueError("No active branch")
        name = branch["stdout"].strip()
        return git(project, ["push", "origin", f"HEAD:refs/heads/{name}"], timeout=45)
