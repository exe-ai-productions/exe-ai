"""A tool call being written reports itself — in a chat AND in a job.

A call is only complete at the end of the stream, so a model writing a long
argument means minutes in which data flows and a watcher sees nothing at all.
The providers report the growing argument (``app/providers/anthropic.py``,
``app/providers/openai_kompatibel.py``), and the chat run forwards it. The job
run's switch over the chunk kinds knew ``content``, ``reasoning``, ``stats``,
``tool_call`` and ``error`` — and nothing else, so on that side the report
fell through to nobody and an agent writing a long argument looked stuck.

One logic for chat and job, so both are driven here. The silent half is worth
as much as the loud one: nothing may invent such a report where the provider
sent none, in either run.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import AsyncIterator

import pytest

from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Generierungsanfrage, Stueck, Werkzeugaufruf
from app.tools.registry import WerkzeugRegistry
from tests.conftest import provider_setzen

# What the providers put in such a packet: which call is being written, its
# name, and how many characters of the argument have arrived so far.
ERSTER = {"index": 0, "name": "read_file", "zeichen": 0}
ZWEITER = {"index": 0, "name": "read_file", "zeichen": 1200}


class _Schreibend(MockProvider):
    """Reports the growing argument, then makes the call, then answers."""

    def __init__(self, *, melden: bool = True) -> None:
        super().__init__(mock_endpunkt("test"))
        self.melden = melden
        self.durchgang = 0

    async def streamen(self, anfrage: Generierungsanfrage) -> AsyncIterator[Stueck]:
        self.alle_anfragen.append(anfrage)
        self.letzte_anfrage = anfrage
        self.durchgang += 1
        if self.durchgang == 1:
            if self.melden:
                yield Stueck(sorte="tool_call_laeuft", daten=dict(ERSTER))
                yield Stueck(sorte="tool_call_laeuft", daten=dict(ZWEITER))
            yield Stueck("content", "Ich sehe nach. ")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(id="a1", name="read_file", argumente={"path": "notiz.txt"})
                ],
            )
        else:
            yield Stueck("content", "Fertig.")
        yield Stueck(
            "stats", daten={"dauer_sekunden": 0.0, "haeppchen": 1, "endpunkt": self.id}
        )


def _fortschritte(ereignisse: list[dict]) -> list[dict]:
    return [e for e in ereignisse if e.get("typ") == "tool_call_laeuft"]


# --- The chat --------------------------------------------------------------


def _chat_lauf(client, tmp_path, *, melden: bool):
    (tmp_path / "notiz.txt").write_text("hallo", encoding="utf-8")
    client.app.state.werkzeuge = WerkzeugRegistry([], shell_an=True)
    client.app.state.config.features.mcp = True
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt.capabilities.tool_calls = True
    chat = client.post("/api/v1/chats", json={"title": "Fortschritt"}).json()
    client.patch(f"/api/v1/chats/{chat['id']}", json={"working_dirs": [str(tmp_path)]})
    provider_setzen(client, _Schreibend(melden=melden))
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat["id"], "endpoint_id": "test", "content": "Sieh nach."},
    )
    return [
        json.loads(zeile[5:].strip())
        for zeile in antwort.text.splitlines()
        if zeile.startswith("data:")
    ]


def test_der_chat_gibt_den_fortschritt_weiter(client, tmp_path):
    fortschritte = _fortschritte(_chat_lauf(client, tmp_path, melden=True))
    assert [e["zeichen"] for e in fortschritte] == [0, 1200]
    assert {e["name"] for e in fortschritte} == {"read_file"}


def test_der_chat_erfindet_keinen_fortschritt(client, tmp_path):
    """The silent half: no packet from the provider, no event in the stream."""
    assert _fortschritte(_chat_lauf(client, tmp_path, melden=False)) == []


# --- The job ---------------------------------------------------------------


@pytest.fixture()
def auftrags_client(config):
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


def _auftrags_lauf(client, config, ordner, monkeypatch, *, melden: bool):
    """Runs the job and returns every line it handed to its watchers.

    Read at ``Generierung.melden`` — the one door a job's events go through
    (``app/generationen.py``) — because the run is unhooked from the job row
    the moment it ends (``generation_verknuepfen(…, None)``), so a finished
    job no longer names the run whose transcript could be fetched.
    """
    from app.generationen import Generierung

    gesammelt: list[str] = []
    echt = Generierung.melden

    def mitschreiben(self, zeile: str) -> None:
        gesammelt.append(zeile)
        echt(self, zeile)

    monkeypatch.setattr(Generierung, "melden", mitschreiben)

    (ordner / "notiz.txt").write_text("hallo", encoding="utf-8")
    verzeichnis = Path(config.agentenverzeichnisse[0])
    verzeichnis.mkdir(parents=True, exist_ok=True)
    (verzeichnis / "leser.md").write_text(
        f"---\nmodel: test\ntools:\n  - read_file\nfolders:\n  - {ordner}\n---\nLies nach.\n",
        encoding="utf-8",
    )
    provider_setzen(client, _Schreibend(melden=melden))
    kennung = client.post(
        "/api/v1/jobs", json={"agent": "leser", "task": "Lies", "endpoint_id": "test"}
    ).json()["id"]
    for _ in range(400):
        daten = client.get(f"/api/v1/jobs/{kennung}").json()
        if daten["state"] in ("fertig", "abgebrochen", "gescheitert"):
            break
        time.sleep(0.02)
    assert daten["state"] == "fertig", f"the job ended as {daten['state']}"
    return [json.loads(zeile[5:].strip()) for zeile in gesammelt]


def test_der_auftrag_gibt_den_fortschritt_weiter(
    auftrags_client, config, tmp_path, monkeypatch
):
    """Without the branch this list is empty: the packet arrived and the
    switch had no case for it."""
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    fortschritte = _fortschritte(
        _auftrags_lauf(auftrags_client, config, geteilt, monkeypatch, melden=True)
    )
    assert [e["zeichen"] for e in fortschritte] == [0, 1200]
    assert {e["name"] for e in fortschritte} == {"read_file"}


def test_der_auftrag_erfindet_keinen_fortschritt(
    auftrags_client, config, tmp_path, monkeypatch
):
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    assert (
        _fortschritte(
            _auftrags_lauf(auftrags_client, config, geteilt, monkeypatch, melden=False)
        )
        == []
    )
