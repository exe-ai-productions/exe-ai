"""A job run that asks, and stands still until it is answered.

The tool existed and worked — in a chat. A job was refused it because it had
no PLACE to put a question: nobody sits in front of a run that fires from a
schedule at three in the morning. The place is the run itself, and what these
tests watch is that the four halves of it hold together:

  * the run really stops, in the state the waiting group reads (``wartet``),
    with the question attached to it;
  * an answer travels the chat's own route and the run carries on with it;
  * cancelling reaches a waiting run as fast as a running one;
  * an agent without the tool behaves exactly as it did before;
  * a restart takes the run but not the work — the row and the question stand,
    and an answer given afterwards carries the job on instead of being lost.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.providers import MockProvider, Stueck, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.tools.registry import WerkzeugRegistry
from tests.conftest import provider_setzen

ENDE = {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}


def agent_schreiben(config, name: str = "recherche", kopf: str = "model: test") -> Path:
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / f"{name}.md"
    datei.write_text(f"---\n{kopf}\n---\n\nDu bist der Rechercheur.\n", encoding="utf-8")
    return datei


class FragtEinmal(MockProvider):
    """Asks once, then answers with whatever came back — so the test can read
    the answer out of the report instead of out of an internal."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if self.durchlaeufe == 1:
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id="w1",
                        name="ask_user",
                        argumente={
                            "question": "Welche der zwei Dateien?",
                            "options": [{"label": "Die erste"}, {"label": "Die zweite"}],
                        },
                    )
                ],
            )
            return
        gegeben = [n for n in anfrage.nachrichten if n.role == "tool"]
        yield Stueck("content", text=f"Genommen: {gegeben[-1].content}")


@pytest.fixture
def client_echt(config):
    """A client with a real registry, so ask_user is actually offered."""
    from fastapi.testclient import TestClient

    from app.main import app_erstellen

    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    with TestClient(app_erstellen(config)) as testclient:
        testclient.headers["X-Sitzungsschluessel"] = testclient.app.state.sitzungsschluessel
        testclient.app.state.werkzeuge = WerkzeugRegistry([], shell_an=True)
        zustand = testclient.app.state.discovery.zustaende["test"]
        zustand.endpunkt.capabilities.tool_calls = True
        yield testclient


def _auf_zustand_warten(client, auftrag_id: str, zustand: str, timeout: float = 8.0):
    frist = time.time() + timeout
    daten: dict = {}
    while time.time() < frist:
        daten = client.get(f"/api/v1/jobs/{auftrag_id}").json()
        if daten.get("state") == zustand:
            return daten
        time.sleep(0.02)
    raise AssertionError(f"state '{zustand}' never came: {daten}")


def _auf_ende_warten(client, auftrag_id: str, timeout: float = 8.0) -> dict:
    frist = time.time() + timeout
    daten: dict = {}
    while time.time() < frist:
        daten = client.get(f"/api/v1/jobs/{auftrag_id}").json()
        if daten.get("state") in ENDE:
            return daten
        time.sleep(0.02)
    raise AssertionError(f"no end state: {daten}")


def _fragender_lauf(config, client_echt):
    agent_schreiben(config)
    provider_setzen(client_echt, FragtEinmal(mock_endpunkt("test")))
    kennung = client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    return kennung, _auf_zustand_warten(client_echt, kennung, "wartet")


def test_der_lauf_haelt_an_und_traegt_die_frage(config, client_echt):
    """The state the waiting group reads, and the question the buttons need
    — both on the run, both from the list route."""
    _, daten = _fragender_lauf(config, client_echt)

    assert daten["state"] == "wartet"
    assert daten["question"]["frage"] == "Welche der zwei Dateien?"
    assert [o["label"] for o in daten["question"]["optionen"]] == [
        "Die erste",
        "Die zweite",
    ]
    assert daten["question"]["aufruf_id"] == "w1"


def test_die_frage_steht_auch_in_der_liste(config, client_echt):
    """The waiting group draws its buttons off the LIST, not off a transcript
    it would have to fetch per run."""
    kennung, _ = _fragender_lauf(config, client_echt)

    liste = client_echt.get("/api/v1/jobs").json()
    zeile = next(z for z in liste if z["id"] == kennung)
    assert zeile["question"]["frage"] == "Welche der zwei Dateien?"


def test_die_antwort_geht_in_den_aufruf_und_der_lauf_macht_weiter(
    config, client_echt
):
    """A clicked label goes in through the job's own route and comes out as
    the tool's result — the run carries on where it stopped."""
    kennung, daten = _fragender_lauf(config, client_echt)

    antwort = client_echt.post(
        f"/api/v1/jobs/{kennung}/answer", json={"antwort": "Die zweite"}
    )
    assert antwort.status_code == 200

    fertig = _auf_ende_warten(client_echt, kennung)
    assert fertig["state"] == "fertig"
    assert "Die zweite" in (fertig["result"] or "")


def test_die_frage_im_strom_traegt_die_felder_des_chats(config, client_echt, monkeypatch):
    """The call and its answer reach the stream with the chat's fields: the
    server beside the call, the picture field and the time beside the
    result."""
    import json

    from app.generationen import Generierung

    gemeldet: list[dict] = []
    original = Generierung.melden

    def mitschreiben(self, zeile):
        gemeldet.append(json.loads(zeile.removeprefix("data: ").strip()))
        original(self, zeile)

    monkeypatch.setattr(Generierung, "melden", mitschreiben)
    kennung, _ = _fragender_lauf(config, client_echt)
    client_echt.post(f"/api/v1/jobs/{kennung}/answer", json={"antwort": "Die zweite"})
    _auf_ende_warten(client_echt, kennung)

    aufruf = next(e for e in gemeldet if e["typ"] == "tool_call")
    ergebnis = next(e for e in gemeldet if e["typ"] == "tool_result")
    assert aufruf["name"] == "ask_user"
    assert aufruf["server"] == client_echt.app.state.werkzeuge.server_von("ask_user")
    assert ergebnis["bild"] is None
    assert isinstance(ergebnis["dauer_sekunden"], float) and ergebnis["dauer_sekunden"] >= 0
    assert ergebnis["text"] == "Die zweite"


def test_freier_text_zaehlt_genauso(config, client_echt):
    """Whoever types instead of clicking has answered — the rule the tool was
    built on, and it must survive the trip through a job."""
    kennung, daten = _fragender_lauf(config, client_echt)

    client_echt.post(
        f"/api/v1/jobs/{kennung}/answer",
        json={"antwort": "Keine von beiden, nimm die dritte"},
    )
    fertig = _auf_ende_warten(client_echt, kennung)
    assert "die dritte" in (fertig["result"] or "")


def test_die_frage_verschwindet_mit_der_antwort(config, client_echt):
    """The row must never say "waiting" with nothing left to answer."""
    kennung, daten = _fragender_lauf(config, client_echt)

    client_echt.post(
        f"/api/v1/jobs/{kennung}/answer", json={"antwort": "Die erste"}
    )
    fertig = _auf_ende_warten(client_echt, kennung)
    assert fertig["question"] is None


def test_abbrechen_raeumt_einen_wartenden_lauf_weg(config, client_echt):
    """Without this a run nobody answers stands in the list for ever."""
    kennung, _ = _fragender_lauf(config, client_echt)

    client_echt.post(f"/api/v1/jobs/{kennung}/cancel")
    ende = _auf_ende_warten(client_echt, kennung)
    assert ende["state"] == "abgebrochen"
    assert ende["question"] is None


def test_ein_agent_ohne_ask_user_verhaelt_sich_wie_vorher(config, client_echt):
    """The silence test. No tool in the list, no question, no waiting — and
    the run ends the way it always did."""
    agent_schreiben(config, kopf="model: test\ntools:\n  - read_file")
    provider_setzen(client_echt, MockProvider(mock_endpunkt("test")))

    kennung = client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    ende = _auf_ende_warten(client_echt, kennung)

    assert ende["state"] == "fertig"
    assert ende["question"] is None


def test_die_wartezeit_kostet_den_lauf_keine_minute(config, client_echt):
    """``max_minutes`` is a budget for WORK. A run must not die because a
    person took their time — that would throw away everything it had done."""
    agent_schreiben(config, kopf="model: test\nmax_minutes: 1")
    provider_setzen(client_echt, FragtEinmal(mock_endpunkt("test")))
    kennung = client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = _auf_zustand_warten(client_echt, kennung, "wartet")

    # Long enough to be measurable, short enough for a test.
    time.sleep(0.6)
    client_echt.post(
        f"/api/v1/jobs/{kennung}/answer", json={"antwort": "Die erste"}
    )
    fertig = _auf_ende_warten(client_echt, kennung)
    assert fertig["state"] == "fertig"
    assert fertig["end_reason"] != "zeitgrenze"


# --- The restart ------------------------------------------------------------


def test_der_neustart_laesst_eine_offene_frage_stehen(tmp_path):
    """``beim_start_aufraeumen`` has always had a line saying ``wartet``
    stays. It never did anything, because nothing ever wrote that state.
    Measured now that something does: the run stands, the question stands,
    and only the dead in-memory reference goes.

    What does NOT survive is the run behind it — the future an answer would
    wake is gone with the process, which is why the panel says so instead of
    drawing buttons that would do nothing.
    """
    import json as _json

    from app.db.connection import Database
    from app.db.repositories.auftraege import AuftragRepository

    db = Database(tmp_path / "t.db")
    db.schema_einrichten()
    repo = AuftragRepository(db)
    auftrag = repo.erstellen(user_id="u", agent="recherche", auftrag="Los")
    repo.generation_verknuepfen(auftrag.id, "gen-1")
    repo.frage_setzen(
        auftrag.id,
        _json.dumps({"aufruf_id": "w1", "frage": "Welche?", "optionen": []}),
    )
    repo.zustand_setzen(auftrag.id, "wartet")

    repo.beim_start_aufraeumen()

    nachher = repo.holen(auftrag.id)
    assert nachher.zustand == "wartet"
    assert nachher.frage is not None
    assert nachher.generation_id is None
    db.schliessen()


def test_nach_dem_neustart_traegt_die_antwort_die_arbeit_weiter(
    config, client_echt, tmp_path
):
    """The case the whole restart rule exists for.

    A run asks, the service is restarted, and somebody answers afterwards.
    There is no call left to hand the answer to — so the work is carried on
    from the run's own status instead, with the question and the answer in
    its assignment. The row ends as handed on, not as a failure.
    """
    kennung, daten = _fragender_lauf(config, client_echt)
    repos = client_echt.app.state.repositories

    # Exactly what a service restart does to this row.
    repos.auftraege.beim_start_aufraeumen()
    nach_neustart = client_echt.get(f"/api/v1/jobs/{kennung}").json()
    assert nach_neustart["state"] == "wartet"
    assert nach_neustart["question"]["frage"] == "Welche der zwei Dateien?"
    assert nach_neustart["generation_id"] is None

    antwort = client_echt.post(
        f"/api/v1/jobs/{kennung}/answer", json={"antwort": "Die zweite"}
    )
    assert antwort.status_code == 200

    zeile = client_echt.get(f"/api/v1/jobs/{kennung}").json()
    assert zeile["state"] == "unterbrochen"
    assert zeile["end_reason"] == "frage_beantwortet"
    assert zeile["question"] is None

    # And the continuation really carries both halves.
    termine = repos.cronjobs.auflisten()
    assert termine, "no continuation scheduled"
    aufgabe = termine[-1].task
    assert "Welche der zwei Dateien?" in aufgabe
    assert "Die zweite" in aufgabe


def test_der_wartende_lauf_traegt_einen_zwischenstand(config, client_echt):
    """A run that asks in its FIRST round has produced no prose, so nothing
    would be on its row to carry it on from. Standing still on a question is
    exactly the moment that has to be resumable."""
    kennung, _ = _fragender_lauf(config, client_echt)
    auftrag = client_echt.app.state.repositories.auftraege.holen(kennung)
    assert auftrag.zwischenstand
    assert "Welche der zwei Dateien?" in auftrag.zwischenstand


def test_wer_nichts_gefragt_hat_nimmt_keine_antwort(config, client_echt):
    """A route that accepted an answer for a run that is not asking would
    quietly end a running job."""
    agent_schreiben(config)
    provider_setzen(client_echt, MockProvider(mock_endpunkt("test")))
    kennung = client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    _auf_ende_warten(client_echt, kennung)

    antwort = client_echt.post(
        f"/api/v1/jobs/{kennung}/answer", json={"antwort": "irgendwas"}
    )
    assert antwort.status_code == 409


def test_eine_leere_antwort_ist_keine(config, client_echt):
    """Otherwise a stray click would take the question away and leave the run
    standing with nothing to go on."""
    kennung, _ = _fragender_lauf(config, client_echt)
    antwort = client_echt.post(
        f"/api/v1/jobs/{kennung}/answer", json={"antwort": "   "}
    )
    assert antwort.status_code == 422
    assert client_echt.get(f"/api/v1/jobs/{kennung}").json()["state"] == "wartet"


# --- The call's result and its time -----------------------------------------


def _stream_recorded(monkeypatch) -> list[dict]:
    """Every event the run reports, as the stream carries it."""
    import json

    from app.generationen import Generierung

    reported: list[dict] = []
    original = Generierung.melden

    def record(self, line):
        reported.append(json.loads(line.removeprefix("data: ").strip()))
        original(self, line)

    monkeypatch.setattr(Generierung, "melden", record)
    return reported


def _stored_results(client, job_id: str) -> list[dict]:
    import json

    steps = client.get(f"/api/v1/jobs/{job_id}").json()["schritte"]
    return [json.loads(s["inhalt"]) for s in steps if s["typ"] == "tool_result"]


def test_a_cancelled_question_gets_its_result(config, client_echt, monkeypatch):
    """Cancelled while it waits on the person: the open call still gets a
    failed result, in the stream and in the stored log, so its row never
    stays "running"."""
    from app.i18n import t

    reported = _stream_recorded(monkeypatch)
    job_id, _ = _fragender_lauf(config, client_echt)
    client_echt.post(f"/api/v1/jobs/{job_id}/cancel")
    assert _auf_ende_warten(client_echt, job_id)["state"] == "abgebrochen"

    results = [e for e in reported if e["typ"] == "tool_result"]
    assert len(results) == 1
    assert results[0]["aufruf_id"] == "w1"
    assert results[0]["fehlgeschlagen"] is True
    assert results[0]["bild"] is None
    assert results[0]["text"] == t("nachricht.abgebrochen_kurz", "de")
    assert isinstance(results[0]["dauer_sekunden"], float)

    stored = _stored_results(client_echt, job_id)
    assert len(stored) == 1
    assert stored[0]["fehlgeschlagen"] is True
    assert stored[0]["dauer_sekunden"] == results[0]["dauer_sekunden"]


def test_an_answered_question_reports_as_before(config, client_echt, monkeypatch):
    """Silence probe: an answer still comes back as the one, successful
    result — the cancel path adds nothing to it."""
    reported = _stream_recorded(monkeypatch)
    job_id, _ = _fragender_lauf(config, client_echt)
    client_echt.post(f"/api/v1/jobs/{job_id}/answer", json={"antwort": "Die erste"})
    _auf_ende_warten(client_echt, job_id)

    results = [e for e in reported if e["typ"] == "tool_result"]
    assert [(e["fehlgeschlagen"], e["text"]) for e in results] == [(False, "Die erste")]


def test_the_wait_on_the_person_is_not_the_calls_time(config, client_echt, monkeypatch):
    """The clock jumps a thousand seconds while the question stands. The
    call's time leaves that out — and the run still gets the wait back on
    its budget, so a one-minute job does not die of it."""
    import types

    from app.api.v1 import auftraege

    jump = [0.0]
    clock = types.SimpleNamespace(
        monotonic=lambda: time.monotonic() + jump[0], time=time.time
    )
    monkeypatch.setattr(auftraege, "time", clock)
    reported = _stream_recorded(monkeypatch)

    agent_schreiben(config, kopf="model: test\nmax_minutes: 1")
    provider_setzen(client_echt, FragtEinmal(mock_endpunkt("test")))
    job_id = client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    _auf_zustand_warten(client_echt, job_id, "wartet")
    jump[0] = 1000.0
    client_echt.post(f"/api/v1/jobs/{job_id}/answer", json={"antwort": "Die erste"})
    finished = _auf_ende_warten(client_echt, job_id)

    result = next(e for e in reported if e["typ"] == "tool_result")
    assert 0 <= result["dauer_sekunden"] < 100
    assert _stored_results(client_echt, job_id)[0]["dauer_sekunden"] < 100
    assert finished["state"] == "fertig"
    assert finished["end_reason"] != "zeitgrenze"


def test_a_job_deleted_while_it_asks_ends_quietly(config, client_echt, caplog):
    """Deleted, not just stopped, while the question stands: the row is gone,
    so the call's result has nowhere to be written and the run ends without
    an error of its own."""
    import logging

    caplog.set_level(logging.INFO, logger="app.api.v1.auftraege")
    job_id, _ = _fragender_lauf(config, client_echt)
    run_id = client_echt.app.state.repositories.auftraege.holen(job_id).generation_id
    # Row first, then the stop — the reverse of the route, which stops first
    # and deletes a moment later; this order leaves no race in a test.
    client_echt.app.state.repositories.auftraege.loeschen(job_id)
    client_echt.app.state.generierungen.abbrechen(run_id)

    deadline = time.time() + 8
    while time.time() < deadline and any(
        r.id == run_id for r in client_echt.app.state.generierungen.laufende()
    ):
        time.sleep(0.02)
    assert not any(r.id == run_id for r in client_echt.app.state.generierungen.laufende())
    assert client_echt.get(f"/api/v1/jobs/{job_id}").status_code == 404
    # The stopped call's result found no row and was dropped, quietly.
    assert f"Job {job_id} is gone" in caplog.text
    assert "failed unexpectedly" not in caplog.text
    assert "IntegrityError" not in caplog.text
