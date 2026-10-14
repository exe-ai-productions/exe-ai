"""How deeply a model is asked to think before it answers.

Its own module for the same reason the sound switch has one: the settings
route only writes what somebody vouches for, and a JSON column cannot vouch
for anything by itself.

This one belongs to the MODEL, not to the chat: thinking is a property of
what the model can do, and somebody who set it low for a small local model
does not mean it for the big one in the next chat. It is therefore written
to ``modell:<endpoint_id>`` and read back through the same cascade.

Stored as an object, not as a bare value: the route reads a falsy value as
"nothing set" and lets the scope above take over, so a plain ``off`` could
never switch thinking off — which is the whole point of the control.

The stored shape used to be ``{"an": true|false}``, back when there were two
positions instead of a scale. Rows in that shape are still out there and are
left exactly as they are: nothing is renamed, nothing is migrated, the
reader translates. ``{"an": false}`` is the ``off`` position, ``{"an":
true}`` is whatever the model's own profile calls its default.
"""

from __future__ import annotations

from typing import Any

from app import denkstufen

SCHLUESSEL = "denken"


def schalter_pruefen(wert: Any) -> dict[str, Any] | None:
    """Keeps what is usable, drops the rest. ``None`` deletes the entry.

    Both shapes pass: the stage, and the older on/off pair a window that has
    not been reloaded still sends.
    """
    if not isinstance(wert, dict):
        return None
    stufe = wert.get("stufe")
    # Not checked against the closed vocabulary: a model's own template can
    # name a stage the catalogue does not, and this route
    # only ever writes what a profile is already offering — refusing it here
    # would silently undo the point of offering it.
    if isinstance(stufe, str) and stufe.strip():
        return {"stufe": stufe.strip().lower()}
    if isinstance(wert.get("an"), bool):
        return {"an": wert["an"]}
    return None


def gespeicherte_stufe(wert: Any) -> str | None:
    """The stage a stored row means, without asking any profile.

    ``None`` here says "nothing was stored", which is not the same answer as
    ``off`` — the first lets the model's own default apply, the second is
    somebody switching thinking off on purpose.
    """
    gepruft = schalter_pruefen(wert)
    if gepruft is None:
        return None
    if "stufe" in gepruft:
        return gepruft["stufe"]
    return "on" if gepruft["an"] else "off"


def aufgeloest(wert: Any, profil: denkstufen.Denkprofil) -> str | None:
    """Which stage applies for this model right now.

    What was stored, as far as the model still offers it. A stage that has
    since disappeared from the list — the model refused it, or the
    catalogue was corrected — is not sent again: the nearest weaker depth
    the model offers takes its place (:func:`nearest_depth`). Only a word
    that stands nowhere on the scale falls back to the model's own default.
    """
    if not profil.schaltbar:
        return None
    gespeichert = gespeicherte_stufe(wert)
    if gespeichert == "on" and "on" not in profil.stufen:
        # The older shape said no more than "yes, think". On a scale that is
        # the default depth, not the top of it.
        return denkstufen.standardstufe(profil)
    if gespeichert in profil.stufen:
        return gespeichert
    substitute = nearest_depth(gespeichert, profil.stufen)
    if substitute is not None:
        return substitute
    return denkstufen.standardstufe(profil)


def sent_stage(einstellungen: Any, profil: denkstufen.Denkprofil, model_id: str) -> str | None:
    """The stage a request for this model carries when nobody names one: the
    stored stage as far as the model still offers it, else the one standing
    in for it (:func:`aufgeloest`). ``None`` where there is nothing to set.

    Read for the model list, so the window shows what goes out and keeps no
    copy of the rule.
    """
    if not profil.schaltbar:
        return None
    return aufgeloest(einstellungen.aufgeloest(SCHLUESSEL, modell=model_id), profil)


def nearest_depth(wanted: str | None, offered: list[str]) -> str | None:
    """The depth to send for a stored stage this model no longer offers.

    The nearest weaker depth it offers; where none is weaker, the weakest it
    offers. Never "off": a model that thinks less than asked still
    thinks, one switched off on its behalf does not. ``None`` where the word
    stands nowhere on the scale or the model offers no depth at all — then
    the model's own default applies.
    """
    if wanted not in denkstufen.SCALE:
        return None
    depths = [s for s in denkstufen.SCALE if s != "off" and s in offered]
    if not depths:
        return None
    position = denkstufen.SCALE.index(wanted)
    weaker = [s for s in depths if denkstufen.SCALE.index(s) < position]
    return weaker[-1] if weaker else depths[0]


def nothing_stored(wert: Any) -> bool:
    """Whether no stage of the scale is stored: nothing at all, the older
    yes-form (``{"an": true}``, which names no stage) or a word that stands
    nowhere on the scale. The older no-form is "off", a stage like any."""
    return gespeicherte_stufe(wert) not in denkstufen.SCALE


def is_substitute(wert: Any, profil: denkstufen.Denkprofil, stufe: str | bool | None) -> bool:
    """Whether ``stufe`` is the depth standing in for a stored stage the
    model no longer offers (:func:`aufgeloest`, :func:`nearest_depth`)."""
    gespeichert = gespeicherte_stufe(wert)
    if not isinstance(stufe, str) or gespeichert not in denkstufen.SCALE:
        return False
    if gespeichert in profil.stufen:
        return False
    return stufe.strip().lower() == aufgeloest(wert, profil)
