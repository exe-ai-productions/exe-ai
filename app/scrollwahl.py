"""Where a conversation was left standing — at the end, or somewhere above.

Its own module for the same reason the sound switch has one: the settings
route only writes what somebody vouches for, and a JSON column cannot vouch
for anything by itself.

Per chat, because that is the only scope where it means anything: a reading
position belongs to the text it is a position in.

``am_boden`` is the one that carries. Following the end of a running answer
is a MODE, not a coordinate — a chat left at the bottom must come back
following along, whatever height its messages happen to render at this time.
``versatz`` is only consulted when that mode is off, and even then it is a
wish rather than a promise: pictures load late and rows re-measure, so the
same number can mean a different place. Which is why it is stored beside the
mode instead of instead of it. "Somewhere above" without a usable ``versatz``
has no place to go back to, so it is not kept: such a chat opens at its end,
like a new one.
"""

from __future__ import annotations

import math
from typing import Any

SCHLUESSEL = "scrollstelle"

# A new chat follows its answer — that is what the reader wants until they
# deliberately scroll up.
VORGABE: dict[str, Any] = {"am_boden": True, "versatz": 0}

# Far above any real conversation. A stop against a runaway value, not a
# rule about how long a chat may get.
VERSATZ_MAX = 10_000_000


def wahl_pruefen(wert: Any) -> dict[str, Any] | None:
    """Keeps what is usable, drops the rest. ``None`` deletes the entry."""
    if not isinstance(wert, dict):
        return None
    sauber: dict[str, Any] = {}
    if isinstance(wert.get("am_boden"), bool):
        sauber["am_boden"] = wert["am_boden"]
    versatz = wert.get("versatz")
    if (
        isinstance(versatz, (int, float))
        and not isinstance(versatz, bool)
        and not (isinstance(versatz, float) and not math.isfinite(versatz))
    ):
        sauber["versatz"] = max(0, min(VERSATZ_MAX, int(round(versatz))))
    if sauber.get("am_boden") is False and "versatz" not in sauber:
        # "Somewhere above" with no place to go back to would be filled in
        # as offset 0 by the window — the very top of the conversation. Left
        # without a usable offset, the chat opens at its end like a new one.
        del sauber["am_boden"]
    return sauber or None

