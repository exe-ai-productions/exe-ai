"""A job's context reading reaches the window live, and the job list carries
each run's newest one.

The tile's context line (frontend/src/teile/Kontextstrich.svelte) reads the
reading off the job list; the live line says when a new one was written, so
the window reloads that list at once instead of on the panel's beat.
"""

from __future__ import annotations

import json
import time

from app import ereignisstrom
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import MitNutzung, provider_setzen
from tests.test_auftraege_api import agent_schreiben, auf_ende_warten


def _meldungen_mitschreiben(monkeypatch) -> list[tuple[str, dict]]:
    gemeldet: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        ereignisstrom.strom, "melden", lambda typ, **felder: gemeldet.append((typ, felder))
    )
    return gemeldet


def _bis_ruhig(gemeldet, typ: str, anzahl: int) -> list[dict]:
    """The announcements of that type, once that many have arrived and a
    further half second has passed quietly — the bus hands them on in a task
    of its own, a moment after the step, and a stray late one must still be
    caught. Expecting none, only that quiet half second is waited."""
    frist = time.time() + 2
    while anzahl and time.time() < frist:
        if len([f for t, f in gemeldet if t == typ]) >= anzahl:
            break
        time.sleep(0.02)
    time.sleep(0.5)
    return [f for t, f in gemeldet if t == typ]


def test_ein_kontextschritt_meldet_sich_genau_einmal_mit_seinem_auftrag(
    config, client, monkeypatch
):
    gemeldet = _meldungen_mitschreiben(monkeypatch)
    agent_schreiben(config)
    provider_setzen(
        client,
        MitNutzung(mock_endpunkt("test"), nutzung={"total_tokens": 150}),
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    schritte = [s for s in daten["schritte"] if s["typ"] == "kontext"]
    assert len(schritte) == 1
    assert _bis_ruhig(gemeldet, "auftrag_kontext", 1) == [{"auftrag_id": kennung}]


def test_ohne_kontextschritt_meldet_sich_nichts(config, client, monkeypatch):
    """The silence check: a run whose model reports no usage writes steps of
    other kinds only, and none of them announces a reading."""
    gemeldet = _meldungen_mitschreiben(monkeypatch)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["schritte"]
    assert not [s for s in daten["schritte"] if s["typ"] == "kontext"]
    assert _bis_ruhig(gemeldet, "auftrag_kontext", 0) == []


def test_die_liste_traegt_den_neuesten_kontextstand_jedes_laufs(config, client):
    agent_schreiben(config)
    provider_setzen(
        client,
        MitNutzung(mock_endpunkt("test"), nutzung={"total_tokens": 150}),
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000
    mit = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    auf_ende_warten(client, mit)
    # A later reading of the same run is the one that counts.
    client.app.state.repositories.auftraege.schritt_anlegen(
        mit, "kontext", json.dumps({"tokens": 420, "kontextgroesse": 1000, "prozent": 42.0})
    )

    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    ohne = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    auf_ende_warten(client, ohne)

    zeilen = {z["id"]: z for z in client.get("/api/v1/jobs").json()}
    assert zeilen[mit]["kontext"] == {"tokens": 420, "kontextgroesse": 1000, "prozent": 42.0}
    assert zeilen[ohne]["kontext"] is None


def test_ein_unlesbarer_kontextschritt_nimmt_die_liste_nicht_mit(config, client):
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)
    client.app.state.repositories.auftraege.schritt_anlegen(kennung, "kontext", "{kaputt")

    antwort = client.get("/api/v1/jobs")
    assert antwort.status_code == 200
    assert {z["id"]: z for z in antwort.json()}[kennung]["kontext"] is None
