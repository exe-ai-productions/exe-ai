"""Whether the program makes a sound, and how loud.

Its own module for the same reason the skill switch has one: the settings
route only writes what somebody vouches for, and a JSON column cannot vouch
for anything by itself. Without an entry here the window would appear to
save and the value would be gone on the next start — which is exactly what
happened.

Stored as an object, not as two bare values: the route reads a falsy value
as "nothing set" and lets the scope above take over, so a plain ``False``
could never switch the sounds OFF, and a volume of 0 would silently jump
back to the default.

It sits in the cascade (default → global → model → chat), which makes it a
per-chat setting for free — a chat that runs long jobs may be allowed to
knock while a quiet one stays silent.
"""

from __future__ import annotations

from typing import Any

SCHLUESSEL = "klaenge"

# The four occurrences that have a sound of their own, each behind a switch
# of its own. An agent's or a cronjob's run that ends well is its own
# occurrence, not "done": that one belongs to an answer in a chat.
SOUND_FIELDS = ("ton_fertig", "ton_wartet", "ton_fehler", "ton_agent_cronjob")

# Shipped switched on, at a level that carries across a room without making
# anybody jump, and only while the window is away — somebody looking at the
# screen has already seen it.
#
# A sound plays when the main switch is on, the volume is above zero and the
# switch of its own occurrence is on. Whether the notice itself is drawn is
# not decided here: that is the popup switch of the same occurrence in
# app/meldewahl.py. The window and the service ask the same switches.
VORGABE: dict[str, Any] = {
    "an": True,
    "pegel": 70,
    "nur_hintergrund": True,
    **{name: True for name in SOUND_FIELDS},
}


def wahl_pruefen(wert: Any) -> dict[str, Any] | None:
    """Keeps what is usable, drops the rest. ``None`` deletes the entry."""
    if not isinstance(wert, dict):
        return None
    sauber: dict[str, Any] = {}
    for name in ("an", "nur_hintergrund", *SOUND_FIELDS):
        if isinstance(wert.get(name), bool):
            sauber[name] = wert[name]
    pegel = wert.get("pegel")
    if isinstance(pegel, (int, float)) and not isinstance(pegel, bool):
        sauber["pegel"] = max(0, min(100, int(round(pegel))))
    return sauber or None


def aufgeloest(wert: Any) -> dict[str, Any]:
    """The stored value with the defaults behind it."""
    return {**VORGABE, **(wahl_pruefen(wert) or {})}
