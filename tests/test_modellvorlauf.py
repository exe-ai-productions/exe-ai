"""How far ahead the local model server should start before a cron entry
fires: a load once measured is a load that need not surprise
the next one.
"""

from __future__ import annotations

from app import modellvorlauf
from app.db.repositories.einstellungen import GLOBAL, MESSWERTE


def test_messung_setzen_und_holen(repos):
    modellvorlauf.messung_setzen(repos, "klein.gguf", 42.5)
    assert modellvorlauf.messung_holen(repos, "klein.gguf") == 42.5


def test_messung_holen_ohne_messung_ist_none(repos):
    assert modellvorlauf.messung_holen(repos, "phantom.gguf") is None


def test_eine_neue_messung_ersetzt_die_alte(repos):
    modellvorlauf.messung_setzen(repos, "klein.gguf", 60)
    modellvorlauf.messung_setzen(repos, "klein.gguf", 30)
    assert modellvorlauf.messung_holen(repos, "klein.gguf") == 30


def test_ungemessen_faellt_auf_den_deckel_zurueck(repos):
    assert modellvorlauf.vorlauf_sekunden(repos, "nie-gemessen.gguf") == 600


def test_vorlauf_ist_messung_plus_puffer(repos):
    modellvorlauf.messung_setzen(repos, "klein.gguf", 120)  # 2 min
    # 2 min + 2 min buffer = 4 min — below the minimum of 5, so 5.
    assert modellvorlauf.vorlauf_sekunden(repos, "klein.gguf") == 300


def test_vorlauf_haelt_den_mindestwert_ein(repos):
    modellvorlauf.messung_setzen(repos, "flink.gguf", 1)  # fast nichts
    assert modellvorlauf.vorlauf_sekunden(repos, "flink.gguf") == 300


def test_vorlauf_haelt_den_deckel_ein(repos):
    modellvorlauf.messung_setzen(repos, "riesig.gguf", 20 * 60)  # 20 min
    assert modellvorlauf.vorlauf_sekunden(repos, "riesig.gguf") == 600


# --- Whether the cap is worth mentioning — the caller decides when -------:
#logging lives with whoever is about to actually
# preload, not inside this pure calculation — called on every 30-second
# tick regardless of reach, a log line here would repeat for a due time
# hours away, for as long as the measurement stands.


def test_gedeckelt_wenn_die_messung_den_deckel_sprengt():
    assert modellvorlauf.gedeckelt(20 * 60) is True


def test_nicht_gedeckelt_innerhalb_der_grenzen():
    assert modellvorlauf.gedeckelt(5 * 60) is False


def test_nicht_gedeckelt_ohne_messung():
    assert modellvorlauf.gedeckelt(None) is False


def test_ein_normaler_wert_zwischen_den_grenzen(repos):
    modellvorlauf.messung_setzen(repos, "mittel.gguf", 5 * 60)  # 5 min
    # 5 min + 2 min buffer = 7 min — between 5 and 10, so unchanged.
    assert modellvorlauf.vorlauf_sekunden(repos, "mittel.gguf") == 420


# --- The measurement never surfaces in the settings cascade ----------------


def test_die_kaskade_sieht_die_messung_nie(repos):
    """The whole point: `messwerte` sits outside `kette()`, which
    only ever builds global/modell:/chat: — a measurement cannot leak into
    a chat's or model's own settings, however they are asked for."""
    modellvorlauf.messung_setzen(repos, "klein.gguf", 42)
    assert repos.einstellungen.kette("klein.gguf") == [GLOBAL]
    assert repos.einstellungen.aufgeloest("klein.gguf") is None
    assert repos.einstellungen.holen(GLOBAL, "klein.gguf") is None
    # It lives exactly where it was put, under its own scope.
    assert repos.einstellungen.holen(MESSWERTE, "klein.gguf") == 42


# ==========================================================================
# The act the measurement above is for: the main model server
# brought up before a due time, instead of the entry waiting for it.
# ==========================================================================

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import agentenmodellwahl, agentenserver, runnermodellwahl
from app.modellrunner import RunnerFehler
from app.providers import MockProvider
from tests.conftest import agentenmodell_leer, agentenmodell_setzen, provider_setzen

# A fixed moment to reckon from, so nothing here depends on the wall clock.
JETZT = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
    hour=13, minute=0, second=0, microsecond=0
)


@pytest.fixture(autouse=True)
def frisches_vorladegedaechtnis():
    """The "already tried" memory is module state — a test must not inherit
    the previous one's attempts. The same goes for what the module remembers
    of the main server's comings and goings."""
    modellvorlauf._versucht.clear()
    modellvorlauf._beobachtung_vergessen()
    yield
    modellvorlauf._versucht.clear()
    modellvorlauf._beobachtung_vergessen()


class Runnerattrappe:
    """Enough of app/modellrunner.py to see what a preload does to it —
    without a llama-server and without a gigabyte of file."""

    def __init__(self, *, laeuft: bool = False, fehler: str | None = None,
                 stirbt_sofort: bool = False, ueberlebt_takte: int | None = None):
        self._laeuft = laeuft
        self._fehler = fehler
        # The process starts and is gone again before anybody can look — what
        # a llama-server does when the file does not fit into the memory.
        self._stirbt_sofort = stirbt_sofort
        # And what it does at nineteen gigabytes: it reads for a while and
        # then dies, so it is found ALIVE by at least one 30-second tick
        # before it is found gone. `stirbt_sofort` covers only the opposite
        # case, which is why the doubling could pass every test here while
        # never happening in the running program.
        self._ueberlebt_takte = ueberlebt_takte
        self._takte_gelebt = 0
        self.starts: list[tuple[str, dict]] = []
        self.port_vorgabe = 8080
        self._lauf = None
        self._von_hand = False

    def laeuft(self) -> bool:
        return self._laeuft

    def von_hand_gestoppt(self) -> bool:
        # Measured on the real runner (app/modellrunner.py): after `stoppen`
        # the run, the process handle and the pid note are gone, while a
        # killed process leaves all three standing. The class says so itself
        # rather than making anybody read its private state.
        return self._von_hand

    def stoppen(self) -> bool:
        self._laeuft = False
        self._lauf = None
        self._von_hand = True
        return True

    def abstuerzen(self) -> None:
        """The process dies while loading: nobody stopped it, and nothing but
        the next look tells anyone it is gone."""
        self._laeuft = False

    def takt_vorbei(self) -> None:
        """One tick of the wecker has gone by — driven by the `takt` helper.

        A stand-in built with `ueberlebt_takte` counts them and dies once it
        has outlived that many, without ever having said it was ready.
        """
        if self._ueberlebt_takte is None or not self._laeuft:
            return
        self._takte_gelebt += 1
        if self._takte_gelebt > self._ueberlebt_takte:
            self.abstuerzen()

    def lauf(self):
        # As the real one answers it: nothing is running, so there is no run
        # to describe (app/modellrunner.py).
        return self._lauf if self._laeuft else None

    def starten(self, modell: str, **werte):
        self.starts.append((modell, werte))
        self._von_hand = False
        self._takte_gelebt = 0
        if self._fehler:
            raise RunnerFehler(self._fehler)
        self._laeuft = not self._stirbt_sofort
        self._lauf = SimpleNamespace(
            modell=modell, port=werte.get("port") or self.port_vorgabe,
            kontext=werte.get("kontext"),
        )
        return self._lauf


def aufbauen(config, client, *, zeitplan: str, angelegt: datetime,
             agent: str = "recherche", skript: str | None = None) -> str:
    """One active cron entry, with a creation time that is not "just now" —
    a fresh entry is deliberately not overdue (app/cronablauf.py)."""
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{agent}.md").write_text("---\n---\n\nPrompt.\n", encoding="utf-8")
    repositories = client.app.state.repositories
    if skript:
        eintrag = repositories.cronjobs.erstellen(
            agent=agent, task="Los", zeitplan=zeitplan, herkunft="chat", skript=skript
        )
    else:
        eintrag = repositories.cronjobs.erstellen(
            agent=agent, task="Los", zeitplan=zeitplan, herkunft="chat"
        )
    repositories.cronjobs.verbindung.execute(
        "UPDATE cronjobs SET created_at = ? WHERE id = ?",
        (angelegt.isoformat(), eintrag.id),
    )
    return eintrag.id


def runner_einsetzen(client, runner: Runnerattrappe) -> list:
    """Swaps in the stand-in and records what gets announced to the discovery
    instead of really checking a port."""
    client.app.state.modellrunner = runner
    angemeldet: list = []

    async def anmelden(endpunkt):
        angemeldet.append(endpunkt)

    client.app.state.discovery.anmelden = anmelden
    return angemeldet


def startwahl_setzen(client, **werte) -> None:
    client.app.state.repositories.einstellungen.setzen(
        "global", runnermodellwahl.SCHLUESSEL, werte
    )


def takt(client, jetzt: datetime) -> None:
    asyncio.run(client.app.state.wecker.einmal_pruefen(jetzt=jetzt))
    # The wall clock the stand-in lives by: a load dies BETWEEN two ticks,
    # not inside one, so a stand-in that outlives ticks is told here.
    vorbei = getattr(client.app.state.modellrunner, "takt_vorbei", None)
    if callable(vorbei):
        vorbei()


# --- The field is the trigger, and only the main model pulls it -----------


def test_hauptmodell_gewaehlt_nur_bei_runner(client):
    repositories = client.app.state.repositories
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    assert agentenmodellwahl.hauptmodell_gewaehlt(repositories) is True


def test_hauptmodell_gewaehlt_bei_slot_cloud_und_ohne_wahl(client):
    """Two answers are "somewhere else" — the slot file and a foreign id —
    and everything else is the main model.

    "Nothing chosen" counts as chosen here: the field has no
    off state, the row shows the main model, and the run lands on it, so a
    due schedule may preload it. It used to answer False, and a schedule
    then did not preload the model its own run was about to use.
    """
    repositories = client.app.state.repositories
    agentenmodell_setzen(client, "klein.gguf", sorte="slot")
    assert agentenmodellwahl.hauptmodell_gewaehlt(repositories) is False
    agentenmodell_setzen(client, "pruefstand:gpt-4o")
    assert agentenmodellwahl.hauptmodell_gewaehlt(repositories) is False
    agentenmodell_leer(client)
    assert agentenmodellwahl.hauptmodell_gewaehlt(repositories) is True


# --- Loading ahead of a due time ------------------------------------------


def test_naher_termin_laedt_das_hauptmodell_vor(config, client):
    """Three minutes to go, no server up: the model starts now, so the entry
    finds it loaded instead of waiting for it."""
    runner = Runnerattrappe()
    angemeldet = runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf", kontext=4096, schichten=20, port=9911)
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)

    assert [modell for modell, _ in runner.starts] == ["klein.gguf"]
    # Window, layers and port come out of the stored choice, never from here.
    _, werte = runner.starts[0]
    assert werte["kontext"] == 4096
    assert werte["schichten"] == 20
    assert werte["port"] == 9911
    # And the started server joins the model list, or the run that follows
    # could not resolve the field's id at all.
    assert [endpunkt.id for endpunkt in angemeldet] == ["runner"]
    assert "9911" in angemeldet[0].base_url


def test_ferner_termin_laedt_nichts_vor(config, client):
    """Half an hour away is outside the reach — the ceiling is ten minutes."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="13:30", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)

    assert runner.starts == []


def test_ueberfaelliger_termin_laedt_vor(config, client):
    """A due time already missed has no lead left to measure — it needs the
    model now. The service was off, is back on, and the entry wants to run."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="12:00", angelegt=JETZT - timedelta(days=1))

    takt(client, JETZT)

    assert [modell for modell, _ in runner.starts] == ["klein.gguf"]


def test_die_gemessene_ladezeit_bestimmt_die_reichweite(config, client):
    """A measurement only ever NARROWS the reach — the ten-minute ceiling is
    what an unmeasured file already gets. One minute to load buys the
    five-minute floor, so eight minutes out is still too early for this one
    and four minutes is not."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    modellvorlauf.messung_setzen(client.app.state.repositories, "klein.gguf", 60)
    aufbauen(config, client, zeitplan="13:08", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)  # eight minutes off, reach is five
    assert runner.starts == []

    takt(client, JETZT + timedelta(minutes=4))  # four minutes off
    assert [modell for modell, _ in runner.starts] == ["klein.gguf"]


# --- The other two rows of the loading table stay exactly as they were ----


def test_feld_auf_slot_laedt_das_hauptmodell_nicht_vor(config, client):
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, "klein.gguf", sorte="slot")
    startwahl_setzen(client, modell="gross.gguf")
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)

    assert runner.starts == []


def test_feld_auf_cloud_laedt_nichts_vor(config, client):
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, "pruefstand:gpt-4o")
    startwahl_setzen(client, modell="gross.gguf")
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)

    assert runner.starts == []


def test_ohne_wahl_laedt_das_hauptmodell_vor(config, client):
    """Nothing chosen means the main model, so a due schedule
    preloads it — exactly as when the main model was picked by hand.

    It used to load nothing at all: the field said "off", while the run it
    belonged to would still have landed on the main model. The schedule then
    waited for a server nobody had started."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_leer(client)
    startwahl_setzen(client, modell="gross.gguf")
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)

    assert [modell for modell, _ in runner.starts] == ["gross.gguf"]


async def test_ein_antwortender_agentenserver_ersetzt_das_vorladen(config, client):
    """While the agent server answers, a run goes to IT — it is the first of
    the two servers a run may take. Loading the main model ahead
    of a due time would then be memory held for a run that lands elsewhere,
    and a load that could take a server out from under whoever is chatting
    with it: the preload follows the run, and this run does not wait for that
    model.

    The counter-check is the test above: with the agent server gone, the same
    due time loads the main model."""
    # The agent server answers: it arrives the way its own process does when
    # it comes up (app/agentenserver.py), and the stand-in answers in its
    # place so no llama-server is needed. Asked BEFORE the runner stand-in:
    # that one takes the discovery's `anmelden` for its own bookkeeping
    # (`runner_einsetzen`).
    from tests.test_cronfunde import werkzeugfaehig

    endpunkt = agentenserver.endpunkt_bauen()
    await client.app.state.discovery.anmelden(endpunkt)
    provider_setzen(
        client,
        MockProvider(endpunkt, haeppchen=["Ok."]),
        endpoint_id=agentenserver.ENDPUNKT_ID,
    )
    # Tool-capable on purpose: the gate asks the tool question (a run that
    # might need tools is the one that waits), so only an agent server that
    # can really take such a run keeps the preload away. The test below is
    # the other side of the same line.
    werkzeugfaehig(client, agentenserver.ENDPUNKT_ID, True)
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    startwahl_setzen(client, modell="gross.gguf")
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1))
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)

    # One tick of the clock, the way `takt` drives it — inline, because the
    # registration above needs a running loop.
    await client.app.state.wecker.einmal_pruefen(jetzt=JETZT)

    assert runner.starts == []


def test_ein_gewaehltes_runner_modell_laedt_ebenso_vor(config, client):
    """``runner:<modell>`` is the same server as ``runner``: the settings route
    accepts both, and the preload is about the SERVER being up, not about
    which of its models was named. Read as "somewhere else", the due time
    would wait on a model nobody starts."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, f"{agentenmodellwahl.HAUPTMODELL}:gross.gguf")
    startwahl_setzen(client, modell="gross.gguf")
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)

    assert [modell for modell, _ in runner.starts] == ["gross.gguf"]


async def test_ein_werkzeugloser_agentenserver_laesst_das_hauptmodell_vorladen(
    config, client
):
    """The preload follows the run's own order, and that order asks the tool
    question: an agent server that answers but cannot call tools is not where
    a tool-using run lands. The main model is — and it is the one that has to
    be up before the due time, or the entry waits on a server nobody starts.

    The case the first version of this gate got wrong: it asked the agent
    server without the tool question, saw it answer and loaded nothing."""
    from tests.test_cronfunde import werkzeugfaehig

    endpunkt = agentenserver.endpunkt_bauen()
    await client.app.state.discovery.anmelden(endpunkt)
    provider_setzen(
        client,
        MockProvider(endpunkt, haeppchen=["Ok."]),
        endpoint_id=agentenserver.ENDPUNKT_ID,
    )
    werkzeugfaehig(client, agentenserver.ENDPUNKT_ID, False)
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    startwahl_setzen(client, modell="gross.gguf")
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1))
    agentenmodell_leer(client)

    await client.app.state.wecker.einmal_pruefen(jetzt=JETZT)

    assert [modell for modell, _ in runner.starts] == ["gross.gguf"]


# --- What is running is not touched ---------------------------------------


def test_laufender_hauptserver_wird_nicht_angefasst(config, client):
    """Not even when it holds a different file than the stored choice names.
    ``runner`` means "whatever the main server is running", and swapping it
    would take the model out from under whoever is using it."""
    runner = Runnerattrappe(laeuft=True)
    runner._lauf = SimpleNamespace(modell="ganz-anderes.gguf", port=8080, kontext=32768)
    angemeldet = runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)

    assert runner.starts == []
    assert angemeldet == []
    assert runner.lauf().modell == "ganz-anderes.gguf"


# --- Nothing chosen is nothing to load ------------------------------------


@pytest.mark.parametrize("gewaehlt", [None, ""])
def test_ohne_gewaehlte_datei_wird_nichts_geladen(config, client, gewaehlt):
    """``None`` (never chosen) and ``""`` (chosen: none) are two different
    answers to "which file" and the same answer to this question. Neither
    may turn into a guess."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell=gewaehlt)
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)

    assert runner.starts == []


# --- A script entry has no model to load ----------------------------------


def test_skript_termin_laedt_nichts_vor(config, client):
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1),
             skript="sicherung.sh")

    takt(client, JETZT)

    assert runner.starts == []


# --- One attempt per due moment, never one per tick -----------------------


def test_kein_dauerfeuer_ueber_viele_takte(config, client):
    """Ten ticks inside the reach, one start. The first brings the server up
    and the rest see it running."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="13:05", angelegt=JETZT - timedelta(hours=1))

    for schritt in range(10):
        takt(client, JETZT + timedelta(seconds=30 * schritt))

    assert len(runner.starts) == 1


def test_gescheitertes_vorladen_versucht_es_nicht_jeden_takt_erneut(config, client):
    """A refused start is one attempt for that due moment, not one every
    thirty seconds. The entry waits visibly instead, exactly as it did
    before any of this existed — no run, no failure counted."""
    runner = Runnerattrappe(fehler="kein_programm")
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    cronjob_id = aufbauen(
        config, client, zeitplan="13:05", angelegt=JETZT - timedelta(hours=1)
    )

    for schritt in range(10):
        takt(client, JETZT + timedelta(seconds=30 * schritt))

    assert len(runner.starts) == 1
    assert client.get("/api/v1/jobs").json() == []
    (eintrag,) = client.get("/api/v1/cronjobs").json()
    assert eintrag["id"] == cronjob_id
    assert eintrag["fehlversuche"] == 0


def test_der_naechste_termin_bekommt_einen_eigenen_versuch(config, client):
    """The block is per due moment, not per entry: a schedule that came due
    again is a new moment and gets its own attempt."""
    runner = Runnerattrappe(fehler="kein_programm")
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/15 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT + timedelta(minutes=6))   # 13:15 is nine minutes off
    takt(client, JETZT + timedelta(minutes=7))   # same moment, no second try
    assert len(runner.starts) == 1

    takt(client, JETZT + timedelta(minutes=21))  # 13:30 — a new due moment
    assert len(runner.starts) == 2


# ==========================================================================
# A load that dies on the way up, a stop by hand
# that has to hold, and a reach measured in real seconds rather than in
# wall-clock ones.
# ==========================================================================

import logging
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
# The night the clocks go forward: 02:00 CET becomes 03:00 CEST, so the hour
# between them never happens. Every schedule between 02:00 and roughly 03:10
# is read across that gap.
VOR_DER_UMSTELLUNG = datetime(2027, 3, 28, 1, 58, tzinfo=BERLIN)
ANGELEGT_VOR_DER_UMSTELLUNG = datetime(2027, 3, 28, 0, 30, tzinfo=BERLIN)


# --- A load that dies while loading ---------------------------------------


def test_sterbender_ladeversuch_wird_nicht_jeden_takt_wiederholt(config, client, caplog):
    """The third way a start comes to nothing, and at nineteen gigabytes the
    likeliest: the process starts and llama-server dies while loading. The
    old bolt only knew "refused" and "already up", so every further due
    moment was a fresh full load — once a minute on a ``*/1`` schedule."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    with caplog.at_level(logging.WARNING, logger="app.modellvorlauf"):
        takt(client, JETZT)
        assert len(runner.starts) == 1
        runner.abstuerzen()
        # Twenty ticks, ten minutes, ten fresh due moments of that schedule.
        for schritt in range(1, 21):
            takt(client, JETZT + timedelta(seconds=30 * schritt))

    assert len(runner.starts) == 1
    gestorben = [
        satz.getMessage() for satz in caplog.records
        if getattr(satz, "ereignis", None) == "hauptmodell_laden_gestorben"
    ]
    # Said once, not once per tick — the same rule the load itself obeys.
    assert len(gestorben) == 1
    assert "klein.gguf" in gestorben[0]


def test_mehrere_nahe_termine_geben_nicht_mehrere_ladeversuche(config, client):
    """The amplifier: the loop walks on to the next entry after one has been
    dealt with, so three entries inside the reach used to mean three full
    load attempts in three ticks. The bolt is on the file, not the entry."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    for minute in ("13:03", "13:04", "13:05"):
        aufbauen(config, client, zeitplan=minute, angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    assert len(runner.starts) == 1
    runner.abstuerzen()
    for schritt in range(1, 11):
        takt(client, JETZT + timedelta(seconds=30 * schritt))

    assert len(runner.starts) == 1


def test_die_sperre_faellt_bei_einer_anderen_datei(config, client):
    """It stands down for the file that would not come up, not for preloading
    as such — another file is another question."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    runner.abstuerzen()
    takt(client, JETZT + timedelta(seconds=30))
    assert len(runner.starts) == 1

    startwahl_setzen(client, modell="anderes.gguf")
    takt(client, JETZT + timedelta(minutes=5))

    assert [modell for modell, _ in runner.starts] == ["klein.gguf", "anderes.gguf"]


def test_die_sperre_faellt_wenn_der_server_von_hand_bereit_wird(config, client):
    """A main server that BECAME READY is the all-clear: whatever kept the
    last load from coming up is over.

    Up is not the same as ready, and this test used to settle for up — which
    is exactly what let the stand-down's level be dropped by the retry that
    was still reading its file (see below)."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    runner.abstuerzen()
    takt(client, JETZT + timedelta(seconds=30))
    assert modellvorlauf._ruhe is not None
    assert modellvorlauf._ruhe.datei == "klein.gguf"

    runner._laeuft = True
    endpunkt_erreichbar_setzen(client)                # and it answered
    takt(client, JETZT + timedelta(minutes=1))

    assert modellvorlauf._ruhe is None


def test_feld_woanders_vergisst_die_beobachtung(config, client):
    """While the field points at the slot or a cloud endpoint nothing is
    being preloaded, so nothing that happens to the main server in that
    stretch may be held against the first preload afterwards."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    runner.abstuerzen()
    takt(client, JETZT + timedelta(seconds=30))
    assert modellvorlauf._ruhe is not None
    assert modellvorlauf._ruhe.datei == "klein.gguf"

    agentenmodell_setzen(client, "gibtesnicht.gguf", sorte="slot")
    takt(client, JETZT + timedelta(minutes=1))

    assert modellvorlauf._ruhe is None


# --- A stop by hand has to hold -------------------------------------------


def test_stopp_von_hand_haelt_bei_nahendem_termin(config, client, caplog):
    """Switched off at 12:56 to get the memory back, with a due time at
    13:00. The tick thirty seconds later used to see "field on the main
    model, nothing running, a file named, that moment never tried" and start
    the same nineteen gigabytes again — the stop held for half a minute."""
    runner = Runnerattrappe(laeuft=True)
    runner._lauf = SimpleNamespace(modell="klein.gguf", port=8080, kontext=8192)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="13:00", angelegt=JETZT - timedelta(hours=2))

    zwoelf56 = JETZT - timedelta(minutes=4)
    with caplog.at_level(logging.INFO, logger="app.modellvorlauf"):
        takt(client, zwoelf56)          # the user's server, seen running
        runner.stoppen()                # ... and switched off by hand
        for schritt in range(1, 21):    # ten minutes of ticks across 13:00
            takt(client, zwoelf56 + timedelta(seconds=30 * schritt))

    assert runner.starts == []
    assert runner.laeuft() is False
    ausgesetzt = [
        satz.getMessage() for satz in caplog.records
        if getattr(satz, "ereignis", None) == "hauptmodell_vorladen_ausgesetzt"
    ]
    assert len(ausgesetzt) == 1


def test_der_stopp_deckt_nur_die_termine_in_seiner_reichweite(config, client):
    """It must not hold for ever, or nothing would ever preload again — with
    the field on the main model this is the only thing that brings the server
    up at all. What the stop cancels is the preload it was aimed at: the due
    moment inside one reach of it. A later one gets its own."""
    runner = Runnerattrappe(laeuft=True)
    runner._lauf = SimpleNamespace(modell="klein.gguf", port=8080, kontext=8192)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="13:00", angelegt=JETZT - timedelta(hours=2))
    aufbauen(config, client, zeitplan="13:30", angelegt=JETZT - timedelta(hours=2),
             agent="zweiter")

    zwoelf56 = JETZT - timedelta(minutes=4)
    takt(client, zwoelf56)
    runner.stoppen()
    takt(client, zwoelf56 + timedelta(seconds=30))
    assert runner.starts == []

    # Half an hour on: 13:30 was never within a reach of the stop.
    takt(client, JETZT + timedelta(minutes=25))

    assert [modell for modell, _ in runner.starts] == ["klein.gguf"]


def test_ein_geglueckter_lauf_der_verschwindet_ist_kein_absturz(config, client, caplog):
    """A server that reported ready and went away later was switched off, not
    killed by the load. Every finished load writes its seconds down here, so
    a measurement that moved is the proof — and the two get different lines
    and different consequences."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    assert len(runner.starts) == 1
    # What app/main.py's bereit_callback does the moment the server says it
    # is ready.
    modellvorlauf.messung_setzen(client.app.state.repositories, "klein.gguf", 12.5)
    runner.stoppen()

    with caplog.at_level(logging.INFO, logger="app.modellvorlauf"):
        takt(client, JETZT + timedelta(seconds=30))

    assert [
        satz for satz in caplog.records
        if getattr(satz, "ereignis", None) == "hauptmodell_laden_gestorben"
    ] == []
    assert modellvorlauf._ruhe is None


# --- The reach is measured in real seconds, not wall-clock ones -----------


def test_abstand_rechnet_ueber_die_zeitumstellung_richtig():
    """Two datetimes carrying one and the same ``ZoneInfo`` subtract without
    either being asked for its offset — which is the wall clock, and on two
    days a year the wall clock is not the truth."""
    moment = datetime(2027, 3, 28, 3, 5, tzinfo=BERLIN)
    assert (moment - VOR_DER_UMSTELLUNG).total_seconds() == 4020
    assert modellvorlauf.abstand_sekunden(moment, VOR_DER_UMSTELLUNG) == 420


@pytest.mark.parametrize("zeitplan", ["03:05", "5 3 * * *", "2027-03-28T03:05"])
def test_die_umstellungsnacht_laedt_trotzdem_vor(config, client, zeitplan):
    """All three schedule shapes, the same night: seven real minutes to go,
    sixty-seven on the wall clock. Read the wall clock and the preload finds
    it out of reach — and the next tick is already past 03:00 with the entry
    due, which is the one case this exists to prevent."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan=zeitplan, angelegt=ANGELEGT_VOR_DER_UMSTELLUNG)

    takt(client, VOR_DER_UMSTELLUNG)

    assert [modell for modell, _ in runner.starts] == ["klein.gguf"]


# --- The port the server actually came up on ------------------------------


def test_anmeldung_nimmt_den_port_aus_dem_start(config, client):
    """A process that is gone again before anybody looks used to be announced
    on the runner's DEFAULT port, because ``lauf()`` answers None for it and
    the fallback behind it was that default. The start itself knows which
    port it used."""
    runner = Runnerattrappe(stirbt_sofort=True)
    angemeldet = runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf", port=9911)
    aufbauen(config, client, zeitplan="13:03", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)

    assert runner.lauf() is None
    assert "9911" in angemeldet[0].base_url
    assert "8080" not in angemeldet[0].base_url


# ==========================================================================
# Nothing here may stop for ever. A stop
# pressed while the file was still being read is a stop and not a crash, and
# a stand-down that nobody lifts is a preload that never runs again.
# ==========================================================================


def endpunkt_erreichbar_setzen(client, erreichbar: bool = True) -> None:
    """What the discovery holds about the endpoint the preload announced.

    The real one puts this there itself, one check after ``anmelden`` — and
    reachable means the server answered ``/v1/models`` under 500, which a
    llama-server still reading its file does not.
    """
    from app.api.v1.runner import RUNNER_ID, _runner_endpunkt
    from app.discovery import EndpunktZustand, provider_bauen

    from app import fenstergroesse

    endpunkt = _runner_endpunkt(8080)
    zustand = EndpunktZustand(endpunkt=endpunkt, provider=provider_bauen(endpunkt))
    zustand.erreichbar = erreichbar
    # The real one resolves a window in the same pass (app/fenstergroesse.py),
    # and a request's own answer ceiling is measured against it
    # (app/antwortgrenze.py) — so a reachable endpoint here has one too.
    zustand.context_tokens = fenstergroesse.ERSATZ
    zustand.kontext_quelle = fenstergroesse.QUELLE_ERSATZ
    client.app.state.discovery.zustaende[RUNNER_ID] = zustand


# --- A stop while the file is still being read is a stop -------------------


def test_stopp_waehrend_des_ladens_ist_kein_absturz(config, client, caplog):
    """The user presses stop while the nineteen gigabytes are still going in
    — he wants that memory back now. Nothing had been measured yet and the
    server never answered, so by the old reading this was a load that died,
    and the file's preload stood down for good."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    assert len(runner.starts) == 1
    # Still loading: no measurement was ever written for this start.
    assert modellvorlauf.messung_holen(client.app.state.repositories, "klein.gguf") is None
    runner.stoppen()

    with caplog.at_level(logging.WARNING, logger="app.modellvorlauf"):
        takt(client, JETZT + timedelta(seconds=30))

    assert [
        satz for satz in caplog.records
        if getattr(satz, "ereignis", None) == "hauptmodell_laden_gestorben"
    ] == []
    assert modellvorlauf._ruhe is None
    assert modellvorlauf._stopp is not None


def test_stopp_waehrend_des_ladens_haelt_nur_seine_reichweite(config, client):
    """The core of it: the stop keeps its own reach and no more. Before, this
    file never preloaded again at all — half an hour of due moments and not
    one attempt.

    The measurement makes the two readings tell each other apart: a minute of
    load buys the five-minute floor, so a stop covers the due moments within
    five minutes of it, while a load counted as DEAD stands down for ten. The
    server comes back inside six."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    modellvorlauf.messung_setzen(client.app.state.repositories, "klein.gguf", 60)
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    assert len(runner.starts) == 1
    runner.stoppen()                              # still loading, nothing measured since

    zweiter = None
    for schritt in range(1, 61):                  # half an hour of ticks
        jetzt = JETZT + timedelta(seconds=30 * schritt)
        takt(client, jetzt)
        if zweiter is None and len(runner.starts) > 1:
            zweiter = jetzt
        if len(runner.starts) > 1:
            runner.stoppen()                      # keep it cold, to count the first one only

    assert zweiter is not None
    assert zweiter - JETZT <= timedelta(minutes=7)


# --- The stand-down after a load that really died has an end on it ---------


def test_ein_echter_absturz_beim_laden_wird_weiter_nicht_wiederholt(config, client):
    """The proof from 502615a has to keep standing: within the stretch, one
    attempt, not one per due moment."""
    runner = Runnerattrappe(stirbt_sofort=True)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    for schritt in range(21):  # ten minutes, ten fresh due moments
        takt(client, JETZT + timedelta(seconds=30 * schritt))

    assert len(runner.starts) == 1


def test_die_ruhe_endet_und_der_vorlauf_versucht_es_wieder(config, client, caplog):
    """And after the stretch it tries again — without the user doing
    anything. The likeliest cause of a load dying is memory somebody else
    holds, and freeing it is none of the four things that used to lift the
    bolt."""
    runner = Runnerattrappe(stirbt_sofort=True)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    takt(client, JETZT + timedelta(seconds=30))       # the death is noticed
    assert len(runner.starts) == 1
    assert modellvorlauf._ruhe is not None

    with caplog.at_level(logging.INFO, logger="app.modellvorlauf"):
        takt(client, JETZT + timedelta(minutes=16))   # the stretch is over

    assert len(runner.starts) == 2
    vorbei = [
        satz for satz in caplog.records
        if getattr(satz, "ereignis", None) == "hauptmodell_ruhe_vorbei"
    ]
    assert len(vorbei) == 1


def test_ein_taeglicher_termin_bekommt_nach_der_ruhe_wirklich_einen_versuch(config, client):
    """The stand-down would end on paper only without this: an overdue entry
    keeps naming the SAME due moment on every tick (app/cronablauf.py), and
    that moment is already in the "already attempted" memory. A daily entry
    whose preload died would never see a second attempt at all."""
    runner = Runnerattrappe(stirbt_sofort=True)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="13:05", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)                               # 13:05 is five minutes off
    takt(client, JETZT + timedelta(seconds=30))       # the death is noticed
    assert len(runner.starts) == 1

    # 13:16: the entry is overdue and still names 13:05, exactly as before.
    takt(client, JETZT + timedelta(minutes=16))

    assert len(runner.starts) == 2


def test_die_ruhe_bleibt_bei_jedem_gescheiterten_ladeversuch_dieselbe(config, client):
    """Fifteen minutes, then fifteen, then fifteen: the wait is as long as
    there is reason for it, and the reason is the same every time — one load
    came to nothing and nothing has changed since.

    It used to double (10, 20, 40, 80 … capped at a day) on the guess that a
    load which has failed often is less likely to work next time. The program
    cannot tell WHY a load died, so after the eighth failure it knows exactly
    what it knew after the first, and the guess was buying hours of silence
    with nothing behind them."""
    runner = Runnerattrappe(stirbt_sofort=True)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    fenster = []
    zeit = JETZT
    for _ in range(4):
        takt(client, zeit)                            # the attempt
        takt(client, zeit + timedelta(seconds=30))    # the death is noticed
        fenster.append(modellvorlauf._ruhe.bis - (zeit + timedelta(seconds=30)))
        zeit = modellvorlauf._ruhe.bis + timedelta(seconds=30)

    assert len(runner.starts) == 4
    assert [int(spanne.total_seconds() // 60) for spanne in fenster] == [15, 15, 15, 15]


def test_die_stufenrechnung_ist_weg():
    """No dead remainder: one flat stretch and no number counting failures.

    A level that nothing reads any more is worse than no level — the next
    reader takes it for a promise the program does not keep."""
    assert modellvorlauf.RUHE_SEKUNDEN == 15 * 60
    assert not hasattr(modellvorlauf, "_ruhefenster")
    assert not hasattr(modellvorlauf, "RUHE_ERST_SEKUNDEN")
    assert not hasattr(modellvorlauf, "RUHE_HOECHST_SEKUNDEN")
    assert "stufe" not in modellvorlauf._Ruhe.__dataclass_fields__


# --- A refused start does not cost the entry every attempt there is --------


def test_ein_abgelehnter_start_wird_nach_der_ruhe_wiederholt(config, client):
    """A port still held by a server on its way down used to cost an overdue
    entry everything: the refusal went into the memory for a due moment that,
    while the entry stays overdue, never changes again. Measured before this:
    one start in three days."""
    runner = Runnerattrappe(fehler="port_belegt")
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="13:05", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    assert len(runner.starts) == 1
    for schritt in range(1, 30):                      # a quarter hour: no second try
        takt(client, JETZT + timedelta(seconds=30 * schritt))
    assert len(runner.starts) == 1

    runner._fehler = None                             # the port is free again
    takt(client, JETZT + timedelta(minutes=16))

    assert len(runner.starts) == 2
    assert runner.laeuft() is True


# --- The second witness for "it became ready", the one with no text in it --


def test_der_erreichbare_endpunkt_beweist_dass_geladen_wurde(config, client):
    """Whether a load finished is read off a measurement, and that
    measurement is written when the engine's log says "model loaded"
    (app/modellrunner.py). Rename that line in llama.cpp and no measurement
    is ever written again — every preloaded server that goes away, even after
    hours, would count as died-on-the-way-up. The endpoint answering is the
    same proof without a text in it."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    endpunkt_erreichbar_setzen(client)                # the server answered
    takt(client, JETZT + timedelta(seconds=30))
    # Nobody stopped it, and no measurement was ever written.
    runner.abstuerzen()
    takt(client, JETZT + timedelta(minutes=1))

    assert modellvorlauf.messung_holen(client.app.state.repositories, "klein.gguf") is None
    assert modellvorlauf._ruhe is None
    assert modellvorlauf._stopp is not None


def test_ein_nie_erreichbarer_endpunkt_bleibt_ein_toter_ladeversuch(config, client):
    """The counter-check: the endpoint never answered, so the second witness
    says nothing and the first one decides — this really is a load that
    died."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    endpunkt_erreichbar_setzen(client, erreichbar=False)
    takt(client, JETZT + timedelta(seconds=30))
    runner.abstuerzen()
    takt(client, JETZT + timedelta(minutes=1))

    assert modellvorlauf._ruhe is not None
    assert modellvorlauf._ruhe.datei == "klein.gguf"



# ==========================================================================
# The wait is as long as there is reason for
# it, and no longer. One flat quarter of an hour, every time — the doubling
# is gone, and with it the level, the cap and the whole idea that a load
# which has failed often is less likely to work next time. The program does
# not know why a load died, so the eighth failure teaches it nothing the
# first did not.
#
# The stand-in used below outlives a tick (`ueberlebt_takte`), which is what
# a real nineteen-gigabyte load does: it is found ALIVE by at least one
# thirty-second tick before it is found gone. `stirbt_sofort` covers only
# the opposite case.
# ==========================================================================


def test_ein_ladender_server_hebt_die_ruhe_nicht_auf(config, client):
    """A process that is merely alive says nothing about whether the file
    fits — it is the attempt, not its result. Were it read as an all-clear, a
    hand start that then died mid-load would leave no stand-down at all and
    the preload would be back at the very next due moment."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    runner.abstuerzen()
    takt(client, JETZT + timedelta(seconds=30))
    assert modellvorlauf._ruhe is not None

    # The stretch is over, the second attempt runs — and is still loading a
    # tick later: nothing measured, endpoint silent.
    takt(client, JETZT + timedelta(minutes=16))
    assert len(runner.starts) == 2
    assert runner.laeuft() is True
    takt(client, JETZT + timedelta(minutes=16, seconds=30))

    assert modellvorlauf._ruhe is not None


def test_ein_bereit_gewordener_server_hebt_die_ruhe_auf(config, client):
    """The other half, so the bolt above cannot be paid for by never lifting
    at all: once the server answers, the stand-down is gone. This is what
    makes a start by hand end the wait on the spot."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    runner.abstuerzen()
    takt(client, JETZT + timedelta(seconds=30))
    assert modellvorlauf._ruhe is not None

    takt(client, JETZT + timedelta(minutes=16))
    assert len(runner.starts) == 2
    endpunkt_erreichbar_setzen(client)                # it answered /v1/models
    takt(client, JETZT + timedelta(minutes=16, seconds=30))

    assert modellvorlauf._ruhe is None


def test_ein_start_von_hand_beendet_die_ruhe_sofort(config, client):
    """Nobody has to wait out the quarter of an hour: the user brings the
    file up himself, it answers, and the stretch is over on that tick — the
    file plainly loads, so there is no reason left to wait."""
    runner = Runnerattrappe(stirbt_sofort=True)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    takt(client, JETZT + timedelta(seconds=30))       # the death is noticed
    assert modellvorlauf._ruhe is not None
    assert modellvorlauf._ruhe.bis - JETZT == timedelta(minutes=15, seconds=30)

    # Two minutes in — thirteen of the fifteen still to go.
    runner._laeuft = True
    runner._stirbt_sofort = False
    endpunkt_erreichbar_setzen(client)
    takt(client, JETZT + timedelta(minutes=2))

    assert modellvorlauf._ruhe is None


def test_ein_laufender_server_der_nicht_antwortet_haelt_die_ruhe(config, client):
    """The counter-check to the two above, and the one that was missing: up
    is not ready. A server that is running but has never answered — a hand
    start whose port is wrong, or a key the discovery is refused with — is
    not proof that the file loads, so the wait stands.

    It ends anyway, fifteen minutes after the death that started it. Nothing
    here stops for good, which is why this bolt is allowed to be this tight:
    the evidence says nothing, so the wait is neither cut short nor extended.
    """
    runner = Runnerattrappe(stirbt_sofort=True)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    takt(client, JETZT + timedelta(seconds=30))       # the death is noticed
    assert modellvorlauf._ruhe is not None

    # Up by hand, and it never answers: no measurement, endpoint unreachable.
    runner._laeuft = True
    runner._stirbt_sofort = False
    endpunkt_erreichbar_setzen(client, erreichbar=False)
    for schritt in range(4, 20):                      # eight more minutes
        takt(client, JETZT + timedelta(seconds=30 * schritt))

    assert modellvorlauf._ruhe is not None
    assert modellvorlauf._ruhe.datei == "klein.gguf"
    assert modellvorlauf.messung_holen(client.app.state.repositories, "klein.gguf") is None


def test_die_gemessene_ladezeit_beweist_es_genauso(config, client):
    """The first of the two witnesses on its own: the endpoint says nothing,
    but the finished load wrote its seconds down (app/main.py's
    bereit_callback). No third proof was built for this.

    The file carries a measurement from an earlier load before any of this
    starts, so what counts is that the number MOVED, not that one exists —
    an older measurement of the same file says nothing about this run."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    modellvorlauf.messung_setzen(client.app.state.repositories, "klein.gguf", 7)
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    runner.abstuerzen()
    takt(client, JETZT + timedelta(seconds=30))
    assert modellvorlauf._ruhe is not None

    takt(client, JETZT + timedelta(minutes=16))
    assert len(runner.starts) == 2
    endpunkt_erreichbar_setzen(client, erreichbar=False)
    modellvorlauf.messung_setzen(client.app.state.repositories, "klein.gguf", 42)
    takt(client, JETZT + timedelta(minutes=16, seconds=30))

    assert modellvorlauf._ruhe is None


def test_die_ruhe_bleibt_auch_ueber_takte_hinweg_bei_fuenfzehn(config, client):
    """The measurement that used to read [10, 20, 40, 80], taken again with a
    load that behaves like a real one: [15, 15, 15, 15]. The reason to wait
    is the same every time, so the wait is."""
    runner = Runnerattrappe(ueberlebt_takte=1)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    fenster = []
    zeit = JETZT
    for _ in range(4):
        takt(client, zeit)                            # the attempt
        takt(client, zeit + timedelta(seconds=30))    # still loading, alive
        assert runner.laeuft() is False               # it died between the ticks
        takt(client, zeit + timedelta(seconds=60))    # the death is noticed
        gemerkt = zeit + timedelta(seconds=60)
        fenster.append(modellvorlauf._ruhe.bis - gemerkt)
        zeit = modellvorlauf._ruhe.bis + timedelta(seconds=30)

    assert len(runner.starts) == 4
    assert [int(spanne.total_seconds() // 60) for spanne in fenster] == [15, 15, 15, 15]


def test_ueber_einen_ganzen_tag_gleichmaessig(config, client):
    """A whole simulated day of thirty-second ticks with a due moment every
    minute: the gaps stay the same size from the first attempt to the last,
    and the second day looks like the first. No growing silence, and no
    twenty-four-hour hole at the end of it."""
    runner = Runnerattrappe(ueberlebt_takte=1)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    minuten = []
    for schritt in range(2 * 60 * 24):                # 24 hours, 2880 ticks
        vorher = len(runner.starts)
        takt(client, JETZT + timedelta(seconds=30 * schritt))
        if len(runner.starts) > vorher:
            minuten.append(schritt // 2)
    erster_tag = len(runner.starts)

    for schritt in range(2 * 60 * 24, 2 * 60 * 48):   # and the second day
        takt(client, JETZT + timedelta(seconds=30 * schritt))
    zweiter_tag = len(runner.starts) - erster_tag

    # One attempt, fifteen minutes of stand-down, one more: sixteen minutes
    # from attempt to attempt, all day long.
    abstaende = {b - a for a, b in zip(minuten, minuten[1:])}
    assert abstaende == {16}
    assert erster_tag == 90
    assert abs(zweiter_tag - erster_tag) <= 1


def test_ein_ladeversuch_der_einen_takt_ueberlebt_wird_nicht_jeden_takt_wiederholt(
        config, client):
    """The core of 502615a, taken with the same stand-in: within one reach,
    one attempt — not one per due moment and not one per tick, however long
    the dying load stayed alive."""
    runner = Runnerattrappe(ueberlebt_takte=1)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    for minute in ("13:03", "13:04", "13:05"):
        aufbauen(config, client, zeitplan=minute, angelegt=JETZT - timedelta(hours=1))

    for schritt in range(21):                         # ten minutes, three entries
        takt(client, JETZT + timedelta(seconds=30 * schritt))

    assert len(runner.starts) == 1


def test_die_ruhe_endet_auch_nach_einem_ladeversuch_der_einen_takt_ueberlebt(
        config, client):
    """And it still ends without the user doing anything — the whole point of
    the stretch. The bolt above must not turn into the "never again" it
    replaced."""
    runner = Runnerattrappe(ueberlebt_takte=1)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/5 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    takt(client, JETZT + timedelta(seconds=30))
    takt(client, JETZT + timedelta(seconds=60))       # the death is noticed
    assert len(runner.starts) == 1

    takt(client, JETZT + timedelta(minutes=16))

    assert len(runner.starts) == 2


# --- A success no tick ever saw ------------------------------------------
# The retry finishes loading and is gone again before the next tick looks —
# the user stops it right after the load, or it falls over. `gestorben` is
# correctly False (the measurement moved), so no stand-down is written, but
# the one from before is left standing.
#
# While the stretch doubled, that cost a level: the next death read as the
# second in a row and stood down for twenty minutes instead of ten. With one
# flat stretch there is no level to leave standing, and the object that is
# left is inert — it has already been released, so it refuses nothing. The
# two tests below are what says so rather than assuming it.


def test_ein_erfolg_zwischen_zwei_takten_schreibt_keine_ruhe(config, client):
    """The load finished, so this is not a death — it is a stop, and the
    stand-down that is still lying there is the released one, not a new
    one."""
    runner = Runnerattrappe(ueberlebt_takte=1)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    takt(client, JETZT + timedelta(seconds=30))
    takt(client, JETZT + timedelta(seconds=60))       # the death is noticed
    erste_ruhe = modellvorlauf._ruhe
    assert erste_ruhe is not None

    # The stretch is over and the retry runs. This one loads — and is gone
    # before the next tick looks.
    takt(client, JETZT + timedelta(minutes=16))
    assert len(runner.starts) == 2
    modellvorlauf.messung_setzen(client.app.state.repositories, "klein.gguf", 12.5)
    runner.abstuerzen()
    takt(client, JETZT + timedelta(minutes=16, seconds=30))

    assert modellvorlauf._ruhe is erste_ruhe          # nothing new was written
    assert modellvorlauf._ruhe.freigegeben is True    # and it refuses nothing
    assert modellvorlauf._stopp is not None


def test_nach_einem_ungesehenen_erfolg_wartet_der_naechste_tod_wieder_fuenfzehn(
        config, client):
    """The consequence, in the number that matters: the death after a success
    nobody saw stands down for fifteen minutes, exactly like the one before
    it. While the stretch doubled this read twenty."""
    runner = Runnerattrappe(ueberlebt_takte=1)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    takt(client, JETZT + timedelta(seconds=30))
    takt(client, JETZT + timedelta(seconds=60))
    assert modellvorlauf._ruhe.bis - (JETZT + timedelta(seconds=60)) == timedelta(minutes=15)

    takt(client, JETZT + timedelta(minutes=16))       # the retry — and it loads
    assert len(runner.starts) == 2
    modellvorlauf.messung_setzen(client.app.state.repositories, "klein.gguf", 12.5)
    runner.abstuerzen()
    takt(client, JETZT + timedelta(minutes=16, seconds=30))

    # On to the next attempt: the stop covers the due moments within one
    # reach of it, the ones after that preload as usual.
    dritter = None
    zeit = JETZT + timedelta(minutes=16, seconds=30)
    for _ in range(60):
        zeit += timedelta(seconds=30)
        takt(client, zeit)
        if len(runner.starts) == 3:
            dritter = zeit
            break
    assert dritter is not None

    takt(client, dritter + timedelta(seconds=30))     # still loading, alive
    takt(client, dritter + timedelta(seconds=60))     # the death is noticed

    assert modellvorlauf._ruhe.bis - (dritter + timedelta(seconds=60)) == timedelta(minutes=15)


# ==========================================================================
# The tick box: may the program bring this server up by itself at all?
# (app/runnermodellwahl.py `vorladen`). Off is the program before preloading existed —
# the entry waits visibly and runs the moment a model is there.
# ==========================================================================


def vorladen_setzen(client, erlaubt: bool) -> None:
    client.app.state.repositories.einstellungen.setzen(
        "global", runnermodellwahl.SCHLUESSEL,
        {**runnermodellwahl.wahl(client.app.state.repositories), "vorladen": erlaubt},
    )


def test_der_schalter_steht_ab_werk_an(client):
    """An installation that has never seen this key preloads exactly as it
    did before the key existed. A default that switches somebody's running
    program off is not a default."""
    assert runnermodellwahl.VORGABE["vorladen"] is True
    assert runnermodellwahl.vorladen_erlaubt(client.app.state.repositories) is True


def test_schalter_aus_laedt_ueber_viele_faelligkeiten_nichts_vor(config, client):
    """Off means off: half an hour of due moments, every minute one, and not
    a single load attempt."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    vorladen_setzen(client, False)
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    for schritt in range(61):                         # half an hour of ticks
        takt(client, JETZT + timedelta(seconds=30 * schritt))

    assert runner.starts == []
    assert runner.laeuft() is False


def test_schalter_an_laedt_vor(config, client):
    """The same run with the tick box set: the preload happens."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    vorladen_setzen(client, True)
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)

    assert [modell for modell, _ in runner.starts] == ["klein.gguf"]


def test_der_schalter_greift_im_selben_takt(config, client):
    """Read on every tick, not once at start: the tick the box is moved is
    the tick it counts on — off stops the very next attempt, on lets it
    through again."""
    runner = Runnerattrappe()
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    vorladen_setzen(client, False)
    takt(client, JETZT)
    assert runner.starts == []

    vorladen_setzen(client, True)
    takt(client, JETZT + timedelta(seconds=30))
    assert len(runner.starts) == 1


def test_ausschalten_waehrend_einer_ruhe_loescht_sie(config, client):
    """Switching the box off while a stand-down is running takes the whole
    thing with it — the user has said the situation is different now, and a
    stretch from before he said it may not still be standing when he switches
    the box back on."""
    runner = Runnerattrappe(stirbt_sofort=True)
    runner_einsetzen(client, runner)
    agentenmodell_setzen(client, agentenmodellwahl.HAUPTMODELL)
    startwahl_setzen(client, modell="klein.gguf")
    aufbauen(config, client, zeitplan="*/1 * * * *", angelegt=JETZT - timedelta(hours=1))

    takt(client, JETZT)
    takt(client, JETZT + timedelta(seconds=30))       # the death is noticed
    assert modellvorlauf._ruhe is not None

    vorladen_setzen(client, False)
    takt(client, JETZT + timedelta(seconds=60))
    assert modellvorlauf._ruhe is None

    # And back on, two minutes into what would have been the stretch: the
    # next due moment preloads instead of waiting the rest of it out.
    runner._stirbt_sofort = False
    vorladen_setzen(client, True)
    takt(client, JETZT + timedelta(minutes=2))

    assert len(runner.starts) == 2
