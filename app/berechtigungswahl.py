"""The permission mode — Auto / Manuell (default) / Restricted — via the
settings cascade, and what picking one writes into ``berechtigungen.json``.

A chat and an agent run under different conditions — one has someone
watching, the other does not — so each gets its own setting, two cascade
keys rather than one:

* ``berechtigungsmodus_chat``
* ``berechtigungsmodus_agent``

A mode is a shortcut, not a separate thing ``berechtigungen.urteil`` has to
know about — picking one just writes the two lines it stands for into the
rule file (``standard`` and ``dateien.innerhalb_der_ordner`` /
``ausserhalb_der_ordner``, for that one origin only). The file stays the
precise, hand-editable source Tor 3 actually reads; a mode change touches
only the lines it owns and leaves everything else — a per-tool rule, the
``niemals`` list, the other origin's lines — exactly as it was.

    mode          inside a shared folder   everything else
    auto          runs                     runs
    manuell       runs                     asks first
    restricted    asks first               asks first

An agent cannot be asked, so "asks first" becomes an outright refusal for
it on its own — that rule already lives in ``app/berechtigungen.py`` and
applies no matter where the "ask" came from, so it does not need repeating
here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.berechtigungsregeln import Antwort, GUELTIGE_ANTWORTEN, beispiel_pfad
from app.config import erststart_kopie

log = logging.getLogger(__name__)

SCHLUESSEL = {"chat": "berechtigungsmodus_chat", "agent": "berechtigungsmodus_agent"}

GUELTIGE_MODI = {"auto", "manuell", "restricted"}

# modus -> (within the folders, everything else)
MODUS_FELDER: dict[str, tuple[Antwort, Antwort]] = {
    "auto": ("ja", "ja"),
    "manuell": ("ja", "fragen"),
    "restricted": ("fragen", "fragen"),
}


def wahl_pruefen(wert: Any) -> str | None:
    if isinstance(wert, str) and wert in GUELTIGE_MODI:
        return wert
    return None


def _herkunft_dict(wert: Any) -> dict[str, str]:
    """Reads a ``standard``-shaped value into a ``{chat, agent}`` dict,
    honoring the legacy bare "ja"/"fragen"/"nein" shorthand that used to set
    both origins at once (``berechtigungsregeln.py``'s own reader still
    accepts it). Losing the untouched origin's value here — by treating the
    shorthand as "not a dict, start empty" — would silently narrow it to the
    class default the next time a mode is picked, exactly the kind of
    unannounced change Tor 3 exists to prevent.
    """
    if isinstance(wert, dict):
        return {k: v for k, v in wert.items() if k in ("chat", "agent")}
    if isinstance(wert, str) and wert in GUELTIGE_ANTWORTEN:
        return {"chat": wert, "agent": wert}
    return {}


def anwenden(pfad: Path, herkunft: str, modus: str) -> None:
    """Writes one mode's two lines into ``berechtigungen.json``, for one
    origin. Anything else already in the file is read back unchanged.

    A broken file is not repaired here — that is ``berechtigungsregeln.laden``'s
    job, and it runs on every judged call regardless of what this write does.
    This function only has to not make a broken file worse, so a JSON error
    here means starting from the shipped defaults rather than guessing at
    what was meant.
    """
    if modus not in MODUS_FELDER:
        return
    innerhalb, alles_andere = MODUS_FELDER[modus]

    erststart_kopie(pfad, beispiel_pfad())
    rohdaten: dict[str, Any] = {}
    if pfad.exists():
        try:
            gelesen = json.loads(pfad.read_text(encoding="utf-8"))
            if isinstance(gelesen, dict):
                rohdaten = gelesen
        except (OSError, json.JSONDecodeError) as fehler:
            log.error(
                "berechtigungen.json was broken when the mode was set (%s) — "
                "it is created anew from the defaults", fehler,
            )

    rohdaten["standard"] = _herkunft_dict(rohdaten.get("standard"))
    rohdaten["standard"][herkunft] = alles_andere

    dateien = rohdaten.get("dateien")
    rohdaten["dateien"] = dateien if isinstance(dateien, dict) else {}

    innerhalb_feld = rohdaten["dateien"].get("innerhalb_der_ordner")
    rohdaten["dateien"]["innerhalb_der_ordner"] = (
        innerhalb_feld if isinstance(innerhalb_feld, dict) else {}
    )
    rohdaten["dateien"]["innerhalb_der_ordner"][herkunft] = innerhalb

    ausserhalb_feld = rohdaten["dateien"].get("ausserhalb_der_ordner")
    rohdaten["dateien"]["ausserhalb_der_ordner"] = (
        ausserhalb_feld if isinstance(ausserhalb_feld, dict) else {}
    )
    rohdaten["dateien"]["ausserhalb_der_ordner"][herkunft] = alles_andere

    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(rohdaten, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
