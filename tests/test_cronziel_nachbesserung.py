"""Four holes in the goal of a cron entry.

Each section is one of them, and each one is a case where the entry did
exactly what it was told and the user still heard nothing:

* **A goal brings its own tool** — a goal on an agent whose own ``tools:``
  leaves ``goal`` out was refused at creation time. Turned around: the tool
  is put into the run regardless, because the entry IS the instruction to
  report.
* **One report per run** — the tool announced on every call, so a model
  calling it three times set off three notifications for one finding. And a
  run that reported its goal and then walked into the round limit was
  booked as a failed run on top of it.
* **A one-off entry always says something** — a ``once`` entry with a goal
  fired once, stayed quiet, and was deactivated. The one message it existed
  for never came, and neither did a "nothing found": the order simply
  vanished.
* **The goal survives the handoff** — a run that overflowed handed its work
  to a continuation entry that carried no goal at all. The continuation
  found the thing, announced it (the tool does that itself), and then
  stamped nothing and switched nothing off.
"""

from __future__ import annotations

import pytest

from app import cronablauf, zwischenstand
from app.agenten import agenten_laden
from app.api.abhaengigkeiten import STANDARD_BENUTZER
from app.api.v1.auftraege import auftrag_anstossen
from app.providers import MockProvider, Stueck, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools import ziel_werkzeug
from app.tools.registry import WerkzeugRegistry
from tests.conftest import provider_setzen
from tests.test_auftraege_api import (
    HANDOFF_ZWEI_PUNKTE,
    NahezuVollerKontext,
    _bis_beendet,
    agent_schreiben,
)

ZIEL = "Eine ungelesene Mail von Müller im Posteingang"
BERICHT = "Mail von Müller: Betreff 'Angebot', 09:12 im Posteingang"


@pytest.fixture
def gemeldet(monkeypatch):
    """Announcements, collected instead of played. Patched on the module
    itself, so the tool's own announcement is caught as well as the end of
    the run's — they are the same function."""
    aufrufe: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich, sprache=None: aufrufe.append((text, erfolgreich)),
    )
    return aufrufe


def eintrag_anlegen(repos, **felder):
    felder.setdefault("ziel", ZIEL)
    return repos.cronjobs.erstellen(
        agent="a", task="Ins Postfach sehen", zeitplan="*/15 * * * *",
        herkunft="chat", **felder,
    )


def _namen(registry, **kwargs) -> list[str]:
    return sorted(w["function"]["name"] for w in registry.als_openai_werkzeuge(**kwargs))


async def lauf_starten(client, config, cronjob_id: str | None, task: str = "Los"):
    """One run, taken to its end — the same route a firing takes, minus the
    waiting. The registry is built here rather than taken from the app: the
    test service starts with ``features.mcp`` off, so ``app.state.werkzeuge``
    is None and a run started off it would be offered nothing at all."""
    app = client.app
    app.state.config.features.mcp = True
    # In the shipped test configuration the mock endpoint cannot do tool
    # calls, and a run whose endpoint cannot is offered no tools at all —
    # which would make every list below read "keine" for the wrong reason.
    app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    auftrag = auftrag_anstossen(
        config=app.state.config,
        repositories=app.state.repositories,
        discovery=app.state.discovery,
        generierungen=app.state.generierungen,
        registry=WerkzeugRegistry(
            [], shell_an=True, cronjobs_repo=app.state.repositories.cronjobs
        ),
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=task,
        endpoint_id=None,
        user_id=STANDARD_BENUTZER,
        sprache="de",
        cronjob_id=cronjob_id,
    )
    await _bis_beendet(app.state.repositories, auftrag.id)
    return auftrag


def _angebotene(repos, auftrag_id: str) -> list[str]:
    return [
        schritt.inhalt
        for schritt in repos.auftraege.schritte(auftrag_id)
        if schritt.inhalt.startswith("Werkzeuge angeboten")
    ]


# --- A goal brings its own tool ----------------------------------------------


async def test_ein_ziel_leiht_dem_lauf_das_werkzeug(config, client):
    """The case the old refusal was written for: an agent naming
    ``tools: []``. Its run now gets exactly one tool — the one its entry
    needs — and the run's own log line names it."""
    agent_schreiben(config, kopf="model: test\ntools: []")
    repos = client.app.state.repositories
    eintrag = repos.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat", ziel=ZIEL,
    )
    provider_setzen(client, MockProvider(mock_endpunkt("test")))

    auftrag = await lauf_starten(client, config, eintrag.id)
    # The clock rides along in every run that has tools, the same widening
    # the shelf gets (app/api/v1/auftraege.py) — the lent tool is what this
    # test is about, and it is there.
    assert _angebotene(repos, auftrag.id) == [
        f"Werkzeuge angeboten: get_current_time, {ziel_werkzeug.WERKZEUG_NAME}"
    ]


async def test_ein_ziel_bringt_nichts_ausser_goal_dazu(config, client):
    """The lending is one tool wide. Anything else would be a schedule
    quietly handing an agent rights its own file does not give it."""
    agent_schreiben(config, kopf="model: test\ntools: [read_file, write_file]")
    repos = client.app.state.repositories
    ohne = repos.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat",
    )
    mit = repos.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat", ziel=ZIEL,
    )
    provider_setzen(client, MockProvider(mock_endpunkt("test")))

    a = await lauf_starten(client, config, ohne.id)
    b = await lauf_starten(client, config, mit.id)
    # The difference between the two runs is exactly the lent tool. The
    # clock is in both — it stands in every run with tools, not because a
    # schedule lent it (app/api/v1/auftraege.py, app/tools/uhr.py).
    assert _angebotene(repos, a.id) == [
        "Werkzeuge angeboten: get_current_time, read_file, write_file"
    ]
    assert _angebotene(repos, b.id) == [
        "Werkzeuge angeboten: get_current_time, goal, read_file, write_file"
    ]


def test_ohne_ziel_gilt_die_liste_des_agenten_wie_bisher():
    """The registry itself is untouched: the allowlist still decides, and
    ``goal`` is in it only when the run put it there."""
    registry = WerkzeugRegistry([], shell_an=True)
    assert ziel_werkzeug.WERKZEUG_NAME not in _namen(registry, nur={"read_file"})
    assert ziel_werkzeug.WERKZEUG_NAME in _namen(
        registry, nur={"read_file", ziel_werkzeug.WERKZEUG_NAME}
    )


def test_ein_abgeschaltetes_goal_bleibt_abgeschaltet():
    """The one thing a lent tool does not outrank: the switch in the tools
    window. That is a decision about the program, not about one schedule —
    and it is the hole this round deliberately leaves open, because a
    warning about it would be another message where a fix belongs."""
    registry = WerkzeugRegistry([], shell_an=True)
    registry.abgeschaltet = {ziel_werkzeug.WERKZEUG_NAME}
    assert _namen(registry, nur={ziel_werkzeug.WERKZEUG_NAME}) == []


async def test_ein_lauf_ohne_ziel_bekommt_bei_leerer_liste_gar_nichts(config, client):
    """The counter-check on the same agent and the same entry: no goal, no
    tools — unchanged from before any of this existed."""
    agent_schreiben(config, kopf="model: test\ntools: []")
    repos = client.app.state.repositories
    eintrag = repos.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat",
    )
    provider_setzen(client, MockProvider(mock_endpunkt("test")))

    auftrag = await lauf_starten(client, config, eintrag.id)
    assert _angebotene(repos, auftrag.id) == ["Werkzeuge angeboten: keine"]


# --- One report per run ------------------------------------------------------


async def test_ein_zweiter_zielruf_meldet_nichts(gemeldet):
    """Refused rather than swallowed: the model is told nothing went out,
    so it does not go on believing it reported twice."""
    with pytest.raises(ziel_werkzeug.ZielVerboten) as fehler:
        await ziel_werkzeug.ausfuehren({"report": BERICHT}, schon_gemeldet=True)
    assert "already" in str(fehler.value)
    assert gemeldet == []


async def test_der_erste_zielruf_meldet_normal(gemeldet):
    await ziel_werkzeug.ausfuehren({"report": BERICHT})
    assert gemeldet == [(BERICHT, True)]


class DreiZielrufe(MockProvider):
    """A model that reports the same finding three times in one round."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if self.durchlaeufe == 1:
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"z{nummer}", name=ziel_werkzeug.WERKZEUG_NAME,
                        argumente={"report": f"{BERICHT} ({nummer})"},
                    )
                    for nummer in (1, 2, 3)
                ],
            )
            return
        yield Stueck("content", text="fertig")


async def test_drei_zielrufe_ergeben_genau_eine_meldung(config, client, gemeldet):
    """``tools: []`` on purpose: the call has to get past the execution gate
    too (app/berechtigungen.py, Hole B), which reads the very same list the
    offered tools come from. Widening only the offered list is not enough:
    every `goal` call is then refused at call time."""
    agent_schreiben(config, kopf="model: test\ntools: []")
    repos = client.app.state.repositories
    # On 'announce': the goal tool's own report passes the same gate as the
    # other six notifications (app/cronablauf.mitteilen), so on the default
    # 'log' nothing would reach the announcing module at all and the single
    # entry below would be the gate's answer rather than this test's. What
    # is measured is three calls, one announcement, and the FIRST report
    # being the one that got booked.
    eintrag = repos.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat",
        ziel=ZIEL, ziel_stilllegen=True, deliver="announce",
    )
    provider_setzen(client, DreiZielrufe(mock_endpunkt("test")))

    await lauf_starten(client, config, eintrag.id)

    assert gemeldet == [(f"{BERICHT} (1)", True)]
    # And the FIRST report is the one that got booked — not the last.
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.ziel_erreicht_am is not None
    assert frisch.aktiv is False


class ZielDannWeiter(MockProvider):
    """Reports the goal, then keeps asking for tools — a model that does not
    stop after its own report and runs into the round limit."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        name = ziel_werkzeug.WERKZEUG_NAME if self.durchlaeufe == 1 else "addieren"
        argumente = {"report": BERICHT} if self.durchlaeufe == 1 else {"a": 1, "b": 2}
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(id=f"w{self.durchlaeufe}", name=name, argumente=argumente)
            ],
        )


async def test_ein_gemeldetes_ziel_zaehlt_keinen_fehlversuch(config, client, gemeldet):
    """A run can report and then walk into the round limit, which ends it
    'gescheitert'. Counted, the entry was switched off with "stopped after
    N failed runs" in the same breath as the finding it exists for — and
    with ``stop_when_reached`` switched off twice over, once as finished and
    once as broken."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 1")
    repos = client.app.state.repositories
    # On 'announce', same reason as above: the point of the last line is that
    # the finding is the ONLY thing said — no "stopped after 1 failed runs"
    # next to it. On 'log' both would be silent and the assertion would pass
    # without ever having looked.
    eintrag = repos.cronjobs.erstellen(
        agent="recherche", task="Ins Postfach sehen", zeitplan="*/15 * * * *",
        herkunft="chat", ziel=ZIEL, ziel_stilllegen=True, fehlergrenze=1,
        deliver="announce",
    )
    provider_setzen(client, ZielDannWeiter(mock_endpunkt("test")))

    auftrag = await lauf_starten(client, config, eintrag.id)
    beendet = repos.auftraege.holen(auftrag.id)
    assert beendet.zustand == "gescheitert"
    assert beendet.ende_grund == "rundengrenze"

    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 0
    assert frisch.ziel_erreicht_am is not None
    # Switched off once, as finished — and the only thing said is the
    # finding itself.
    assert frisch.aktiv is False
    assert gemeldet == [(BERICHT, True)]


# --- A one-off entry always says something -----------------------------------


async def test_einmaliger_eintrag_ohne_meldung_sagt_es(repos, gemeldet):
    """The worst ending a goal entry could have: one run, nothing found,
    entry deactivated at firing time, and not a word to anybody."""
    # On 'announce': this sentence is a notification like every other, and
    # an entry on 'log' hears it in the log. What the test is about is that
    # a one-off never ends without a word, and the log line is written
    # either way.
    eintrag = eintrag_anlegen(repos, einmalig=True, deliver="announce")
    repos.cronjobs.aktiv_setzen(eintrag.id, False)  # a fired one-off

    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=True
    )
    assert gemeldet == [
        ("Ins Postfach sehen — Ran once; goal not reached.", False)
    ]


async def test_einmaliger_eintrag_sagt_es_auch_nach_einem_fehlschlag(repos, gemeldet):
    """"Always something" means always — a run that broke off found nothing
    either, and this entry has no second chance to find it."""
    eintrag = eintrag_anlegen(repos, einmalig=True, deliver="announce")
    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=False
    )
    assert len(gemeldet) == 1
    assert "Ran once; goal not reached." in gemeldet[0][0]


async def test_einmaliger_eintrag_mit_meldung_sagt_nichts_zusaetzlich(repos, gemeldet):
    """The goal was reported — the tool already said it, with the finding
    in it. A "not reached" behind that would contradict it."""
    # On 'announce': on the default 'log' nothing reaches the announcing
    # module at all (``_mitteilen``), so the empty list was the
    # gate's answer rather than this branch's — the "not reached" sentence
    # could have come right behind the report and the test would not have
    # seen it.
    eintrag = eintrag_anlegen(
        repos, einmalig=True, ziel_stilllegen=True, deliver="announce"
    )
    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht=BERICHT, erfolgreich=True
    )
    assert gemeldet == []
    assert repos.cronjobs.holen(eintrag.id).ziel_erreicht_am is not None


async def test_einmaliger_eintrag_sagt_nichts_doppelt(repos, gemeldet):
    """The failure limit already announced this very ending. Two
    notifications about one run is the flood, not the fix."""
    # On 'announce', same reason as the two above: on the default 'log' the
    # gate (``_mitteilen``) swallows every notification, so the
    # empty list said nothing about ``schon_gemeldet`` — the second sentence
    # could have gone out and this test would not have seen it.
    eintrag = eintrag_anlegen(repos, einmalig=True, deliver="announce")
    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=False,
        schon_gemeldet=True,
    )
    assert gemeldet == []


async def test_einmaliger_eintrag_schweigt_solange_die_fortsetzung_laeuft(repos, gemeldet):
    """A handed-off run is not the end of the order — the continuation is
    on the clock and reports for it."""
    # On 'announce' for the same reason: the silence has to be this
    # branch's own (``fortsetzung_geplant``), not the gate's.
    eintrag = eintrag_anlegen(repos, einmalig=True, deliver="announce")
    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=False,
        fortsetzung_geplant=True,
    )
    assert gemeldet == []


async def test_wiederkehrender_eintrag_bleibt_still(repos, gemeldet):
    """The counter-check, and the whole point of a goal: a standing watch
    that found nothing says nothing at all."""
    # On 'announce', for the reason above: on 'log' this entry could not
    # have said anything whatever the code did.
    eintrag = eintrag_anlegen(repos, deliver="announce")
    await cronablauf.ziel_verbuchen(
        repos, eintrag.id, "Ins Postfach sehen", bericht=None, erfolgreich=True
    )
    assert gemeldet == []
    assert repos.cronjobs.holen(eintrag.id).laeufe_ohne_ruf == 1


# --- The goal survives the handoff -------------------------------------------


def _ueberlauf(client, handoff_text: str = HANDOFF_ZWEI_PUNKTE) -> None:
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text=handoff_text)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000


async def test_die_fortsetzung_erbt_das_ziel(config, client):
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = repos.cronjobs.erstellen(
        agent="recherche", task="Ins Postfach sehen", zeitplan="*/15 * * * *",
        herkunft="chat", ziel=ZIEL, ziel_stilllegen=True,
    )
    _ueberlauf(client)

    auftrag = await lauf_starten(
        client, config, eintrag.id, task=cronablauf.auftragstext(eintrag)
    )
    assert repos.auftraege.holen(auftrag.id).ende_grund == "kontext_voll"

    ketten = [e for e in repos.cronjobs.auflisten() if e.id != eintrag.id]
    assert len(ketten) == 1
    kette = ketten[0]
    assert zwischenstand.ist_kette(kette)
    assert kette.ziel == ZIEL
    assert kette.ziel_stilllegen is True
    # And the goal instruction sits in the continuation's own task exactly
    # once: the entry carries it now, and every firing appends it.
    assert kette.basisaufgabe == "Ins Postfach sehen"
    assert cronablauf.auftragstext(kette).count("Call the goal tool") == 1


async def test_ein_uebergabelauf_zaehlt_als_stiller_lauf(config, client):
    """The insurance against a model that forgot the call counts runs that
    ended without a report. An overflowing run reported nothing either —
    and used to count neither as quiet nor as failed, so on that path the
    insurance never fired at all."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = repos.cronjobs.erstellen(
        agent="recherche", task="Ins Postfach sehen", zeitplan="*/15 * * * *",
        herkunft="chat", ziel=ZIEL,
    )
    _ueberlauf(client)

    await lauf_starten(
        client, config, eintrag.id, task=cronablauf.auftragstext(eintrag)
    )

    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.laeufe_ohne_ruf == 1
    assert frisch.fehlversuche == 0
    assert frisch.aktiv is True


def test_ohne_ziel_bleibt_die_basisaufgabe_der_lauftext(repos):
    """The counter-check on the one thing ``urspruengliche_aufgabe`` had to
    change: an entry without a goal answers exactly as before."""
    eintrag = eintrag_anlegen(repos, ziel=None)
    assert zwischenstand.urspruengliche_aufgabe(eintrag, "Lauftext") == "Lauftext"
    assert zwischenstand.urspruengliche_aufgabe(None, "Lauftext") == "Lauftext"
    assert zwischenstand.zielfelder(eintrag) == {"ziel": None, "ziel_stilllegen": False}


def test_eine_bestehende_kette_behaelt_ihre_basisaufgabe(repos):
    """Carried once and never re-derived — the rule this helper existed for
    before a goal was ever involved."""
    eintrag = eintrag_anlegen(repos, ziel=None, basisaufgabe="Ordner aufräumen")
    assert (
        zwischenstand.urspruengliche_aufgabe(eintrag, "Lauftext") == "Ordner aufräumen"
    )
