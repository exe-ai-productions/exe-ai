"""Writing one key into the user's .env file, or taking it out again.

Line by line rather than through a parser: the file belongs to the user,
and their comments and order are worth more than a tidy rewrite. The file
serves the next start; whoever needs the value now sets it into the
process environment as well.
"""

from __future__ import annotations

import re
from pathlib import Path


def _zeilen_lesen(datei: Path) -> tuple[list[str], str]:
    """The lines of the file and the line ending it uses: CRLF for a file a
    Windows editor wrote, LF otherwise and for a file that is not there yet.
    Read without translation, so a rewrite hands every line back the way it
    stood."""
    if not datei.exists():
        return [], "\n"
    with open(datei, encoding="utf-8", newline="") as quelle:
        text = quelle.read()
    return text.splitlines(), "\r\n" if "\r\n" in text else "\n"


def _zeilen_schreiben(datei: Path, zeilen: list[str], ende: str) -> None:
    """The lines, each closed by ``ende`` and none translated by the system
    (``newline=""``: on Windows a plain LF would turn into CRLF)."""
    text = ende.join(zeilen).rstrip() + ende if zeilen else ""
    with open(datei, "w", encoding="utf-8", newline="") as ziel:
        ziel.write(text)


def env_schreiben(datei: Path, name: str, wert: str) -> None:
    zeilen, ende = _zeilen_lesen(datei)
    neu, gesetzt = [], False
    for zeile in zeilen:
        if re.match(rf"^\s*#?\s*{re.escape(name)}\s*=", zeile):
            if not gesetzt:
                neu.append(f"{name}={wert}")
                gesetzt = True
            continue
        neu.append(zeile)
    if not gesetzt:
        neu.append(f"{name}={wert}")
    datei.parent.mkdir(parents=True, exist_ok=True)
    _zeilen_schreiben(datei, neu, ende)
    datei.chmod(0o600)


def key_leaves_with(endpoints, endpoint_id: str) -> bool:
    """Whether removing this provider takes its key line along: it names a
    key variable and no other provider reads the same one.

    The one rule behind both the removal and the question put before it, so
    the window and the route cannot disagree."""
    own = next((e for e in endpoints if e.id == endpoint_id), None)
    name = own.api_key_env if own else None
    return bool(name) and not any(
        e.id != endpoint_id and e.api_key_env == name for e in endpoints
    )


def env_entfernen(datei: Path, name: str) -> bool:
    """Takes the key's active line out; commented lines and every other key
    stay as the user wrote them. Says whether there was a line to take."""
    if not datei.exists():
        return False
    zeilen, ende = _zeilen_lesen(datei)
    neu = [z for z in zeilen if not re.match(rf"^\s*{re.escape(name)}\s*=", z)]
    if len(neu) == len(zeilen):
        return False
    _zeilen_schreiben(datei, neu, ende)
    datei.chmod(0o600)
    return True
