"""What the band between a chain and its origin still let fall through.

The band itself is built (``ursprung_id``): what a chain reaches, notes and
reports gets back to the entry a person made. These are the three holes that
opened up behind it, and all three end the same way — in silence.

* A permanently dead model server was never announced again at all. Every
  run of the origin hands its work on, so the origin never counts a failed
  run; the chain dies at the restart ceiling, switched off a moment before
  the failure counter could speak, and the origin opens a fresh one
  tomorrow. The user waits for a mail and is never told anything.
* The note travelled backward only. A fresh continuation opened with an
  empty memory and reported the same mails again — worst at a provider
  outage, where the handoff text is nothing but "the model server was
  unreachable" and carries no state at all.
* ``fehlergrenze`` was not inherited, so a chain answered to the default of
  5 whatever the person had set.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest

from app import cronablauf, cronmeldung, wiederversuch, zwischenstand
from app.db.models import Cronjob
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen
from tests.test_auftraege_api import agent_schreiben
from tests.test_kettenband import (
    AUFGABE,
    ERSTLAUF,
    ZIEL,
    eintrag_anlegen,
    gemeldet,  # noqa: F401 — fixture, used by name
    kette_von,
    lauf_starten,
    ueberlauf,
)

NOTIZ = "zuletzt gesehen: Mail 5"
NOTIZ_AM = "2026-09-01T06:00:00.000000+00:00"


async def _until(condition, seconds: float = 5.0) -> None:
    """Waits for what a run still does on its way out. An announcement
    leaves on a worker thread (``cronablauf.mitteilen``), a moment after
    the run's row reads as ended; reading the list at once asks the
    system which of the two threads it ran first."""
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


@pytest.fixture
def kaputter_anbieter(client, monkeypatch):
    """A model server that is simply gone, and no waiting between the
    retries — the outage is the subject here, its backoff is not."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="kaputt"))


@pytest.fixture
def deckel_bei_zwei(monkeypatch):
    """The restart ceiling, moved down to two: the origin's own run is the
    first restart, the chain's single run the second and last. The same
    three steps a real outage takes — hand on, run out of restarts, end —
    without ten identical rounds in between."""
    monkeypatch.setattr(zwischenstand, "MAX_NEUSTARTS", 2)


# --- A permanently dead provider has to become audible --------------


async def test_die_ausfallkette_bucht_ihr_ende_auf_den_ursprung(
    config, client, gemeldet, kaputter_anbieter, deckel_bei_zwei
):
    """One dead day costs the origin exactly one failed run — the chain's
    last, the one that ran out of restarts with nothing behind it. The
    handed-on runs before it still cost nothing, which is the rule that
    stays."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None, fehlergrenze=3, deliver="announce")

    await lauf_starten(client, config, ursprung.id)
    kette = kette_von(repos, ursprung.id)
    # The handoff itself: not a failed run, on neither row.
    assert repos.cronjobs.holen(ursprung.id).fehlversuche == 0

    await lauf_starten(client, config, kette.id)

    assert repos.cronjobs.holen(kette.id).aktiv is False
    assert repos.cronjobs.holen(ursprung.id).fehlversuche == 1
    assert repos.cronjobs.holen(ursprung.id).aktiv is True
    # On 'announce': on the default 'log' nothing reaches the
    # announcing module at all (``_mitteilen``), so an empty list here proved
    # nothing — the origin could have said "stopped after 1 failed runs" at
    # one of three and the test would still have been green. What really goes
    # out is the chain's OWN ending and nothing else: it ran out of restarts
    # with nothing behind it, which is a real ending and rightly announces
    # (``melde_wenn_faellig``). The origin, one failed run into three, is
    # silent — and that is the sentence this list pins down.
    await _until(lambda: gemeldet)
    assert gemeldet == [(cronmeldung.mit_grund(AUFGABE, "anbieter_ausfall"), False)]


async def test_ein_dauerhaft_toter_anbieter_wird_genau_einmal_gemeldet(
    config, client, gemeldet, kaputter_anbieter, deckel_bei_zwei
):
    """The whole point. The origin is the only row that sees the same thing
    happen again the next day — the chains are new rows every time — so it
    is the one that reaches its limit, says so once, and stops. Once: it is
    switched off in the same breath, so there is no second day to announce
    on."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    # On 'announce': an entry on 'log' gets the limit's sentence in the log
    # alone. The booking itself is the same on either setting.
    ursprung = eintrag_anlegen(
        repos, ziel=None, fehlergrenze=2, deliver="announce"
    )

    for _ in range(2):  # two dead days
        await lauf_starten(client, config, ursprung.id)
        await lauf_starten(client, config, kette_von_neuester(repos, ursprung.id))

    frisch = repos.cronjobs.holen(ursprung.id)
    assert frisch.fehlversuche == 2
    assert frisch.aktiv is False
    # The limit's own sentence, once. Filtered rather than listed whole,
    # because on 'announce' a chain that ran out of restarts is a real
    # ending with nothing behind it and rightly announces its own — that is
    # what ``melde_wenn_faellig`` says it does, and it is not what this test
    # is about.
    await _until(lambda: any("stopped after" in t for t, _ in gemeldet))
    assert [t for t, _ in gemeldet if "stopped after" in t] == [
        f"{AUFGABE} — stopped after 2 failed runs"
    ]


async def test_der_ursprung_meldet_nicht_noch_einmal(
    config, client, gemeldet, kaputter_anbieter, deckel_bei_zwei
):
    """No daily repeat. Even fired again by hand after it gave up, a
    switched-off origin says nothing a second time — the ``aktiv`` check is
    what makes "once" mean once."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    # On 'announce': an entry on 'log' gets the limit's sentence in the log
    # alone. The booking itself is the same on either setting.
    ursprung = eintrag_anlegen(
        repos, ziel=None, fehlergrenze=1, deliver="announce"
    )

    def grenzsaetze():
        # As above: the chain's own ending is not what "once" is about here.
        return [t for t, _ in gemeldet if "stopped after" in t]

    await lauf_starten(client, config, ursprung.id)
    await lauf_starten(client, config, kette_von_neuester(repos, ursprung.id))
    assert len(grenzsaetze()) == 1

    await lauf_starten(client, config, ursprung.id)
    await lauf_starten(client, config, kette_von_neuester(repos, ursprung.id))

    assert len(grenzsaetze()) == 1


async def test_ein_ausfall_der_zurueckkommt_meldet_nichts(
    config, client, gemeldet, monkeypatch
):
    """The counter-check that has to cost nothing: the provider drops out
    once and comes back. The continuation gets through, and a run that got
    through is what puts the origin's count back to zero — from the chain
    just as much as from the origin's own next run."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None, fehlergrenze=1, deliver="announce")
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="kaputt"))

    await lauf_starten(client, config, ursprung.id)
    kette = kette_von(repos, ursprung.id)

    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    await lauf_starten(client, config, kette.id)

    # On 'announce': on 'log' the empty list would be the gate's answer, not
    # this booking's — the limit could have fired at one of one and nothing
    # would have shown it. What goes out is the continuation's closing
    # notification, the one piece of work saying its piece once — and NOT a
    # "stopped after" behind it.
    assert gemeldet == [(AUFGABE, True)]
    frisch = repos.cronjobs.holen(ursprung.id)
    assert frisch.aktiv is True
    assert frisch.fehlversuche == 0


async def test_ein_erfolgreicher_kettenlauf_raeumt_den_ursprung_auf(
    config, client, gemeldet
):
    """The same healing, from a count that already stood: a chain that ends
    properly clears the failed runs the entry it continues had piled up."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None, fehlergrenze=5, deliver="announce")
    repos.cronjobs.fehlversuch_zaehlen(ursprung.id)
    kette = repos.cronjobs.erstellen(
        agent="recherche", task=AUFGABE, zeitplan="08:00", herkunft="agent",
        basisaufgabe=AUFGABE, **zwischenstand.kettenfelder(ursprung, ERSTLAUF),
    )
    provider_setzen(client, MockProvider(mock_endpunkt("test")))

    await lauf_starten(client, config, kette.id)

    assert repos.cronjobs.holen(ursprung.id).fehlversuche == 0
    # On 'announce' for the same reason as above: the chain that ended
    # properly says its one closing sentence, and the origin it just cleared
    # says nothing at all.
    assert gemeldet == [(AUFGABE, True)]


async def test_ein_ueberlauf_mit_fortsetzung_zaehlt_weiterhin_nicht(
    config, client, gemeldet
):
    """The rule the whole way out is built around stays untouched: a run
    that hands its work on is not a failed run, on the chain or on the
    origin."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None, fehlergrenze=1, deliver="announce")
    ueberlauf(client)

    await lauf_starten(client, config, ursprung.id)
    kette = kette_von(repos, ursprung.id)
    await lauf_starten(client, config, kette.id)

    assert repos.cronjobs.holen(ursprung.id).fehlversuche == 0
    assert repos.cronjobs.holen(ursprung.id).aktiv is True
    # On 'announce', and here the empty list stays empty: both
    # runs handed their work on, and a handoff is not an ending
    # (``melde_wenn_faellig``, ``fortsetzung_geplant``). On the default 'log'
    # that silence came out of the gate and would have held even if the rule
    # were gone; on 'announce' it is the rule's own.
    assert gemeldet == []


async def test_ein_eintrag_ohne_kette_zaehlt_wie_zuvor(config, client, gemeldet, repos):
    """And an entry with no chain behind it is booked exactly as it always
    was — one row, one count, one announcement at the limit."""
    # On 'announce': an entry on 'log' gets the limit's sentence in the log
    # alone. The booking itself is the same on either setting.
    eintrag = eintrag_anlegen(
        repos, ziel=None, fehlergrenze=1, deliver="announce"
    )

    angehalten = await cronablauf.ausgang_verbuchen(
        repos, eintrag.id, AUFGABE, erfolgreich=False
    )

    assert angehalten is True
    assert repos.cronjobs.holen(eintrag.id).aktiv is False
    assert gemeldet == [(f"{AUFGABE} — stopped after 1 failed runs", False)]


async def test_ein_verschwundener_ursprung_haelt_die_buchung_nicht_auf(
    repos, gemeldet
):
    """A chain whose origin was deleted while it was out still books its own
    row and simply has nothing else to book."""
    kette = repos.cronjobs.erstellen(
        agent="recherche", task=AUFGABE, zeitplan="08:00", herkunft="agent",
        basisaufgabe=AUFGABE, fehlergrenze=1, ursprung_id="weg",
        # On 'announce' — see the entries above.
        deliver="announce",
    )

    angehalten = await cronablauf.ausgang_verbuchen(
        repos, kette.id, AUFGABE, erfolgreich=False
    )

    assert angehalten is True
    assert repos.cronjobs.holen(kette.id).aktiv is False


# --- The note travels forward too -----------------------------------


async def test_die_kette_erbt_den_zettel_beim_anbieterausfall(
    config, client, kaputter_anbieter
):
    """The worst case of the three the handoff has: the text handed on is
    nothing but "the model server was unreachable", so without the note the
    continuation opens with no state at all and reports mails 1-5 again."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None)
    repos.cronjobs.notiz_setzen(ursprung.id, NOTIZ)
    geschrieben_am = repos.cronjobs.holen(ursprung.id).notiz_am

    await lauf_starten(client, config, ursprung.id)

    kette = kette_von(repos, ursprung.id)
    assert kette.notiz == NOTIZ
    # The moment of the WRITE, carried over as it stands — re-stamped with
    # the handoff, the continuation would be told its state is fresher than
    # it is, and everything in between would count as seen.
    assert kette.notiz_am == geschrieben_am


async def test_die_kette_erbt_den_zettel_auch_beim_ueberlauf(config, client):
    """The same forward step at the other trigger, where the handoff text
    does carry state — but only as much of it as the model happened to
    write down, which is not a guarantee."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None)
    repos.cronjobs.notiz_setzen(ursprung.id, NOTIZ)
    ueberlauf(client)

    await lauf_starten(client, config, ursprung.id)

    assert kette_von(repos, ursprung.id).notiz == NOTIZ


async def test_der_erste_kettenlauf_kennt_den_zettel(
    config, client, kaputter_anbieter
):
    """What the run actually reads. Not the column — the opening message."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None)
    repos.cronjobs.notiz_setzen(ursprung.id, NOTIZ)
    await lauf_starten(client, config, ursprung.id)
    kette = kette_von(repos, ursprung.id)

    text = cronablauf.auftragstext(kette)

    assert NOTIZ in text
    assert kette.notiz_am in text


async def test_der_notizblock_steht_im_kettenlauf_genau_einmal(
    config, client, kaputter_anbieter
):
    """The trap ``urspruengliche_aufgabe`` already closes for the goal. The
    note is appended to every firing of the chain as well, so a chain whose
    stored task still had the old block inside it would hand the run two
    contradicting versions of its own state."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None)
    repos.cronjobs.notiz_setzen(ursprung.id, NOTIZ)
    await lauf_starten(client, config, ursprung.id)
    kette = kette_von(repos, ursprung.id)

    text = cronablauf.auftragstext(kette)

    assert text.count("Your note from the previous run") == 1
    assert text.count(NOTIZ) == 1


async def test_ohne_zettel_und_ohne_ziel_bleibt_alles_wie_es_war(
    config, client, kaputter_anbieter
):
    """The counter-check: an entry with neither costs its continuation
    nothing — no extra block, no blank line, not one character."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=None)

    await lauf_starten(client, config, ursprung.id)

    kette = kette_von(repos, ursprung.id)
    assert kette.notiz is None
    assert kette.notiz_am is None
    assert cronablauf.auftragstext(kette) == kette.task


# --- And the rest of the fields -------------------------------------


async def test_die_kette_erbt_die_fehlergrenze(config, client, kaputter_anbieter):
    """Both counts that read it run on the continuation now — the failed
    runs and the quiet ones. An entry told "give up
    after 1" quietly got five tries the moment its work was handed on."""
    agent_schreiben(config)
    repos = client.app.state.repositories
    ursprung = eintrag_anlegen(repos, ziel=ZIEL, fehlergrenze=1)

    await lauf_starten(client, config, ursprung.id)

    assert kette_von(repos, ursprung.id).fehlergrenze == 1


# Every column of ``cronjobs`` a continuation deliberately does NOT inherit,
# with the reason next to it. Everything the model has and this set does not
# name has to come out of ``kettenfelder`` — which is what turns a new column
# nobody thought about into a red test instead of another silent loss.
NICHT_VERERBT = {
    # The row's own identity. A continuation IS a new row.
    "id", "created_at", "updated_at",
    # Written by the caller at creation time, per continuation: its own
    # agent, its own wrapped task, its own "in two minutes" schedule, its
    # own 'agent' origin, and the original sentence it carries forward
    # (app/zwischenstand.py, app/api/v1/auftraege.py).
    "agent", "task", "zeitplan", "herkunft", "basisaufgabe",
    # A fresh row starts armed and has never fired.
    "aktiv", "zuletzt_ausgeloest",
    # The chain's progress, written right after creation with
    # ``fortschritt_setzen`` — worked out for THIS restart, never copied.
    "erledigt_anzahl", "ohne_fortschritt", "neustarts",
    # The day a one-off was due: it has already come, and pinned to it the
    # continuation would never be due again (``kettenfelder``).
    "datum",
    # Records of what has happened, not settings. They stay on the row they
    # happened to, and the origin keeps its own tally through
    # ``ausgang_verbuchen`` / ``ziel_verbuchen`` (app/cronablauf.py).
    "fehlversuche", "laeufe_ohne_ruf", "ziel_erreicht_am",
    # A script entry can never be the origin of a chain: it starts
    # no model, so nothing about it can run out of context or lose a
    # provider. There is nothing here to carry forward, and carrying it
    # forward would be worse than nothing — a continuation is written for a
    # model run, and one that also named a script would be both kinds at
    # once, with the firing loop's script branch deciding which it is.
    "skript", "zeitgrenze",
}


def test_die_kettenfelder_decken_alle_spalten_ab():
    """Derived from the model's own column list, never from a copy of it.

    The hand-written version of this test compared a fixed dictionary with
    the current output of ``kettenfelder`` — so it went red when an existing
    field DISAPPEARED, and stayed green for the case that actually costs
    something: a new column on ``cronjobs`` that ought to travel with the
    work and is forgotten. It grew with the very list it was meant to check.
    """
    spalten = {feld.name for feld in dataclasses.fields(Cronjob)}
    # The exception list cannot go stale either: a column renamed or dropped
    # leaves a name here that no longer exists.
    assert NICHT_VERERBT <= spalten, (
        "NICHT_VERERBT names columns that no longer exist: "
        f"{sorted(NICHT_VERERBT - spalten)}"
    )
    assert set(zwischenstand.kettenfelder(None, ERSTLAUF)) == spalten - NICHT_VERERBT, (
        "A column of 'cronjobs' is neither inherited nor justified in NICHT_VERERBT "
        "— decide which of the two applies"
    )


def test_die_kettenfelder_sind_vollstaendig(repos):
    """And the values, not only the names: what each of them actually
    carries forward, said out loud."""
    ursprung = eintrag_anlegen(
        repos, ziel=ZIEL, ziel_stilllegen=True, einmalig=True, fehlergrenze=3,
        deliver="announce",
    )
    repos.cronjobs.notiz_setzen(ursprung.id, NOTIZ)
    ursprung = repos.cronjobs.holen(ursprung.id)

    # The run's own id only speaks where there is no entry to inherit from.
    assert zwischenstand.kettenfelder(ursprung, ERSTLAUF) == {
        "ziel": ZIEL,
        "ziel_stilllegen": True,
        "einmalig": True,
        "ursprung_id": ursprung.id,
        "notiz": NOTIZ,
        "notiz_am": ursprung.notiz_am,
        "fehlergrenze": 3,
        "deliver": "announce",
    }


def test_ohne_vorgaenger_erbt_die_kette_nichts(repos):
    """A job no schedule fired writes its continuation too — with nothing to
    inherit, and nothing pretending otherwise. Its one link back is the run
    itself: that run is what a person started. ``fehlergrenze`` of ``None``
    is "whatever the default is", said once on the dataclass; ``deliver``
    has no such spelling, so the column's own default is written out."""
    assert zwischenstand.kettenfelder(None, ERSTLAUF) == {
        "ziel": None,
        "ziel_stilllegen": False,
        "einmalig": False,
        "ursprung_id": ERSTLAUF,
        "notiz": None,
        "notiz_am": None,
        "fehlergrenze": None,
        "deliver": "log",
    }


def test_die_vorgabe_gilt_ohne_vorgaenger(repos):
    """And that ``None`` really lands on the default rather than in the
    column."""
    kette = repos.cronjobs.erstellen(
        agent="recherche", task=AUFGABE, zeitplan="08:00", herkunft="agent",
        basisaufgabe=AUFGABE, **zwischenstand.kettenfelder(None, ERSTLAUF),
    )
    assert kette.fehlergrenze == 5
    assert repos.cronjobs.holen(kette.id).fehlergrenze == 5


def kette_von_neuester(repos, ursprung_id: str) -> str:
    """The most recent continuation of this entry — a fresh one is created
    per dead day, and the older ones stay in the table, switched off."""
    ketten = [e for e in repos.cronjobs.auflisten() if e.ursprung_id == ursprung_id]
    assert ketten
    return ketten[-1].id
