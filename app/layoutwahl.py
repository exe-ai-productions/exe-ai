"""Where the two panels stand — the chat list on the left, the work rail on
the right.

Its own module for the same reason the sound switch has one: the settings
route only writes what somebody vouches for, and a JSON column cannot vouch
for anything by itself.

Both panels are dragged, not configured, and both remember what they were
left at — somebody who works with the terminal open should find it open
after a restart. That memory used to sit in browser storage, so a second
window on the same service started over at the defaults.

The widths are clamped here to the same bounds the seam clamps the hand to
(``lib/arbeitsleiste.svelte.js``, ``lib/zustand.svelte.js``): below them the
labels clip, above them the chat loses its room. A value arriving from
anywhere else has to meet the same limits, or the panel would come back from
storage in a shape no drag could produce.

One object rather than five settings: the route reads a falsy value as
"nothing set", so a closed rail could never be stored as closed.
"""

from __future__ import annotations

from typing import Any

SCHLUESSEL = "layout"

# The names the rail may remember, a SUPERSET of MODULE in
# lib/arbeitsleiste.svelte.js: the retired ones stand here so a layout stored
# while they existed is still accepted and the client can hand it to the tool
# that holds it today (`FRUEHER` there). An unknown name would leave the rail
# open on nothing, so it is dropped.
MODULE = (
    "terminal",
    "cli",
    "vorschau",
    "notiz",
    "docfolder",
    "bilder",
    "cronjobs",
    "agenten",
)

# Seven 40 px signs of the row at the column's foot, six 10 px gaps and 12 px
# either side: no sign of the row ever has to shrink.
LEISTE_MIN = 364
LEISTE_MAX = 900

# Six 40 px buttons of the sidebar's window row, five 10 px gaps and 12 px
# either side.
SEITE_MIN = 314
SEITE_MAX = 400

# What stands where nothing is stored: a fresh installation opens in its
# basic state, both panels folded to their bars of signs. The route hands out
# only what is stored, so the copy the interface holds (`VORGABE_LAYOUT` in
# lib/anzeige.js) is the one a fresh installation draws from; a test keeps the
# two equal.
VORGABE: dict[str, Any] = {
    "leiste_offen": False,
    "leiste_modul": "terminal",
    "leiste_breite": LEISTE_MIN,
    "seitenleiste_zu": True,
    "seitenleiste_breite": SEITE_MIN,
}


def _breite(wert: Any, kleinste: int, groesste: int) -> int | None:
    if not isinstance(wert, (int, float)) or isinstance(wert, bool):
        return None
    return max(kleinste, min(groesste, int(round(wert))))


def wahl_pruefen(wert: Any) -> dict[str, Any] | None:
    """Keeps what is usable, drops the rest. ``None`` deletes the entry."""
    if not isinstance(wert, dict):
        return None
    sauber: dict[str, Any] = {}
    for name in ("leiste_offen", "seitenleiste_zu"):
        if isinstance(wert.get(name), bool):
            sauber[name] = wert[name]
    if wert.get("leiste_modul") in MODULE:
        sauber["leiste_modul"] = wert["leiste_modul"]
    leiste = _breite(wert.get("leiste_breite"), LEISTE_MIN, LEISTE_MAX)
    if leiste is not None:
        sauber["leiste_breite"] = leiste
    seite = _breite(wert.get("seitenleiste_breite"), SEITE_MIN, SEITE_MAX)
    if seite is not None:
        sauber["seitenleiste_breite"] = seite
    return sauber or None


def aufgeloest(wert: Any) -> dict[str, Any]:
    """The stored value with the defaults behind it."""
    return {**VORGABE, **(wahl_pruefen(wert) or {})}
