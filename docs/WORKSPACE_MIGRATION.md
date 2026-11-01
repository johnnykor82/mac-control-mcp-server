# Independent user workspace — beta.22

Mac Control's installer owns releases, GUI, dependencies, runtime state,
config and service logs under `~/MacControlMCP/`. User-generated sources,
repositories, databases and artifacts belong **outside** the installation,
by default in `~/AgentWorkspace/` with `projects/`, `shared/`,
`artifacts/`, `downloads/` and `scratch/`.

The configured `workspace_root` is stored in the owner-only
`<install>/data/config/workspace.json` (0600), independent of release versions.
The development preview defaults to `~/AgentWorkspace-Dev/`.
Custom-prefix installations default to a sibling `AgentWorkspace` directory.
Changing the path does not move files and must not create a phantom local
directory when an external disk has been unmounted.

```sh
maccontrol workspace status
maccontrol workspace set /Volumes/ExternalDisk/AgentWorkspace
maccontrol workspace inventory --from ~/chatgpt-mcp/workspace
maccontrol workspace migrate --from ~/chatgpt-mcp/workspace --name old-server
# Copy only after explicit consent, never during install/update:
maccontrol workspace migrate --from ~/chatgpt-mcp/workspace --name old-server --execute --yes
```

Migration defaults to a read-only dry-run, reporting file counts, bytes,
symlinks, SQLite databases and WAL companions, free space and LaunchAgents
mentioning the source path. Explicit `--execute --yes` copies the entire
legacy tree into `workspace_root/projects/old-server`, without touching
the original. Non-SQLite files are verified with SHA-256; live SQLite
databases are copied via the SQLite backup API and checked for integrity.
Symlinks are preserved without following them; file modes and timestamps
are preserved. Conflicting destination paths are refused without overwrite.
The copy is staged and only published after verification.

The migration tool does **not** restart services, rewrite LaunchAgents,
change production network access or migrate application-specific secrets.
Service dependency rewrites require separate owner authorization and tests.
Keep an additional independent backup before retiring the legacy installation.

`update`, `rollback` and ordinary `uninstall` leave the workspace
unchanged. A rollback to a release without external workspace awareness
is blocked rather than hiding projects. Full `uninstall --all` never
deletes the external workspace; it refuses to purge a legacy workspace
that still contains user files. Existing installations continue to use
their populated legacy workspace until migration is explicitly requested.

This is a **default location and data-lifecycle separation**, not a
sandbox or restriction on authorized operations outside that location.

### Watcher reports and backward compatibility

New Watcher human-readable browser results and file-task reports are saved
under `workspace_root/artifacts/watcher-results/` and
`workspace_root/artifacts/watcher-reports/`. Its internal task database,
locks and service configuration remain under the product data directory.
Historical indexed reports at their original paths remain readable, and
install/update will not move or overwrite them. Changing the user workspace
path does not relocate existing reports.
