"""Portable maintenance tools and a frozen compatibility dispatcher.

Only workspace text can be changed. Shipped source is read-only, workspace
Python is never imported, and restarting is limited to the exact owned remote
LaunchAgent. No directories, processes or services are changed on import.
"""
from __future__ import annotations

from collections import deque
import importlib.util
from types import ModuleType
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import time
from types import MappingProxyType
from typing import Any

from .runtime_paths import DATA_ROOT
from .legacy_handlers import fs_ops
from .legacy_adapter import inspect_existing_handlers

MAX_FILE = 256 * 1024
# Legacy agents commonly pass a path relative to the approved workspace.
# Accept only known generated-workspace folders, not arbitrary project roots.
WORKSPACE_RELATIVE_PREFIXES = frozenset({
    'projects', 'scratch', 'artifacts', 'downloads', 'shared',
})
MAX_ARGUMENT_BYTES = 128 * 1024
MAX_LOG_BYTES = 8 * 1024 * 1024
RELEASE_ROOT = Path(__file__).resolve().parents[2]
READ_ONLY_FILES = frozenset({
    'scripts/dev_mcp_server.py', 'scripts/setup_remote_service.py',
    'src/mac_control/maintenance_ops.py', 'src/mac_control/audit_middleware.py',
})
LOG_NAMES = MappingProxyType({'stdout': 'remote-mcp.stdout.log',
                              'stderr': 'remote-mcp.stderr.log',
                              'restart': 'restart.log'})
_WRITE_LOCK = threading.Lock()
_SECRET_LINE = re.compile(
    r'(?i)password|passwd|secret|token|authorization|cookie|credential|'
    r'private[ _-]?key|api[ _-]?key|bearer\s|\bgh[pousr]_|\bgithub_pat_|\bsk-|'
    r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b'
)


def _scrub(line: str) -> str:
    # Logs are diagnostic text, not a safe structured secret transport. Drop
    # entire sensitive lines, including quoted/multiline credential material.
    if _SECRET_LINE.search(line):
        return '[REDACTED sensitive log line]'
    return line[:2000]


def _scrub_log(content: str) -> list[str]:
    lines, private_block = [], False
    for line in content.splitlines():
        if re.search(r'-----BEGIN .*PRIVATE KEY-----', line):
            private_block = True
        lines.append('[REDACTED private key block]' if private_block else _scrub(line))
        if re.search(r'-----END .*PRIVATE KEY-----', line):
            private_block = False
    return lines


def _no_symlinks(path: Path) -> None:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise PermissionError('Symlinks are not supported')


def _read(path: Path, maximum: int, *, require_owner: bool = True) -> bytes:
    _no_symlinks(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (require_owner and info.st_uid != os.getuid())):
            raise PermissionError('Only permitted unlinked regular files are supported')
        if info.st_size > maximum:
            raise ValueError('File exceeds size limit')
        content = source.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError('File exceeds size limit')
    return content


def _workspace_path(name: str, *, write: bool = False) -> Path:
    """Default AgentWorkspace; external absolute path needs specific owner approval.

    Audit metadata is a record of user intent, not an authorization grant.
    """
    if not isinstance(name,str) or not name or len(name)>2048 or "\x00" in name:
        raise ValueError('Invalid filesystem path')
    path=Path(name).expanduser()
    if ".." in path.parts:
        raise PermissionError('Path traversal is denied')
    if path.is_absolute():
        _no_symlinks(path)
        target=path.resolve(strict=False)
    else:
        root=fs_ops.roots()['workspace']
        parts=path.parts[1:] if path.parts and path.parts[0]=='workspace' else path.parts
        if not parts:
            raise ValueError('Specify a concrete file within AgentWorkspace')
        _,target=fs_ops.target_for('workspace',Path(*parts).as_posix(),read_only=not write)
        if target==root:
            raise ValueError('Specify a concrete workspace file')
    _no_symlinks(target)
    if target.is_dir():
        raise ValueError('Expected a file, not a directory')
    if target.exists() and target.stat().st_nlink!=1:
        raise PermissionError('Hardlinked files are not supported')
    return target


def _read_target(name: str) -> Path:
    """Read owner-approved file; preserve historic shipped-source aliases."""
    if not isinstance(name,str) or not name or len(name)>2048 or "\x00" in name:
        raise ValueError('Invalid path')
    path=Path(name)
    if not path.is_absolute() and path.as_posix() in READ_ONLY_FILES:
        return RELEASE_ROOT/path
    return _workspace_path(name)


def _audit_record(raw: str) -> dict | None:
    try:
        record = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(record, dict):
        return None
    # Project audit is metadata-only. Do not re-expose historic args/results or
    # arbitrary extra properties if an older writer recorded sensitive data.
    result = {}
    for key in ('time_utc', 'id', 'event', 'tool', 'status', 'duration_ms'):
        value = record.get(key)
        if isinstance(value, str):
            result[key] = _scrub(value)[:160]
        elif key == 'duration_ms' and type(value) in (int, float):
            result[key] = value
    return result


def _log_content(path: Path) -> str | None:
    try:
        return _read(path, MAX_LOG_BYTES).decode('utf-8', errors='replace')
    except (FileNotFoundError, PermissionError):
        return None


def _generic_log_content(path: Path) -> str | None:
    """Read task-authorized absolute log from OS-readable regular file only.

    This bypasses neither OS permissions nor symlink/size safeguards.
    Owner approval for this specific external task must precede use.
    """
    try:
        _no_symlinks(path)
        canonical = path.resolve(strict=True)
        _no_symlinks(canonical)
        fd = os.open(canonical, os.O_RDONLY |
                     getattr(os, 'O_NOFOLLOW', 0) |
                     getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise PermissionError('Only regular log files')
            if info.st_size > MAX_LOG_BYTES:
                raise ValueError('Log exceeds maximum bytes')
            data = source.read(MAX_LOG_BYTES + 1)
            if len(data) > MAX_LOG_BYTES:
                raise ValueError('Log exceeds maximum bytes')
        return data.decode('utf-8', errors='replace')
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return None



def _service_helper():
    """Import ONLY the shipped release module, independently of sys.path/cwd.

    Use a private package name so relative imports inside setup_remote_service
    resolve to the same pinned release/scripts directory. Do not execute
    similarly named modules from a user's workspace, site-packages or sys.path.
    """
    source = RELEASE_ROOT / "scripts" / "setup_remote_service.py"
    parent = source.parent
    if (source.is_symlink() or parent.is_symlink() or not source.is_file()
            or source.resolve(strict=True) != source):
        raise RuntimeError("Shipped remote lifecycle helper is not trustworthy")
    oauth = parent / "setup_github_oauth.py"
    if (oauth.is_symlink() or not oauth.is_file()
            or oauth.resolve(strict=True) != oauth):
        raise RuntimeError("Shipped OAuth dependency is not trustworthy")
    package_name = "_maccontrol_shipped_remote_helpers"
    module_name = package_name + ".setup_remote_service"
    existing = sys.modules.get(module_name)
    if existing is not None and Path(existing.__file__).resolve() == source:
        return existing
    with _WRITE_LOCK:
        existing = sys.modules.get(module_name)
        if existing is not None and Path(existing.__file__).resolve() == source:
            return existing
        if package_name in sys.modules:
            raise RuntimeError("Shipped module namespace collision")
        package = ModuleType(package_name)
        package.__path__ = [str(parent)]
        package.__package__ = package_name
        spec = importlib.util.spec_from_file_location(module_name, source)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load shipped remote lifecycle helper")
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = package
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            if Path(module.__file__).resolve() != source:
                raise RuntimeError("Unexpected remote lifecycle helper source")
        except BaseException:
            sys.modules.pop(module_name, None)
            sys.modules.pop(package_name + ".setup_github_oauth", None)
            sys.modules.pop(package_name, None)
            raise
        return module


def _owned_service(root: Path | None = None) -> tuple[Path, dict]:
    root = root or DATA_ROOT.parent
    if DATA_ROOT != root / 'data' or not (root / '.mac-control-installer-owned').is_file():
        raise FileNotFoundError('No owned installation for this data root')
    service = _service_helper()
    _, plist, expected = service._layout(root, None)
    if not service._read_owned_plist(plist, expected):
        raise FileNotFoundError('Owned remote LaunchAgent is not installed')
    job = service._job(plist, expected)
    if job is None:
        raise FileNotFoundError('Owned remote LaunchAgent is not loaded')
    helper = root / 'current/scripts/setup_remote_service.py'
    # current is the installer-managed release symlink verified by _layout.
    source = helper.resolve(strict=True)
    service._owned(source)
    if source != RELEASE_ROOT / 'scripts/setup_remote_service.py':
        raise RuntimeError('Running release is not the owned current release')
    return source, {'status': job.get('state'), 'pid': job.get('pid'), 'label': service.LABEL}


def _restart_worker(root: Path) -> None:
    time.sleep(3)
    _owned_service(root)  # Revalidate ownership after the delay.
    _service_helper().restart_if_installed(root)


def register(mcp) -> None:
    """Register maintenance tools; custom wrappers freeze shipped handlers once."""
    registry = MappingProxyType(dict(inspect_existing_handlers()))

    def available_entries():
        # The same feature gate controls advertised tools and wrapper dispatch.
        from .dev_enabled_operations import operation_enabled
        return {name: found for name, found in registry.items() if operation_enabled(name)}

    def readonly(fn):
        return mcp.tool(annotations={
                                        'readOnlyHint': True,
                                        'destructiveHint': False,
                                        'idempotentHint': fn.__name__ != 'chat_marker_issue',
                                        'openWorldHint': False,
                                    })(fn)

    def mutation(fn):
        return mcp.tool(annotations={
                                        'readOnlyHint': False,
                                        'destructiveHint': True,
                                        'idempotentHint': False,
                                        'openWorldHint': False,
                                    })(fn)

    @readonly
    def chat_marker_issue() -> dict:
        """Issue a new WC+16hex label ONLY on first use in an unmarked chat.

        The assistant publishes the new marker in its reply, then reuses the
        same audit_context.chat_marker for every subsequent Mac Control call.
        If the current chat already contains a WC marker, DO NOT issue another.
        This is correlation, not authentication; it does not create a ChatGPT chat.
        """
        from .chat_identity import generate_chat_marker
        marker = generate_chat_marker()
        return {
            "chat_marker": marker,
            "instruction": "Publish once in this ChatGPT conversation and reuse "
                           "in audit_context.chat_marker on all subsequent calls.",
            "creates_chat": False,
            "authorizes_actions": False,
        }

    @readonly
    def audit_tail(limit: int = 20) -> dict:
        """Read the latest metadata-only audit events, skipping malformed JSONL."""
        limit = max(1, min(int(limit), 100))
        path = DATA_ROOT / 'logs/audit.jsonl'
        content = _log_content(path)
        events = deque(maxlen=limit)
        for line in (content or '').splitlines():
            record = _audit_record(line)
            if record is not None:
                events.append(record)
        return {'events': list(events), 'source': str(path), 'retention_days': 7}

    @readonly
    def audit_search(tool: str = '', status: str = '', contains: str = '', limit: int = 30) -> dict:
        """Search retained audit metadata; at most 50,000 lines and 8 MiB per file."""
        if any(not isinstance(x, str) or len(x) > 100 for x in (tool, status, contains)):
            raise ValueError('Search filters must be strings of at most 100 characters')
        limit = max(1, min(int(limit), 80))
        directory = DATA_ROOT / 'logs'
        _no_symlinks(directory)
        paths = sorted(directory.glob('audit.jsonl.*')) + [directory / 'audit.jsonl']
        matches, scanned = deque(maxlen=limit), 0
        for path in paths:
            content = _log_content(path)
            for line in (content or '').splitlines():
                if scanned >= 50000:
                    break
                scanned += 1
                record = _audit_record(line)
                if record is None or (tool and record.get('tool') != tool) or (status and record.get('status') != status):
                    continue
                if contains and contains not in json.dumps(record, ensure_ascii=False):
                    continue
                matches.append(record)
            if scanned >= 50000:
                break
        return {'matches': list(matches), 'lines_scanned': scanned,
                'scan_limited': scanned >= 50000, 'retention_days': 7}

    @readonly
    def list_workspace(path: str = 'workspace', limit: int = 100) -> dict:
        """List AgentWorkspace default or task-authorized absolute directory."""
        source=Path(path).expanduser()
        if ".." in source.parts:
            raise PermissionError('Directory traversal is denied')
        if source.is_absolute():
            _no_symlinks(source)
            directory=source.resolve(strict=True)
            _no_symlinks(directory)
            if not directory.is_dir():
                raise NotADirectoryError(path)
        else:
            parts=source.parts[1:] if source.parts and source.parts[0]=='workspace' else source.parts
            nested=Path(*parts).as_posix() if parts else '.'
            _,directory=fs_ops.target_for('workspace',nested,read_only=True)
            _no_symlinks(directory)
            if not directory.is_dir():
                raise NotADirectoryError(path)
        limit=max(1,min(int(limit),200))
        entries=[]
        for entry in sorted(directory.iterdir(),key=lambda item:item.name):
            if len(entries)>=limit:break
            if entry.is_symlink():continue
            entries.append({'name':entry.name,'type':'directory' if entry.is_dir() else 'file',
                            'bytes':entry.stat().st_size if entry.is_file() else None})
        return {'path':path,'entries':entries,'limit':limit}

    @readonly
    def process_snapshot(limit: int = 40) -> dict:
        """List service executable names and resource use; never command arguments."""
        limit = max(1, min(int(limit), 2000))
        proc = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,%cpu=,%mem=,rss=,comm='],
                              capture_output=True, text=True, timeout=5, check=True)
        matched = []
        for line in proc.stdout.splitlines():
            fields = line.strip().split(None, 5)
            if len(fields) != 6:
                continue
            pid, ppid, cpu, mem, rss, command = fields
            executable = Path(command).name.lower()
            matched.append({'pid': pid, 'ppid': ppid, 'cpu_pct': cpu, 'mem_pct': mem,
                            'rss_kb': rss, 'executable': executable})
        return {'processes': matched[:limit], 'total_matched': len(matched)}

    @readonly
    def read_service_log(name: str, lines: int = 25) -> dict:
        """Read scrubbed lines from ANY specifically owner-authorized log path.

        'stdout', 'stderr', 'restart' are convenient owned MCP aliases.
        Absolute external log paths require explicit owner consent for this
        particular task; AgentWorkspace remains the default work directory.
        """
        if not isinstance(name,str) or not name or len(name)>2048 or "\x00" in name:
            raise ValueError('Invalid log name/path')
        lines = max(1, min(int(lines), 100))
        if name in LOG_NAMES:
            path = DATA_ROOT / 'logs' / LOG_NAMES[name]
            content = _log_content(path)
        else:
            path = Path(name).expanduser()
            if not path.is_absolute():
                raise ValueError('Use built-in log alias or explicitly authorized absolute log path')
            content = _generic_log_content(path)
        if content is None:
            return {'name': name, 'lines': [], 'missing': True}
        return {'name': name, 'lines': _scrub_log(content)[-lines:],
                'bytes': path.stat().st_size}

    @readonly
    def mcp_diagnostics(log_paths: list[str] | None = None) -> dict:
        """Show owned MCP state plus log sizes for any task-authorized absolute paths.

        AgentWorkspace is default; log_paths outside it require specific
        owner approval. Never interpret audit metadata as permission.
        """
        try:
            _, state = _owned_service()
        except FileNotFoundError:
            state = {'status': 'not_installed'}
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            state = {'status': 'unavailable', 'error_code': 'OWNERSHIP_OR_SERVICE_CHECK_FAILED'}
        files = {}
        for name in ('audit.jsonl', *LOG_NAMES.values()):
            path = DATA_ROOT / 'logs' / name
            try:
                _no_symlinks(path)
                info = path.stat()
                files[name] = info.st_size if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid() else None
            except (OSError, PermissionError):
                files[name] = None
        for source in log_paths or []:
            if not isinstance(source,str) or not Path(source).expanduser().is_absolute():
                raise ValueError('Explicit log_paths must be absolute')
            path = Path(source).expanduser()
            try:
                _no_symlinks(path)
                resolved = path.resolve(strict=True)
                _no_symlinks(resolved)
                info = resolved.stat()
                files[source] = info.st_size if stat.S_ISREG(info.st_mode) and info.st_size <= MAX_LOG_BYTES else None
            except (OSError, PermissionError):
                files[source] = None
        return {'launchd': state, 'log_bytes': files, 'active_pid': os.getpid()}

    @readonly
    def read_file(path: str) -> dict:
        """Read OS-accessible task-authorized text. AgentWorkspace default; outside only with explicit owner permission for this task."""
        try:
            data = _read(_read_target(path), MAX_FILE, require_owner=False)
            content = data.decode('utf-8')
        except (OSError, ValueError, UnicodeError) as exc:
            return {'ok': False, 'path': str(path)[:2048],
                    'error_code': 'PERMISSION_DENIED' if isinstance(exc, PermissionError) else
                    'NOT_FOUND' if isinstance(exc, FileNotFoundError) else
                    'FILE_TOO_LARGE' if isinstance(exc, ValueError) and 'size limit' in str(exc) else 'UNREADABLE_PATH',
                    'error': 'File is unavailable or outside the approved text-file scope',
                    'path_hint': 'workspace/<file> (or absolute data-workspace equivalent); read-only source: ' + ', '.join(sorted(READ_ONLY_FILES))}
        return {'ok': True, 'path': path, 'content': content, 'sha256': hashlib.sha256(data).hexdigest()}

    @mutation
    def write_file(path: str, content: str, expected_sha256: str | None = None) -> dict:
        """Write task-authorized text, AgentWorkspace DEFAULT; external paths require specific owner permission. SHA256/CAS/backup remain mandatory."""
        data = content.encode('utf-8')
        if len(data) > MAX_FILE:
            raise ValueError('Content exceeds 256 KiB')
        with _WRITE_LOCK:
            target = _workspace_path(path, write=True)
            if target.suffix == '.py':
                compile(content, str(target), 'exec')
            original = _read(target, MAX_FILE) if target.exists() else None
            if original is not None and hashlib.sha256(original).hexdigest() != expected_sha256:
                raise ValueError('SHA256 mismatch or missing')
            if original is None and expected_sha256 is not None:
                raise ValueError('File does not exist')
            _no_symlinks(fs_ops.RECOVERY)
            backup_id = fs_ops.atomic_write(target, data, original)
        return {'written': path, 'sha256': hashlib.sha256(data).hexdigest(),
                'backup': str(fs_ops.RECOVERY / backup_id) if backup_id else None,
                'restart_required': False}

    @readonly
    def self_update_status() -> dict:
        """Read independent self-update status and detect a disappeared watchdog."""
        from . import self_update
        return self_update.status(DATA_ROOT.parent)

    @mutation
    def self_update_start(with_chatbridge: bool = False) -> dict:
        """Schedule verified release update with an independent rollback watchdog.

        Uses the installed owner's current Mac Control release only. The
        watchdog survives this MCP session's restart. ChatBridge updates
        require an explicit true argument; default preserves ChatBridge.
        """
        from . import self_update
        return self_update.start(DATA_ROOT.parent, RELEASE_ROOT, with_chatbridge)

    @mutation
    def restart_server() -> dict:
        """Schedule restart only for this installed, loaded, exactly owned remote agent."""
        try:
            _, _ = _owned_service()
        except FileNotFoundError:
            return {'status': 'not_installed', 'changed': False,
                    'message': 'No loaded owned remote LaunchAgent for this data root'}
        # argv only; no shell, plugin path or caller-selected target. Revalidate
        # ownership in the delayed worker before the lifecycle helper can stop.
        environment = dict(os.environ)
        environment['PYTHONPATH'] = str(RELEASE_ROOT / 'src') + os.pathsep + str(RELEASE_ROOT)
        environment.pop('PYTHONHOME', None)
        subprocess.Popen([sys.executable, '-P', '-B', '-m', 'mac_control.maintenance_ops',
                          '--restart-worker', str(DATA_ROOT.parent)],
                         cwd=RELEASE_ROOT, env=environment, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
        return {'status': 'restart_scheduled', 'delay_seconds': 3, 'message': 'Reconnect after restart'}

    from .argument_guidance import guided_validation_error

    async def execute(operation: str, arguments: dict[str, Any] | None, read_only: bool):
        if not isinstance(operation, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', operation):
            raise ValueError('VALIDATION_ERROR: operation must match [a-z][a-z0-9_]{0,79}; call custom_query(operation=\'help\') to list allowed operations.')
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict) or not all(isinstance(key, str) for key in arguments):
            raise TypeError('arguments must be a JSON object')
        try:
            payload = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, RecursionError):
            raise ValueError('Arguments must be finite JSON values') from None
        if len(payload.encode('utf-8')) > MAX_ARGUMENT_BYTES:
            raise ValueError('Arguments exceed 128 KiB')
        entries = available_entries()
        if operation in ('help', 'list_commands'):
            return {'operations': [{'name': name, 'read_only': found.read_only,
                                    'signature': str(inspect.signature(found.handler)),
                                    'description': (inspect.getdoc(found.handler) or '')[:350]}
                                   for name, found in sorted(entries.items())],
                    'dynamic_plugin': None, 'security': 'Frozen shipped handlers; no workspace executable imports'}
        if operation not in entries:
            raise ValueError('VALIDATION_ERROR: unknown or disabled operation; call custom_query(operation=\'help\') to list available operations. Do not retry disabled tools by another route.')
        found = entries[operation]
        if read_only and not found.read_only:
            raise PermissionError('State-changing operation requires custom_command')
        try:
            inspect.signature(found.handler).bind(**arguments)
        except TypeError as error:
            detail = guided_validation_error(operation, found.handler, error, signature=True)
            raise TypeError(str(detail)) from None
        try:
            result = found.handler(**arguments)
            if inspect.isawaitable(result):
                result = await result
        except ValueError as error:
            raise guided_validation_error(operation, found.handler, error) from None
        if operation in ('mcp_bridge_read', 'mcp_bridge_call') and isinstance(result, list):
            return result
        return {'operation': operation, 'result': result}

    @readonly
    async def custom_query(operation: str = 'help', arguments: dict[str, Any] | None = None):
        """Call a shipped read-only operation; help lists enabled frozen handlers."""
        return await execute(operation, arguments, True)

    @mutation
    async def custom_command(operation: str, arguments: dict[str, Any] | None = None):
        """Call a shipped operation using JSON arguments; respects installed feature flags."""
        return await execute(operation, arguments, False)


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--restart-worker':
        raise SystemExit('Only the owned restart worker entry point is supported')
    try:
        _restart_worker(Path(sys.argv[2]))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        raise SystemExit(1) from None
