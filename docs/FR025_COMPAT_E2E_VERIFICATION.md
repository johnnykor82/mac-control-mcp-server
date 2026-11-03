# FR-025.3 — argument compatibility: E2E and Converge verification

2026-11-03, pre-release verification; owner-approved Mac Control roadmap 1.1.

## Reproduction and root cause (Assess)

Maintenance write_file required path=workspace/projects/... but legacy
fs_write(project=workspace, path=projects/...) resolved the same
file. Earlier use of write_file(path=projects/...) raised an opaque
permission error, even though the target was within the authorized
workspace. The failure occurred before writing. This was a tool
contract mismatch, not evidence of an unauthorized target.

## Fix

- Allow known workspace-relative prefixes (projects/, scratch/,
  artifacts/, downloads/, shared/) in maintenance read_file/write_file.
  Both spellings continue to resolve through fs_ops.target_for workspace.
- Keep read/write signatures and all 106 legacy FastMCP signatures.
- Keep 256 KiB limit, CAS hash required for an existing file, backup,
  sensitive path denylist, no hidden directories or symlinks, no outside
  roots, no hidden fallback or side-effect retry.
- Return WORKSPACE_PATH_FORMAT_INVALID for ambiguous relative paths
  before executing anything; no echo of the rejected caller path.
- Ship TOOL_ARGUMENT_COMPATIBILITY_FR025.md through the installer
  manifest AND explicit COPY_FILES allowlist.

## Tests (Test)

- Existing original-path regression was RED before implementation.
- Maintenance and path contracts: 22 focused PASS, including all five
  prefixes, CAS/backups, cross-tool read/write and rejected traversal.
- Full isolated test discovery: 647 PASS with 1 skipped
  (the summary convention counts all 647, including the skipped test).
- Isolated packaged-release subprocess: copy_source into a disposable
  release directory, configure a fresh isolated workspace/data root,
  invoke actual MCP write_file then fs_write then read_file, verify
  identical content and SHA256/backup, no real owned services.
- Concurrent update/restart recovery and rollback fixtures:
  30 tests covering staged release, lifecycle and retention all PASS.
- Independent macOS CI for source fix SHA 06476ed:
  https://github.com/johnnykor82/mac-control-mcp-server/actions/runs/41614382278
  = success. New staged test must pass its own subsequent CI before merge.
- Strict tracked-source audit: 0 critical, 18 historical warnings.
  Deterministic copied-release payload: 116 files,
  SHA256 4fbd6459897c4dd30f8c7807bab0a3adb7fe8a8ba4eafa3528d2a3d90e6a0d82.

## Limits and pending gates (Converge)

- Source-level interface and isolated runtime are verified.
  Real jkmac Android A08 files were not touched; new Mac Control release
  must be installed before the updated alias works there.
- Actual ChatGPT OAuth linked account deduplication and missing
  openai/session cannot be proven through this isolated E2E.
  Tool signatures in a frozen ChatGPT snapshot may require refresh.
- No public release, PR merge, GitHub app reauthorization, real-host
  SSH command or remote service restart occurs during these tests.
  Final independent CI and explicit review/merge/release gates remain.


## macOS CI portability correction / 2026-11-03

The first PR CI isolated E2E failed on macos-15 because
TemporaryDirectory used /var/folders/..., where /var is a macOS
symlink to /private/var. The protected backup path was correctly
rejected by the production _no_symlinks guard. The test now resolves
its disposable temporary root to an actual filesystem path before
setting MAC_CONTROL_DATA_ROOT and workspace_root. No production
permission check or security guard was changed. The original local
pass alone was insufficient; final macOS CI is required.


## E9 native GUI release parity candidate / 2026-11-03

The earlier fresh installer downloaded the beta.11 GUI, even when
the server source advanced. A source-built beta.29 universal helper
archive was staged independently with package_gui_release.py and
verified with extract_release(), _verify_payload(), codesign --verify,
and universal Mach-O architecture checks. SHA256:
7c1e99163d3c765492f3b035daf609b43092c28ea1380f4c4886b655fdf156ad.
No installed app, TCC approval or production service was changed.
The default source pin now references the beta.29 artifact. Until
release publication, the URL is intentionally not yet downloadable;
do not interpret the pin as a successfully published binary.
