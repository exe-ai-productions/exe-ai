"""Five holes the review of 78afa26 found in the new reason display.

The reason a run ended reached the eye for the first time in 78afa26. The
review that followed found five places where what reaches the eye is not
quite the truth, and this file is the guard for all five:

F1  A run that handed its work on stood there in red saying "context window
    full" about work that was still going. It ends ``unterbrochen`` now —
    this program's own word for a run that was cut short and can still be
    resumed — so the reason is still read and still shown, quietly.
F2  A dead model server restarts one job up to MAX_NEUSTARTS times, and every
    link left its own row: ten rows about one disturbance. A handed-on link
    steps aside now for anything newer of the same work, and the work is
    named by the chain's origin (``work_id``, from ``ursprung_id``).
F3  The branch drawing "quiet, cut short by a service restart" could never be
    reached: such a run has no result either, and the list only took runs
    that had one or had failed.
F4  A script run's ending reached the reports row and not the notification.
F5  An announcing entry that broke on its last allowed run got TWO
    notifications about one ending — the failure limit's and the blanket one.

The frontend half is not asserted by reading the source for a substring: the
two blocks that decide it are lifted out of the .svelte file and run in node
against real rows, the way tests/test_chatringe.py runs ``ringfarbe.js``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import cronablauf, skriptlauf, speicherorte, wiederversuch, zwischenstand
from app.agenten import agenten_laden
from app.api.v1.auftraege import auftrag_anstossen
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen, script_file

# The run helpers and the near-full-context double live where the jobs API is
# tested — borrowed rather than copied, so a change to how a handoff is
# provoked cannot leave a second, quietly outdated copy behind here.
from tests.test_auftraege_api import (  # noqa: E402
    HANDOFF_ZWEI_PUNKTE,
    NahezuVollerKontext,
    _bis_beendet,
    agent_schreiben,
    auf_ende_warten,
)

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODUL_AGENTEN = FRONTEND / "src" / "teile" / "ModulAgenten.svelte"
LAUFSTAND = FRONTEND / "src" / "lib" / "laufstand.js"

ENDE = {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}

MORGEN = datetime.now(timezone.utc).replace(
    hour=13, minute=0, second=0, microsecond=0
) + timedelta(days=1)


# --- Helpers ----------------------------------------------------------------


def _lauf_ueber_termin(client, config, cronjob_id):
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    return auftrag_anstossen(
        config=client.app.state.config,
        repositories=client.app.state.repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Los",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=cronjob_id,
    )


# --- F1 · a handed-on run is not a failure ----------------------------------


def test_ein_kontextueberlauf_mit_fortsetzung_ist_kein_fehlschlag(config, client):
    """The most important of the five. The continuation is written,
    scheduled and about to run — the counter skips this run, the goal
    booking is told about it, the notification stays quiet for it, and the
    one field the eye reads said 'gescheitert' anyway."""
    agent_schreiben(config)
    provider_setzen(
        client,
        NahezuVollerKontext(mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE),
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "unterbrochen"
    # And the reason is not lost with it — WHY it stopped is still the news.
    assert daten["end_reason"] == "kontext_voll"
    # The continuation really is on the clock; without it this would be a
    # lie told the other way round.
    (kette,) = client.app.state.repositories.cronjobs.auflisten()
    assert kette.aktiv is True
    assert kette.basisaufgabe == "Los"


def test_ein_ueberlauf_ohne_fortsetzung_bleibt_rot(config, client):
    """The counter-check, and the line that keeps F1 from being a blanket
    excuse: a handoff that came back empty has nothing behind it. That is a
    real ending, and it stays 'gescheitert'."""
    agent_schreiben(config)
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text="   ")
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "gescheitert"
    assert daten["end_reason"] == "kontext_voll"
    assert client.app.state.repositories.cronjobs.auflisten() == []


def test_ein_anbieter_ausfall_mit_fortsetzung_ist_kein_fehlschlag(
    config, client, monkeypatch
):
    """The second ending that hands its work on, and the one a dead model
    server produces over and over."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="Kabelbrand"))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "unterbrochen"
    assert daten["end_reason"] == "anbieter_ausfall"


async def test_ein_ausfall_ohne_neustart_bleibt_rot(config, client, monkeypatch):
    """The restart ceiling reached: nothing carries this work on, so this run
    is the ending — red, and final."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="Kabelbrand"))
    repos = client.app.state.repositories
    kette = repos.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Los",
    )
    repos.cronjobs.fortschritt_setzen(
        kette.id, erledigt_anzahl=None, ohne_fortschritt=0,
        neustarts=zwischenstand.MAX_NEUSTARTS,
    )

    auftrag = _lauf_ueber_termin(client, config, kette.id)
    beendet = await _bis_beendet(repos, auftrag.id)

    assert beendet.zustand == "gescheitert"
    assert beendet.ende_grund == "anbieter_ausfall"


# --- F2 · one piece of work, one row ----------------------------------------


def test_ein_lauf_ohne_termin_ist_sein_eigenes_werk(config, client):
    """Nothing to group a hand-started run with, and grouping it with
    anything else would be a guess."""
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["work_id"] == kennung


async def test_die_kette_traegt_die_kennung_ihres_ursprungs(config, client, monkeypatch):
    """The way back the chain already knew: ``ursprung_id``, set on every
    continuation and always naming the real origin. The origin's own run and
    every link of its chain answer with the same work — which is what lets
    the list show one disturbance as one row."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="Kabelbrand"))
    repos = client.app.state.repositories
    ursprung = repos.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="chat",
    )

    erst = _lauf_ueber_termin(client, config, ursprung.id)
    await _bis_beendet(repos, erst.id)
    (kette,) = [e for e in repos.cronjobs.auflisten() if e.id != ursprung.id]
    assert kette.ursprung_id == ursprung.id

    zweit = _lauf_ueber_termin(client, config, kette.id)
    await _bis_beendet(repos, zweit.id)

    zeilen = {z["id"]: z["work_id"] for z in client.get("/api/v1/jobs").json()}
    assert zeilen[erst.id] == ursprung.id
    assert zeilen[zweit.id] == ursprung.id
    # The entry that fired each run is its own row, not the origin — the
    # chain row fired the second one.
    termine = {z["id"]: z["cronjob_id"] for z in client.get("/api/v1/jobs").json()}
    assert termine[erst.id] == ursprung.id
    assert termine[zweit.id] == kette.id
    # And the single-run route says the same thing, or the list and the
    # detail view would disagree about what a run belongs to.
    assert client.get(f"/api/v1/jobs/{zweit.id}").json()["work_id"] == ursprung.id


# --- F4/F5 · the notification -----------------------------------------------


@pytest.fixture
def gemeldet(monkeypatch):
    """Announcements, collected instead of played — no test may put a real
    notification into the machine's notification centre."""
    aufrufe: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich: aufrufe.append((text, erfolgreich)),
    )
    return aufrufe


@pytest.fixture
def skriptordner(config) -> Path:
    ordner = speicherorte.ort(config, "scripts")
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


async def feuern(client, jetzt: datetime) -> None:
    await client.app.state.wecker.einmal_pruefen(jetzt=jetzt)
    for lauf in list(client.app.state.generierungen.laufende()):
        if lauf.aufgabe is not None:
            await lauf.aufgabe


async def test_ein_skript_meldet_woran_es_gescheitert_ist(client, skriptordner, gemeldet):
    """F4. The reports row had the reason; the notification — the half that
    reaches somebody who is not looking at the screen — did not."""
    script_file(skriptordner, "kaputt.py", "print('ging schief')\nraise SystemExit(1)\n")
    repos = client.app.state.repositories
    eintrag = repos.cronjobs.erstellen(
        agent=skriptlauf.SKRIPT_AGENT, task="", zeitplan="08:00", herkunft="chat",
        skript="kaputt.py", deliver="announce", fehlergrenze=5,
    )

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    assert gemeldet == [("kaputt.py — ging schief — script ended with an error", False)]
    lauf = repos.auftraege.laeufe_fuer_cronjob(eintrag.id)[0]
    assert lauf.ende_grund == skriptlauf.GRUND_FEHLGESCHLAGEN


async def test_ein_sauberes_skript_meldet_sich_wie_bisher(client, skriptordner, gemeldet):
    """The counter-check for F4: an ending with nothing to explain stays
    byte for byte what it was."""
    script_file(skriptordner, "gut.py", "print('fertig')\n")
    repos = client.app.state.repositories
    repos.cronjobs.erstellen(
        agent=skriptlauf.SKRIPT_AGENT, task="", zeitplan="08:00", herkunft="chat",
        skript="gut.py", deliver="announce",
    )

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    assert gemeldet == [("gut.py — fertig", True)]


async def test_ein_skript_an_seiner_fehlergrenze_meldet_sich_einmal(
    client, skriptordner, gemeldet
):
    """F5 on the script road: the failure limit speaks for this run, so the
    blanket announcement does not speak again a moment later."""
    script_file(skriptordner, "kaputt.py", "print('ging schief')\nraise SystemExit(1)\n")
    repos = client.app.state.repositories
    eintrag = repos.cronjobs.erstellen(
        agent=skriptlauf.SKRIPT_AGENT, task="", zeitplan="08:00", herkunft="chat",
        skript="kaputt.py", deliver="announce", fehlergrenze=1,
    )

    await feuern(client, MORGEN.replace(hour=8, minute=1))

    assert repos.cronjobs.holen(eintrag.id).aktiv is False
    assert gemeldet == [("kaputt.py — stopped after 1 failed runs", False)]


async def test_die_grenze_schweigt_die_zweite_mitteilung_weg(repos, monkeypatch):
    """The mechanism itself, without a run around it — and the same flag
    ``ziel_verbuchen`` has been reading all along."""
    aufrufe: list[str] = []
    monkeypatch.setattr(
        cronablauf.cronmeldung, "melden",
        lambda text, *, erfolgreich: aufrufe.append(text),
    )
    eintrag = repos.cronjobs.erstellen(
        agent="a", task="Postfach lesen", zeitplan="08:00", herkunft="chat",
        deliver="announce",
    )

    await cronablauf.melde_wenn_faellig(
        repos, eintrag.id, "Postfach lesen", erfolgreich=False,
        grund="zeitgrenze", schon_gemeldet=True,
    )
    assert aufrufe == []

    # And without the flag it still says its piece — the guard must not be a
    # blanket off switch.
    await cronablauf.melde_wenn_faellig(
        repos, eintrag.id, "Postfach lesen", erfolgreich=False, grund="zeitgrenze",
    )
    assert aufrufe == ["Postfach lesen — time limit reached"]


# --- The list itself, run rather than read ----------------------------------


nodepflicht = pytest.mark.skipif(
    shutil.which("node") is None, reason="no Node on this machine"
)


def _bloecke() -> str:
    """The rule and the block that decide which rows the reports list shows,
    lifted out as plain JavaScript.

    Lifted rather than copied: a copy in this file would go on passing long
    after the rule in the component had changed, which is the failure mode a
    test about a display is most likely to have.

    ``weitergereicht`` is the one distinction this list and the dot on the
    rail share, and it stands in frontend/src/lib/laufstand.js so that
    neither display can quietly grow its own reading of it — so that is
    normally where it is taken from. Should the component declare one of its
    own again, THAT is what is lifted, because that is then what it really
    runs; a lift that reached past a local declaration to the shared file
    would report on a rule the list is no longer using, which is the same
    mistake as copying. tests/test_laufstand.py is the one that says there
    must be no local declaration at all.
    """
    quelle = MODUL_AGENTEN.read_text(encoding="utf-8")
    eigene = "  function weitergereicht(auftrag) {"
    if eigene in quelle:
        anfang = quelle.index(eigene)
        regel = quelle[anfang : quelle.index("\n  }\n", anfang) + len("\n  }\n")]
    else:
        regel = LAUFSTAND.read_text(encoding="utf-8").replace(
            "export function weitergereicht", "function weitergereicht"
        )
    anfang = quelle.index("  const berichte = $derived.by(() => {")
    rumpf = quelle[anfang : quelle.index("\n  })", anfang)]
    rumpf = rumpf.replace(
        "  const berichte = $derived.by(() => {",
        "function berichteAus(auftraege) {",
    ).replace("zustand.auftraege", "auftraege")
    return regel + rumpf + "\n}\n"


@nodepflicht
def _zeilen(auftraege: list[dict]) -> list[str]:
    """Runs the lifted block in node and returns the ids it keeps.

    The driver is written to a private temporary folder OUTSIDE the
    repository, not next to the component under a fixed name. It used to be
    ``frontend/anzeigefunde.pruefung.mjs``, and that costs twice: two test
    runs at once — the everyday case here — write over each other's file,
    and a run killed between writing and cleaning up leaves a stray .mjs
    lying in the working tree, which no ignore rule catches. Nothing in the
    lifted block imports anything, so it needs no node_modules beside it and
    can live anywhere.
    """
    with tempfile.TemporaryDirectory(prefix="anzeigefunde-") as ordner:
        treiber = Path(ordner) / "pruefung.mjs"
        treiber.write_text(
            _bloecke()
            + textwrap.dedent(
                """
                const auftraege = %s
                console.log(JSON.stringify(berichteAus(auftraege).map((a) => a.id)))
                """
            )
            % json.dumps(auftraege),
            encoding="utf-8",
        )
        lauf = subprocess.run(
            ["node", treiber.name], cwd=ordner, capture_output=True, text=True, timeout=60
        )
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-2000:]
    return json.loads(lauf.stdout.strip().splitlines()[-1])


def _lauf(id_, state, *, grund=None, result=None, werk=None) -> dict:
    return {
        "id": id_,
        "state": state,
        "end_reason": grund,
        "result": result,
        "work_id": werk or id_,
    }


@nodepflicht
def test_zehn_kettenglieder_geben_eine_zeile():
    """F2, measured on the shape a dead model server really produces: the
    origin's run and nine restarts hand their work on, the tenth runs out of
    restarts and is the ending. Newest first, the way the route hands the
    list out."""
    laeufe = [_lauf("l10", "gescheitert", grund="anbieter_ausfall", werk="w")]
    laeufe += [
        _lauf(f"l{n}", "unterbrochen", grund="anbieter_ausfall", result="weg", werk="w")
        for n in range(9, 0, -1)
    ]

    assert _zeilen(laeufe) == ["l10"]


@nodepflicht
def test_ein_weitergereichter_lauf_ohne_nachfolger_steht_da():
    """Nothing is swallowed: while a chain's newest link is the newest thing
    there is, it stands in the list with its reason — quietly, because
    'unterbrochen' is not what the row paints red."""
    assert _zeilen(
        [_lauf("l1", "unterbrochen", grund="kontext_voll", result="Uebergabe", werk="w")]
    ) == ["l1"]


@nodepflicht
def test_ein_laufender_nachfolger_schliesst_das_glied_schon_aus():
    """A link is superseded by a continuation that is still running just as
    much as by one that has ended — or every chain would show two rows for
    the minute between its links."""
    assert _zeilen(
        [
            _lauf("l2", "laeuft", werk="w"),
            _lauf("l1", "unterbrochen", grund="kontext_voll", result="Uebergabe", werk="w"),
        ]
    ) == []


@nodepflicht
def test_ein_dienst_neustart_steht_in_der_liste():
    """F3, and since d9f6e3c the normal case rather than the rare one: the
    sweep at service start writes 'unterbrochen' with no result at all, so
    the branch meant to draw it quietly could never be reached."""
    assert _zeilen([_lauf("l1", "unterbrochen", grund="dienst_neustart")]) == ["l1"]


@nodepflicht
def test_ein_abgeschnittener_lauf_weicht_keinem_nachfolger():
    """And it is not folded away either: a restart cut it off, nothing was
    handed anywhere, and the next run of the same schedule is a different
    piece of news."""
    assert _zeilen(
        [
            _lauf("l2", "fertig", grund="fertig", result="Bericht", werk="w"),
            _lauf("l1", "unterbrochen", grund="dienst_neustart", werk="w"),
        ]
    ) == ["l2", "l1"]


@nodepflicht
def test_sechs_echte_cronlaeufe_bleiben_sechs_zeilen():
    """The proof from 78afa26 has to keep standing: several runs of the same
    schedule are several pieces of news, not one. Only a handed-on link
    folds."""
    laeufe = [
        _lauf("l6", "gescheitert", grund="ablage_gescheitert", result="x", werk="ablage"),
        _lauf("l5", "fertig", grund="fertig", result="x", werk="eilig"),
        _lauf("l4", "gescheitert", grund="zeitgrenze", werk="eilig"),
        _lauf("l3", "gescheitert", grund="anbieter_ausfall", werk="ruhig"),
        _lauf("l2", "fertig", grund="fertig", result="x", werk="ruhig"),
        _lauf("l1", "fertig", grund="fertig", result="x", werk="ruhig2"),
    ]

    assert _zeilen(laeufe) == ["l6", "l5", "l4", "l3", "l2", "l1"]


@nodepflicht
def test_ein_sauberer_lauf_ohne_text_und_ein_abbruch_bleiben_draussen():
    """Unchanged from before: a finished run with nothing to say and an
    abort are not news."""
    assert _zeilen(
        [
            _lauf("l2", "fertig", grund="fertig"),
            _lauf("l1", "abgebrochen", grund="benutzer_abbruch"),
        ]
    ) == []
