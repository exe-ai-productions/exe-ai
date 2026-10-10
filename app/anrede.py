"""The name the terminal calls its user by.

One setting, two effects: the surface shows a greeting, and the system
prompt carries one line telling the model who is sitting here. One switch
rules both — switched off, the line is not appended and the greeting is not
drawn, so nothing whispers the name anywhere.

The name lives in the settings store on this PC. When the switch is on it
travels inside the system prompt — to a cloud endpoint too, which is why
the settings text says exactly that.

``erststart`` rides along in the same object because it is the same act: the
first-start window is what asks for the name, and once it has been answered
it never comes back. It used to be a mark in browser storage, so the window
returned in every new browser profile — on an installation that had long
since been set up.
"""

from __future__ import annotations

from typing import Any

SCHLUESSEL = "anrede"

# A name is opt-in by content: the switch ships on, but until a name is
# written nothing changes anywhere.
VORGABE: dict[str, Any] = {"name": "", "an": True, "erststart": False}

NAME_HOECHSTLAENGE = 60


def schalter_pruefen(wert: Any) -> dict[str, Any]:
    """``anrede``: one name, one switch, checked before they are stored.

    Only the two known keys survive: the name as a trimmed, bounded string,
    the switch as a real boolean. Everything else is dropped rather than
    stored — the settings column holds JSON and cannot check anything by
    itself.
    """
    if not isinstance(wert, dict):
        return {}
    sauber: dict[str, Any] = {}
    if "name" in wert:
        name = str(wert["name"] or "").strip()[:NAME_HOECHSTLAENGE]
        sauber["name"] = name
    if "an" in wert:
        sauber["an"] = bool(wert["an"])
    if "erststart" in wert:
        sauber["erststart"] = bool(wert["erststart"])
    return sauber


def lesen(repositories) -> dict[str, Any]:
    """The stored name and switch, defaults filled in.

    ``erststart`` is deliberately not part of this: this is what the system
    prompt is built from, and whether a window was once answered has no
    business in it.
    """
    stand = repositories.einstellungen.zusammengefuehrt(
        SCHLUESSEL, vorgabe=dict(VORGABE)
    )
    if not isinstance(stand, dict):
        stand = dict(VORGABE)
    return {
        "name": str(stand.get("name", "") or "").strip()[:NAME_HOECHSTLAENGE],
        "an": bool(stand.get("an", VORGABE["an"])),
    }


def anhaengen(system_prompt: str, stand: dict[str, Any]) -> str:
    """Appends the one line that names the user — or appends nothing.

    The quotes around the name keep an exotic name from reading as part of
    the sentence; the model sees exactly where it begins and ends.
    """
    name = str(stand.get("name", "") or "").strip()
    if not (stand.get("an") and name):
        return system_prompt
    zeile = (
        f'The user goes by "{name}". '
        "Address them by name when it feels natural."
    )
    if not system_prompt:
        return zeile
    return f"{system_prompt}\n\n{zeile}"
