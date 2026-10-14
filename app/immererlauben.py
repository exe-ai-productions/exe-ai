"""Turning "always allow" into a real rule — a name written
into ``berechtigungen.json``'s own ``regeln`` map, the flat per-tool
override Tor 3 (``app/berechtigungen.py``) already treats as the strongest
signal there is: it wins over every other line in the file, for both a chat
and an agent alike, with no herkunft split to get wrong.

Before this, the confirmation box's third button only remembered its yes in
the browser (``frontend/src/lib/zustand.svelte.js``) — gone on reload, never
seen by an agent run, and nowhere to look it up or take it back. Writing it
here instead makes it exactly what the file's own docstring calls it: "the
precise, hand-editable source" — permanent, visible, deletable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.berechtigungsregeln import beispiel_pfad
from app.config import erststart_kopie

log = logging.getLogger(__name__)


def _lesen(pfad: Path) -> dict[str, Any]:
    erststart_kopie(pfad, beispiel_pfad())
    if not pfad.exists():
        return {}
    try:
        gelesen = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as fehler:
        log.error(
            "berechtigungen.json was broken when a rule was set (%s) — "
            "it is created anew from the defaults", fehler,
        )
        return {}
    return gelesen if isinstance(gelesen, dict) else {}


def _schreiben(pfad: Path, rohdaten: dict[str, Any]) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(rohdaten, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def setzen(pfad: Path, name: str) -> None:
    """Writes ``name`` into the rule file as an unconditional "ja".

    Anything else already in the file — the mode's own lines, other
    per-tool rules, the ``niemals`` list — is read back unchanged, the same
    promise ``app/berechtigungswahl.py`` makes for the mode shortcut.
    """
    rohdaten = _lesen(pfad)
    regeln = rohdaten.get("regeln")
    rohdaten["regeln"] = dict(regeln) if isinstance(regeln, dict) else {}
    rohdaten["regeln"][name] = "ja"
    _schreiben(pfad, rohdaten)


def entfernen(pfad: Path, name: str) -> bool:
    """Removes one per-tool rule again. Returns whether there was one."""
    rohdaten = _lesen(pfad)
    regeln = rohdaten.get("regeln")
    if not isinstance(regeln, dict) or name not in regeln:
        return False
    regeln = dict(regeln)
    del regeln[name]
    rohdaten["regeln"] = regeln
    _schreiben(pfad, rohdaten)
    return True


def auflisten(pfad: Path) -> dict[str, str]:
    """Every per-tool rule currently on file — the "findable" half."""
    regeln = _lesen(pfad).get("regeln")
    return dict(regeln) if isinstance(regeln, dict) else {}
