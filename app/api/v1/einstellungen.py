"""Settings across their scopes.

Every setting is reachable under the scope it belongs to — `global`,
`modell:<endpoint_id>` or `chat:<chat_id>` — and the resolved route gives back
what actually applies, together with where each value comes from.

That last part matters: a cascade without provenance is a black box. You see a
number and cannot tell whether it is yours, the model's, or the default.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.abhaengigkeiten import hole_config, hole_repositories, hole_sprache
from app.i18n import t
from app.config import Config
from app.db import Repositories
from app.db.repositories.einstellungen import GLOBAL, WriteRefused
from app.anrede import SCHLUESSEL as ANREDE
from app.anrede import schalter_pruefen as anrede_pruefen
from app.befehlszeitwahl import SCHLUESSEL as BEFEHL_ZEITGRENZE
from app.befehlszeitwahl import wahl_pruefen as befehl_zeitgrenze_pruefen
from app.berechtigungswahl import SCHLUESSEL as BERECHTIGUNGSMODUS
from app.berechtigungswahl import anwenden as berechtigungsmodus_anwenden
from app.berechtigungswahl import wahl_pruefen as berechtigungsmodus_pruefen
from app.bildaufbereitung import SCHLUESSEL as BILDAUFBEREITUNG
from app.bildaufbereitung import wahl_pruefen as bildaufbereitung_pruefen
from app.bildfensterwahl import SCHLUESSEL as BILDFENSTER
from app.bildfensterwahl import wahl_pruefen as bildfenster_pruefen
from app.bildgeraete import SCHLUESSEL as BILDGERAETE
from app.bildgeraete import pruefen as bildgeraete_pruefen
from app.bildmodellwerte import SCHLUESSEL as BILDMODELLWERTE
from app.bildmodellwerte import pruefen as bildmodellwerte_pruefen
from app.bildstandardmodell import SCHLUESSEL as BILD_STANDARDMODELL
from app.bildstandardmodell import pruefen as bild_standardmodell_pruefen
from app.darstellungwahl import SCHLUESSEL as DARSTELLUNG
from app.darstellungwahl import wahl_pruefen as darstellung_pruefen
from app.denkenwahl import SCHLUESSEL as DENKEN
from app.denkenwahl import schalter_pruefen as denken_pruefen
from app.denkablehnung import SCHLUESSEL as DENKEN_ABGELEHNT
from app.denkablehnung import liste_pruefen as denken_abgelehnt_pruefen
from app.feineinstellungenwahl import SCHLUESSEL as FEINEINSTELLUNGEN
from app.feineinstellungenwahl import wahl_pruefen as feineinstellungen_pruefen
from app.gedaechtnis import SCHLUESSEL as GEDAECHTNIS
from app.gedaechtnis import schalter_pruefen
from app.klangwahl import SCHLUESSEL as KLAENGE
from app.klangwahl import wahl_pruefen as klaenge_pruefen
from app.meldewahl import SCHLUESSEL as MELDEWESEN
from app.meldewahl import wahl_pruefen as meldewesen_pruefen
from app.layoutwahl import SCHLUESSEL as LAYOUT
from app.bildstile import SCHLUESSEL as BILDSTILE
from app.bildstile import wahl_pruefen as bildstile_pruefen
from app.layoutwahl import wahl_pruefen as layout_pruefen
from app.moduswahl import SCHLUESSEL as MODUS
from app.moduswahl import wahl_pruefen as modus_pruefen
from app.modellwahl import SCHLUESSEL_ZULETZT as MODELL_ZULETZT
from app.modellwahl import aus_pruefen, wahl_pruefen, zuletzt_pruefen
from app.parameter import pruefen
from app.skillwahl import SCHLUESSEL as SKILLS_AUTO
from app.skillwahl import schalter_pruefen as skills_auto_pruefen
from app.scrollwahl import SCHLUESSEL as SCROLLSTELLE
from app.scrollwahl import VORGABE as SCROLL_DEFAULT
from app.scrollwahl import wahl_pruefen as scrollstelle_pruefen
from app.sprachwahl import SCHLUESSEL as SPRACHE
from app.sprachwahl import wahl_pruefen as sprache_pruefen
from app.diktatsprachewahl import SCHLUESSEL as DIKTAT
from app.diktatsprachewahl import wahl_pruefen as diktat_pruefen
# The one field (Stage 8): which model an agent or cron run uses when nobody
# picked one for that run. The retired guardian's own `waechter` key is NOT
# listed any more — the row that used to write it writes this one now, and an
# old database simply keeps its stored value lying there, unread.
from app.agentenmodellwahl import SCHLUESSEL as AGENTENMODELL
from app.agentenmodellwahl import wahl_pruefen as agentenmodell_pruefen
# Stage 11: how the MAIN model server starts — the file, the window, the
# layers, the port and the module chosen per file. It stood in the browser's
# `runner:*` keys, where nothing without a browser could read it.
from app.runnermodellwahl import SCHLUESSEL as RUNNERMODELL
from app.runnermodellwahl import row_check as runnermodell_row_check
from app.runnermodellwahl import wahl_pruefen as runnermodell_pruefen
from app.werkzeugwahl import SCHLUESSEL as WERKZEUGE_AUS
from app.werkzeugwahl import aus_pruefen as werkzeuge_aus_pruefen
from app.werkzeugrundenwahl import SCHLUESSEL as WERKZEUG_RUNDEN
from app.werkzeugrundenwahl import wahl_pruefen as werkzeug_runden_pruefen
# At what share of the context a chat folds its own settled middle into a
# summary (app/verdichtungswahl.py).
from app.verdichtungswahl import SCHLUESSEL as VERDICHTUNG_SCHWELLE
from app.verdichtungswahl import wahl_pruefen as verdichtung_schwelle_pruefen
# How often a finished background command may carry a chat on by itself
# before it stops and says so (app/hintergrundwecken.py).
from app.weckrundenwahl import SCHLUESSEL as WECK_RUNDEN
from app.weckrundenwahl import wahl_pruefen as weck_runden_pruefen
from app.bildschutz import SCHLUESSEL as BILDSCHUTZ
from app.bildschutz import schalter_pruefen as bildschutz_pruefen
# The helpers' two limits (app/helper.py): how many at once, how many rounds.
from app import helper

router = APIRouter(prefix="/settings", tags=["settings"])

# Which settings may be written through this route, and how each is checked.
# A setting nobody vouches for does not get in — the JSON column cannot check
# anything by itself.
PRUEFER: dict[str, Callable[[Any], Any]] = {
    "parameter": pruefen,
    "modelle_aus": aus_pruefen,
    "katalog_wahl": wahl_pruefen,
    MODELL_ZULETZT: zuletzt_pruefen,
    WERKZEUGE_AUS: werkzeuge_aus_pruefen,
    WERKZEUG_RUNDEN: werkzeug_runden_pruefen,
    VERDICHTUNG_SCHWELLE: verdichtung_schwelle_pruefen,
    WECK_RUNDEN: weck_runden_pruefen,
    BEFEHL_ZEITGRENZE: befehl_zeitgrenze_pruefen,
    GEDAECHTNIS: schalter_pruefen,
    ANREDE: anrede_pruefen,
    SKILLS_AUTO: skills_auto_pruefen,
    SPRACHE: sprache_pruefen,
    KLAENGE: klaenge_pruefen,
    MELDEWESEN: meldewesen_pruefen,
    DARSTELLUNG: darstellung_pruefen,
    LAYOUT: layout_pruefen,
    MODUS: modus_pruefen,
    DENKEN: denken_pruefen,
    DENKEN_ABGELEHNT: denken_abgelehnt_pruefen,
    AGENTENMODELL: agentenmodell_pruefen,
    RUNNERMODELL: runnermodell_pruefen,
    DIKTAT: diktat_pruefen,
    BILDFENSTER: bildfenster_pruefen,
    BILDSTILE: bildstile_pruefen,
    BILDMODELLWERTE: bildmodellwerte_pruefen,
    BILDGERAETE: bildgeraete_pruefen,
    BILD_STANDARDMODELL: bild_standardmodell_pruefen,
    BILDAUFBEREITUNG: bildaufbereitung_pruefen,
    SCROLLSTELLE: scrollstelle_pruefen,
    FEINEINSTELLUNGEN: feineinstellungen_pruefen,
    BILDSCHUTZ: bildschutz_pruefen,
    helper.AT_ONCE_KEY: helper.limit_check,
    helper.STEPS_KEY: helper.limit_check,
    BERECHTIGUNGSMODUS["chat"]: berechtigungsmodus_pruefen,
    BERECHTIGUNGSMODUS["agent"]: berechtigungsmodus_pruefen,
}

# Checks on a whole row, old and new side by side, that refuse a write by
# raising ``WriteRefused`` instead of trimming it.
ROW_CHECKS: dict[str, Callable[[Any, Any], None]] = {
    RUNNERMODELL: runnermodell_row_check,
}

# Nested sets a PATCH checks as they were sent rather than merged with the
# stored set first. The module memory: its entries each stand alone, and the
# cap on its size is the whole-row check's (``ROW_CHECKS``).
AS_SENT: dict[str, frozenset[str]] = {
    RUNNERMODELL: frozenset({"module"}),
}

# Nested sets a PATCH stores as the check leaves them: the sent set merged
# into the stored one, and what the check keeps of that in place of the
# stored set. An entry sent as unset is gone from the row that way — the
# picture generator's memory switches, where off means not kept and the
# generator starts without the switch.
AS_KEPT: dict[str, frozenset[str]] = {
    BILDGERAETE: frozenset({"switches"}),
}


class WertSetzen(BaseModel):
    wert: Any = None


class WertAntwort(BaseModel):
    bereich: str
    schluessel: str
    wert: Any = None


class AufgeloesterWert(BaseModel):
    # Usually a set of values merged key by key. A setting that cannot be
    # taken apart — a list, say — travels whole from the most specific scope
    # that set it.
    wert: Any = Field(default_factory=dict)
    # Per value: which scope it came from. The UI shows it, so nobody has to
    # guess why a number is what it is.
    herkunft: dict[str, str] = Field(default_factory=dict)


class AufgeloesteAntwort(BaseModel):
    schluessel: str
    # Usually a set of values merged key by key. A setting that cannot be
    # taken apart — a list, say — travels whole from the most specific scope
    # that set it.
    wert: Any = Field(default_factory=dict)
    # Per value: which scope it came from. The UI shows it, so nobody has to
    # guess why a number is what it is.
    herkunft: dict[str, str] = Field(default_factory=dict)


def _bereich_pruefen(bereich: str, sprache: str) -> str:
    if bereich == GLOBAL or bereich.startswith(("modell:", "chat:")):
        return bereich
    raise HTTPException(400, t("fehler.einstellung_bereich", sprache))


def _value_and_origin(
    repositories: Repositories, schluessel: str, modell: str | None, chat: str | None
) -> tuple[Any, dict[str, str]]:
    """The merged value and, per field of it, the scope it came from.

    The scroll position is read scope by scope through the same check a
    write goes through, before the scopes are merged: what the check throws
    out of a scope counts as unset there. A row stored before that check
    existed can still say "somewhere above" without an offset; checked on
    its own, that "above" is dropped, so the chat opens at its end instead
    of at offset 0 — the very top — and never borrows the offset of another
    scope. Fields no scope sets come from the scroll position's defaults and
    name no scope. Every other key is merged as stored.
    """
    if schluessel == SCROLLSTELLE:
        return repositories.einstellungen.value_and_origin(
            schluessel, modell=modell, chat=chat,
            vorgabe=SCROLL_DEFAULT, pruefen=scrollstelle_pruefen,
        )
    return repositories.einstellungen.value_and_origin(schluessel, modell=modell, chat=chat)


@router.get(
    "/resolved",
    response_model=dict[str, AufgeloesterWert],
    summary="What really applies here — several keys at once",
)
def aufgeloest_viele(
    keys: str,
    modell: str | None = None,
    chat: str | None = None,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> dict[str, AufgeloesterWert]:
    """The same answer as the single route, for a whole list of keys.

    The screen needs a dozen of them before it can draw anything, and one
    round trip per key means the window builds itself in a dozen steps that
    the user watches happen. Resolving is a read of already-loaded scopes,
    so doing them together costs nothing extra.

    Duplicates collapse and the order of `keys` is kept, so the caller can
    pair the answer with its own list without sorting it.
    """
    schluessel: list[str] = []
    for roh in keys.split(","):
        name = roh.strip()
        if name and name not in schluessel:
            schluessel.append(name)
    if not schluessel:
        raise HTTPException(400, t("fehler.einstellung_keys_leer", sprache))

    response: dict[str, AufgeloesterWert] = {}
    for name in schluessel:
        wert, herkunft = _value_and_origin(repositories, name, modell, chat)
        response[name] = AufgeloesterWert(wert=wert, herkunft=herkunft)
    return response


@router.get(
    "/resolved/{schluessel}",
    response_model=AufgeloesteAntwort,
    summary="What really applies here",
)
def aufgeloest(
    schluessel: str,
    modell: str | None = None,
    chat: str | None = None,
    repositories: Repositories = Depends(hole_repositories),
) -> AufgeloesteAntwort:
    wert, herkunft = _value_and_origin(repositories, schluessel, modell, chat)
    return AufgeloesteAntwort(schluessel=schluessel, wert=wert, herkunft=herkunft)


@router.get(
    "/{bereich}/{schluessel}",
    response_model=WertAntwort,
    summary="What exactly this scope holds",
)
def holen(
    bereich: str,
    schluessel: str,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> WertAntwort:
    _bereich_pruefen(bereich, sprache)
    return WertAntwort(
        bereich=bereich,
        schluessel=schluessel,
        wert=repositories.einstellungen.holen(bereich, schluessel),
    )


@router.put(
    "/{bereich}/{schluessel}",
    response_model=WertAntwort,
    summary="Set a value of a scope",
)
def setzen(
    bereich: str,
    schluessel: str,
    daten: WertSetzen,
    repositories: Repositories = Depends(hole_repositories),
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> WertAntwort:
    """Stores a value. `null` removes it and lets the scope above take over."""
    _bereich_pruefen(bereich, sprache)
    if schluessel not in PRUEFER:
        raise HTTPException(
            400, t("fehler.einstellung_unbekannt", sprache, name=schluessel)
        )

    wert = daten.wert
    if wert is not None:
        wert = PRUEFER[schluessel](wert)
        if schluessel in ROW_CHECKS:
            try:
                # PUT replaces the row, so it is judged as a new one.
                ROW_CHECKS[schluessel]({}, wert)
            except WriteRefused:
                raise HTTPException(400, t("fehler.einstellung_speichern", sprache)) from None
        # Everything discarded by the check means: nothing was set. Storing an
        # empty set would shadow the scope above it with emptiness.
        if not wert:
            wert = None

    repositories.einstellungen.setzen(bereich, schluessel, wert)

    # The permission mode is a shortcut for lines in berechtigungen.json
    # (app/berechtigungswahl.py) — picking one has to write them, not only
    # remember the choice in the cascade. Global only: there is one shared
    # rule file, not one per chat or model, so a scoped write here would
    # look like it applies narrowly while it actually rewrites the file for
    # everyone.
    if bereich == GLOBAL:
        for herkunft, modus_schluessel in BERECHTIGUNGSMODUS.items():
            if schluessel != modus_schluessel:
                continue
            # Clearing the cascade value falls back to "manuell" in the file
            # too — otherwise the resolved value in the UI and what Tor 3
            # actually enforces would quietly drift apart.
            berechtigungsmodus_anwenden(
                config.pfad(config.app.berechtigungen_datei),
                herkunft, wert or "manuell",
            )

    return WertAntwort(
        bereich=bereich,
        schluessel=schluessel,
        wert=repositories.einstellungen.holen(bereich, schluessel),
    )


@router.patch(
    "/{bereich}/{schluessel}",
    response_model=WertAntwort,
    summary="Set single values of a scope",
)
def teilweise_setzen(
    bereich: str,
    schluessel: str,
    daten: WertSetzen,
    repositories: Repositories = Depends(hole_repositories),
    sprache: str = Depends(hole_sprache),
) -> WertAntwort:
    """Writes only the values sent, leaving the rest of the row alone.

    PUT replaces, which is right for a setting one writer owns. It is wrong
    where two writers share a row: to keep the parts it did not change, each
    of them has to resend the whole object — and the whole object it has is
    the copy it read when its page opened. Two windows on the model server
    then take turns undoing each other, which is the one thing the browser
    storage this replaced could not do, because every value had a key of its
    own there.

    Only a set of values can be written this way. A list or a bare value has
    nothing to merge along, and a caller sending one means PUT.

    Not a way past the check: the value goes through the same ``PRUEFER``
    entry a PUT does, judged beside the stored values, a sent set merged
    deep into the stored one first — a part can be meaningless on its own
    and fine together with what is already there (``am_boden`` false needs
    the stored ``versatz`` beside it). Reading,
    checking and writing happen in one place, under the repository's lock
    (``zusammenlegen``). When the check keeps none of the values sent, the
    write is refused and the stored row stays as it was — except for a set
    that is stored as the check leaves it (``AS_KEPT``): there an entry sent
    as unset is taken out, down to an empty set.
    """
    _bereich_pruefen(bereich, sprache)
    if schluessel not in PRUEFER:
        raise HTTPException(400, t("fehler.einstellung_unbekannt", sprache, name=schluessel))
    if not isinstance(daten.wert, dict):
        raise HTTPException(400, t("fehler.einstellung_kein_wertesatz", sprache))

    try:
        wert = repositories.einstellungen.zusammenlegen(
            bereich, schluessel, daten.wert,
            pruefen=PRUEFER[schluessel], row_check=ROW_CHECKS.get(schluessel),
            as_sent=AS_SENT.get(schluessel, frozenset()),
            as_kept=AS_KEPT.get(schluessel, frozenset()),
        )
    except WriteRefused:
        # The merged row was refused (a cap on its size): the stored row
        # stays as it was.
        raise HTTPException(400, t("fehler.einstellung_speichern", sprache)) from None
    if wert is None:
        raise HTTPException(400, t("fehler.einstellung_kein_wertesatz", sprache))

    return WertAntwort(bereich=bereich, schluessel=schluessel, wert=wert)
