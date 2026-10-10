"""How the program reports itself: what is worth a notice at all, how long
one stands, and which status dots are allowed to move.

Its own module for the same reason the sound switch has one: the settings
route only writes what somebody vouches for, and a JSON column cannot vouch
for anything by itself. Without an entry here the window would appear to
save and the value would be gone on the next start.

What is heard is not decided here: the main switch, the volume and the
background rule live in app/klangwahl.py, which the settings page reads
alongside this one and shows as one block. What IS decided here is whether
an occurrence is reported at all — and that governs the whole notice, its
text as much as its sound. One meaning, one switch.

One object rather than five settings: the route reads a falsy value as
"nothing set" and lets the scope above take over, so a plain ``False``
could never switch a dot's pulse off, and a duration of 0 — which is the
one that means "stand until it has been read" — would spring back to the
default.
"""

from __future__ import annotations

from typing import Any

SCHLUESSEL = "meldewesen"

# The four status dots, each behind a switch of its own
# (frontend/src/lib/meldewesen.svelte.js).
PUNKTE = ("punkt_agenten", "punkt_cronjob", "punkt_terminal", "punkt_chat")

# The three things worth reporting, each behind a switch of its own. Off
# means the whole notice stays away — no text, no sound. These sat under
# `klaenge` while they only governed the sound; they govern the notice now,
# and a switch called "Failed" that silences a sound while its message
# still appears would be four ways to say one thing.
MELDER = ("melde_fertig", "melde_wartet", "melde_fehler")

# Seconds a notice stands before it goes. Zero is not "no time at all": it
# is the field's ``nullwort``, and it means the notice stands until the
# thing it is about has been looked at.
POPUP_MAX = 60

VORGABE: dict[str, Any] = {
    "popup_sekunden": 0,
    **{name: True for name in (*PUNKTE, *MELDER)},
}


def wahl_pruefen(wert: Any) -> dict[str, Any] | None:
    """Keeps what is usable, drops the rest. ``None`` deletes the entry."""
    if not isinstance(wert, dict):
        return None
    sauber: dict[str, Any] = {}
    for name in (*PUNKTE, *MELDER):
        if isinstance(wert.get(name), bool):
            sauber[name] = wert[name]
    sekunden = wert.get("popup_sekunden")
    if isinstance(sekunden, (int, float)) and not isinstance(sekunden, bool):
        sauber["popup_sekunden"] = max(0, min(POPUP_MAX, int(round(sekunden))))
    return sauber or None


def aufgeloest(wert: Any) -> dict[str, Any]:
    """The stored value with the defaults behind it."""
    return {**VORGABE, **(wahl_pruefen(wert) or {})}
