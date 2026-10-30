"""Owner-configured local ChatBridge endpoint and optional private credentials."""
import os
import stat
from urllib.parse import urlsplit
from ..runtime_paths import DATA_ROOT

def validate_gateway(value):
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or parsed.hostname not in
            ("127.0.0.1", "localhost", "::1") or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("ChatBridge must be a loopback HTTP origin")
    parsed.port  # Reject malformed or out-of-range ports before any request.
    return value

def gateway():
    value = os.environ.get("MACCONTROL_CHATBRIDGE_URL", "").strip()
    config = DATA_ROOT / "chatbridge_connection.txt"
    if not value and config.is_file() and not config.is_symlink():
        value = config.read_text(encoding="utf-8").strip()
    return validate_gateway(value or "http://127.0.0.1:8787")


def _validated_key(value):
    value = value.strip()
    if len(value.encode("utf-8")) > 4096 or "\n" in value or "\r" in value:
        raise ValueError("Invalid ChatBridge key format")
    return value


def _private_key_file(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
        raise PermissionError("Unsafe ChatBridge credential file")


def api_key():
    """Resolve a key on demand; keyless local ChatBridge remains supported."""
    explicit = os.environ.get("MACCONTROL_CHATBRIDGE_API_KEY", "").strip()
    if explicit:
        return _validated_key(explicit)
    path = DATA_ROOT / "chatbridge_api_key.txt"
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise PermissionError("Refusing symlink ChatBridge credential path")
    try:
        info = path.lstat()
    except FileNotFoundError:
        return ""
    _private_key_file(info)
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as source:
        _private_key_file(os.fstat(source.fileno()))
        # Permit the installer's final newline in addition to a 4096-byte key.
        content = source.read(4098)
    if len(content) > 4097:
        raise ValueError("ChatBridge key file is too large")
    try:
        value = content.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Invalid ChatBridge key encoding") from None
    return _validated_key(value)
