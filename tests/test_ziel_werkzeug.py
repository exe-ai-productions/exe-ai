"""The goal tool: what it announces, what it refuses, and where it is offered.

Three things are worth pinning down.

The report is the message. It is cleaned before it goes anywhere, for the
same reason a schedule's task text is: a page the model read can carry
invisible characters, and this text ends up in a system notification and in
the answer's own mark.

It works everywhere. A goal can be handed out in a chat exactly as well as in
a scheduled run, so the tool is in the offering without a precondition — and
it disappears from it the moment somebody switches it off, through the one
switch every other tool uses.

And it says what it did in a way the model can act on: "you can stop here",
because a model that has just reported a finished goal must not keep working
on it.
"""

from __future__ import annotations

import asyncio

import pytest

from app.tools import ziel_werkzeug
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten


# --- The report itself -------------------------------------------------------


def test_der_bericht_kommt_getrimmt_zurueck():
    assert ziel_werkzeug.bericht({"report": "  Mail von Müller, Betreff: Angebot  "}) == (
        "Mail von Müller, Betreff: Angebot"
    )


def test_unsichtbare_zeichen_fliegen_raus():
    """A read page could otherwise plant something nobody would ever see —
    the same rule the schedule's task text follows."""
    text = ziel_werkzeug.bericht({"report": "Mail​ von‮ Müller"})
    assert text == "Mail von Müller"


def test_zeilenumbruch_und_tabulator_bleiben():
    assert ziel_werkzeug.bericht({"report": "Zeile eins\nZeile\tzwei"}) == (
        "Zeile eins\nZeile\tzwei"
    )


def test_ohne_bericht_wird_nichts_gemeldet():
    with pytest.raises(ziel_werkzeug.ZielVerboten):
        ziel_werkzeug.bericht({})


def test_ein_bericht_aus_lauter_unsichtbarem_ist_keiner():
    with pytest.raises(ziel_werkzeug.ZielVerboten):
        ziel_werkzeug.bericht({"report": "​​"})


def test_zu_lang_wird_abgewiesen_statt_gekuerzt():
    """Refused, not trimmed — a model that got a thousand characters through
    would learn that a thousand is fine, and the notification would show the
    first line of it."""
    with pytest.raises(ziel_werkzeug.ZielVerboten) as fehler:
        ziel_werkzeug.bericht({"report": "x" * (ziel_werkzeug.MAX_LAENGE + 1)})
    assert str(ziel_werkzeug.MAX_LAENGE) in str(fehler.value)


# --- What actually happens on a call ----------------------------------------


def test_der_aufruf_meldet_und_sagt_dem_modell_dass_es_aufhoeren_darf(monkeypatch):
    gemeldet: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        ziel_werkzeug.cronmeldung,
        "melden",
        lambda text, *, erfolgreich: gemeldet.append((text, erfolgreich)),
    )
    antwort = asyncio.run(ziel_werkzeug.ausfuehren({"report": "Testziel erreicht"}))
    assert gemeldet == [("Testziel erreicht", True)]
    assert antwort == ziel_werkzeug.GEMELDET


def test_ein_leerer_aufruf_meldet_gar_nichts(monkeypatch):
    gemeldet: list[str] = []
    monkeypatch.setattr(
        ziel_werkzeug.cronmeldung,
        "melden",
        lambda text, *, erfolgreich: gemeldet.append(text),
    )
    with pytest.raises(ziel_werkzeug.ZielVerboten):
        asyncio.run(ziel_werkzeug.ausfuehren({"report": "   "}))
    assert gemeldet == []


# --- Where it is offered ----------------------------------------------------


def test_es_gilt_ueberall_auch_ohne_jede_ausstattung():
    """No folder, no table, no file — and still there. A goal can be handed
    out in any conversation, so nothing gates this one.

    The clock stands beside it for the same reason (app/tools/uhr.py): a run
    with no other tool still has to know what day it is."""
    registry = WerkzeugRegistry([])
    namen = [w["function"]["name"] for w in registry.als_openai_werkzeuge()]
    assert namen == [ziel_werkzeug.WERKZEUG_NAME, "get_current_time"]
    assert ziel_werkzeug.WERKZEUG_NAME in registry.namen()


def test_abgeschaltet_verschwindet_es_aus_dem_angebot():
    registry = WerkzeugRegistry([])
    registry.abgeschaltet = {ziel_werkzeug.WERKZEUG_NAME}
    namen = [w["function"]["name"] for w in registry.als_openai_werkzeuge()]
    assert ziel_werkzeug.WERKZEUG_NAME not in namen


def test_abgeschaltet_laeuft_es_auch_nicht_mehr():
    """The second lock: a run can be older than the click."""
    registry = WerkzeugRegistry([])
    registry.abgeschaltet = {ziel_werkzeug.WERKZEUG_NAME}
    with pytest.raises(WerkzeugVerboten):
        asyncio.run(registry.ausfuehren(ziel_werkzeug.WERKZEUG_NAME, {"report": "x"}))


def test_ein_agent_darf_es_nennen_und_bekommt_es_dann_auch():
    """The per-run allowlist (6.3) has to reach it like every other tool."""
    registry = WerkzeugRegistry([])
    namen = [
        w["function"]["name"]
        for w in registry.als_openai_werkzeuge(nur={ziel_werkzeug.WERKZEUG_NAME})
    ]
    assert namen == [ziel_werkzeug.WERKZEUG_NAME]
    assert registry.als_openai_werkzeuge(nur={"etwas_anderes"}) == []


def test_es_steht_in_der_werkzeugliste_der_maske():
    eintraege = {e["name"]: e for e in WerkzeugRegistry([]).uebersicht()}
    assert ziel_werkzeug.WERKZEUG_NAME in eintraege
    assert eintraege[ziel_werkzeug.WERKZEUG_NAME]["needs_confirmation"] is False


def test_die_marke_der_zeile_kennt_seinen_server():
    assert WerkzeugRegistry([]).server_von(ziel_werkzeug.WERKZEUG_NAME) == (
        ziel_werkzeug.SERVER_NAME
    )


# --- What the description teaches -------------------------------------------


def test_die_beschreibung_lehrt_den_beweisgedanken():
    """A good goal names what makes it recognisable. Said in the tool's own
    words, so it holds in a chat as well as on a schedule — and so no goal
    has to be rewritten when a checking build is set up beside this one."""
    text = ziel_werkzeug.werkzeug_beschreibung().beschreibung.lower()
    assert "evidence" in text
    assert "sender" in text and "subject" in text


def test_die_laengengrenze_steht_als_zahl_am_feld():
    """Interpolated from the constant, so the two cannot drift apart —
    what this catches is the way that construction breaks: somebody edits
    the text and drops the f-prefix, and the model is told the limit is
    "{MAX_LAENGE}"."""
    feld = ziel_werkzeug.werkzeug_beschreibung().schema["properties"]["report"]
    assert str(ziel_werkzeug.MAX_LAENGE) in feld["description"]


def test_der_pflichtteil_ist_der_bericht():
    schema = ziel_werkzeug.werkzeug_beschreibung().schema
    assert schema["required"] == ["report"]
