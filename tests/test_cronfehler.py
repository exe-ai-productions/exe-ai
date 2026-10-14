"""The failure counter behind a cron entry.

The one distinction everything here turns on: a run that could not do its
work is a failure, and a run that did its work and found nothing to report
is not. Looking into the inbox every fifteen minutes and finding no new mail
is a successful run — an entry doing exactly what it was made for must never
be switched off for it.
"""

from __future__ import annotations

import pytest

from app import cronablauf
from app.tools import cronjob as cronjob_werkzeug


@pytest.fixture
def gemeldet(monkeypatch):
    """Announcements, collected instead of played — nothing may pop up a
    notification or make a sound during a test run."""
    aufrufe: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich, sprache=None: aufrufe.append((text, erfolgreich)),
    )
    return aufrufe


def eintrag_anlegen(repos, **felder):
    return repos.cronjobs.erstellen(
        agent="a", task="Ins Postfach sehen", zeitplan="*/15 * * * *",
        herkunft="chat", **felder,
    )


# --- Counting, resetting, stopping ------------------------------------------


async def test_gescheiterter_lauf_zaehlt_hoch(repos, gemeldet):
    # On 'announce' on purpose: this entry never cared about ``deliver`` and
    # so stood on the default 'log', where NOTHING reaches the
    # announcing module at all (``_mitteilen``). The silence below was then
    # the gate's, not the counter's — the limit could have fired on the very
    # first failed run and this test would still have been green. On
    # 'announce' the sentence would really go out, so the empty list is once
    # more what the name says: the limit does not speak before it is reached.
    eintrag = eintrag_anlegen(repos, deliver="announce")
    assert eintrag.fehlversuche == 0
    assert eintrag.fehlergrenze == 5

    await cronablauf.ausgang_verbuchen(repos, eintrag.id, "x", erfolgreich=False)

    assert repos.cronjobs.holen(eintrag.id).fehlversuche == 1
    assert repos.cronjobs.holen(eintrag.id).aktiv is True
    assert gemeldet == []


async def test_ziel_nicht_erfuellt_zaehlt_nicht(repos, gemeldet):
    """The heart of it: a run that went, looked and found nothing ends
    properly, and an entry doing that fifty times a day must stand at zero
    the whole time."""
    # On 'announce' for the reason above: on the default 'log' the empty
    # list came out of the gate, and fifty successful runs could each have
    # announced without this test noticing.
    eintrag = eintrag_anlegen(repos, deliver="announce")

    for _ in range(50):
        await cronablauf.ausgang_verbuchen(repos, eintrag.id, "x", erfolgreich=True)

    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 0
    assert frisch.aktiv is True
    assert gemeldet == []


async def test_erfolgreicher_lauf_setzt_zurueck(repos, gemeldet):
    eintrag = eintrag_anlegen(repos, fehlergrenze=5)

    for _ in range(4):
        await cronablauf.ausgang_verbuchen(repos, eintrag.id, "x", erfolgreich=False)
    assert repos.cronjobs.holen(eintrag.id).fehlversuche == 4

    await cronablauf.ausgang_verbuchen(repos, eintrag.id, "x", erfolgreich=True)
    assert repos.cronjobs.holen(eintrag.id).fehlversuche == 0

    # And the entry has its whole budget back, not one last try.
    for _ in range(4):
        await cronablauf.ausgang_verbuchen(repos, eintrag.id, "x", erfolgreich=False)
    assert repos.cronjobs.holen(eintrag.id).aktiv is True


async def test_grenze_haelt_an_und_meldet_einmal(repos, gemeldet):
    # On 'announce': the limit's sentence is a notification like any other,
    # and an entry on 'log' gets it in the log alone. What this test is
    # about is one message, on the run that reaches the limit, with the
    # number in it.
    eintrag = eintrag_anlegen(repos, deliver="announce", fehlergrenze=2)

    angehalten = await cronablauf.ausgang_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", erfolgreich=False
    )
    assert angehalten is False
    assert repos.cronjobs.holen(eintrag.id).aktiv is True

    angehalten = await cronablauf.ausgang_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", erfolgreich=False
    )
    assert angehalten is True
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.aktiv is False
    assert frisch.fehlversuche == 2
    # The number is in the message — that is what makes it worth sending.
    assert gemeldet == [("Ins Postfach sehen — stopped after 2 failed runs", False)]


async def test_bei_deliver_log_haelt_es_still_an(repos, gemeldet):
    """On 'log' the failure limit stays silent too, not only the announcement
    per run — although a schedule must not run itself to death in silence.

    It does not die in silence. The log line, the switched-off row and the
    grey lamp are all written before the notification is ever reached — what
    'log' buys is that nothing pops up and nothing makes a noise, which
    is what the setting says. The counter-proof on 'announce' is
    ``test_grenze_haelt_an_und_meldet_einmal`` above.
    """
    eintrag = eintrag_anlegen(repos, deliver="log", fehlergrenze=1)
    angehalten = await cronablauf.ausgang_verbuchen(
        repos, eintrag.id, "x", erfolgreich=False
    )

    assert gemeldet == []
    # Stopped all the same — silent is not the same as still running.
    assert repos.cronjobs.holen(eintrag.id).aktiv is False
    assert repos.cronjobs.holen(eintrag.id).fehlversuche == 1
    # And "did an announcement go out" answers honestly, so the caller does
    # not suppress a second one that never existed.
    assert angehalten is False


async def test_kein_zweiter_stopp_fuer_denselben_eintrag(repos, gemeldet):
    """A late-arriving run of an entry that is already off says nothing —
    one message per stop, not one per failed run."""
    eintrag = eintrag_anlegen(repos, deliver="announce", fehlergrenze=1)
    await cronablauf.ausgang_verbuchen(repos, eintrag.id, "x", erfolgreich=False)
    assert len(gemeldet) == 1

    await cronablauf.ausgang_verbuchen(repos, eintrag.id, "x", erfolgreich=False)
    assert len(gemeldet) == 1


async def test_wieder_einschalten_setzt_den_zaehler_zurueck(repos, gemeldet):
    """Otherwise 'resume' would be a lie: the count would still stand at the
    limit and the next failed run would switch the entry straight back off."""
    eintrag = eintrag_anlegen(repos, fehlergrenze=2)
    for _ in range(2):
        await cronablauf.ausgang_verbuchen(repos, eintrag.id, "x", erfolgreich=False)
    assert repos.cronjobs.holen(eintrag.id).aktiv is False

    wieder = repos.cronjobs.aktiv_setzen(eintrag.id, True)
    assert wieder.aktiv is True
    assert wieder.fehlversuche == 0


async def test_ausschalten_laesst_die_zahl_stehen(repos):
    """The mask reads that number back to tell "gave up" from "switched off
    by hand" — clearing it on the way out would erase the evidence."""
    eintrag = eintrag_anlegen(repos, fehlergrenze=5)
    await cronablauf.ausgang_verbuchen(repos, eintrag.id, "x", erfolgreich=False)
    ab = repos.cronjobs.aktiv_setzen(eintrag.id, False)
    assert ab.fehlversuche == 1


async def test_ohne_cronjob_id_passiert_nichts(repos, gemeldet):
    assert await cronablauf.ausgang_verbuchen(repos, None, "x", erfolgreich=False) is False
    assert gemeldet == []


async def test_geloeschter_eintrag_passiert_nichts(repos, gemeldet):
    assert await cronablauf.ausgang_verbuchen(repos, "phantom", "x", erfolgreich=False) is False
    assert gemeldet == []


# --- The limit, set from the tool -------------------------------------------


async def test_werkzeug_legt_mit_eigener_grenze_an(repos, tmp_path):
    antwort = await cronjob_werkzeug.ausfuehren(
        {"action": "create", "time": "08:00", "task": "Los", "max_failures": 2},
        repos.cronjobs, (str(tmp_path),),
    )
    assert "stops after 2 failed runs" in antwort
    assert repos.cronjobs.auflisten()[0].fehlergrenze == 2


async def test_werkzeug_ohne_angabe_bleibt_bei_fuenf(repos, tmp_path):
    await cronjob_werkzeug.ausfuehren(
        {"action": "create", "time": "08:00", "task": "Los"},
        repos.cronjobs, (str(tmp_path),),
    )
    assert repos.cronjobs.auflisten()[0].fehlergrenze == 5


async def test_werkzeug_aendert_die_grenze(repos, tmp_path):
    eintrag = eintrag_anlegen(repos, fehlergrenze=5)
    antwort = await cronjob_werkzeug.ausfuehren(
        {"action": "update", "id": eintrag.id, "max_failures": 9},
        repos.cronjobs, (str(tmp_path),),
    )
    assert "stops after 9 failed runs" in antwort
    assert repos.cronjobs.holen(eintrag.id).fehlergrenze == 9


@pytest.mark.parametrize("wert", [0, 21, -3, "viele", 2.5, True, ""])
async def test_werkzeug_weist_unmoegliche_grenzen_ab(repos, tmp_path, wert):
    with pytest.raises(cronjob_werkzeug.CronjobVerboten):
        await cronjob_werkzeug.ausfuehren(
            {"action": "create", "time": "08:00", "task": "Los", "max_failures": wert},
            repos.cronjobs, (str(tmp_path),),
        )
    assert repos.cronjobs.auflisten() == []


# --- What the interface gets to see -----------------------------------------


def test_api_liefert_zaehler_und_grenze(client):
    repos = client.app.state.repositories
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="x", zeitplan="08:00", herkunft="chat", fehlergrenze=3
    )
    repos.cronjobs.fehlversuch_zaehlen(eintrag.id)

    zeile = client.get("/api/v1/cronjobs").json()[0]
    assert zeile["fehlversuche"] == 1
    assert zeile["fehlergrenze"] == 3
