"""Text folding for searches, the same way the message index folds.

The message index (``messages_fts``) tokenizes with ``unicode61
remove_diacritics 2``: letters are lowercased and the accents of Latin letters
are dropped, so "heizkorper" finds "Heizkörper". SQLite's own ``LIKE`` folds
ASCII case and nothing else, so a title was only found by the exact accents it
was written with. Folding both sides with this function gives titles the
index's rule.

What the index keeps, this keeps: ``ß`` stays ``ß`` (``str.casefold`` would
turn it into "ss"), ``ø`` and ``ł`` stay, and the marks of other scripts
(Greek tonos, Hebrew points, Hangul jamo) are not removed. The final sigma
``ς`` is the one letter the index folds into ``σ``.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from functools import lru_cache
from typing import Any

FOLD_FUNCTION = "fold_text"

_COMBINING_DIACRITICS = range(0x0300, 0x0370)


@lru_cache(maxsize=16384)
def fold_text(text: str) -> str:
    """Lowercase ``text`` and drop the accents of its Latin letters.

    Cached: a search folds every title once per word and again on the next keystroke.
    """
    decomposed = unicodedata.normalize("NFD", text).lower().replace("ς", "σ")
    kept: list[str] = []
    base = ""
    for ch in decomposed:
        if unicodedata.category(ch) != "Mn":
            base = ch
        elif ord(ch) in _COMBINING_DIACRITICS and unicodedata.name(base, "").startswith("LATIN"):
            continue
        kept.append(ch)
    return unicodedata.normalize("NFC", "".join(kept))


def _fold_sql_value(value: Any) -> Any:
    return fold_text(value) if isinstance(value, str) else value


def register_fold_function(connection: sqlite3.Connection) -> None:
    """Make ``fold_text(x)`` callable in SQL on ``connection``; other types pass through."""
    connection.create_function(FOLD_FUNCTION, 1, _fold_sql_value)
