"""How the program reports itself: what is worth a notice at all, how long
one stands, and which status dots are allowed to move.

Its own module for the same reason the sound switch has one: the settings
route only writes what somebody vouches for, and a JSON column cannot vouch
for anything by itself. Without an entry here the window would appear to
save and the value would be gone on the next start.

What is heard is not decided here: the main switch, the volume, the
background rule and the sound switch of each occurrence live in
app/klangwahl.py, which the settings page reads alongside this one and
shows beside it. What IS decided here is whether an occurrence's notice is
shown at all — its card in the window and its notification of the system.

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

# The four things worth reporting, each behind a switch of its own: the
# popup of that occurrence. Off means its card and its system notification
# stay away; whether it also makes a sound is the sound switch of the same
# occurrence (app/klangwahl.py). `agent_cronjob` is the run of an agent or a
# cronjob that ended well.
MELDER = ("melde_fertig", "melde_wartet", "melde_fehler", "melde_agent_cronjob")

# The one switch that stops every notice card from being drawn, whatever it
# is about: it governs the display only, not the sounds and not the dots, and
# it comes shipped off. A plain bool is enough, since the stored value is an
# object (see the module note above).
POPUPS_AUS = "popups_aus"

# Seconds a notice stands before it goes. Zero is not "no time at all": it
# is the field's ``nullwort``, and it means the notice stands until the
# thing it is about has been looked at.
POPUP_MAX = 60

VORGABE: dict[str, Any] = {
    "popup_sekunden": 0,
    POPUPS_AUS: False,
    **{name: True for name in (*PUNKTE, *MELDER)},
}


def wahl_pruefen(wert: Any) -> dict[str, Any] | None:
    """Keeps what is usable, drops the rest. ``None`` deletes the entry."""
    if not isinstance(wert, dict):
        return None
    sauber: dict[str, Any] = {}
    for name in (*PUNKTE, *MELDER, POPUPS_AUS):
        if isinstance(wert.get(name), bool):
            sauber[name] = wert[name]
    sekunden = wert.get("popup_sekunden")
    if isinstance(sekunden, (int, float)) and not isinstance(sekunden, bool):
        sauber["popup_sekunden"] = max(0, min(POPUP_MAX, int(round(sekunden))))
    return sauber or None


def aufgeloest(wert: Any) -> dict[str, Any]:
    """The stored value with the defaults behind it."""
    return {**VORGABE, **(wahl_pruefen(wert) or {})}
