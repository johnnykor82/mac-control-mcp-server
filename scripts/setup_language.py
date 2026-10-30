"""Small shared language selection for owner-facing setup prompts."""
from __future__ import annotations

import locale
import os
import plistlib
import subprocess
import sys


def detect_language() -> str:
    """Use macOS preferred language, falling back to the process locale."""
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["/usr/bin/defaults", "export", "NSGlobalDomain", "-"],
                capture_output=True, check=True, timeout=3,
            )
            languages = plistlib.loads(result.stdout).get("AppleLanguages", [])
            if languages:
                return "ru" if str(languages[0]).lower().startswith("ru") else "en"
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
            pass
    value = next((os.environ[key] for key in ("LC_ALL", "LC_MESSAGES", "LANG")
                  if os.environ.get(key)), None)
    if not value:
        value = locale.getlocale()[0] or "en"
    return "ru" if value.lower().startswith("ru") else "en"


def text(language: str | None, english: str, russian: str) -> str:
    return russian if (language or detect_language()) == "ru" else english


def choose_language(*, input_fn=input, language: str | None = None) -> str:
    """Select once, before setup; an explicit CLI choice avoids another prompt."""
    if language is not None:
        if language not in ("en", "ru"):
            raise ValueError("Language must be en or ru")
        return language
    default = detect_language()
    while True:
        answer = input_fn(
            "Language / Язык: 1 — English, 2 — Русский "
            + ("[2]: " if default == "ru" else "[1]: ")
        ).strip().casefold()
        if not answer:
            return default
        if answer in ("1", "en", "english"):
            return "en"
        if answer in ("2", "ru", "русский"):
            return "ru"
        print("Choose 1 or 2 / Выберите 1 или 2.")
