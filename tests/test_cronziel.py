"""A goal on a cron entry — announce only once it is met.

The whole point in one line: fourteen quiet passes, and on the fifteenth
"it is here". So the two things checked hardest here are that a run which
reported nothing changes nothing and says nothing, and that a run which did
report says the text from the CALL and not a stand-in sentence about goals
in general.
"""

from __future__ import annotations

from pathlib import Path

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
    felder.setdefault("ziel", "Eine ungelesene Mail von Müller im Posteingang")
    return repos.cronjobs.erstellen(
        agent="a", task="Ins Postfach sehen", zeitplan="*/15 * * * *",
        herkunft="chat", **felder,
    )


def agent_schreiben(ordner: Path, name: str, werkzeuge: str | None = None) -> None:
    ordner.mkdir(parents=True, exist_ok=True)
    kopf = f"tools: {werkzeuge}\n" if werkzeuge is not None else ""
    (ordner / f"{name}.md").write_text(f"---\n{kopf}---\n\nPrompt.\n", encoding="utf-8")


# --- The goal reaches the run -----------------------------------------------


def test_ohne_ziel_bleibt_der_auftragstext_der_aufgabentext(repos):
    eintrag = eintrag_anlegen(repos, ziel=None)
    assert cronablauf.auftragstext(eintrag) == "Ins Postfach sehen"


def test_mit_ziel_traegt_der_auftragstext_ziel_und_anweisung(repos):
    eintrag = eintrag_anlegen(repos)
    text = cronablauf.auftragstext(eintrag)
    assert text.startswith("Ins Postfach sehen")
    assert "Eine ungelesene Mail von Müller im Posteingang" in text
    # The two halves that make silence the default: call it only when met,
    # and otherwise stop rather than explain.
    assert "ONLY when this goal has been achieved" in text
    assert "finish without a notification" in text


def test_geaendertes_ziel_wirkt_ab_dem_naechsten_lauf(repos):
    """Glued together at firing time, not stored joined — otherwise an
    edited goal would only take hold on entries created after the edit."""
    eintrag = eintrag_anlegen(repos, ziel="altes Ziel")
    repos.cronjobs.aktualisieren(eintrag.id, ziel="neues Ziel")
    assert "neues Ziel" in cronablauf.auftragstext(repos.cronjobs.holen(eintrag.id))


# --- A run that reported nothing --------------------------------------------


async def test_stiller_lauf_meldet_nichts(repos, gemeldet):
    eintrag = eintrag_anlegen(repos, deliver="announce")

    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=True
    )
    await cronablauf.melde_wenn_faellig(repos, eintrag.id, "Ins Postfach sehen")

    assert gemeldet == []
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.aktiv is True
    assert frisch.ziel_erreicht_am is None


async def test_stiller_lauf_zaehlt_keinen_fehlversuch(repos, gemeldet):
    """The line the failure counter draws, checked from this side too: a run that went,
    looked and found nothing is a successful run."""
    # Above the quiet count's own limit on purpose: even the entry that has
    # said nothing for far longer than that is not a failing one.
    #
    # And on 'announce': this entry never cared about ``deliver`` and so
    # stood on the default 'log', where nothing reaches the
    # announcing module at all (``_mitteilen``). The silence below was then
    # the gate's, not the quiet count's — "no goal report in N runs" could
    # have fired after every single one of the fourteen and this test would
    # still have been green.
    eintrag = eintrag_anlegen(repos, fehlergrenze=20, deliver="announce")

    for _ in range(14):
        await cronablauf.ausgang_verbuchen(
            repos, eintrag.id, "Ins Postfach sehen", erfolgreich=True
        )
        await cronablauf.ziel_verbuchen(
            repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=True
        )

    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 0
    assert frisch.aktiv is True
    assert gemeldet == []


async def test_gescheiterter_lauf_zaehlt_nicht_als_still(repos, gemeldet):
    """It did not go and look, so it says nothing about whether the goal is
    being reported — that run belongs to the failure counter."""
    eintrag = eintrag_anlegen(repos)
    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=False
    )
    assert repos.cronjobs.holen(eintrag.id).laeufe_ohne_ruf == 0


# --- A run that reported ----------------------------------------------------


async def test_gemeldetes_ziel_wird_gestempelt(repos, gemeldet):
    eintrag = eintrag_anlegen(repos)
    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen",
        bericht="Mail von Müller: „Angebot“, 09:12", erfolgreich=True,
    )
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.ziel_erreicht_am is not None
    # Not switched off: this entry was never told to stop when it reached it.
    assert frisch.aktiv is True


async def test_gemeldetes_ziel_meldet_nicht_ein_zweites_mal(repos, gemeldet):
    """The tool announced the report at the moment it was called
    (app/tools/ziel_werkzeug.py). Announcing it again at the end of the run
    would be the same sentence twice."""
    eintrag = eintrag_anlegen(repos, deliver="announce")
    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht="Mail da", erfolgreich=True
    )
    await cronablauf.melde_wenn_faellig(repos, eintrag.id, "Ins Postfach sehen")
    assert gemeldet == []


async def test_stilllegen_schaltet_den_eintrag_ab(repos, gemeldet):
    eintrag = eintrag_anlegen(repos, ziel_stilllegen=True)
    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht="Mail da", erfolgreich=True
    )
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.aktiv is False
    assert frisch.ziel_erreicht_am is not None


async def test_ohne_stilllegen_laeuft_der_eintrag_weiter(repos, gemeldet):
    """The daily-report case: it reports on the days it finds something and
    keeps looking on the days it does not."""
    eintrag = eintrag_anlegen(repos, ziel_stilllegen=False)
    for _ in range(3):
        await cronablauf.ziel_verbuchen(
            repos, eintrag.id, "Ins Postfach sehen", bericht="Mail da", erfolgreich=True
        )
        assert repos.cronjobs.holen(eintrag.id).aktiv is True


async def test_meldung_setzt_den_stillen_zaehler_zurueck(repos, gemeldet):
    eintrag = eintrag_anlegen(repos, fehlergrenze=5)
    for _ in range(3):
        await cronablauf.ziel_verbuchen(
            repos, eintrag.id, "x", bericht=None, erfolgreich=True
        )
    assert repos.cronjobs.holen(eintrag.id).laeufe_ohne_ruf == 3

    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "x", bericht="Mail da", erfolgreich=True
    )
    assert repos.cronjobs.holen(eintrag.id).laeufe_ohne_ruf == 0


# --- The quiet count --------------------------------------------------------


async def test_zu_lange_still_meldet_einmal_und_laeuft_weiter(repos, gemeldet):
    # On 'announce': the notice is a notification like any other, and 'log'
    # keeps it in the log alone. The count itself is the same on either
    # setting.
    eintrag = eintrag_anlegen(repos, fehlergrenze=3, deliver="announce")

    for _ in range(2):
        await cronablauf.ziel_verbuchen(
            repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=True
        )
    assert gemeldet == []

    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=True
    )
    # The program saying it has heard nothing back, not the entry's own
    # report — which is why it comes even though this entry has a goal and
    # is otherwise exempt from the closing announcement.
    assert gemeldet == [("Ins Postfach sehen - no goal completion report after 3 runs", False)]

    frisch = repos.cronjobs.holen(eintrag.id)
    # Never switched off for being quiet — that was the whole decision.
    assert frisch.aktiv is True
    assert frisch.fehlversuche == 0
    # And it starts over rather than announcing on every run from here on.
    assert frisch.laeufe_ohne_ruf == 0

    for _ in range(2):
        await cronablauf.ziel_verbuchen(
            repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=True
        )
    assert len(gemeldet) == 1


async def test_wieder_einschalten_setzt_den_stillen_zaehler_zurueck(repos, gemeldet):
    eintrag = eintrag_anlegen(repos, fehlergrenze=5)
    for _ in range(3):
        await cronablauf.ziel_verbuchen(
            repos, eintrag.id, "x", bericht=None, erfolgreich=True
        )
    repos.cronjobs.aktiv_setzen(eintrag.id, False)
    wieder = repos.cronjobs.aktiv_setzen(eintrag.id, True)
    assert wieder.laeufe_ohne_ruf == 0


# --- Entries without a goal are untouched ------------------------------------


async def test_ohne_ziel_meldet_announce_weiter_nach_jedem_lauf(repos, gemeldet):
    eintrag = eintrag_anlegen(repos, ziel=None, deliver="announce")
    for _ in range(3):
        await cronablauf.ziel_verbuchen(
            repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=True
        )
        await cronablauf.melde_wenn_faellig(repos, eintrag.id, "Ins Postfach sehen")
    assert gemeldet == [("Ins Postfach sehen", True)] * 3
    assert repos.cronjobs.holen(eintrag.id).laeufe_ohne_ruf == 0


async def test_ohne_cronjob_id_passiert_nichts(repos, gemeldet):
    await cronablauf.ziel_verbuchen(repos, None, "x", bericht="Mail da", erfolgreich=True)
    assert gemeldet == []


async def test_geloeschter_eintrag_passiert_nichts(repos, gemeldet):
    await cronablauf.ziel_verbuchen(
        repos, "phantom", "x", bericht="Mail da", erfolgreich=True
    )
    assert gemeldet == []


# --- The tool ----------------------------------------------------------------


async def test_werkzeug_legt_mit_ziel_an(repos, tmp_path):
    agent_schreiben(tmp_path, "wache")
    antwort = await cronjob_werkzeug.ausfuehren(
        {
            "action": "create", "time": "*/15 * * * *", "task": "Ins Postfach sehen",
            "agent": "wache", "goal": "Eine ungelesene Mail von Müller",
            "stop_when_reached": True,
        },
        repos.cronjobs, (tmp_path,),
    )
    assert "reports only when the goal is reached and stops" in antwort
    eintrag = repos.cronjobs.auflisten()[0]
    assert eintrag.ziel == "Eine ungelesene Mail von Müller"
    assert eintrag.ziel_stilllegen is True


async def test_werkzeug_verspricht_keine_meldung_je_lauf_bei_ziel(repos, tmp_path):
    """With a goal set, ``notify`` no longer decides anything about an
    ordinary run — saying "announces on end" would promise the flood."""
    agent_schreiben(tmp_path, "wache")
    antwort = await cronjob_werkzeug.ausfuehren(
        {
            "action": "create", "time": "08:00", "task": "Los", "agent": "wache",
            "notify": True, "goal": "Mail von Müller",
        },
        repos.cronjobs, (tmp_path,),
    )
    assert "announces on end" not in antwort


async def test_werkzeug_bereinigt_das_ziel(repos, tmp_path):
    """A page the model read must not be able to plant anything invisible in
    a text that goes back into every future run's task."""
    agent_schreiben(tmp_path, "wache")
    await cronjob_werkzeug.ausfuehren(
        {
            "action": "create", "time": "08:00", "task": "Los", "agent": "wache",
            "goal": "Mail​ von‮ Müller",
        },
        repos.cronjobs, (tmp_path,),
    )
    assert repos.cronjobs.auflisten()[0].ziel == "Mail von Müller"


async def test_werkzeug_weist_stilllegen_ohne_ziel_ab(repos, tmp_path):
    with pytest.raises(cronjob_werkzeug.CronjobVerboten):
        await cronjob_werkzeug.ausfuehren(
            {
                "action": "create", "time": "08:00", "task": "Los",
                "stop_when_reached": True,
            },
            repos.cronjobs, (tmp_path,),
        )
    assert repos.cronjobs.auflisten() == []


async def test_werkzeug_nimmt_ziel_auch_bei_agent_ohne_zielwerkzeug(repos, tmp_path):
    """An agent naming ``tools: []`` used to be refused a goal — it could
    never have reported one. Turned around: the
    entry is accepted, and the run it fires is offered ``goal`` regardless
    of that list (tests/test_cronziel_nachbesserung.py). A message telling
    the user to pick a different agent was a message about wiring."""
    agent_schreiben(tmp_path, "stumm", werkzeuge="[]")
    await cronjob_werkzeug.ausfuehren(
        {
            "action": "create", "time": "08:00", "task": "Los",
            "agent": "stumm", "goal": "Mail von Müller",
        },
        repos.cronjobs, (tmp_path,),
    )
    angelegt = repos.cronjobs.auflisten()[0]
    assert angelegt.agent == "stumm"
    assert angelegt.ziel == "Mail von Müller"


async def test_werkzeug_nimmt_ziel_bei_agent_mit_zielwerkzeug_an(repos, tmp_path):
    agent_schreiben(tmp_path, "kann", werkzeuge="[goal]")
    await cronjob_werkzeug.ausfuehren(
        {
            "action": "create", "time": "08:00", "task": "Los",
            "agent": "kann", "goal": "Mail von Müller",
        },
        repos.cronjobs, (tmp_path,),
    )
    assert repos.cronjobs.auflisten()[0].ziel == "Mail von Müller"


async def test_werkzeug_setzt_ein_ziel_nachtraeglich(repos, tmp_path):
    agent_schreiben(tmp_path, "a")
    eintrag = eintrag_anlegen(repos, ziel=None)
    antwort = await cronjob_werkzeug.ausfuehren(
        {"action": "update", "id": eintrag.id, "goal": "Mail von Müller"},
        repos.cronjobs, (tmp_path,),
    )
    assert "reports only when the goal is reached" in antwort
    assert repos.cronjobs.holen(eintrag.id).ziel == "Mail von Müller"


async def test_werkzeug_nimmt_das_ziel_wieder_weg(repos, tmp_path):
    """And takes the stop-on-reached switch with it — left behind, it would
    sit on an entry nothing can ever reach a goal on."""
    eintrag = eintrag_anlegen(repos, ziel_stilllegen=True)
    antwort = await cronjob_werkzeug.ausfuehren(
        {"action": "update", "id": eintrag.id, "goal": ""},
        repos.cronjobs, (tmp_path,),
    )
    assert "goal removed" in antwort
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.ziel is None
    assert frisch.ziel_stilllegen is False


async def test_werkzeug_weist_stilllegen_beim_entfernen_des_ziels_ab(repos, tmp_path):
    eintrag = eintrag_anlegen(repos)
    with pytest.raises(cronjob_werkzeug.CronjobVerboten):
        await cronjob_werkzeug.ausfuehren(
            {
                "action": "update", "id": eintrag.id, "goal": "",
                "stop_when_reached": True,
            },
            repos.cronjobs, (tmp_path,),
        )
    assert repos.cronjobs.holen(eintrag.id).ziel is not None


async def test_werkzeug_schaltet_stilllegen_auf_bestehendem_ziel(repos, tmp_path):
    eintrag = eintrag_anlegen(repos, ziel_stilllegen=False)
    await cronjob_werkzeug.ausfuehren(
        {"action": "update", "id": eintrag.id, "stop_when_reached": True},
        repos.cronjobs, (tmp_path,),
    )
    assert repos.cronjobs.holen(eintrag.id).ziel_stilllegen is True


async def test_werkzeug_haengt_ein_ziel_auch_auf_einen_stummen_agenten_um(repos, tmp_path):
    """The same turn-around from the other side: moving an entry that has a
    goal onto an agent whose tools: list leaves ``goal`` out goes through."""
    agent_schreiben(tmp_path, "stumm", werkzeuge="[]")
    eintrag = eintrag_anlegen(repos)
    await cronjob_werkzeug.ausfuehren(
        {"action": "update", "id": eintrag.id, "agent": "stumm"},
        repos.cronjobs, (tmp_path,),
    )
    assert repos.cronjobs.holen(eintrag.id).agent == "stumm"


# --- What the interface gets to see -----------------------------------------


def test_api_liefert_ziel_stilllegen_und_stempel(client):
    repos = client.app.state.repositories
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="Ins Postfach sehen", zeitplan="*/15 * * * *",
        herkunft="chat", ziel="Mail von Müller", ziel_stilllegen=True,
    )
    repos.cronjobs.ziel_erreicht_setzen(eintrag.id, "2026-09-01T09:12:00+00:00")
    repos.cronjobs.aktiv_setzen(eintrag.id, False)

    zeile = client.get("/api/v1/cronjobs").json()[0]
    assert zeile["ziel"] == "Mail von Müller"
    assert zeile["ziel_stilllegen"] is True
    assert zeile["ziel_erreicht_am"] == "2026-09-01T09:12:00+00:00"
    assert zeile["aktiv"] is False
    # And the failure counter stayed out of it — this entry did its job.
    assert zeile["fehlversuche"] == 0


def test_api_ohne_ziel_liefert_leere_felder(client):
    repos = client.app.state.repositories
    repos.cronjobs.erstellen(
        agent="a", task="Los", zeitplan="08:00", herkunft="chat"
    )
    zeile = client.get("/api/v1/cronjobs").json()[0]
    assert zeile["ziel"] is None
    assert zeile["ziel_stilllegen"] is False
    assert zeile["ziel_erreicht_am"] is None
