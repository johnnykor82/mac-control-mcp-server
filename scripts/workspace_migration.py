"""Explicit, non-destructive migration of legacy data into an external workspace.

Nothing executes on import. No service configuration, launchd, or source
project is modified. All writes are inside the chosen external workspace.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import uuid

from mac_control.workspace_config import ensure, _safe_path


def _hash(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk(source):
    for current, dirs, files in os.walk(source, followlinks=False):
        base=Path(current)
        for name in sorted(dirs+files):
            path=base/name
            if path.is_symlink():
                yield path,"link"
            elif path.is_file():
                if not stat.S_ISREG(path.stat().st_mode):
                    raise ValueError("Unsupported nonregular source file")
                yield path,"file"
            elif path.is_dir():
                yield path,"directory"
            else:
                raise ValueError("Unsupported special source path")


def inventory(source: Path, destination_root: Path):
    source=_safe_path(source)
    destination_root=_safe_path(destination_root)
    if not source.is_dir():
        raise FileNotFoundError("Legacy source workspace unavailable")
    if destination_root == source or destination_root.is_relative_to(source) or source.is_relative_to(destination_root):
        raise ValueError("Migration source and destination must be independent")
    stats={"files":0,"directories":0,"symlinks":0,"sqlite":0,
           "bytes":0,"sqlite_wal_files":0}
    for item,kind in _walk(source):
        if kind=="link":
            stats["symlinks"]+=1
        elif kind=="directory":
            stats["directories"]+=1
        else:
            stats["files"]+=1
            size=item.stat().st_size
            stats["bytes"]+=size
            if item.suffix in (".sqlite",".sqlite3",".db") or _sqlite_header(item):
                stats["sqlite"]+=1
            if item.name.endswith(("-wal","-shm")):
                stats["sqlite_wal_files"]+=1
    agents=Path.home()/"Library/LaunchAgents"
    referenced=[]
    if agents.is_dir():
        for plist in agents.glob("*.plist"):
            if plist.is_file() and not plist.is_symlink() and plist.stat().st_size<1024*1024:
                if str(source).encode("utf-8") in plist.read_bytes():
                    referenced.append(plist.name)
    free = shutil.disk_usage(destination_root if destination_root.exists() else destination_root.parent).free
    return {"source":str(source),"destination_root":str(destination_root),
            "inventory":stats,"free_bytes":free,"enough_space":free>=stats["bytes"]*2,
            "launchagents_referring_to_source":referenced,
            "source_preserved":True, "services_changed":False}


def _sqlite_header(path):
    if path.stat().st_size<16:
        return False
    with path.open("rb") as f:
        return f.read(16)==b"SQLite format 3\x00"


def _snapshot_database(source, target):
    connection=sqlite3.connect(source.as_uri()+"?mode=ro",uri=True,timeout=10)
    destination=sqlite3.connect(str(target))
    try:
        connection.backup(destination,pages=256,sleep=0.05)
        result=destination.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0]!="ok":
            raise RuntimeError("SQLite migration integrity check failed")
        destination.commit()
    finally:
        connection.close()
        destination.close()
    shutil.copystat(source,target,follow_symlinks=False)


def _copy_verified(source,destination):
    source=Path(source)
    sqlite_sources={str(path) for path,kind in _walk(source) if kind=="file" and _sqlite_header(path)}
    for file,kind in _walk(source):
        rel=file.relative_to(source)
        target=destination/rel
        if kind=="directory":
            target.mkdir(mode=0o700,parents=True,exist_ok=False)
            continue
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if kind=="link":
            target.symlink_to(os.readlink(file))
        elif file.name.endswith(("-wal","-shm")) and str(file)[:-4] in sqlite_sources:
            # A live SQLite backup contains committed WAL pages already.
            continue
        elif str(file) in sqlite_sources:
            _snapshot_database(file,target)
        else:
            shutil.copy2(file,target,follow_symlinks=False)
            if _hash(file)!=_hash(target):
                raise RuntimeError("SHA-256 mismatch while copying source")
    for folder,kind in reversed(list(_walk(source))):
        if kind=="directory":
            shutil.copystat(folder,destination/folder.relative_to(source),follow_symlinks=False)
    shutil.copystat(source,destination,follow_symlinks=False)


def migrate(source: Path, destination_root: Path, name: str="legacy-import", *,
            execute: bool=False, confirmed: bool=False) -> dict:
    result=inventory(source,destination_root)
    if not name or name in (".","..") or len(name)>80 or "/" in name or "\\" in name:
        raise ValueError("Invalid import directory name")
    destination=Path(result["destination_root"])/"projects"/name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Migration destination already exists; no overwrite permitted")
    result["destination"]=str(destination)
    result["mode"]="dry_run" if not execute else "copy"
    if not execute:
        return result
    if not confirmed:
        raise PermissionError("Copy requires explicit --execute --yes confirmation")
    if not result["enough_space"]:
        raise OSError("Insufficient free space for verified migration copy")
    workspace=ensure(Path(result["destination_root"]),create=False)
    projects=workspace/"projects"
    if projects.is_symlink() or not projects.is_dir():
        raise PermissionError("Projects directory unavailable or unsafe")
    stage=projects/(".migration-"+uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    try:
        _copy_verified(Path(result["source"]),stage)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Destination was created during migration")
        # Atomic publish of copied tree only. Source is never removed.
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    result["status"]="copied_and_verified"
    return result
