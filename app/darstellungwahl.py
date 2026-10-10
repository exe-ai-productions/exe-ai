"""How the interface looks — the code colours, the bubble colour, the
frame gradient and the chat layout.

Its own module for the same reason the sound switch has one: the settings
route only writes what somebody vouches for, and a JSON column cannot vouch
for anything by itself. Without an entry here the window would appear to
save and the value would be gone on the next start.

These lived in browser storage before, which meant a different truth on
every device and none at all for the program itself. The look belongs to
the person, not to the browser profile that happened to open the app.

One object rather than two settings: the route reads a falsy value as
"nothing set" and lets the scope above take over, so a bubble colour
cleared back to the house palette could never be stored as "cleared".

The outline switch and the two size steps are gone: the window's own zoom
(Cmd+plus and Cmd+minus) makes everything larger. A value stored while they
existed still carries them; they are passed over without a word, and what
else it holds is kept.
"""

from __future__ import annotations

import re
from typing import Any

SCHLUESSEL = "darstellung"

# `exe` is the house pack and follows light and dark; the other eight bring
# their own ground, which is the point of them (stil/codefarben.css).
CODEFARBEN = (
    "exe",
    "tokyo",
    "onelight",
    "github",
    "githubdark",
    "dracula",
    "nord",
    "solarizedlight",
    "solarizeddark",
)

# A six-digit hex colour, the only thing an `<input type="color">` produces.
# Matched with `fullmatch`: `$` would also accept a trailing line break,
# which no colour field can produce.
FARBE = re.compile(r"#[0-9a-fA-F]{6}")

# The looks a frame gradient may be chosen for, each with the number of
# colours its own run carries (stil/global.css). The window offers the
# fields from the look's own sheet; this table is what the route vouches
# for — the two must not drift. Only the own gradient is the user's to
# paint; every fixed look keeps the gradient its design gave it, and a
# choice stored for one of them falls away here.
VERLAUF_ANZAHL = {"eigen": 4}

# The chat layout the user sets in the layout mode, each value with the
# range the window's controls offer: font size and spacing in pixels, the
# column and the picture tile in pixels, the two bubble widths and the two
# anchors in percent. Only values off the factory setting are stored; a key
# that is missing means the factory value applies (the frontend holds it).
CHAT_GRENZEN = {
    "schrift": (10, 26),
    "breite": (600, 2000),
    "blase_eigen": (15, 100),
    "blase_ki": (15, 100),
    "anker_eigen": (0, 100),
    "anker_ki": (0, 100),
    "abstand": (0, 120),
    "bildkachel": (200, 700),
}

VORGABE: dict[str, Any] = {
    "codefarben": "exe",
    # Empty means: no colour of its own, the house palette applies.
    "blasenfarbe": "",
    # The colours, hue and angle the user set for the own gradient, under
    # its look's key. An empty map means it draws its start.
    "verlauf": {},
    # The chat layout from the layout mode. Empty means the factory layout.
    "chat": {},
}


def _farbe(wert: Any) -> str | None:
    """A colour value in the one stored shape — six-digit hex, lower case,
    the shape a colour field hands out. ``None`` for anything else; the
    bubble colour and the frame colours share this one rule."""
    return wert.lower() if isinstance(wert, str) and FARBE.fullmatch(wert) else None


def _verlauf_pruefen(wert: Any) -> dict[str, Any]:
    """The usable looks of a stored gradient choice; an entry that holds no
    real choice at all falls away, and with it the entry."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    for schema, anzahl in VERLAUF_ANZAHL.items():
        wahl = wert.get(schema)
        if not isinstance(wahl, dict):
            continue
        eintrag: dict[str, Any] = {}
        farben = wahl.get("farben")
        if isinstance(farben, list) and len(farben) == anzahl:
            saubere_farben = [_farbe(farbe) for farbe in farben]
            if all(saubere_farben):
                eintrag["farben"] = saubere_farben
        ton = wahl.get("ton")
        # Zero is a real hue here: the own gradient starts turned, so a
        # hue of zero is a change the panel keeps (it drops only the start).
        if isinstance(ton, int) and not isinstance(ton, bool) and -180 <= ton <= 180:
            eintrag["ton"] = ton
        winkel = wahl.get("winkel")
        if isinstance(winkel, int) and not isinstance(winkel, bool) and 0 <= winkel <= 360:
            eintrag["winkel"] = winkel
        if eintrag:
            sauber[schema] = eintrag
    return sauber


def _chat_pruefen(wert: Any) -> dict[str, int]:
    """The usable values of a stored chat layout: whole numbers inside the
    range the layout mode offers. Anything else falls away on its own, so a
    broken value costs that one value, never the rest."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, int] = {}
    for name, (unten, oben) in CHAT_GRENZEN.items():
        zahl = wert.get(name)
        if isinstance(zahl, int) and not isinstance(zahl, bool) and unten <= zahl <= oben:
            sauber[name] = zahl
    return sauber


def wahl_pruefen(wert: Any) -> dict[str, Any] | None:
    """Keeps what is usable, drops the rest. ``None`` deletes the entry."""
    if not isinstance(wert, dict):
        return None
    sauber: dict[str, Any] = {}
    if wert.get("codefarben") in CODEFARBEN:
        sauber["codefarben"] = wert["codefarben"]
    farbe = wert.get("blasenfarbe")
    if farbe == "":
        sauber["blasenfarbe"] = ""
    else:
        gesetzt = _farbe(farbe)
        if gesetzt:
            sauber["blasenfarbe"] = gesetzt
    verlauf = _verlauf_pruefen(wert.get("verlauf"))
    if verlauf:
        sauber["verlauf"] = verlauf
    # Kept even when empty: "Standard" in the layout mode stores an empty
    # map, and that has to reach the row to replace a layout stored before.
    if isinstance(wert.get("chat"), dict):
        sauber["chat"] = _chat_pruefen(wert["chat"])
    return sauber or None


def aufgeloest(wert: Any) -> dict[str, Any]:
    """The stored value with the defaults behind it. The nested map is
    copied — a caller's write must never land in the module's default."""
    sauber = {**VORGABE, **(wahl_pruefen(wert) or {})}
    sauber["verlauf"] = dict(sauber["verlauf"])
    sauber["chat"] = dict(sauber["chat"])
    return sauber
