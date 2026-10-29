"""Generic media transport for existing Mac Control MCP bridge; no new tools."""
import base64
import binascii
import hashlib
import json
import mimetypes
import os
import re
import secrets
import stat
import time
from pathlib import Path

from mcp.types import ImageContent, AudioContent, TextContent
from ..runtime_paths import DATA_ROOT

ROOT = DATA_ROOT / "run" / "bridge-media"
TTL = 3600
INLINE_MAX = 512 * 1024
STAGE_MAX = 128 * 1024 * 1024
CACHE_MAX = 512 * 1024 * 1024
FILE_MAX = 16 * 1024**3
CHUNK_MAX = 12 * 1024
B64_FIELDS = {
    "image_data": "image/jpeg",
    "audio_data": "audio/wav",
    "video_data": "video/mp4",
    "file_data": "application/octet-stream",
}
MEDIA_ID = re.compile(r"[0-9a-f]{32}\Z")
MIME = re.compile(r"[-\w.+]+/[-\w.+]+(?:;[-\w=.+]+)?\Z")


def _root():
    if ROOT.is_symlink():
        raise PermissionError("Media cache cannot be a symlink")
    ROOT.mkdir(parents=True, mode=0o700, exist_ok=True)
    st = ROOT.stat()
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise PermissionError("Media cache must be owner-only 0700")
    return ROOT


def _name(name):
    value = str(name or "media.bin").split("/")[-1].split("\\")[-1]
    return ("".join(c for c in value if c.isascii() and
                    (c.isalnum() or c in "._-")) or "media.bin")[:90]


def _mime(value, fallback):
    return value if isinstance(value, str) and MIME.fullmatch(value) else fallback


def _hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def _public(metadata):
    return {k: metadata[k] for k in
            ("id", "name", "mime_type", "bytes", "sha256", "expires")} | {
        "chunk_max_bytes": CHUNK_MAX,
        "read_via": "mcp_bridge_read(target,tool,media={id,offset,length})",
    }


def _gc(root):
    now = time.time()
    for path in root.glob("*.json"):
        if path.is_symlink() or not MEDIA_ID.fullmatch(path.stem):
            continue
        try:
            if json.loads(path.read_text()).get("expires", 0) < now:
                path.unlink()
                (root / (path.stem + ".bin")).unlink(missing_ok=True)
        except (ValueError, OSError):
            pass


def _record(metadata, raw=None):
    root = _root()
    _gc(root)
    if raw is not None:
        if len(raw) > STAGE_MAX:
            raise ValueError("Large media must use a media_file reference")
        cached = sum(p.stat().st_size for p in root.glob("*.bin")
                     if p.is_file() and not p.is_symlink())
        if cached + len(raw) > CACHE_MAX:
            raise ValueError("Media cache quota exhausted")
    token = secrets.token_hex(16)
    meta = {**metadata, "id": token, "expires": int(time.time()) + TTL}
    blob = root / (token + ".bin")
    record = root / (token + ".json")
    try:
        if raw is not None:
            fd = os.open(blob, os.O_EXCL | os.O_CREAT | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
        fd = os.open(record, os.O_EXCL | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(meta, f)
    except BaseException:
        blob.unlink(missing_ok=True)
        record.unlink(missing_ok=True)
        raise
    return _public(meta)


def stage_bytes(raw, target, tool, mime, name):
    return _record({
        "source": "cache", "target": target, "tool": tool,
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "mime_type": _mime(mime, "application/octet-stream"),
        "name": _name(name),
    }, raw=raw)


def stage_file(data, target, tool, allowed_root):
    """Stream-hash a file solely in the owner's configured per-target media root."""
    if not allowed_root or not isinstance(data, dict):
        raise PermissionError("media_file needs an explicitly approved media_root")
    root = Path(allowed_root)
    path = Path(data.get("path", ""))
    if (not root.is_absolute() or not root.is_dir() or root.is_symlink()
        or not path.is_absolute() or not path.is_file() or path.is_symlink()):
        raise PermissionError("Invalid media root or file")
    root_resolved = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root_resolved) or resolved == root_resolved:
        raise PermissionError("File outside approved media root")
    cursor = path
    while cursor != root:
        if cursor.is_symlink():
            raise PermissionError("Symlinked media path")
        cursor = cursor.parent
        if cursor == cursor.parent:
            raise PermissionError("Media path traversal")
    if root.stat().st_uid != os.getuid() or path.stat().st_uid != os.getuid():
        raise PermissionError("Media root/file must be owned by current user")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_size > FILE_MAX:
        raise ValueError("Media file is invalid or exceeds configured limit")
    meta = {
        "source": "file", "target": target, "tool": tool,
        "path": str(resolved), "root": str(root_resolved),
        "inode": st.st_ino, "mtime_ns": st.st_mtime_ns,
        "bytes": st.st_size, "sha256": _hash_file(path),
        "mime_type": _mime(data.get("mime_type"),
                           mimetypes.guess_type(str(path))[0] or "application/octet-stream"),
        "name": _name(data.get("name") or path.name),
    }
    return _record(meta)


def chunk(target, tool, request):
    """Bounded, resumable byte range; never expands to more than 16k JSON."""
    if not isinstance(request, dict):
        raise ValueError("Media request must be an object")
    token = request.get("id")
    off, length = request.get("offset", 0), request.get("length", 8192)
    if not isinstance(token, str) or not MEDIA_ID.fullmatch(token):
        raise ValueError("Invalid media id")
    if type(off) is not int or type(length) is not int or off < 0 or not 1 <= length <= CHUNK_MAX:
        raise ValueError("Invalid media byte range")
    root = _root()
    path = root / (token + ".json")
    if not path.is_file() or path.is_symlink() or path.stat().st_uid != os.getuid():
        raise FileNotFoundError("Media reference not found")
    meta = json.loads(path.read_text())
    if meta.get("target") != target or meta.get("tool") != tool or meta.get("id") != token:
        raise PermissionError("Media ticket is scoped to its originating target/tool")
    if meta.get("expires", 0) < time.time():
        raise FileNotFoundError("Media reference expired")
    total = meta["bytes"]
    if off > total:
        raise ValueError("Offset beyond end of file")
    if meta["source"] == "cache":
        source = root / (token + ".bin")
    elif meta["source"] == "file":
        source = Path(meta["path"])
        allowed = Path(meta["root"])
        if (source.is_symlink() or not source.resolve().is_relative_to(allowed)
            or not source.is_file() or source.stat().st_uid != os.getuid()
            or source.stat().st_size != total or source.stat().st_ino != meta["inode"]
            or source.stat().st_mtime_ns != meta["mtime_ns"]):
            raise PermissionError("Media source changed since ticket creation")
    else:
        raise ValueError("Unknown media storage type")
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError("Media bytes no longer available")
    # O_NOFOLLOW + fstat ties checks to the opened descriptor; no symlink swap.
    descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as f:
        opened = os.fstat(f.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                or opened.st_size != total
                or (meta["source"] == "file" and
                    (opened.st_ino != meta["inode"] or
                     opened.st_mtime_ns != meta["mtime_ns"]))):
            raise PermissionError("Media source changed during opening")
        f.seek(off)
        payload = f.read(min(length, total - off))
    return {
        "id": token, "offset": off, "bytes": len(payload),
        "next_offset": off + len(payload), "complete": off + len(payload) == total,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "base64": base64.b64encode(payload).decode("ascii"),
        "total_bytes": total, "mime_type": meta["mime_type"],
    }


def _decode(encoded):
    if len(encoded) > 4 * ((STAGE_MAX + 2) // 3) + 4:
        raise ValueError("Media base64 too large; use media_file reference")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid downstream media encoding") from exc
    if len(data) > STAGE_MAX:
        raise ValueError("Media exceeds staging allowance")
    return data


def pack(target, tool, result, settings):
    """Promote binary MCP data to native content blocks or small metadata."""
    body = getattr(result, "data", None)
    contents = getattr(result, "content", []) or []
    original_unstructured = body is None
    if body is None:
        body = {"text": [v.text[:24000] for v in contents if isinstance(v, TextContent)][:5]}
    parts = []
    if isinstance(body, dict):
        clean = {}
        for key, value in body.items():
            if key == "media_file":
                parts.append((stage_file(value, target, tool, settings.get("media_root")), None))
            elif key in B64_FIELDS and isinstance(value, str):
                data = _decode(value)
                parts.append((stage_bytes(data, target, tool,
                                          _mime(body.get("mime_type"), B64_FIELDS[key]),
                                          body.get("name") or key), data))
            else:
                clean[key] = value
    else:
        clean = body
    if not parts:
        for block in contents:
            if isinstance(block, (ImageContent, AudioContent)):
                raw = _decode(block.data)
                parts.append((stage_bytes(raw, target, tool, block.mime_type,
                                          "downstream-" + block.type), raw))
    if not parts:
        if original_unstructured and hasattr(result, "model_dump"):
            # Preserve legacy downstream text/resource response exactly.
            return {"result": result.model_dump(mode="json")}
        return {"result": clean}
    manifest = {"result": clean, "media": [p[0] for p in parts]}
    blocks = [TextContent(type="text", text=json.dumps(manifest, ensure_ascii=False))]
    for metadata, raw in parts:
        if raw is not None and len(raw) <= INLINE_MAX:
            base64_data = base64.b64encode(raw).decode("ascii")
            mime = metadata["mime_type"]
            if mime.startswith("image/"):
                blocks.append(ImageContent(type="image", data=base64_data, mimeType=mime))
            elif mime.startswith("audio/"):
                blocks.append(AudioContent(type="audio", data=base64_data, mimeType=mime))
    return blocks if len(blocks) > 1 else manifest
