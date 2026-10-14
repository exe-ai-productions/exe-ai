"""The schedule's note: what one run leaves for the next one.

Four things are pinned down here, and each of them is the whole point of
the feature rather than a detail of it.

**It replaces.** The note is fed back into the opening message of every
future run of the entry. A note that appended would grow by a line per run
until it crowded out the task itself — so there is no append, and a second
call simply overwrites the first.

**It is fed back with a time on it.** The timestamp comes from the program,
not from the model: it is the previous firing's due time, and it is what
turns "is this mail new" from a guess into a comparison.

**An entry without a note costs nothing.** No empty paragraph, no sentence
about there being nothing — the first run of an entry has to read exactly
the way it did before any of this existed.

**It exists only inside a scheduled run.** A chat has no entry a note could
belong to, so the tool is not offered there, and a call that reaches the
registry from one is refused rather than quietly writing somewhere.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import cronablauf
from app.tools import cron_notiz, cronjob as cronjob_werkzeug, ziel_werkzeug
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten


def eintrag_bauen(repos, **felder):
    return repos.cronjobs.erstellen(
        agent=felder.pop("agent", "beobachter"),
        task=felder.pop("task", "Ins Postfach sehen"),
        zeitplan=felder.pop("zeitplan", "*/15 * * * *"),
        herkunft="chat",
        **felder,
    )


# --- The text itself --------------------------------------------------------


def test_die_notiz_kommt_getrimmt_zurueck():
    assert cron_notiz.notiz({"note": "  zuletzt gesehen: Mail 5  "}) == (
        "zuletzt gesehen: Mail 5"
    )


def test_unsichtbare_zeichen_fliegen_raus():
    """Sharper here than anywhere else: this text is handed to every future
    run of the entry, so an invisible standing instruction planted by a page
    the run read would keep working long after the page is forgotten."""
    assert cron_notiz.notiz({"note": "Mail​ 5‮ gesehen"}) == "Mail 5 gesehen"


def test_zeilenumbruch_und_tabulator_bleiben():
    assert cron_notiz.notiz({"note": "Mail 5\nBetreff\tAngebot"}) == (
        "Mail 5\nBetreff\tAngebot"
    )


def test_leere_notiz_heisst_loeschen():
    assert cron_notiz.notiz({"note": "   "}) is None
    assert cron_notiz.notiz({}) is None


def test_eine_notiz_aus_lauter_unsichtbarem_ist_keine():
    assert cron_notiz.notiz({"note": "​​"}) is None


def test_zu_lang_wird_abgewiesen_nicht_gekuerzt():
    """Refused, not trimmed — a model whose 4000 characters came back
    shortened would learn that 4000 is fine and keep writing them."""
    with pytest.raises(cron_notiz.NotizVerboten, match="too long"):
        cron_notiz.notiz({"note": "x" * (cron_notiz.MAX_LAENGE + 1)})


def test_genau_die_grenze_geht_noch_durch():
    text = "x" * cron_notiz.MAX_LAENGE
    assert cron_notiz.notiz({"note": text}) == text


# --- Writing it -------------------------------------------------------------


async def test_die_notiz_landet_am_eintrag(repos):
    eintrag = eintrag_bauen(repos)
    antwort = await cron_notiz.ausfuehren(
        {"note": "zuletzt gesehen: Mail 5"}, repos.cronjobs, eintrag.id
    )
    assert repos.cronjobs.holen(eintrag.id).notiz == "zuletzt gesehen: Mail 5"
    assert antwort == cron_notiz.GESPEICHERT


async def test_der_zweite_aufruf_ersetzt_den_ersten(repos):
    """No appending, anywhere: the row holds the new text and nothing of
    the old one."""
    eintrag = eintrag_bauen(repos)
    await cron_notiz.ausfuehren({"note": "Mail 5"}, repos.cronjobs, eintrag.id)
    await cron_notiz.ausfuehren({"note": "Mail 7"}, repos.cronjobs, eintrag.id)
    assert repos.cronjobs.holen(eintrag.id).notiz == "Mail 7"


async def test_eine_leere_notiz_loescht_den_zettel(repos):
    eintrag = eintrag_bauen(repos)
    await cron_notiz.ausfuehren({"note": "Mail 5"}, repos.cronjobs, eintrag.id)
    antwort = await cron_notiz.ausfuehren({"note": ""}, repos.cronjobs, eintrag.id)
    assert repos.cronjobs.holen(eintrag.id).notiz is None
    assert antwort == cron_notiz.GELOESCHT


async def test_zu_lang_schreibt_nichts_und_laesst_die_alte_stehen(repos):
    eintrag = eintrag_bauen(repos)
    await cron_notiz.ausfuehren({"note": "Mail 5"}, repos.cronjobs, eintrag.id)
    with pytest.raises(cron_notiz.NotizVerboten):
        await cron_notiz.ausfuehren(
            {"note": "x" * (cron_notiz.MAX_LAENGE + 1)}, repos.cronjobs, eintrag.id
        )
    assert repos.cronjobs.holen(eintrag.id).notiz == "Mail 5"


async def test_ohne_eintrag_wird_nichts_geschrieben(repos):
    """A chat, or a job started by hand — there is no entry a note could
    belong to."""
    with pytest.raises(cron_notiz.NotizVerboten, match="only available in scheduled runs"):
        await cron_notiz.ausfuehren({"note": "x"}, repos.cronjobs, None)


async def test_ein_geloeschter_eintrag_wird_nicht_beschrieben(repos):
    """Deleted while its own run was still going: nothing to write to, and
    answering "saved" would be a lie about a row that is gone."""
    eintrag = eintrag_bauen(repos)
    repos.cronjobs.loeschen(eintrag.id)
    with pytest.raises(cron_notiz.NotizVerboten, match="no longer exists"):
        await cron_notiz.ausfuehren({"note": "x"}, repos.cronjobs, eintrag.id)


# --- Where it is offered ----------------------------------------------------


def _namen(registry, **kwargs):
    return [w["function"]["name"] for w in registry.als_openai_werkzeuge(**kwargs)]


def test_im_chat_wird_es_nicht_angeboten(repos):
    """The default is off, and the default is what a chat uses."""
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    assert cron_notiz.WERKZEUG_NAME not in _namen(registry)
    assert cronjob_werkzeug.WERKZEUG_NAME in _namen(registry)


def test_im_cron_lauf_wird_es_angeboten(repos):
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    assert cron_notiz.WERKZEUG_NAME in _namen(registry, cron_notiz_an=True)


def test_ohne_cron_tabelle_gibt_es_es_gar_nicht():
    """Same convention as every other equipped tool: no table, no tool —
    even in a run that would otherwise be offered it."""
    registry = WerkzeugRegistry([])
    assert cron_notiz.WERKZEUG_NAME not in _namen(registry, cron_notiz_an=True)
    assert cron_notiz.WERKZEUG_NAME not in registry.namen()


def test_abgeschaltet_verschwindet_es_aus_dem_angebot(repos):
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    registry.abgeschaltet = {cron_notiz.WERKZEUG_NAME}
    assert cron_notiz.WERKZEUG_NAME not in _namen(registry, cron_notiz_an=True)


def test_ein_agent_der_es_nicht_nennt_bekommt_es_nicht(repos):
    """The per-run allowlist (6.3) reaches it like every other tool."""
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    assert cron_notiz.WERKZEUG_NAME not in _namen(
        registry, nur={ziel_werkzeug.WERKZEUG_NAME}, cron_notiz_an=True
    )
    assert cron_notiz.WERKZEUG_NAME in _namen(
        registry, nur={cron_notiz.WERKZEUG_NAME}, cron_notiz_an=True
    )


def test_es_steht_in_der_werkzeugliste_der_maske(repos):
    """Switchable like everything else — a tool nobody can switch off would
    be the one exception to the rule the tools window rests on."""
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    assert cron_notiz.WERKZEUG_NAME in registry.namen()
    namen = [e["name"] for e in registry.uebersicht()]
    assert cron_notiz.WERKZEUG_NAME in namen
    assert registry.server_von(cron_notiz.WERKZEUG_NAME) == cron_notiz.SERVER_NAME


def test_ueber_die_registry_ohne_eintrag_abgelehnt(repos):
    """The registry is the outer boundary: a call that got here from a chat
    is refused, not stored somewhere plausible."""
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    with pytest.raises(WerkzeugVerboten, match="only available in scheduled runs"):
        asyncio.run(registry.ausfuehren(cron_notiz.WERKZEUG_NAME, {"note": "x"}))


def test_ueber_die_registry_mit_eintrag_geschrieben(repos):
    eintrag = eintrag_bauen(repos)
    registry = WerkzeugRegistry([], cronjobs_repo=repos.cronjobs)
    antwort = asyncio.run(
        registry.ausfuehren(
            cron_notiz.WERKZEUG_NAME, {"note": "Mail 5"}, cronjob_id=eintrag.id
        )
    )
    assert antwort == cron_notiz.GESPEICHERT
    assert repos.cronjobs.holen(eintrag.id).notiz == "Mail 5"


# --- How it reaches the next run --------------------------------------------


def _eintrag(**felder):
    grund = {
        "task": "Ins Postfach sehen",
        "notiz": None,
        "notiz_am": None,
        "ziel": None,
        "zuletzt_ausgeloest": None,
    }
    grund.update(felder)
    return SimpleNamespace(**grund)


def test_ohne_notiz_kostet_der_eintrag_nichts():
    """Not an empty paragraph, not a line about there being no note — the
    text has to be exactly what it was before cron notes existed."""
    assert cronablauf.auftragstext(_eintrag()) == "Ins Postfach sehen"


def test_die_notiz_kommt_mit_dem_zeitpunkt_ihrer_niederschrift():
    """The time on the note is when it was WRITTEN, not the previous
    firing's due time — a due time is stamped for a firing that was merely
    skipped as well, and that skip can land after the note was written."""
    text = cronablauf.auftragstext(
        _eintrag(
            notiz="zuletzt gesehen: Mail 5",
            notiz_am="2026-09-01T10:03:00+02:00",
            zuletzt_ausgeloest="2026-09-01T10:15:00+02:00",
        )
    )
    assert "Ins Postfach sehen" in text
    assert "2026-09-01T10:03:00+02:00" in text
    assert "2026-09-01T10:15:00+02:00" not in text
    assert "zuletzt gesehen: Mail 5" in text
    assert cron_notiz.WERKZEUG_NAME in text


def test_eine_notiz_ohne_zeitstempel_bekommt_keine_leere_klammer():
    text = cronablauf.auftragstext(_eintrag(notiz="Mail 5"))
    assert "Mail 5" in text
    assert "()" not in text
    assert "None" not in text


def test_notiz_und_ziel_stehen_beide_drin_und_das_ziel_zuletzt():
    """The note is context, the goal is the instruction — and the
    instruction is the last thing the model reads."""
    text = cronablauf.auftragstext(
        _eintrag(
            notiz="Mail 5",
            ziel="Eine ungelesene Mail im Posteingang",
            notiz_am="2026-09-01T10:00:00+02:00",
        )
    )
    assert text.index("Mail 5") < text.index("Goal:")
    assert text.rstrip().endswith("Otherwise, finish without a notification.")
