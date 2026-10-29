"""Static, trusted operations. No import or execution from a user workspace."""
import platform

def system_info() -> dict[str, str]:
    """Return non-sensitive OS and Python version information."""
    return {
        "system": platform.system(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
    }
