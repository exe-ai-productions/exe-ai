"""Loads and validates ``berechtigungen.json`` — what Tor 3 judges by.

Ships as ``berechtigungen.example.json`` and is copied into the user's data
folder on first start, the same pattern ``mcp_servers.json`` already uses
(``app.config.erststart_kopie``). From then on the file belongs to the user
and is read fresh on every call — like an agent's Markdown file, a change
takes effect immediately, no restart.

A missing or broken file does not shut anything down: ``laden()`` falls back
to the built-in default (share a folder and its contents run, nothing else
does) and marks the result as ``kaputt`` so the caller can say so loudly.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.config import erststart_kopie
from app.paketierung import aufloesen

log = logging.getLogger(__name__)

Antwort = Literal["ja", "fragen", "nein"]

# Public: the one place this three-value domain is spelled out. Every other
# module that needs to validate or order an Antwort (app/agenten.py's
# permissions:, app/berechtigungen.py's strictness order, app/berechtigungswahl.py)
# imports this instead of copying the three strings again.
GUELTIGE_ANTWORTEN: set[str] = {"ja", "fragen", "nein"}

DATEIWERKZEUGE_STANDARD: tuple[str, ...] = (
    "read_file", "search_files", "write_file", "edit_file", "list_dir", "run_command",
    "create_folder",
)


def _standard_paar() -> dict[str, Antwort]:
    return {"chat": "ja", "agent": "ja"}


@dataclass
class Regeldatei:
    # Per origin: the fallback for anything not covered below — a tool with
    # no path (not a file tool), no explicit rule, no static confirm flag.
    standard: dict[str, Antwort] = field(default_factory=_standard_paar)
    nur_was_der_agent_nennt: bool = True
    regeln: dict[str, Antwort] = field(default_factory=dict)
    dateiwerkzeuge: tuple[str, ...] = DATEIWERKZEUGE_STANDARD
    # Per origin: a file-tool call whose path resolves INSIDE the shared
    # folders. "ja" is what sharing a folder has always meant — Restricted
    # mode is the one case that asks even here.
    innerhalb_der_ordner: dict[str, Antwort] = field(default_factory=_standard_paar)
    ausserhalb_der_ordner: dict[str, Antwort] = field(
        default_factory=lambda: {"chat": "fragen", "agent": "nein"}
    )
    niemals: tuple[str, ...] = ()
    # Set when the file on disk could not be used — the reason, for the UI.
    # None means: the file was fine (or there simply is none yet).
    kaputt: str | None = None


def _antwort(wert: object, feld: str) -> Antwort | None:
    # isinstance first: an unhashable wert (a list, a nested object) would
    # otherwise crash the `in` check itself, before it gets a chance to say
    # "invalid" — a broken file must fall back, never take the service down.
    if isinstance(wert, str) and wert in GUELTIGE_ANTWORTEN:
        return wert  # type: ignore[return-value]
    if wert is not None:
        log.warning("berechtigungen.json: '%s' is not a valid answer for %s", wert, feld)
    return None


def _je_herkunft(rohdaten: object, ziel: dict[str, Antwort], feld: str) -> None:
    """Reads a ``{"chat": ..., "agent": ...}`` pair into ``ziel``, in place.

    Shared by every field shaped this way (``standard``,
    ``innerhalb_der_ordner``, ``ausserhalb_der_ordner``) so the same
    validation and logging happens once, not three times slightly differently.
    """
    if not isinstance(rohdaten, dict):
        return
    for herkunft in ("chat", "agent"):
        if (antwort := _antwort(rohdaten.get(herkunft), f"{feld}.{herkunft}")) is not None:
            ziel[herkunft] = antwort


def _regeldatei_aus(rohdaten: dict) -> Regeldatei:
    datei = Regeldatei()

    standard = rohdaten.get("standard")
    if isinstance(standard, dict):
        _je_herkunft(standard, datei.standard, "standard")
    elif (wert := _antwort(standard, "standard")) is not None:
        # A bare "ja"/"fragen"/"nein" sets both origins — an older file
        # written before this field had a chat/agent split stays readable
        # without anyone having to rewrite it by hand.
        datei.standard = {"chat": wert, "agent": wert}

    if isinstance(rohdaten.get("nur_was_der_agent_nennt"), bool):
        datei.nur_was_der_agent_nennt = rohdaten["nur_was_der_agent_nennt"]

    regeln_roh = rohdaten.get("regeln")
    if not isinstance(regeln_roh, dict):
        regeln_roh = {}
    regeln: dict[str, Antwort] = {}
    for name, wert in regeln_roh.items():
        if not isinstance(name, str):
            continue
        if (antwort := _antwort(wert, f"regeln.{name}")) is not None:
            regeln[name] = antwort
    datei.regeln = regeln

    dateien = rohdaten.get("dateien")
    if not isinstance(dateien, dict):
        dateien = {}
    if "werkzeuge" in dateien:
        werkzeuge = dateien["werkzeuge"]
        if isinstance(werkzeuge, list) and all(isinstance(w, str) for w in werkzeuge):
            # An explicit [] is honored, not treated as "unset" — an operator
            # who empties this list means to remove the path check from
            # every file tool, not to keep the five defaults.
            datei.dateiwerkzeuge = tuple(werkzeuge)
        else:
            log.warning("berechtigungen.json: 'dateien.werkzeuge' must be a list of names")
    _je_herkunft(
        dateien.get("innerhalb_der_ordner") or {},
        datei.innerhalb_der_ordner, "dateien.innerhalb_der_ordner",
    )
    _je_herkunft(
        dateien.get("ausserhalb_der_ordner") or {},
        datei.ausserhalb_der_ordner, "dateien.ausserhalb_der_ordner",
    )

    niemals = rohdaten.get("niemals")
    if niemals is not None:
        if isinstance(niemals, list):
            # A single bad entry salvages the rest instead of dropping the
            # whole tripwire — this list is security-relevant, and silently
            # disarming every pattern over one stray typo is worse than
            # losing just that one pattern.
            if not all(isinstance(m, str) for m in niemals):
                log.warning(
                    "berechtigungen.json: 'niemals' holds an entry that "
                    "is not text — it is skipped, the rest still applies"
                )
            datei.niemals = tuple(m.strip() for m in niemals if isinstance(m, str) and m.strip())
        else:
            log.warning("berechtigungen.json: 'niemals' must be a list of patterns")

    return datei


def _pfad_nutzer() -> Path:
    return aufloesen("berechtigungen.json", schreibbar=True)


def beispiel_pfad() -> Path:
    """The shipped template — public: ``app/berechtigungswahl.py`` reuses it
    to make sure a mode change has a file to write its lines into."""
    return aufloesen("berechtigungen.example.json")


def laden(pfad: Path | None = None) -> Regeldatei:
    """Reads berechtigungen.json fresh. Broken or missing → the safe default.

    ``pfad`` is the user's live file — passed in by the registry (resolved
    once from ``config.app.berechtigungen_datei``, the same way
    ``memory_pfad``/``skills_orte`` arrive pre-resolved) so a test can point
    it into an isolated folder instead of always landing next to the
    program. Only the shipped template is still resolved internally: reading
    it has no side effect, there is nothing here for a test to isolate from.
    """
    pfad = pfad or _pfad_nutzer()
    erststart_kopie(pfad, beispiel_pfad())
    if not pfad.exists():
        return Regeldatei()

    try:
        rohdaten = json.loads(pfad.read_text(encoding="utf-8"))
        if not isinstance(rohdaten, dict):
            raise ValueError("die oberste Ebene muss ein Objekt sein")
        # Reading a shape _regeldatei_aus does not expect (a list where a
        # section should be, say) belongs to the same "broken file" case as
        # bad JSON — it must fall back, not take Tor 3 down with it.
        return _regeldatei_aus(rohdaten)
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError) as fehler:
        log.error("berechtigungen.json is broken (%s) — the base rule applies", fehler)
        datei = Regeldatei()
        datei.kaputt = str(fehler)
        return datei
