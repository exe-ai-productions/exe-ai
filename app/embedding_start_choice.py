"""What the embedding server starts with: the file and the port.

The window used to hold both in the page, so after closing it or restarting
the program the picker stood on the first file of the folder and the port
field on 8081 again. They are stored here, in a row of their own, the way the
speech and clean-up servers' start values are (app/diktatsprachewahl.py) —
written as they are touched, read again when the window opens, and used at
the next start when the request does not name them.

Two keys, each only when it was sent, so the window can write the file
without resending the port and the other way round.
"""

from __future__ import annotations

from typing import Any

SCHLUESSEL = "embedding"

NAME_MAX = 200
PORT_MIN, PORT_MAX = 1024, 65535


def wahl_pruefen(wert: Any) -> dict[str, Any]:
    """The choice before it is stored. A file name is trimmed and bounded; a
    port outside the unprivileged range is not stored at all (the works port
    stands), because clamping it would store a number nobody typed."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    if "model" in wert:
        roh = wert["model"]
        sauber["model"] = "" if roh is None else str(roh).strip()[:NAME_MAX]
    if "port" in wert:
        roh = wert["port"]
        if isinstance(roh, int) and not isinstance(roh, bool) and PORT_MIN <= roh <= PORT_MAX:
            sauber["port"] = roh
    return sauber


def wahl(repositories) -> dict[str, Any]:
    """What is stored: ``model`` ("" for none chosen) and ``port`` (None for
    the server's own port)."""
    stand = repositories.einstellungen.zusammengefuehrt(SCHLUESSEL, vorgabe={})
    return {"model": "", "port": None, **wahl_pruefen(stand if isinstance(stand, dict) else {})}


__all__ = ["SCHLUESSEL", "wahl", "wahl_pruefen"]
