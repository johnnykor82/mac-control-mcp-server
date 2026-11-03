#!/usr/bin/env python3
"""Deterministic, byte-for-byte E9 source-payload archive acceptance.

Source file list is the installer's explicit manifest, not a Git archive
or all files present in a developer's source checkout.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

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


def build_archive(root: Path) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0, compresslevel=9) as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in _entries(root):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def inspect_archive(data: bytes, root: Path) -> dict:
    expected = dict(_entries(root))
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        actual = {}
        for member in archive.getmembers():
            if not member.isfile() or member.name in actual:
                raise ValueError("Invalid archive member or duplicate name")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Missing regular archive payload")
            actual[member.name] = stream.read()
    if actual != expected:
        raise ValueError("Source archive content mismatch")
    return {"files": len(actual), "bytes": sum(len(value) for value in actual.values()),
            "sha256": hashlib.sha256(data).hexdigest()}


if __name__ == "__main__":
    archive = build_archive(ROOT)
    print(json.dumps(inspect_archive(archive, ROOT), indent=2))
