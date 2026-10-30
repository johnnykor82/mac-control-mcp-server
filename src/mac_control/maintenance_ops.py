"""Portable maintenance tools and a frozen compatibility dispatcher.

Only workspace text can be changed. Shipped source is read-only, workspace
Python is never imported, and restarting is limited to the exact owned remote
LaunchAgent. No directories, processes or services are changed on import.
"""
from __future__ import annotations

from collections import deque
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


def _read(path: Path, maximum: int) -> bytes:
    _no_symlinks(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid()):
            raise PermissionError('Only owned, unlinked regular files are permitted')
        if info.st_size > maximum:
            raise ValueError('File exceeds size limit')
        content = source.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError('File exceeds size limit')
    return content


def _workspace_path(name: str, *, write: bool = False) -> Path:
    if not isinstance(name, str) or not name or len(name) > 2048 or '\x00' in name:
        raise ValueError('Nonempty relative workspace path required (max 2048 characters)')
    relative = Path(name)
    if relative.is_absolute():
        if write:
            raise PermissionError('Writes require a workspace-relative path')
        try:
            relative = relative.relative_to(DATA_ROOT)
        except ValueError:
            raise PermissionError('Path is outside the data workspace') from None
    if (not relative.parts or relative.parts[0] != 'workspace'
            or len(relative.parts) < 2 or '..' in relative.parts):
        raise PermissionError('Only workspace/<file> is writable')
    _no_symlinks(DATA_ROOT / 'workspace')
    # Reuse the existing sensitive/hidden/generated path denylist. No new
    # project root or credentials configuration can be written through aliases.
    _, target = fs_ops.target_for('workspace', Path(*relative.parts[1:]).as_posix())
    if target == (DATA_ROOT / 'workspace') or target.is_dir():
        raise ValueError('Expected a workspace file')
    if target.exists() and target.stat().st_nlink != 1:
        raise PermissionError('Hardlinked files are not supported')
    return target


def _read_target(name: str) -> Path:
    if not isinstance(name, str) or not name or len(name) > 2048 or '\x00' in name:
        raise ValueError('Invalid path')
    relative = Path(name)
    if relative.is_absolute():
        try:
            relative = relative.relative_to(RELEASE_ROOT)
        except ValueError:
            return _workspace_path(name)
    if relative.as_posix() in READ_ONLY_FILES:
        return RELEASE_ROOT / relative
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


def _service_helper():
    # Static shipped import. Never load executable code from DATA_ROOT.
    try:
        from scripts import setup_remote_service
    except ModuleNotFoundError as exc:
        if exc.name != 'scripts':
            raise
        # Script launches put release/scripts, rather than release, on sys.path.
        import setup_remote_service
    if Path(setup_remote_service.__file__).resolve() != RELEASE_ROOT / 'scripts/setup_remote_service.py':
        raise RuntimeError('Unexpected remote lifecycle helper source')
    return setup_remote_service


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
        return mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})(fn)

    def mutation(fn):
        return mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True,
                                     'openWorldHint': False})(fn)

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
        """List non-sensitive entries under workspace, without following symlinks."""
        relative = Path(path)
        if relative.is_absolute() or not relative.parts or relative.parts[0] != 'workspace' or '..' in relative.parts:
            raise ValueError('Only workspace-relative paths are allowed')
        _no_symlinks(DATA_ROOT / 'workspace')
        nested = Path(*relative.parts[1:]).as_posix()
        base, directory = fs_ops.target_for('workspace', nested)
        if not directory.is_dir():
            raise NotADirectoryError(path)
        limit = max(1, min(int(limit), 200))
        entries = []
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            try:
                fs_ops.target_for('workspace', entry.relative_to(base).as_posix())
            except (ValueError, PermissionError):
                continue
            if entry.is_symlink():
                continue
            entries.append({'name': entry.name, 'type': 'directory' if entry.is_dir() else 'file',
                            'bytes': entry.stat().st_size if entry.is_file() else None})
            if len(entries) >= limit:
                break
        return {'path': path, 'entries': entries, 'limit': limit}

    @readonly
    def process_snapshot(limit: int = 40) -> dict:
        """List service executable names and resource use; never command arguments."""
        limit = max(1, min(int(limit), 100))
        proc = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,%cpu=,%mem=,rss=,comm='],
                              capture_output=True, text=True, timeout=5, check=True)
        matched = []
        for line in proc.stdout.splitlines():
            fields = line.strip().split(None, 5)
            if len(fields) != 6:
                continue
            pid, ppid, cpu, mem, rss, command = fields
            executable = Path(command).name.lower()
            if any(name in executable for name in ('python', 'litellm', 'openclaw', 'node', 'hermes', 'tailscale')):
                matched.append({'pid': pid, 'ppid': ppid, 'cpu_pct': cpu, 'mem_pct': mem,
                                'rss_kb': rss, 'executable': executable})
        return {'processes': matched[:limit], 'total_matched': len(matched)}

    @readonly
    def read_service_log(name: str, lines: int = 25) -> dict:
        """Read a scrubbed tail of stdout, stderr or restart from the data logs."""
        if name not in LOG_NAMES:
            raise ValueError('Allowed names: stdout, stderr, restart')
        lines = max(1, min(int(lines), 100))
        path = DATA_ROOT / 'logs' / LOG_NAMES[name]
        content = _log_content(path)
        if content is None:
            return {'name': name, 'lines': [], 'missing': True}
        return {'name': name, 'lines': _scrub_log(content)[-lines:],
                'bytes': path.stat().st_size}

    @readonly
    def mcp_diagnostics() -> dict:
        """Show only owned launchd state, PID and allowlisted log sizes."""
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
        return {'launchd': state, 'log_bytes': files, 'active_pid': os.getpid()}

    @readonly
    def read_file(path: str) -> dict:
        """Read UTF-8 workspace text or explicit read-only shipped source (256 KiB)."""
        try:
            data = _read(_read_target(path), MAX_FILE)
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
        """Write workspace UTF-8 text atomically with existing-file SHA256 and backup."""
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

    async def execute(operation: str, arguments: dict[str, Any] | None, read_only: bool):
        if not isinstance(operation, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', operation):
            raise ValueError('Invalid operation')
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
            raise ValueError('Unknown or disabled operation; call help')
        found = entries[operation]
        if read_only and not found.read_only:
            raise PermissionError('State-changing operation requires custom_command')
        inspect.signature(found.handler).bind(**arguments)
        result = found.handler(**arguments)
        if inspect.isawaitable(result):
            result = await result
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
