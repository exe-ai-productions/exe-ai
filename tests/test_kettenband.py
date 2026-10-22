"""The band between a restart chain and the entry it continues.

One root, five symptoms. A run whose context fills up hands the rest of its
work to a fresh cron entry that carries on — and that entry did not know
where it came from. ``basisaufgabe`` holds the original TEXT, and
``herkunft='agent'`` only says that this is a chain at all; nothing pointed
back. So nothing the chain learned or reached ever got back to the entry a
person actually made:

* a ``once`` entry with a goal handed its work on and vanished without a
  word — the continuation was created as a standing entry, so the
  announcement that exists for exactly this ending never fired;
* the original went on firing after the continuation had reached the goal,
  reporting the same finding a second time on its next pass;
* and where the goal was no longer recognisable on that pass, the original
  eventually raised "no goal report in N runs" about a goal reported long
  ago;
* the note the continuation wrote stayed on the continuation, so the
  original looked at the same mails again;
* and the time on that note was the previous DUE time, which is stamped for
  a firing that was merely skipped as well.

Plus the one ending that follows the context overflow's rule: a provider
outage that writes a continuation is not a failed run.
"""

from __future__ import annotations

import pytest

from app import cronablauf, wiederversuch, zwischenstand
from app.agenten import agenten_laden
from app.api.abhaengigkeiten import STANDARD_BENUTZER
from app.api.v1.auftraege import auftrag_anstossen
from app.db.connection import jetzt_iso
from app.providers import MockProvider, Stueck, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools import cron_notiz, ziel_werkzeug
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
AUFGABE = "Ins Postfach sehen"
# The id of the run that hands the work on, where a test has no real run.
ERSTLAUF = "erstlauf"


@pytest.fixture(autouse=True)
def gemeldet(monkeypatch):
    """Announcements, collected instead of played — on this machine they
    would otherwise be real system notifications under the installed app's
    own name. Patched on the module, which is how both callers reach it.

    ``autouse`` because the damage does not depend on a test ASKING for the
    list: ten tests in this file run a chain with a goal and never named the
    fixture, so the notification really went out, under the installed app's
    name, on the machine of whoever ran the suite. A test that wants to READ
    what was announced still takes it as an argument and gets the same list
    """
    aufrufe: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich, sprache=None: aufrufe.append((text, erfolgreich)),
    )
    return aufrufe


def test_kein_test_dieser_datei_klingelt_beim_nutzer(monkeypatch):
    """The silence probe for the fixture itself: a test that never names it
    still runs with the announcement patched away. Without ``autouse`` this
    is the original function, and a chain with a goal rings on the machine
    of whoever runs the suite."""
    assert cronablauf.cronmeldung.melden.__module__ != "app.cronmeldung"


def eintrag_anlegen(repos, **felder):
    felder.setdefault("ziel", ZIEL)
    return repos.cronjobs.erstellen(
        agent="recherche", task=AUFGABE, zeitplan="*/15 * * * *",
        herkunft="chat", **felder,
    )


async def lauf_starten(client, config, cronjob_id: str | None, task: str | None = None):
    """One run of this entry, taken to its end — the same path a firing
    takes, minus the waiting. The task defaults to what a firing would
    actually hand the run, so the note and goal blocks are really in it."""
    app = client.app
    app.state.config.features.mcp = True
    app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    repos = app.state.repositories
    if task is None:
        eintrag = repos.cronjobs.holen(cronjob_id) if cronjob_id else None
        task = cronablauf.auftragstext(eintrag) if eintrag else AUFGABE
    auftrag = auftrag_anstossen(
        config=app.state.config,
        repositories=repos,
        discovery=app.state.discovery,
        generierungen=app.state.generierungen,
        registry=WerkzeugRegistry(
            [], shell_an=True, cronjobs_repo=repos.cronjobs
        ),
        agent=agenten_laden(*config.agentenverzeichnisse)["recherche"],
        task=task,
        endpoint_id=None,
        user_id=STANDARD_BENUTZER,
        sprache="de",
        cronjob_id=cronjob_id,
    )
    await _bis_beendet(repos, auftrag.id)
    return auftrag


def ueberlauf(client, handoff_text: str = HANDOFF_ZWEI_PUNKTE) -> None:
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text=handoff_text)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000


def kette_von(repos, eintrag_id: str):
    ketten = [e for e in repos.cronjobs.auflisten() if e.id != eintrag_id]
    assert len(ketten) == 1
    return ketten[0]


class ZielRuf(MockProvider):
    """Reports the goal in its first round, then finishes."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if self.durchlaeufe == 1:
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id="z1", name=ziel_werkzeug.WERKZEUG_NAME,
                        argumente={"report": BERICHT},
                    )
                ],
            )
            return
        yield Stueck("content", text="fertig")


class NotizRuf(MockProvider):
    """Writes a note in its first round, then finishes."""

    def __init__(self, *args, notiz: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.notiz = notiz

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if self.durchlaeufe == 1:
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id="n1", name=cron_notiz.WERKZEUG_NAME,
                        argumente={"note": self.notiz},
                    )
                ],
            )
            return
        yield Stueck("content", text="fertig")


# --- The band itself ---------------------------------------------------------


async def test_die_fortsetzung_kennt_ihren_ursprung(config, client):
    """The one thing everything below hangs off: the continuation names the
    entry whose work it took over."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos)
    ueberlauf(client)

    await lauf_starten(client, config, eintrag.id)

    kette = kette_von(repos, eintrag.id)
    assert zwischenstand.ist_kette(kette)
    assert kette.ursprung_id == eintrag.id


def test_eine_kette_aus_der_kette_zeigt_auf_den_echten_ursprung(repos):
    """Passed through, not re-pointed: however long the chain gets, one hop
    leads to the entry a person made. Pointing at the immediate predecessor
    would make the origin unreachable from the third link on, exactly where
    a long-running job needs it most."""
    ursprung = eintrag_anlegen(repos)
    kette = repos.cronjobs.erstellen(
        agent="recherche", task="weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe=AUFGABE, **zwischenstand.kettenfelder(ursprung, ERSTLAUF),
    )
    enkel = repos.cronjobs.erstellen(
        agent="recherche", task="weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe=AUFGABE, **zwischenstand.kettenfelder(kette, ERSTLAUF),
    )
    assert kette.ursprung_id == ursprung.id
    assert enkel.ursprung_id == ursprung.id


def test_ein_lauf_ohne_termin_ist_der_ursprung_seiner_kette(repos):
    """A job no schedule fired writes its continuation too — and the run a
    person started is then the origin, because there is no entry to name.
    The full field list this is one line of lives in
    tests/test_rueckverbindung.py, which is where the rest of it was added."""
    assert zwischenstand.kettenfelder(None, ERSTLAUF)["ursprung_id"] == ERSTLAUF


async def test_ein_handstart_und_seine_fortsetzung_sind_ein_werk(config, client):
    """Measured on a real run: a run somebody started by hand filled
    its context and handed on, and the continuation named no origin — the
    reports list showed the started run as a context overflow and the result
    on a row of its own. The continuation names the run now, and both runs
    answer with that one work."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ueberlauf(client)
    erst = await lauf_starten(client, config, None)

    (kette,) = repos.cronjobs.auflisten()
    assert zwischenstand.ist_kette(kette)
    assert kette.ursprung_id == erst.id

    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    zweit = await lauf_starten(client, config, kette.id)
    assert repos.auftraege.holen(zweit.id).zustand == "fertig"

    zeilen = {z["id"]: z for z in client.get("/api/v1/jobs").json()}
    assert zeilen[erst.id]["work_id"] == erst.id
    assert zeilen[zweit.id]["work_id"] == erst.id
    # And the entry that fired each run, which is what the cron list's dot
    # reads (frontend/src/lib/cronjobampel.svelte.js).
    assert zeilen[erst.id]["cronjob_id"] is None
    assert zeilen[zweit.id]["cronjob_id"] == kette.id


async def test_die_fortsetzung_der_fortsetzung_nennt_weiter_den_handstart(config, client):
    """One hop, always: the second handoff adopts the chain's own row and
    keeps its origin, and the link that finally finishes still belongs to
    the run a person started — never to the link before it."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ueberlauf(client)
    erst = await lauf_starten(client, config, None)
    (kette,) = repos.cronjobs.auflisten()

    zweit = await lauf_starten(client, config, kette.id)
    assert repos.auftraege.holen(zweit.id).ende_grund == "kontext_voll"
    (kette,) = repos.cronjobs.auflisten()
    assert kette.ursprung_id == erst.id

    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    dritt = await lauf_starten(client, config, kette.id)

    zeilen = {z["id"]: z["work_id"] for z in client.get("/api/v1/jobs").json()}
    assert zeilen[zweit.id] == erst.id
    assert zeilen[dritt.id] == erst.id


async def test_die_notiz_einer_handstart_kette_bleibt_an_der_kette(config, client):
    """The note tool writes to the origin as well — and the origin of a
    hand-started job is a run, not an entry. The note lands on the chain,
    and no other row is written or refused."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ueberlauf(client)
    await lauf_starten(client, config, None)
    (kette,) = repos.cronjobs.auflisten()

    provider_setzen(client, NotizRuf(mock_endpunkt("test"), notiz="bis Mail 9"))
    await lauf_starten(client, config, kette.id)

    assert repos.cronjobs.holen(kette.id).notiz == "bis Mail 9"
    assert [e.id for e in repos.cronjobs.auflisten()] == [kette.id]


# --- Symptom 1 · a one-off with a goal must not vanish -----------------------


async def test_ein_einmaliger_eintrag_meldet_auch_nach_einer_uebergabe(
    config, client, gemeldet
):
    """The heaviest of the five. A ``once`` entry with a goal overflows, the
    continuation looks and finds nothing — and before this, nobody was ever
    told: the original stayed quiet on purpose (the continuation reports for
    it), and the continuation was not a one-off, so the "ran once, goal not
    reached" branch never applied to it either."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    # On 'announce': the one-off's "goal not reached" is a
    # notification like every other. The chain inherits ``deliver``
    # (app/zwischenstand.py), so this also proves it travels.
    eintrag = eintrag_anlegen(repos, einmalig=True, deliver="announce")
    ueberlauf(client)

    await lauf_starten(client, config, eintrag.id)
    assert gemeldet == []

    kette = kette_von(repos, eintrag.id)
    assert kette.einmalig is True

    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    await lauf_starten(client, config, kette.id)

    assert gemeldet == [(f"{AUFGABE} - Einmal ausgeführt; Ziel nicht erreicht.", False)]


async def test_die_fortsetzung_findet_das_ziel_und_meldet_genau_einmal(
    config, client, gemeldet
):
    """The counter-check to the one above: the continuation of the very same
    one-off DOES find it. One announcement, and it carries the finding —
    not a "not reached" behind it."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    # On 'announce': the goal tool's report passes the same gate as every
    # other notification (app/cronablauf.mitteilen), so on the
    # default 'log' the single announcement below would be the gate's answer
    # rather than this test's. It travels down the chain with the rest
    # (``kettenfelder``), which is why the continuation can announce at all.
    eintrag = eintrag_anlegen(repos, einmalig=True, deliver="announce")
    ueberlauf(client)
    await lauf_starten(client, config, eintrag.id)
    kette = kette_von(repos, eintrag.id)

    provider_setzen(client, ZielRuf(mock_endpunkt("test")))
    await lauf_starten(client, config, kette.id)

    assert gemeldet == [(BERICHT, True)]
    assert repos.cronjobs.holen(eintrag.id).ziel_erreicht_am is not None


async def test_ein_einmaliger_eintrag_ohne_ziel_bleibt_wie_er_war(config, client):
    """The one-off flag travels with the goal, not instead of it: an entry
    without a goal never reaches the announcement at all, and its
    continuation is still a plain entry that runs when it is due."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, ziel=None, einmalig=True)
    ueberlauf(client)

    await lauf_starten(client, config, eintrag.id)

    kette = kette_von(repos, eintrag.id)
    assert kette.einmalig is True
    assert kette.ziel is None
    # The day of the original one-off is deliberately NOT inherited: it has
    # already been and gone, and pinned to it the continuation would never
    # be due again.
    assert kette.datum is None


async def test_die_kette_wird_fuer_ihre_naechste_uebergabe_wieder_scharf(
    config, client
):
    """A continuation that inherited ``einmalig`` switches itself off the
    moment it fires. Its own next handoff writes into that same row, so it
    has to be armed again in the same breath — otherwise the work is handed
    to an entry that can never run, which is the silent ending all over
    again, one link further down."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, einmalig=True)
    ueberlauf(client)
    await lauf_starten(client, config, eintrag.id)
    kette = kette_von(repos, eintrag.id)
    repos.cronjobs.aktiv_setzen(kette.id, False)  # what firing it does

    await lauf_starten(client, config, kette.id)

    frisch = repos.cronjobs.holen(kette.id)
    assert frisch.aktiv is True
    assert frisch.neustarts == 2


# --- Symptom 2 · the origin is laid to rest ---------------------------------


async def test_der_ursprung_wird_still_wenn_die_kette_das_ziel_meldet(
    config, client, gemeldet
):
    """"Stop when reached" is a promise about the entry a person made. The
    continuation reached it — so that entry is done, and must not go on
    firing and report the same finding a second time."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    # On 'announce', same reason as above — and here it carries the second
    # half of the check too: the origin must not report the same finding a
    # SECOND time, which an entry set to 'log' could not have shown.
    eintrag = eintrag_anlegen(repos, ziel_stilllegen=True, deliver="announce")
    ueberlauf(client)
    await lauf_starten(client, config, eintrag.id)
    kette = kette_von(repos, eintrag.id)
    assert repos.cronjobs.holen(eintrag.id).aktiv is True

    provider_setzen(client, ZielRuf(mock_endpunkt("test")))
    await lauf_starten(client, config, kette.id)

    ursprung = repos.cronjobs.holen(eintrag.id)
    assert ursprung.aktiv is False
    assert ursprung.ziel_erreicht_am is not None
    # One finding, one announcement — the tool's own, at the moment it was
    # called.
    assert gemeldet == [(BERICHT, True)]


async def test_ein_ursprung_auf_weiterlaufen_laeuft_weiter(config, client, gemeldet):
    """The counter-check, and the other half of the same per-entry wish: a
    daily report is not finished just because today's edition was found."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, ziel_stilllegen=False, deliver="announce")
    ueberlauf(client)
    await lauf_starten(client, config, eintrag.id)
    kette = kette_von(repos, eintrag.id)

    provider_setzen(client, ZielRuf(mock_endpunkt("test")))
    await lauf_starten(client, config, kette.id)

    ursprung = repos.cronjobs.holen(eintrag.id)
    assert ursprung.aktiv is True
    assert ursprung.ziel_erreicht_am is not None
    # ``ZielRuf`` really reports, so the goal tool really announces. Taking
    # the fixture is what keeps that off the machine's own notification
    # centre; on 'announce' the assertion is about the report rather than
    # about ``deliver``.
    assert gemeldet == [(BERICHT, True)]


# --- Symptom 3 · no false alarm about a goal already reported ----------------


async def test_der_stille_zaehler_des_ursprungs_faellt_auf_null(config, client, gemeldet):
    """The quiet count is the insurance against a model that forgot the
    call. A handed-off run counts as quiet, so an entry that overflows often
    creeps toward its limit — and when the continuation then reports, the
    count has to be answered, or "no goal report in N runs" eventually goes
    out about a goal that was reported long ago."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, ziel_stilllegen=False, deliver="announce")
    ueberlauf(client)
    await lauf_starten(client, config, eintrag.id)
    assert repos.cronjobs.holen(eintrag.id).laeufe_ohne_ruf == 1
    kette = kette_von(repos, eintrag.id)

    provider_setzen(client, ZielRuf(mock_endpunkt("test")))
    await lauf_starten(client, config, kette.id)

    assert repos.cronjobs.holen(eintrag.id).laeufe_ohne_ruf == 0
    # The report that answers the count — once, and caught rather than
    # played, for the reason above.
    assert gemeldet == [(BERICHT, True)]


# --- Symptom 4 · the note belongs to the original job ------------------------


async def test_die_notiz_der_kette_landet_auch_am_ursprung(config, client):
    """The continuation works through mails 6 to 9 and notes "up to 9". The
    original is what keeps running — and used to fire again still holding
    "up to 5", look at the same four mails, and report them a second time."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, ziel=None)
    repos.cronjobs.notiz_setzen(eintrag.id, "zuletzt gesehen: Mail 5")
    ueberlauf(client)
    await lauf_starten(client, config, eintrag.id)
    kette = kette_von(repos, eintrag.id)

    provider_setzen(client, NotizRuf(mock_endpunkt("test"), notiz="bis Mail 9"))
    await lauf_starten(client, config, kette.id)

    assert repos.cronjobs.holen(kette.id).notiz == "bis Mail 9"
    assert repos.cronjobs.holen(eintrag.id).notiz == "bis Mail 9"


def test_eine_notiz_ohne_ursprung_bleibt_wo_sie_ist(repos):
    """The counter-check: an ordinary entry writes to itself and nowhere
    else — no second row is touched because there is none."""
    eintrag = eintrag_anlegen(repos, ziel=None)
    fremd = eintrag_anlegen(repos, ziel=None)
    repos.cronjobs.notiz_setzen(eintrag.id, "Mail 5")
    assert repos.cronjobs.holen(fremd.id).notiz is None


async def test_der_notizblock_steht_genau_einmal(config, client):
    """The second half of the same symptom. A firing glues the note onto the
    task before handing it to the run; taking THAT text as the chain's
    original task bakes the note in — and once the chain has a note of its
    own, its firing appends a second block, with the older one still sitting
    inside the "Original task:" line."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, ziel=None)
    repos.cronjobs.notiz_setzen(eintrag.id, "zuletzt gesehen: Mail 5")
    ueberlauf(client)

    await lauf_starten(client, config, eintrag.id)

    kette = kette_von(repos, eintrag.id)
    assert kette.basisaufgabe == AUFGABE
    assert "zuletzt gesehen: Mail 5" not in kette.task
    repos.cronjobs.notiz_setzen(kette.id, "bis Mail 9")
    text = cronablauf.auftragstext(repos.cronjobs.holen(kette.id))
    assert text.count("Your note from the previous run") == 1
    assert "zuletzt gesehen: Mail 5" not in text


# --- Symptom 5 · the time on the note is when it was written ----------------


def test_der_zeitstempel_der_notiz_ist_der_schreibzeitpunkt(repos):
    """A due time is stamped even when the firing was SKIPPED because a run
    was still going — and that skip lands after the note was written by the
    run that was still going. Everything in between would count as seen and
    never be reported by anyone."""
    eintrag = eintrag_anlegen(repos, ziel=None)
    repos.cronjobs.notiz_setzen(eintrag.id, "zuletzt gesehen: Mail 5")
    geschrieben = repos.cronjobs.holen(eintrag.id).notiz_am
    # The 10:15 firing, skipped because the 10:00 run was still going.
    repos.cronjobs.ausgeloest_setzen(eintrag.id, jetzt_iso())

    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.notiz_am == geschrieben
    assert frisch.zuletzt_ausgeloest > geschrieben
    text = cronablauf.auftragstext(frisch)
    assert geschrieben in text
    assert frisch.zuletzt_ausgeloest not in text


def test_eine_geloeschte_notiz_nimmt_ihren_zeitstempel_mit(repos):
    """Cleared means cleared — a time left behind would sit on an entry with
    nothing to put it on."""
    eintrag = eintrag_anlegen(repos, ziel=None)
    repos.cronjobs.notiz_setzen(eintrag.id, "Mail 5")
    repos.cronjobs.notiz_setzen(eintrag.id, None)
    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.notiz is None
    assert frisch.notiz_am is None


# --- The provider outage, by the context overflow's rule ---------------------


async def test_ein_anbieterausfall_mit_fortsetzung_zaehlt_nicht(
    config, client, monkeypatch
):
    """Same rule as the context overflow's, same reason: this run could not
    reach the model, but it wrote down where it stood and put the rest on
    the clock. Counted, the failure limit switches off the very entry the
    continuation was written into a second earlier."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, ziel=None, fehlergrenze=1)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="kaputt"))

    auftrag = await lauf_starten(client, config, eintrag.id)
    assert repos.auftraege.holen(auftrag.id).ende_grund == "anbieter_ausfall"

    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.fehlversuche == 0
    assert frisch.aktiv is True
    assert kette_von(repos, eintrag.id).ursprung_id == eintrag.id


async def test_eine_ausfallkette_stirbt_nicht_an_der_fehlergrenze(
    config, client, monkeypatch
):
    """Read out of the code before it was measured: an outage on an entry
    that is ITSELF a chain updates that same row and then counted a failure
    on it — so the chain died at ``fehlergrenze`` (5) instead of at the
    restart ceiling (10) that governs it."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    repos = client.app.state.repositories
    kette = eintrag_anlegen(repos, ziel=None, basisaufgabe=AUFGABE, fehlergrenze=2)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="kaputt"))

    for _ in range(4):
        await lauf_starten(client, config, kette.id)

    frisch = repos.cronjobs.holen(kette.id)
    assert frisch.fehlversuche == 0
    assert frisch.aktiv is True
    assert frisch.neustarts == 4


# --- The counter-check that costs nothing ------------------------------------


async def test_ein_eintrag_ohne_ziel_und_ohne_notiz_bleibt_unveraendert(
    config, client, gemeldet
):
    """Nothing above may show up on an entry that uses none of it: the task
    text is the task text, no extra block, no blank line, and a plain
    'announce' still announces after every run exactly as before."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    eintrag = eintrag_anlegen(repos, ziel=None, deliver="announce")
    assert cronablauf.auftragstext(eintrag) == AUFGABE

    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    await lauf_starten(client, config, eintrag.id)

    frisch = repos.cronjobs.holen(eintrag.id)
    assert frisch.ursprung_id is None
    assert frisch.notiz is None
    assert frisch.notiz_am is None
    assert frisch.fehlversuche == 0
    assert frisch.laeufe_ohne_ruf == 0
    assert frisch.aktiv is True
    assert gemeldet == [(AUFGABE, True)]
