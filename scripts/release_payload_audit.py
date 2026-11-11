"""Deterministic, byte-for-byte E9 source-payload archive acceptance.

Source file list is the installer's explicit manifest, not a Git archive
or all files present in a developer's source checkout.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

from scripts.install_mac_control import COPY_DIRS, COPY_FILES

ROOT = Path(__file__).resolve().parents[1]


def _entries(root: Path) -> list[tuple[str, bytes]]:
    path = root / "scripts/install_manifest.txt"
    files = []
    seen = set()
    for entry in path.read_text(encoding="utf-8").splitlines():
        relative = Path(entry)
        if (not entry or relative.is_absolute() or ".." in relative.parts
                or not (relative.parts[0] in COPY_DIRS or entry in COPY_FILES)):
            raise ValueError("Invalid manifest source path")
        if entry in seen:
            raise ValueError("Duplicate manifest source: " + entry)
        seen.add(entry)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Refusing symlink in release payload")
        if not current.is_file():
            raise ValueError("Manifest file missing or not regular: " + entry)
        files.append((entry, current.read_bytes()))
    return sorted(files)


def _mode(root: Path, name: str) -> int:
    # The updater maps executable tar members to private mode 0700.
    # Preserve Git checkout execute bits instead of downgrading every
    # launcher to 0644 (which becomes non-executable 0600 on install).
    return 0o755 if (root / name).stat().st_mode & 0o111 else 0o644


def _prefix(tagged_prefix: str | None) -> str | None:
    if tagged_prefix is not None and not re.fullmatch(
        r"mac-control-mcp-server-v0\.1\.0-beta\.\d+", tagged_prefix
    ):
        raise ValueError("Invalid release archive root prefix")
    return tagged_prefix


def build_archive(root: Path, prefix: str | None = None) -> bytes:
    prefix = _prefix(prefix)
    buffer = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0, compresslevel=9) as zipped,
        tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as archive,
    ):
        if prefix is not None:
            directory = tarfile.TarInfo(prefix)
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o755
            directory.mtime = 0
            archive.addfile(directory)
        for name, data in _entries(root):
            info = tarfile.TarInfo(f"{prefix}/{name}" if prefix else name)
            info.size = len(data)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode = _mode(root, name)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def inspect_archive(data: bytes, root: Path, prefix: str | None = None) -> dict:
    prefix = _prefix(prefix)
    expected = dict(_entries(root))
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        actual = {}
        found_root = False
        for member in archive.getmembers():
            if prefix is not None and member.name == prefix and member.isdir():
                if found_root:
                    raise ValueError("Duplicate release archive root")
                found_root = True
                continue
            name = member.name
            if prefix is not None:
                if not name.startswith(prefix + "/"):
                    raise ValueError("Unexpected release archive path")
                name = name[len(prefix) + 1:]
            if not member.isfile() or name in actual or name not in expected:
                raise ValueError("Invalid archive member or duplicate name")
            if (member.mode & 0o777) != _mode(root, name):
                raise ValueError("Source archive permission mismatch: " + name)
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Missing regular archive payload")
            actual[name] = stream.read()
        if prefix is not None and not found_root:
            raise ValueError("Release archive root missing")
    if actual != expected:
        raise ValueError("Source archive content mismatch")
    return {"files": len(actual), "bytes": sum(len(value) for value in actual.values()),
            "sha256": hashlib.sha256(data).hexdigest()}


if __name__ == "__main__":
    archive = build_archive(ROOT)
    print(json.dumps(inspect_archive(archive, ROOT), indent=2))
