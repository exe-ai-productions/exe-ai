"""The client's sentences, read from the catalogues the service ships.

The catalogues are plain JSON files, one per language, fetched by a dotted
key. They are read here as files: the client stays free of the service's
code and still says every sentence the way the window says it.

A key that is missing in the chosen language is looked up in the default
language; a key missing there too comes back as the key itself — visible on
screen, and no crash.
"""

from __future__ import annotations

import json
import locale
import os
import sys
from pathlib import Path
from typing import Any

CATALOGUE_DIRECTORY = Path(__file__).resolve().parent.parent / "app" / "locales"

# The language every catalogue falls back to, and the one the client speaks
# where nothing else decides.
DEFAULT_LANGUAGE = "en"

# Where a POSIX system says which language it is set to, most specific first.
_LOCALE_VARIABLES = ("LC_ALL", "LC_MESSAGES", "LANG")


def available_languages(directory: Path | None = None) -> list[str]:
    """The catalogues on disk, by their language code."""
    return sorted(path.stem for path in (directory or CATALOGUE_DIRECTORY).glob("*.json"))


def _language_code(locale_name: str | None) -> str | None:
    """The two-letter code a locale name starts with — ``de`` for ``de_DE.UTF-8``.

    ``C`` and ``POSIX`` name no language, and a spelled-out name such as
    ``German_Germany`` does not start with a code either: only two letters
    followed by something that is no letter count.
    """
    if not locale_name or len(locale_name) < 2 or not locale_name[:2].isalpha():
        return None
    if len(locale_name) > 2 and locale_name[2].isalpha():
        return None
    return locale_name[:2].lower()


def _windows_interface_language() -> str | None:
    """The language Windows shows its own interface in, as a locale name."""
    try:
        import ctypes

        identifier = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
    except (ImportError, AttributeError, OSError):
        return None
    return locale.windows_locale.get(identifier)


def system_language() -> str | None:
    """The language the system is set to, or ``None`` where it does not say."""
    candidates: list[str | None] = [os.environ.get(name) for name in _LOCALE_VARIABLES]
    if sys.platform == "win32":
        candidates.append(_windows_interface_language())
    try:
        candidates.append(locale.getlocale()[0])
    except ValueError:
        # An environment naming a locale the system does not know.
        pass
    for candidate in candidates:
        code = _language_code(candidate)
        if code:
            return code
    return None


def resolve_language(
    chosen: str | None, remembered: str | None, directory: Path | None = None
) -> str:
    """The language the client speaks: the one asked for, else the remembered
    one, else the system's, else the default — the first that has a catalogue."""
    known = available_languages(directory)
    for candidate in (chosen, remembered, system_language()):
        if candidate and candidate.lower() in known:
            return candidate.lower()
    return DEFAULT_LANGUAGE


class Texts:
    """One language's sentences, fetched by key."""

    def __init__(self, language: str, directory: Path | None = None) -> None:
        self._directory = directory or CATALOGUE_DIRECTORY
        self._catalogues: dict[str, dict[str, Any]] = {}
        self.language = language

    def set_language(self, language: str) -> None:
        """Switches the language every later sentence comes in."""
        self.language = language

    def _catalogue(self, language: str) -> dict[str, Any]:
        if language not in self._catalogues:
            file = self._directory / f"{language}.json"
            try:
                loaded = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                loaded = {}
            self._catalogues[language] = loaded if isinstance(loaded, dict) else {}
        return self._catalogues[language]

    def _lookup(self, language: str, key: str) -> str | None:
        node: Any = self._catalogue(language)
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node if isinstance(node, str) else None

    def t(self, key: str, **placeholders: Any) -> str:
        """The sentence behind ``key`` with its placeholders filled in."""
        text = self._lookup(self.language, key)
        if text is None and self.language != DEFAULT_LANGUAGE:
            text = self._lookup(DEFAULT_LANGUAGE, key)
        if text is None:
            return key
        if not placeholders:
            return text
        try:
            return text.format(**placeholders)
        except (KeyError, IndexError, ValueError):
            # A sentence asking for a value nobody handed in, or carrying a
            # brace that opens no placeholder, is still better shown unfilled
            # than not at all.
            return text
