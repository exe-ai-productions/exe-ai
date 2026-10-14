"""The context-full handoff (app/zwischenstand.py)
— the pure pieces: counting "Done" bullets, deciding whether a chain gets
another restart, and building the next task text."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.zwischenstand import (
    MAX_NEUSTARTS,
    OHNE_FORTSCHRITT_GRENZE,
    entscheiden,
    erledigt_zaehlen,
    ist_kette,
    naechste_aufgabe,
    nach_neustart_fortsetzen,
)


def cronjob(*, erledigt_anzahl=None, ohne_fortschritt=0, neustarts=0):
    return SimpleNamespace(
        erledigt_anzahl=erledigt_anzahl, ohne_fortschritt=ohne_fortschritt, neustarts=neustarts
    )


# --- erledigt_zaehlen -------------------------------------------------------


def test_zaehlt_die_striche_im_done_abschnitt():
    text = "## Task\nx\n\n## Done\n- eins\n- zwei\n- drei\n\n## Next\ny"
    assert erledigt_zaehlen(text) == 3


def test_zaehlt_nichts_ausserhalb_von_done():
    text = "## Task\n- x\n\n## Done\n- echt"
    assert erledigt_zaehlen(text) == 1


def test_ohne_done_abschnitt_ist_null():
    assert erledigt_zaehlen("## Task\nx\n\n## Next\ny") == 0


def test_grossschreibung_der_ueberschrift_ist_egal():
    assert erledigt_zaehlen("## done\n- eins") == 1


# --- entscheiden -------------------------------------------------------


def test_allererster_handoff_zaehlt_nie_als_stillstand():
    entscheidung = entscheiden(None, erledigt_anzahl=1)
    assert entscheidung.weiter is True
    assert entscheidung.ohne_fortschritt == 0
    assert entscheidung.neustarts == 1
    assert entscheidung.erledigt_anzahl == 1


def test_wachstum_setzt_den_zaehler_zurueck():
    vorheriger = cronjob(erledigt_anzahl=2, ohne_fortschritt=1, neustarts=3)
    entscheidung = entscheiden(vorheriger, erledigt_anzahl=3)
    assert entscheidung.weiter is True
    assert entscheidung.ohne_fortschritt == 0
    assert entscheidung.neustarts == 4


def test_gleichstand_zaehlt_als_kein_fortschritt():
    vorheriger = cronjob(erledigt_anzahl=2, ohne_fortschritt=1, neustarts=3)
    entscheidung = entscheiden(vorheriger, erledigt_anzahl=2)
    assert entscheidung.ohne_fortschritt == 2


def test_drei_in_folge_ohne_wachstum_stoppt_die_kette():
    vorheriger = cronjob(erledigt_anzahl=2, ohne_fortschritt=OHNE_FORTSCHRITT_GRENZE - 1, neustarts=5)
    entscheidung = entscheiden(vorheriger, erledigt_anzahl=2)
    assert entscheidung.ohne_fortschritt == OHNE_FORTSCHRITT_GRENZE
    assert entscheidung.weiter is False


def test_obergrenze_greift_auch_bei_wachstum():
    """The hard ceiling is independent of the done-count heuristic."""
    vorheriger = cronjob(erledigt_anzahl=2, ohne_fortschritt=0, neustarts=MAX_NEUSTARTS - 1)
    entscheidung = entscheiden(vorheriger, erledigt_anzahl=99)
    assert entscheidung.weiter is False


# --- naechste_aufgabe -------------------------------------------------------


def test_naechste_aufgabe_traegt_beides():
    aufgabe = naechste_aufgabe("Ordner X aufräumen", "## Task\n...\n\n## Done\n- eins")
    assert "Ordner X aufräumen" in aufgabe
    assert "## Done" in aufgabe


# --- nach_neustart_fortsetzen -----------------------------------


def test_ein_frischer_lauf_bekommt_einen_neuen_cronjob(repos, config):
    """A job that was never part of a chain — no cronjob_id at all — gets
    one now, the same way the context-full handoff creates one on a chain's
    first restart — naming that run as its origin."""
    auftrag = repos.auftraege.erstellen(user_id="b", agent="a", auftrag="Ordner aufräumen")
    repos.auftraege.zwischenstand_setzen(auftrag.id, "Bisher: die Hälfte.")
    repos.auftraege.beim_start_aufraeumen()

    geplant = nach_neustart_fortsetzen(config, repos)

    assert geplant == 1
    (eintrag,) = repos.cronjobs.auflisten()
    assert eintrag.agent == "a"
    assert eintrag.basisaufgabe == "Ordner aufräumen"
    assert "Bisher: die Hälfte." in eintrag.task
    assert eintrag.neustarts == 1
    assert eintrag.aktiv is True
    assert eintrag.ursprung_id == auftrag.id


def test_eine_bestehende_kette_wird_weitergezaehlt_nicht_neu_gestartet(repos, config):
    """The restart ceiling is shared with the context-full handoff and the
    provider-outage retry — a chain does not get a second budget just
    because THIS restart's cause was a plain service restart."""
    kette = repos.cronjobs.erstellen(
        agent="a", task="Weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Ordner aufräumen",
    )
    repos.cronjobs.fortschritt_setzen(
        kette.id, erledigt_anzahl=2, ohne_fortschritt=0, neustarts=3
    )
    auftrag = repos.auftraege.erstellen(
        user_id="b", agent="a", auftrag="Weiter", cronjob_id=kette.id
    )
    repos.auftraege.zwischenstand_setzen(auftrag.id, "Noch mehr geschafft.")
    repos.auftraege.beim_start_aufraeumen()

    geplant = nach_neustart_fortsetzen(config, repos)

    assert geplant == 1
    aktualisiert = repos.cronjobs.holen(kette.id)
    assert aktualisiert is not None
    # Same entry, not a second one.
    assert len(repos.cronjobs.auflisten()) == 1
    assert aktualisiert.neustarts == 4
    assert aktualisiert.basisaufgabe == "Ordner aufräumen"
    assert "Noch mehr geschafft." in aktualisiert.task


def test_die_obergrenze_bremst_auch_hier(repos, config):
    kette = repos.cronjobs.erstellen(
        agent="a", task="Weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Weiter",
    )
    repos.cronjobs.fortschritt_setzen(
        kette.id, erledigt_anzahl=None, ohne_fortschritt=0, neustarts=MAX_NEUSTARTS - 1
    )
    auftrag = repos.auftraege.erstellen(
        user_id="b", agent="a", auftrag="Weiter", cronjob_id=kette.id
    )
    repos.auftraege.zwischenstand_setzen(auftrag.id, "Stand")
    repos.auftraege.beim_start_aufraeumen()

    geplant = nach_neustart_fortsetzen(config, repos)

    assert geplant == 0
    danach = repos.cronjobs.holen(kette.id)
    assert danach.aktiv is False
    # Untouched — a chain that stops does not get a last rewrite of its task.
    assert danach.task == "Weiter"


def test_ein_zweiter_dienststart_plant_denselben_lauf_nicht_erneut(repos, config):
    """Nothing used to mark the row
    handled, so every later service start found the exact same
    'unterbrochen' row and planned another restart for it — the ceiling
    never really applied, because each one looked like a fresh chain."""
    auftrag = repos.auftraege.erstellen(user_id="b", agent="a", auftrag="Ordner aufräumen")
    repos.auftraege.zwischenstand_setzen(auftrag.id, "Bisher: die Hälfte.")
    repos.auftraege.beim_start_aufraeumen()

    erster_start = nach_neustart_fortsetzen(config, repos)
    zweiter_start = nach_neustart_fortsetzen(config, repos)
    dritter_start = nach_neustart_fortsetzen(config, repos)

    assert (erster_start, zweiter_start, dritter_start) == (1, 0, 0)
    (eintrag,) = repos.cronjobs.auflisten()
    assert eintrag.neustarts == 1


def test_ein_fremder_auftrag_wird_nicht_fortgesetzt(repos, config):
    """The third write of one startup, and the one the owner column was
    almost not handed to.

    'unterbrochen' with a status is exactly what the OTHER service on this
    data folder writes when IT restarts — the state says nothing about who
    owns the job. Picking it up would start a second run of work that
    service is about to carry on itself, and both would write into the same
    row. So beside a living second service only our own jobs are resumed.
    """
    repos.auftraege.db.dienst_port = 8095
    eigen = repos.auftraege.erstellen(user_id="b", agent="a", auftrag="Unser")
    fremd = repos.auftraege.erstellen(user_id="b", agent="a", auftrag="Seins")
    for auftrag in (eigen, fremd):
        repos.auftraege.zwischenstand_setzen(auftrag.id, "Bisher: die Hälfte.")
    repos.auftraege.beim_start_aufraeumen()
    repos.auftraege.verbindung.execute(
        "UPDATE auftraege SET dienst_port = 8099 WHERE id = ?", (fremd.id,)
    )

    # Ours is resumed in the same run that leaves his alone — so the zero
    # below is the port and not a filter that matches nothing at all.
    assert nach_neustart_fortsetzen(config, repos, nur_eigene=True) == 1
    (eintrag,) = repos.cronjobs.auflisten()
    assert eintrag.basisaufgabe == "Unser"
    # Alone on the folder his row IS ours to finish — nobody else will.
    assert nach_neustart_fortsetzen(config, repos) == 1


def test_auch_an_der_obergrenze_gilt_die_zeile_als_behandelt(repos, config):
    kette = repos.cronjobs.erstellen(
        agent="a", task="Weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Weiter",
    )
    repos.cronjobs.fortschritt_setzen(
        kette.id, erledigt_anzahl=None, ohne_fortschritt=0, neustarts=MAX_NEUSTARTS - 1
    )
    auftrag = repos.auftraege.erstellen(
        user_id="b", agent="a", auftrag="Weiter", cronjob_id=kette.id
    )
    repos.auftraege.zwischenstand_setzen(auftrag.id, "Stand")
    repos.auftraege.beim_start_aufraeumen()

    nach_neustart_fortsetzen(config, repos)
    assert repos.auftraege.holen(auftrag.id).zwischenstand is None
    # A second start must not try to switch the (already deactivated)
    # chain off a second time via a fresh, wrongly-counted attempt.
    assert nach_neustart_fortsetzen(config, repos) == 0


def test_ohne_zwischenstand_bleibt_unangefasst(repos, config):
    """Nothing to hand off, nothing reconstructed from the transcript — the
    job stays plain 'unterbrochen', no cronjob appears."""
    repos.auftraege.erstellen(user_id="b", agent="a", auftrag="x")
    repos.auftraege.beim_start_aufraeumen()

    geplant = nach_neustart_fortsetzen(config, repos)

    assert geplant == 0
    assert repos.cronjobs.auflisten() == []


# --- A chain never adopts a person's own schedule -----


def test_ist_kette_unterscheidet_nach_basisaufgabe():
    assert ist_kette(None) is False
    fremd = SimpleNamespace(basisaufgabe=None)
    assert ist_kette(fremd) is False
    eigene_kette = SimpleNamespace(basisaufgabe="Ordner aufräumen")
    assert ist_kette(eigene_kette) is True


def test_ein_fremder_termin_bleibt_unangetastet_und_bekommt_eine_eigene_kette(repos, config):
    """The decision itself: a person's own daily reminder is their own
    entry, not the program's bookkeeping — a chain that starts from it
    leaves it exactly as it was and creates its own entry instead."""
    fremder_termin = repos.cronjobs.erstellen(
        agent="a", task="Water the plants", zeitplan="08:00", herkunft="chat",
    )
    auftrag = repos.auftraege.erstellen(
        user_id="b", agent="a", auftrag="Water the plants", cronjob_id=fremder_termin.id,
    )
    repos.auftraege.zwischenstand_setzen(auftrag.id, "Halb erledigt.")
    repos.auftraege.beim_start_aufraeumen()

    geplant = nach_neustart_fortsetzen(config, repos)

    assert geplant == 1
    unveraendert = repos.cronjobs.holen(fremder_termin.id)
    assert unveraendert.task == "Water the plants"
    assert unveraendert.zeitplan == "08:00"
    assert unveraendert.aktiv is True
    assert unveraendert.basisaufgabe is None

    (neue_kette,) = [e for e in repos.cronjobs.auflisten() if e.id != fremder_termin.id]
    assert neue_kette.basisaufgabe == "Water the plants"
    assert "Halb erledigt." in neue_kette.task
    assert neue_kette.neustarts == 1


def test_ein_fremder_termin_wird_an_der_obergrenze_nicht_abgeschaltet(repos, config):
    fremder_termin = repos.cronjobs.erstellen(
        agent="a", task="Water the plants", zeitplan="08:00", herkunft="chat",
    )
    repos.cronjobs.fortschritt_setzen(
        fremder_termin.id, erledigt_anzahl=None, ohne_fortschritt=0,
        neustarts=MAX_NEUSTARTS - 1,
    )
    auftrag = repos.auftraege.erstellen(
        user_id="b", agent="a", auftrag="Water the plants", cronjob_id=fremder_termin.id,
    )
    repos.auftraege.zwischenstand_setzen(auftrag.id, "Stand")
    repos.auftraege.beim_start_aufraeumen()

    geplant = nach_neustart_fortsetzen(config, repos)

    assert geplant == 0
    unveraendert = repos.cronjobs.holen(fremder_termin.id)
    assert unveraendert.aktiv is True
    assert unveraendert.task == "Water the plants"
    # Hitting the ceiling on someone else's schedule creates nothing either
    # — there is no chain here to continue.
    assert repos.cronjobs.auflisten() == [unveraendert]


# --- anfordern: the handoff round's clocks ----------------------------------


class _HandoffServer:
    """A provider for the handoff round alone: either nothing but
    keepalives — no piece ever arrives — or an ordinary short answer."""

    def __init__(self, *, keepalives_only: bool):
        self.keepalives_only = keepalives_only
        self.closed = False

    async def streamen(self, anfrage):
        from app.providers import Stueck

        try:
            if self.keepalives_only:
                await asyncio.sleep(3600)
            yield Stueck("content", text="## Done\n- one")
        finally:
            self.closed = True


def _handoff_round(monkeypatch, server, *, stopped=False):
    """One call of ``anfordern`` against ``server``, with the ceiling
    arithmetic around it stood still: what is measured is how the round
    reads its stream, nothing about the request it builds."""
    from app import zwischenstand
    from app.generationen import Generierung

    monkeypatch.setattr(zwischenstand.antwortgrenze, "geltender_deckel", lambda *a, **k: None)
    monkeypatch.setattr(zwischenstand.antwortgrenze, "eingabe_schaetzen", lambda *a, **k: 0)
    monkeypatch.setattr(zwischenstand.antwortgrenze, "hoechste_passende", lambda *a, **k: 100)
    monkeypatch.setattr(zwischenstand.kontextvoll, "mit_grenze", lambda request, *a: request)
    state = SimpleNamespace(provider=server, context_tokens=1000)
    request = SimpleNamespace(modell="m", nachrichten=[], werkzeuge=[])
    generation = Generierung(id="g", chat_id="c", endpoint_id="e")
    if stopped:
        generation.signal.set()
    return zwischenstand.anfordern(state, request, None, generation)


async def test_a_handoff_that_only_gets_keepalives_ends_on_the_silence_clock(
    monkeypatch, caplog
):
    """Nobody presses stop in an unattended job, so the race against the stop
    button never ends this round: a server sending nothing but keepalives
    held it for good. The silence clock ends it, and the stream is closed.

    Ended the way a failed fold ends: the clock's own line in the log, no
    stack trace, and nothing to hand off — not an exception that ends the
    job as an unexpected failure."""
    import logging

    from app import faltversuche

    monkeypatch.setattr(faltversuche, "STILLE_SEKUNDEN", 0.05)
    server = _HandoffServer(keepalives_only=True)
    with caplog.at_level(logging.WARNING, logger="app.zwischenstand"):
        handoff = await asyncio.wait_for(_handoff_round(monkeypatch, server), 5)
    assert handoff == ""
    assert server.closed
    lines = [r for r in caplog.records if r.name == "app.zwischenstand"]
    assert [r.getMessage() for r in lines] == ["Handoff not received: No response from the server for 0 s."]
    assert lines[0].exc_info is None


async def test_a_handoff_that_fails_otherwise_still_raises(monkeypatch):
    """Silence probe: only the clocks end the round quietly. Any other
    failure of the request still goes to the caller as before."""

    class _Failing:
        async def streamen(self, anfrage):
            raise ConnectionError("refused")
            yield  # pragma: no cover - makes this a generator

    with pytest.raises(ConnectionError):
        await asyncio.wait_for(_handoff_round(monkeypatch, _Failing()), 5)


async def test_an_ordinary_handoff_still_comes_back_whole(monkeypatch):
    """Silence probe: a server that answers ends the round as before, with
    its text as the handoff and the stream closed."""
    server = _HandoffServer(keepalives_only=False)
    handoff = await asyncio.wait_for(_handoff_round(monkeypatch, server), 5)
    assert handoff == "## Done\n- one"
    assert server.closed


async def test_the_stream_is_closed_even_where_closing_the_reader_raises(monkeypatch):
    """A stop lands while the reader is parked on a piece, so the reader is
    closed from the outside — and closing it raises. The stream behind it is
    the connection to the server, and it is closed all the same."""
    from app import faltversuche
    from app.providers import Stueck

    async def reader_failing_on_close(source, request):
        piece = await anext(source)
        try:
            yield piece
        except GeneratorExit:
            raise RuntimeError("closing the reader failed") from None
        yield Stueck("content", text="never read")

    monkeypatch.setattr(faltversuche, "read_stream", reader_failing_on_close)
    server = _HandoffServer(keepalives_only=False)
    with pytest.raises(RuntimeError, match="closing the reader failed"):
        await asyncio.wait_for(_handoff_round(monkeypatch, server, stopped=True), 5)
    assert server.closed
