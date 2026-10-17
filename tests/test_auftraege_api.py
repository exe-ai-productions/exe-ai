"""The jobs API: start an agent, log, limits, endings.

The run is a background task — the tests submit the job, poll the state
until it reaches a terminal state, and then check the log, result, and
reason. The TestClient runs the event loop in its own thread, so
``time.sleep`` in the test does not stall it.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from app import (
    agentenmodellwahl, kontextdruck, cronmeldung, fenstergroesse, skills, skillwahl,
    verdichtung, werkzeugwahl, wiederversuch, zwischenstand,
)
from app.agenten import agenten_laden
from app.api.v1.auftraege import auftrag_anstossen
from app.providers import MockProvider, ProviderFehler, Stueck, mock_endpunkt
from app.generationen import Generierung
from app.providers.base import Werkzeugaufruf, kontext_stueck
from app.tools.mcp_client import MCPWerkzeug
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten
from tests.conftest import MitNutzung, agentenmodell_leer, provider_setzen

ENDE = {"fertig", "abgebrochen", "gescheitert", "unterbrochen"}


# --- Helpers ---------------------------------------------------------------


def agent_schreiben(config, name: str = "recherche", kopf: str = "model: test") -> Path:
    ordner = Path(config.app.agenten_verzeichnis)
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / f"{name}.md"
    datei.write_text(f"---\n{kopf}\n---\n\nDu bist der Rechercheur.\n", encoding="utf-8")
    return datei


def auf_ende_warten(client, auftrag_id: str, timeout: float = 8.0) -> dict:
    frist = time.time() + timeout
    daten: dict = {}
    while time.time() < frist:
        daten = client.get(f"/api/v1/jobs/{auftrag_id}").json()
        if daten.get("state") in ENDE:
            return daten
        time.sleep(0.05)
    raise AssertionError(f"the job reached no end state: {daten}")


class ImmerWerkzeuge(MockProvider):
    """Requests a tool every round — for the limit tests."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if self.verzoegerung:
            import asyncio

            await asyncio.sleep(self.verzoegerung)
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id=f"w{self.durchlaeufe}", name="addieren", argumente={"a": 1, "b": 2}
                )
            ],
        )


class RegistryDouble(WerkzeugRegistry):
    """A registry without real MCP servers: one tool, hard-wired."""

    def __init__(self) -> None:
        super().__init__([])
        self._werkzeuge = {
            "addieren": (None, MCPWerkzeug(name="addieren", beschreibung="addiert"), False),
            "verboten": (None, MCPWerkzeug(name="verboten", beschreibung="nie"), False),
        }
        self.aufrufe: list[tuple[str, dict]] = []

    async def ausfuehren(
        self, name, argumente, bild_senke=None, ordner=None, chat_id=None,
        herkunft="chat", agent=None, shell_zeitgrenze=None,
    ):
        if name not in self._werkzeuge:
            raise AssertionError("the filter failed")
        self.aufrufe.append((name, argumente))
        return "3"


@pytest.fixture
def mcp_client(config):
    """A client with the tool feature enabled and a registry double."""
    from fastapi.testclient import TestClient

    from app.main import app_erstellen

    config.features.mcp = True
    # Points nowhere: the lifecycle must not start any real MCP servers.
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    with TestClient(app_erstellen(config)) as testclient:
        testclient.headers["X-Sitzungsschluessel"] = testclient.app.state.sitzungsschluessel
        testclient.app.state.werkzeuge = RegistryDouble()
        # In the configuration the test endpoint cannot do tool calls —
        # here it can, otherwise there would be nothing to test.
        zustand = testclient.app.state.discovery.zustaende["test"]
        zustand.endpunkt.capabilities.tool_calls = True
        yield testclient


@pytest.fixture
def mcp_client_echt(config):
    """Like ``mcp_client``, but with a REAL registry.

    ``RegistryDouble`` overrides ``ausfuehren`` completely and never runs
    Tor 3 (``app/berechtigungen.py``) — the Hole A/B tests need the actual
    enforcement, not a stand-in that always approves.
    """
    from fastapi.testclient import TestClient

    from app.main import app_erstellen
    from app.tools.aufbau import registry_bauen

    config.features.mcp = True
    config.mcp.servers_file = str(Path(config.app.data_dir) / "keine_server.json")
    with TestClient(app_erstellen(config)) as testclient:
        testclient.headers["X-Sitzungsschluessel"] = testclient.app.state.sitzungsschluessel
        # Built by the app's own factory (app/tools/aufbau.py), not by hand:
        # the hand-built one knew only the built-ins, so every tool that
        # hangs on a path — the agent folder, the dock, the memory file —
        # was missing from it. A run whose agent names one of those would be
        # refused as "unknown tool" in a test that never meant to say that.
        testclient.app.state.werkzeuge = registry_bauen(testclient.app, config)
        zustand = testclient.app.state.discovery.zustaende["test"]
        zustand.endpunkt.capabilities.tool_calls = True
        yield testclient


# --- Agent list ------------------------------------------------------------


def test_agentenliste_ohne_dateien_ist_leer(client):
    """The program brings no agent and writes none at startup: without a
    file of one's own, the roster is empty."""
    assert client.get("/api/v1/agents").json() == []


def test_agentenliste_zeigt_kopfteil(config, client):
    agent_schreiben(
        config,
        kopf="model: test\ntools:\n  - web_search\nmax_rounds: 7\nmax_tokens: 16000",
    )
    eintraege = {e["name"]: e for e in client.get("/api/v1/agents").json()}
    eintrag = eintraege["recherche"]
    # No ``model`` in the answer any more: the head field is
    # retired, and an interface still offering it would offer a choice that
    # decides nothing.
    assert "model" not in eintrag
    assert eintrag["tools"] == ["web_search"]
    assert eintrag["max_rounds"] == 7
    assert eintrag["max_tokens"] == 16000


def test_agentenliste_zeigt_kein_max_tokens_wenn_nicht_gesetzt(config, client):
    agent_schreiben(config, kopf="model: test")
    eintraege = {e["name"]: e for e in client.get("/api/v1/agents").json()}
    assert eintraege["recherche"]["max_tokens"] is None


# --- Starting and ending ---------------------------------------------------


def test_unbekannter_agent_gibt_404(config, client):
    agent_schreiben(config)
    antwort = client.post("/api/v1/jobs", json={"agent": "phantom", "task": "x"})
    assert antwort.status_code == 404
    # The refusal names the real agents, so the caller is not left guessing
    # (the same wording as the cronjob path and the schedule tool's schema).
    assert "recherche" in antwort.json()["detail"]


def test_auftrag_loeschen_entfernt_auftrag_und_protokoll(config, client):
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    antwort = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "x"})
    auftrag_id = antwort.json()["id"]
    auf_ende_warten(client, auftrag_id)

    assert client.delete(f"/api/v1/jobs/{auftrag_id}").status_code == 204
    assert client.get(f"/api/v1/jobs/{auftrag_id}").status_code == 404
    assert client.get("/api/v1/jobs").json() == []


def test_unbekannter_auftrag_loeschen_gibt_404(client):
    assert client.delete("/api/v1/jobs/phantom").status_code == 404


def test_laufenden_auftrag_loeschen_stoppt_ihn(config, client):
    """Deleting mid-run: the run is stopped, and its completion writes
    nothing anymore — the job is gone, after all (no FK error)."""
    agent_schreiben(config)
    provider_setzen(
        client, MockProvider(mock_endpunkt("test"), verzoegerung=0.4, haeppchen=["…"])
    )
    antwort = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "x"})
    auftrag_id = antwort.json()["id"]

    assert client.delete(f"/api/v1/jobs/{auftrag_id}").status_code == 204
    assert client.get(f"/api/v1/jobs/{auftrag_id}").status_code == 404
    # Give the stopped run time to finish cleanly — it must not write to
    # the database anymore while doing so.
    time.sleep(0.8)
    assert client.get("/api/v1/jobs").json() == []


def test_agent_ohne_modell_nimmt_erreichbaren_endpunkt(config, client):
    # tools: [] on purpose: this test is about model selection, not about
    # tool capability — "tools: left out" requires a tool-capable
    # endpoint, which the plain "test" endpoint here is not.
    agent_schreiben(config, name="ohne", kopf="max_rounds: 3\ntools: []")
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    antwort = client.post("/api/v1/jobs", json={"agent": "ohne", "task": "x"})
    assert antwort.status_code == 201
    daten = auf_ende_warten(client, antwort.json()["id"])
    assert daten["state"] == "fertig"


def test_agent_ohne_modell_ohne_lokalen_ersatz_wird_abgelehnt(config, client):
    """No model chosen, no main server, and nothing LOCAL either: the run is
    refused. The endpoint that answers here is a cloud one, and a cloud
    endpoint is not a replacement — it costs money and sends the
    task off this machine, and neither is a decision a missing main server
    may make.

    The other half — that a reachable LOCAL endpoint IS taken — stands in
    `tests/test_cronfunde.py`, where the discovery can be given endpoints."""
    agent_schreiben(config, name="ohne", kopf="tools:\n  - web_search")
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    client.app.state.discovery.zustaende["test"].endpunkt.group = "cloud"
    agentenmodell_leer(client)
    antwort = client.post("/api/v1/jobs", json={"agent": "ohne", "task": "x"})
    assert antwort.status_code == 400


def test_auftrag_laeuft_zu_ende_und_protokolliert(config, client):
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Der ", "Bericht."]))

    antwort = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"})
    assert antwort.status_code == 201
    daten = auf_ende_warten(client, antwort.json()["id"])

    assert daten["state"] == "fertig"
    assert daten["end_reason"] == "fertig"
    assert daten["result"] == "Der Bericht."
    assert daten["generation_id"] is None
    typen = [schritt["typ"] for schritt in daten["schritte"]]
    assert typen[0] == "status"
    assert "text" in typen
    assert typen[-1] == "ende"


def test_jede_runde_schreibt_ihren_zwischenstand(config, client):
    """Not just at the context-full handoff or a provider
    outage — every round, so a hard restart mid-run always has something to
    resume from. Checked on the row itself, since a run that finishes
    normally never surfaces it through the API."""
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Der ", "Bericht."]))

    antwort = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"})
    auftrag_id = antwort.json()["id"]
    auf_ende_warten(client, auftrag_id)

    auftrag = client.app.state.repositories.auftraege.holen(auftrag_id)
    assert auftrag.zwischenstand == "Der Bericht."


class ThoughtInsteadOfWritten(MockProvider):
    """A model that thinks its report and ends without writing one.

    The measured shape: the stream carries `reasoning` chunks and not one
    `content` chunk, and the end word is the model's own — it was DONE, it
    just never wrote the report out. Each round is a tuple of (thinking,
    visible text); the last one is the run's.
    """

    def __init__(self, *runden: tuple[str, str]) -> None:
        super().__init__(mock_endpunkt("test"))
        self.runden = list(runden)
        self.ende = "stop"
        self.aufrufe = 0

    async def streamen(self, anfrage):
        gedanke, text = self.runden[min(self.aufrufe, len(self.runden) - 1)]
        self.aufrufe += 1
        if gedanke:
            yield Stueck("reasoning", text=gedanke)
        if text:
            yield Stueck("content", text=text)
        yield Stueck(
            "stats",
            daten={
                "dauer_sekunden": 0.0,
                "haeppchen": 1,
                "endpunkt": self.id,
                "ende_grund": self.ende,
            },
        )


def _job_to_the_end(client, config, provider, header: str = "") -> dict:
    """One agent run against the double, until it reaches a terminal state.

    `tools: []` on purpose: the plain test endpoint is not tool-capable, and
    none of these runs is about tools. `header` adds to the agent's own
    lines — which is how a run can be given a ceiling of its own.
    """
    agent_schreiben(config, name="ohne", kopf="max_rounds: 3\ntools: []" + header)
    provider_setzen(client, provider)
    antwort = client.post("/api/v1/jobs", json={"agent": "ohne", "task": "Los"})
    assert antwort.status_code == 201
    return auf_ende_warten(client, antwort.json()["id"])


def test_a_report_that_was_only_thought_becomes_the_result(config, client):
    """A job whose model thought its report instead of writing it.

    The chat has lifted that thought into the answer since one shared rule
    (app/reasoning.denktext_als_antwort, the same call and the same stage);
    a job ran out with an empty result and told the next chat "The agent
    left no report." (app/agent_report.py) although the model had written
    something.
    """
    bericht = "| Schritt | Werkzeug | Ergebnis |\n| 1 | list_dir | drei Dateien |"

    daten = _job_to_the_end(client, config, ThoughtInsteadOfWritten((bericht, "")))

    assert daten["state"] == "fertig"
    assert daten["result"] == bericht


def test_a_written_report_stays_the_result(config, client):
    """Silence probe: a report the model wrote is the report — unchanged,
    and the thinking beside it does not become one too."""
    daten = _job_to_the_end(
        client, config, ThoughtInsteadOfWritten(("kurz gedacht", "Der Bericht."))
    )

    assert daten["state"] == "fertig"
    assert daten["result"] == "Der Bericht."


class SentenceThenThought(MockProvider):
    """Round one writes a sentence and calls a tool; round two only thinks
    and ends on its own."""

    def __init__(self, vorspann: str, gedanke: str) -> None:
        super().__init__(mock_endpunkt("test"))
        self.vorspann = vorspann
        self.gedanke = gedanke
        self.aufrufe = 0

    async def streamen(self, anfrage):
        self.aufrufe += 1
        if self.aufrufe == 1:
            yield Stueck("content", text=self.vorspann)
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(id="w1", name="addieren", argumente={"a": 1, "b": 2})
                ],
            )
            return
        yield Stueck("reasoning", text=self.gedanke)
        yield Stueck(
            "stats",
            daten={"dauer_sekunden": 0.0, "haeppchen": 1, "endpunkt": self.id,
                   "ende_grund": "stop"},
        )


def test_a_report_thought_after_a_sentence_follows_the_sentence(config, mcp_client):
    """The closing round decides, not the whole run.

    Round one wrote a sentence before its tool call; the closing round
    thought the report and ended. The result is the sentence and the report
    one blank line behind it — not the sentence alone.
    """
    vorspann = "Ich schaue nach.\n"
    bericht = "| Schritt | 1 |"
    agent_schreiben(config, kopf="model: test\ntools:\n  - addieren\nmax_rounds: 3")
    modell = provider_setzen(mcp_client, SentenceThenThought(vorspann, bericht))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Rechne"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert modell.aufrufe == 2, "there were not two rounds"
    assert daten["state"] == "fertig"
    assert daten["result"] == vorspann + "\n" + bericht


class SentenceThenWritten(SentenceThenThought):
    """Round one writes a sentence and calls a tool; round two writes the
    report out, in the pieces given."""

    def __init__(self, vorspann: str, *stuecke: str) -> None:
        super().__init__(vorspann, "")
        self.stuecke = stuecke

    async def streamen(self, anfrage):
        if self.aufrufe == 0:
            async for stueck in super().streamen(anfrage):
                yield stueck
            return
        self.aufrufe += 1
        for text in self.stuecke:
            yield Stueck("content", text=text)
        yield Stueck(
            "stats",
            daten={"dauer_sekunden": 0.0, "haeppchen": 1, "endpunkt": self.id,
                   "ende_grund": "stop"},
        )


def test_a_written_report_stands_a_blank_line_below_the_sentence(config, mcp_client):
    """Two written rounds of a job, joined as they came, put the table on the
    sentence's line and it was not drawn as one. The report, the step log
    and the stream carry the one blank line between them alike."""
    bericht = "| Schritt | 1 |\n|---|---|"
    agent_schreiben(config, kopf="model: test\ntools:\n  - addieren\nmax_rounds: 3")
    modell = provider_setzen(mcp_client, SentenceThenWritten("Ich schaue nach.", bericht))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Rechne"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert modell.aufrufe == 2, "there were not two rounds"
    assert daten["result"] == "Ich schaue nach.\n\n" + bericht
    texte = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "text"]
    assert "".join(texte) == daten["result"]


def test_a_report_that_already_starts_apart_gets_no_second_blank_line(config, mcp_client):
    """Silence probe: a sentence that ends with a line break and a round whose
    first piece is only one more are joined as written."""
    agent_schreiben(config, kopf="model: test\ntools:\n  - addieren\nmax_rounds: 3")
    provider_setzen(mcp_client, SentenceThenWritten("Ich schaue nach.\n", "\n", "| a |"))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Rechne"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert daten["result"] == "Ich schaue nach.\n\n| a |"


def test_a_cut_off_thought_stays_out_of_the_result(config, client):
    """Silence probe: `length` with an empty report changes nothing.

    The run was cut off mid-thought and says in words where the length went
    (app/antwortende.denken_aufgebraucht) — half a sentence must not be
    dressed up as the report. The ceiling is the agent's own here, which is
    what makes that reading the one that ends the run: without it the free
    room in the window decides first (app/api/v1/auftraege.py), and the run
    would end for the other reason while the assertion still held.
    """
    modell = ThoughtInsteadOfWritten(("angefangen zu denken", ""))
    modell.ende = "length"

    daten = _job_to_the_end(client, config, modell, header="\nmax_tokens: 4096")

    assert daten["end_reason"] == "denken_aufgebraucht_eigene_grenze"
    assert not daten["result"]
    assert daten["state"] == "gescheitert"


def test_prompt_ist_gestapelt_global_dann_agent(config, client):
    """Global prompt, then agent prompt, one message."""
    prompt_datei = Path(config.app.system_prompt_file)
    prompt_datei.parent.mkdir(parents=True, exist_ok=True)
    prompt_datei.write_text("GLOBAL.", encoding="utf-8")
    agent_schreiben(config)
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)

    system = provider.letzte_anfrage.nachrichten[0]
    assert system.role == "system"
    # Three layers in order: shipped instructions, the user's prompt, the
    # agent's — the agent last, because that is what makes this run an agent.
    assert "inside Exe AI" in system.content
    assert system.content.endswith("GLOBAL.\n\nDu bist der Rechercheur.")
    benutzer = provider.letzte_anfrage.nachrichten[1]
    # The date block rides in front of the task in the same user message
    # (app/grundprompt.environment_block) — the same road the chat
    # takes, and never a second user message: Mistral-, Gemma- and
    # Command-R templates break on two user turns in a row.
    assert benutzer.role == "user"
    assert benutzer.content.startswith(
        "<environment_context>\n<current_date>"
    )
    assert benutzer.content.endswith("</environment_context>\n\nLos")


def test_auftrag_mit_dateiwerkzeugen_bekommt_die_anleitung_dafuer(config, mcp_client_echt, tmp_path):
    """The job prompt used to skip the file-tool usage instructions a chat
    gets for the same tools — dateiwerkzeuge= was never passed."""
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    agent_schreiben(
        config, kopf=f"model: test\ntools:\n  - read_file\nfolders:\n  - {geteilt}",
    )
    provider = provider_setzen(mcp_client_echt, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "lies"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    system = provider.letzte_anfrage.nachrichten[0]
    assert "For file work use the file tools" in system.content


def test_auftrag_bietet_ask_user_an(config, mcp_client_echt):
    """A job may ask now. The tool was withheld while a job had no PLACE to
    put a question; it has one — the run goes to 'wartet' and the question
    stands on it until somebody answers (app/auftragsfrage.py)."""
    agent_schreiben(config, kopf="model: test")
    provider = provider_setzen(mcp_client_echt, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    namen = {w["function"]["name"] for w in provider.letzte_anfrage.werkzeuge}
    assert "ask_user" in namen


def test_ohne_ask_user_in_der_liste_sagt_der_prompt_nichts_vom_fragen(
    config, mcp_client_echt
):
    """The silence test. An agent whose tools leave ask_user out has to read
    exactly what it read before: nobody can answer."""
    agent_schreiben(config, kopf="model: test\ntools:\n  - read_file")
    provider = provider_setzen(mcp_client_echt, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    namen = {w["function"]["name"] for w in provider.letzte_anfrage.werkzeuge}
    assert "ask_user" not in namen
    system = provider.letzte_anfrage.nachrichten[0].content
    assert "There is no way to ask the user for clarification" in system
    assert "ask_user stops the run" not in system


def test_mit_ask_user_sagt_der_prompt_dass_gefragt_werden_darf(
    config, mcp_client_echt
):
    """The other half: a run that may ask must not be told it cannot."""
    agent_schreiben(config, kopf="model: test")
    provider = provider_setzen(mcp_client_echt, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    system = provider.letzte_anfrage.nachrichten[0].content
    assert "ask_user stops the run" in system
    assert "There is no way to ask the user for clarification" not in system


# --- Provider outage: retry with backoff (app/wiederversuch.py) -----------


class WartetDannScheitert(MockProvider):
    """Blocks on its first call until the test says to continue — lets the
    test arrange a cancel or delete BEFORE the outage actually happens, with
    no race between "the retry loop checks the signal" and "the test just
    got around to setting it" to depend on."""

    def __init__(self, *args, bereit: threading.Event, weiter: threading.Event, **kwargs):
        super().__init__(*args, **kwargs)
        self._bereit = bereit
        self._weiter = weiter

    async def streamen(self, anfrage):
        self._bereit.set()
        await asyncio.get_event_loop().run_in_executor(None, self._weiter.wait)
        raise ProviderFehler("Verbindung verweigert")
        yield  # pragma: no cover - keeps this an async generator, never reached


def test_abbruch_waehrend_ausfall_plant_nichts_neu(config, client, monkeypatch):
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    bereit, weiter = threading.Event(), threading.Event()
    provider_setzen(client, WartetDannScheitert(mock_endpunkt("test"), bereit=bereit, weiter=weiter))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    assert bereit.wait(timeout=2.0)
    assert client.post(f"/api/v1/jobs/{kennung}/cancel").status_code == 200
    weiter.set()

    daten = auf_ende_warten(client, kennung)
    assert daten["state"] == "abgebrochen"
    assert client.app.state.repositories.cronjobs.auflisten() == []


def test_loeschen_waehrend_ausfall_plant_nichts_neu(config, client, monkeypatch):
    """The sharper case: DELETE routes through the same signal too — a
    deleted run is gone, it does not keep running headless."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    bereit, weiter = threading.Event(), threading.Event()
    provider_setzen(client, WartetDannScheitert(mock_endpunkt("test"), bereit=bereit, weiter=weiter))

    auftrag_id = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    assert bereit.wait(timeout=2.0)
    assert client.delete(f"/api/v1/jobs/{auftrag_id}").status_code == 204
    weiter.set()

    time.sleep(0.3)
    assert client.get("/api/v1/jobs").json() == []
    assert client.app.state.repositories.cronjobs.auflisten() == []


class ScheitertMehrmalsDannOk(MockProvider):
    """Fails a fixed number of calls, then behaves like a plain MockProvider
    — the recoverable outage: the server comes back before the run gives
    up on it."""

    def __init__(self, *args, fehlschlaege: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.fehlschlaege = fehlschlaege
        self.aufrufe = 0

    async def streamen(self, anfrage):
        self.aufrufe += 1
        if self.aufrufe <= self.fehlschlaege:
            raise ProviderFehler("Verbindung verweigert")
        async for stueck in super().streamen(anfrage):
            yield stueck


def test_ausfall_erholt_sich_innerhalb_der_wiederversuche(config, client, monkeypatch):
    """Two failed attempts, then the round succeeds — the run never even
    ends, it just took longer to get an answer. The outage is still visible
    in the transcript, with the evidence on record."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(client, ScheitertMehrmalsDannOk(mock_endpunkt("test"), fehlschlaege=2))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "fertig"
    status_schritte = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    treffer = [s for s in status_schritte if "Anbieter nicht erreichbar" in s]
    assert len(treffer) == 2


def test_dauerhafter_ausfall_wird_nach_wiederversuchen_umgeplant(config, client, monkeypatch):
    """The server never comes back within the retry budget. The run ends
    'unterbrochen' with 'anbieter_ausfall' as its reason — cut short and
    resumable, not failed — it keeps the provider's own error text in its
    result, and a cron entry picks the job back up
    automatically, active, counted as one restart, carrying the original
    task.

    Until e959e99 this docstring said the run "ends cleanly instead of
    'gescheitert' with a raw error", and that sentence was never about the
    state: both sides of the contrast it drew ended 'gescheitert', and what
    it was measuring was the REASON — a named 'anbieter_ausfall' where
    there had been the provider's error text and nothing else. The state
    moved later, when a run that handed its work on stopped counting as a
    failed one, and the old sentence stayed behind describing neither."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="Kabelbrand"))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "unterbrochen"
    assert daten["end_reason"] == "anbieter_ausfall"
    assert "Kabelbrand" in daten["result"]

    (eintrag,) = client.app.state.repositories.cronjobs.auflisten()
    assert eintrag.agent == "recherche"
    assert eintrag.herkunft == "agent"
    assert eintrag.aktiv is True
    assert eintrag.neustarts == 1
    assert eintrag.erledigt_anzahl is None
    assert eintrag.ohne_fortschritt == 0
    assert eintrag.basisaufgabe == "Los"


async def test_dauerausfall_ueber_die_neustartgrenze_gibt_auf(config, client, monkeypatch):
    """The absolute ceiling shared with the context handoff — a permanently gone
    endpoint stops being retried, rather than rescheduling forever."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="Kabelbrand"))
    repositories = client.app.state.repositories
    vorheriger = repositories.cronjobs.erstellen(
        agent="recherche", task="Los", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Los",
    )
    repositories.cronjobs.fortschritt_setzen(
        vorheriger.id,
        erledigt_anzahl=None,
        ohne_fortschritt=0,
        neustarts=zwischenstand.MAX_NEUSTARTS - 1,
    )
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]

    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Los",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=vorheriger.id,
    )
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert beendet.ende_grund == "anbieter_ausfall"
    aktualisiert = repositories.cronjobs.holen(vorheriger.id)
    assert aktualisiert.aktiv is False
    assert aktualisiert.task == "Los"  # not rescheduled, so left untouched


async def test_ausfall_an_der_obergrenze_laesst_einen_fremden_termin_aktiv(config, client, monkeypatch):
    """The exact same ceiling, but the entry it would
    hit belongs to someone else — a schedule without basisaufgabe must
    stay active and untouched, even at MAX_NEUSTARTS."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="Kabelbrand"))
    repositories = client.app.state.repositories
    fremder_termin = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="08:00", herkunft="chat",
    )
    repositories.cronjobs.fortschritt_setzen(
        fremder_termin.id,
        erledigt_anzahl=None,
        ohne_fortschritt=0,
        neustarts=zwischenstand.MAX_NEUSTARTS - 1,
    )
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]

    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Water the plants",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=fremder_termin.id,
    )
    await _bis_beendet(repositories, auftrag.id)

    unveraendert = repositories.cronjobs.holen(fremder_termin.id)
    assert unveraendert.aktiv is True
    assert unveraendert.task == "Water the plants"
    assert unveraendert.zeitplan == "08:00"


class Scheitert404(MockProvider):
    """A 404 the provider names outright — a model that plainly does not
    exist, deterministic on every attempt, not an outage a retry could
    ever cure."""

    def __init__(self, *args, text: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._text = text
        self.aufrufe = 0

    async def streamen(self, anfrage):
        self.aufrufe += 1
        raise ProviderFehler(
            f"test antwortete mit 404: {self._text}", status=404, rohtext=self._text
        )
        yield  # pragma: no cover - keeps this an async generator, never reached


def _404_lauf_starten(config, client, repositories, text: str):
    agent_schreiben(config)
    provider = provider_setzen(client, Scheitert404(mock_endpunkt("test"), text=text))
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Los",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
    )
    return provider, auftrag


async def test_404_not_a_chat_model_beendet_sofort_ohne_wiederversuch(config, client, monkeypatch):
    """OpenAI's own wording for a model that cannot serve chat completions —
    none of the common model-not-found wordings cover it, so it is listed
    on its own. One request, no retry, no continuation, the server's own
    text as the result instead of 'Anbieter nicht erreichbar'."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    repositories = client.app.state.repositories
    provider, auftrag = _404_lauf_starten(
        config, client, repositories, "gpt-3.5-turbo-instruct is not a chat model"
    )
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert beendet.zustand == "gescheitert"
    assert beendet.ende_grund == "modell_nicht_gefunden"
    assert "is not a chat model" in beendet.ergebnis
    assert provider.aufrufe == 1
    assert repositories.cronjobs.auflisten() == []


class ErfolgreicheRundeDann404(MockProvider):
    """The first round produces real output and asks for a tool, so there
    is a second round — which is the one that meets the deterministic 404.
    The scenario: an ending that only ever showed the bare refusal text
    would silently drop that first round's work."""

    def __init__(self, *args, text404: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._text404 = text404
        self.durchlaeufe = 0

    async def streamen(self, anfrage):
        self.durchlaeufe += 1
        if self.durchlaeufe == 1:
            yield Stueck("content", text="Erste Runde erledigt.")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(id="w1", name="addieren", argumente={"a": 1, "b": 2})
                ],
            )
            return
        raise ProviderFehler(
            f"test antwortete mit 404: {self._text404}", status=404, rohtext=self._text404
        )
        yield  # pragma: no cover - keeps this an async generator, never reached


async def test_404_modell_nicht_gefunden_behaelt_schon_erzeugten_text(config, client, monkeypatch):
    """The program's own rule for an ending that cuts a run short (already
    kept for the outage path, app/api/v1/auftraege.py 'Produced so far:'):
    whatever earlier rounds of THIS run already produced must survive in the
    report, not just the refusal that ended it."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(
        client,
        ErfolgreicheRundeDann404(mock_endpunkt("test"), text404="model_not_found"),
    )
    repositories = client.app.state.repositories
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]

    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Los",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
    )
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert beendet.ende_grund == "modell_nicht_gefunden"
    assert "Erste Runde erledigt." in beendet.ergebnis
    assert "model_not_found" in beendet.ergebnis


async def test_404_model_not_found_beendet_sofort_ohne_wiederversuch(config, client, monkeypatch):
    """A common provider wording for a model that does not exist — the
    `model_not_found` error code — ends the run at once, without a retry."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    repositories = client.app.state.repositories
    provider, auftrag = _404_lauf_starten(
        config, client, repositories, '{"error": {"code": "model_not_found"}}'
    )
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert beendet.ende_grund == "modell_nicht_gefunden"
    assert provider.aufrufe == 1


async def test_404_mit_anderem_text_laeuft_weiter_in_den_wiederversuch(config, client, monkeypatch):
    """A 404 matching none of the patterns is retried exactly as before; the
    server answered it every time, so after the fifth attempt the run ends
    with the error named, not as an outage."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    repositories = client.app.state.repositories
    provider, auftrag = _404_lauf_starten(config, client, repositories, "internal routing error")
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert provider.aufrufe == wiederversuch.VERSUCHE
    assert beendet.zustand == "gescheitert"
    assert beendet.ende_grund.startswith("fehler:")
    assert "404" in beendet.ergebnis.splitlines()[-1]


async def test_503_laeuft_weiter_in_den_wiederversuch(config, client, monkeypatch):
    """A 503 is retried as before; after the fifth attempt the server's
    answer ends the run with the error named — it did answer, so this is no
    outage a later run has to wait out."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    repositories = client.app.state.repositories
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]

    class Scheitert503(MockProvider):
        async def streamen(self, anfrage):
            raise ProviderFehler(
                "test antwortete mit 503: service unavailable",
                status=503,
                rohtext="service unavailable",
            )
            yield  # pragma: no cover

    provider = Scheitert503(mock_endpunkt("test"))
    provider_setzen(client, provider)
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Los",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
    )
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert beendet.zustand == "gescheitert"
    assert beendet.ende_grund.startswith("fehler:")
    assert "503" in beendet.ergebnis.splitlines()[-1]


def test_voller_kontext_endet_sauber_mit_bericht(config, client):
    """A full context is not a crash."""
    agent_schreiben(config)
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            fehler="the request exceeds the maximum context length of 4096",
        ),
    )

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "gescheitert"
    assert daten["end_reason"] == "kontext_voll"
    assert daten["schritte"][-1]["inhalt"] == "kontext_voll"


def test_kontextstand_wird_je_runde_protokolliert(config, client):
    agent_schreiben(config)
    provider_setzen(
        client,
        MitNutzung(
            mock_endpunkt("test"),
            nutzung={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        ),
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    kontext_schritte = [s for s in daten["schritte"] if s["typ"] == "kontext"]
    assert len(kontext_schritte) == 1
    assert json.loads(kontext_schritte[0]["inhalt"]) == {
        "tokens": 150,
        "kontextgroesse": 1000,
        "prozent": 15.0,
    }


def test_kontextschritt_ohne_bekannte_kontextgroesse_nutzt_den_ersatzwert(config, client):
    """Nothing confirms a size anywhere — not entered, not the server, not
    learned, not the table — so app/fenstergroesse.py's fallback applies
    (128,000) and the run folds on that basis rather than never at all."""
    agent_schreiben(config)
    provider_setzen(
        client,
        MitNutzung(mock_endpunkt("test"), nutzung={"total_tokens": 150}),
    )
    zustand = client.app.state.discovery.zustaende["test"]
    assert zustand.context_tokens == fenstergroesse.ERSATZ
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_ERSATZ

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    kontext_schritte = [s for s in daten["schritte"] if s["typ"] == "kontext"]
    assert len(kontext_schritte) == 1
    assert json.loads(kontext_schritte[0]["inhalt"]) == {
        "tokens": 150,
        "kontextgroesse": fenstergroesse.ERSATZ,
        "prozent": round(100 * 150 / fenstergroesse.ERSATZ, 1),
    }


# --- The proactive context-full handoff (app/zwischenstand.py) -------------


class NahezuVollerKontext(MockProvider):
    """A tool call every round, alongside a near-full context reading — the
    threshold that turns the loop toward a handoff instead of another round.
    The one request whose last message is the handoff prompt itself
    (app/zwischenstand.ANFRAGE_TEXT) answers with ``handoff_text`` instead."""

    def __init__(self, *args, handoff_text: str, tokens: int = 950, **kwargs):
        super().__init__(*args, **kwargs)
        self.handoff_text = handoff_text
        self.tokens = tokens

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and letzte.content == zwischenstand.ANFRAGE_TEXT:
            yield Stueck("content", text=self.handoff_text)
            return
        yield Stueck("stats", daten={"nutzung": {"total_tokens": self.tokens}})
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(id=f"w{self.durchlaeufe}", name="addieren", argumente={"a": 1, "b": 2})
            ],
        )


HANDOFF_ZWEI_PUNKTE = "## Task\nLos\n\n## Done\n- eins\n- zwei\n\n## Next\nweiter"


def test_voller_kontext_schreibt_zwischenstand_und_plant_neu(config, client):
    agent_schreiben(config)
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    # Not a failure: the continuation below is written, scheduled and about
    # to run. 'unterbrochen' — cut short, resumable, not a result.
    assert daten["state"] == "unterbrochen"
    assert daten["end_reason"] == "kontext_voll"
    assert daten["result"] == HANDOFF_ZWEI_PUNKTE

    (eintrag,) = client.app.state.repositories.cronjobs.auflisten()
    assert eintrag.agent == "recherche"
    assert eintrag.herkunft == "agent"
    assert eintrag.aktiv is True
    assert eintrag.erledigt_anzahl == 2
    assert eintrag.ohne_fortschritt == 0
    assert eintrag.neustarts == 1
    assert eintrag.basisaufgabe == "Los"
    assert "Los" in eintrag.task
    assert HANDOFF_ZWEI_PUNKTE in eintrag.task


DENK_UEBERGABE = "## Task\nDenken\n\n## Done\n- eins\n- zwei\n\n## Next\nweiter"


class DenkendeUebergabe(NahezuVollerKontext):
    """The handoff prompt answered in one of three shapes — only thought
    (``gedacht``), thought beside a written status (``beides``), or neither
    (``leer``). ``ende`` is the ending its stream reports."""

    def __init__(self, *args, art: str = "gedacht", ende: str = "stop", **kwargs):
        super().__init__(*args, handoff_text="", **kwargs)
        self.art = art
        self.ende = ende

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and letzte.content == zwischenstand.ANFRAGE_TEXT:
            if self.art in ("gedacht", "beides"):
                yield Stueck("reasoning", text=DENK_UEBERGABE)
            if self.art == "beides":
                yield Stueck("content", text=HANDOFF_ZWEI_PUNKTE)
            yield Stueck("stats", daten={"ende_grund": self.ende})
            return
        yield Stueck("stats", daten={"nutzung": {"total_tokens": self.tokens}})
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(id=f"w{self.durchlaeufe}", name="addieren", argumente={"a": 1, "b": 2})
            ],
        )


def test_eine_gedachte_uebergabe_plant_die_fortsetzung(config, client):
    """A handoff the model thought instead of writing is a handoff: the run
    ends 'unterbrochen' with kontext_voll, and the continuation carries the
    thinking — the same swap chat and job make at the end of a run
    (app/reasoning.denktext_als_antwort)."""
    agent_schreiben(config)
    provider_setzen(client, DenkendeUebergabe(mock_endpunkt("test")))
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "unterbrochen"
    assert daten["end_reason"] == "kontext_voll"
    assert daten["result"] == DENK_UEBERGABE

    (eintrag,) = client.app.state.repositories.cronjobs.auflisten()
    assert eintrag.aktiv is True
    assert eintrag.erledigt_anzahl == 2
    assert DENK_UEBERGABE in eintrag.task


def test_eine_geschriebene_uebergabe_schlaegt_den_denktext(config, client):
    """Silence test: a status that was written beside thinking is taken as
    it is — the stage keeps the two apart, exactly as in chat and job."""
    agent_schreiben(config)
    provider_setzen(client, DenkendeUebergabe(mock_endpunkt("test"), art="beides"))
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "unterbrochen"
    assert daten["result"] == HANDOFF_ZWEI_PUNKTE


def test_eine_uebergabe_ohne_text_und_ohne_denktext_bleibt_gescheitert(config, client):
    """Silence test: neither a written status nor thinking is no handoff —
    the run ends as failed, and nothing is scheduled."""
    agent_schreiben(config)
    provider_setzen(client, DenkendeUebergabe(mock_endpunkt("test"), art="leer"))
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "gescheitert"
    assert client.app.state.repositories.cronjobs.auflisten() == []


def test_gedachte_uebergabe_an_der_grenze_bleibt_gescheitert(config, client):
    """Silence test: thinking cut off at the ceiling is no handoff — the run
    ends as failed, and nothing is scheduled."""
    agent_schreiben(config)
    provider_setzen(client, DenkendeUebergabe(mock_endpunkt("test"), ende="length"))
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "gescheitert"
    assert client.app.state.repositories.cronjobs.auflisten() == []


def test_uebergabe_bekommt_eine_grenze_die_ins_fenster_passt(config, client):
    """The handoff fires at 90 % of the WHOLE window (unchanged — the same
    number the context bar itself shows), so its own request — sent beside
    the transcript that just triggered it — must not carry the round's
    ordinary ceiling unchanged: that ceiling is exactly what stopped
    fitting."""
    agent_schreiben(config, kopf="model: test\nmax_tokens: 900")
    provider = provider_setzen(
        client,
        NahezuVollerKontext(
            mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE, tokens=901
        ),
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "unterbrochen"
    assert daten["end_reason"] == "kontext_voll"
    (eintrag,) = client.app.state.repositories.cronjobs.auflisten()
    assert eintrag.basisaufgabe == "Los"

    # The last call made: the run ends right after the handoff succeeds, so
    # nothing later mutates its ``max_tokens`` the way the shared,
    # ever-growing ``nachrichten`` list would if read out of a past entry.
    handoff = provider.letzte_anfrage
    assert handoff.max_tokens is not None
    assert handoff.max_tokens < 900


def test_uebergabe_mit_reichlich_platz_bleibt_bei_der_eingestellten_grenze(config, client):
    """Schweigeprobe: with plenty of window left beside the transcript, the
    handoff's own request still goes out with the set ceiling, unchanged."""
    agent_schreiben(config, kopf="model: test\nmax_tokens: 50")
    provider = provider_setzen(
        client,
        NahezuVollerKontext(
            mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE, tokens=90_100
        ),
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 100_000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["end_reason"] == "kontext_voll"
    # The last call made: the run ends right after the handoff succeeds, so
    # nothing later mutates its ``max_tokens`` the way the shared,
    # ever-growing ``nachrichten`` list would if read out of a past entry.
    handoff = provider.letzte_anfrage
    assert handoff.max_tokens == 50


async def test_die_ursprungsaufgabe_waechst_nicht_mit_jedem_neustart(config, client):
    """The second handoff on a chain must wrap the chain's real original
    task (kept on the cron entry as ``basisaufgabe``) — not the FIRST
    handoff's own wrapped text, which is what ``task`` already holds by
    then. Re-wrapping that would grow the opening message with every
    restart, exactly what ``basisaufgabe`` exists to prevent."""
    agent_schreiben(config)
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000
    repositories = client.app.state.repositories
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]

    def anstossen(task, cronjob_id=None):
        return auftrag_anstossen(
            config=client.app.state.config,
            repositories=repositories,
            discovery=client.app.state.discovery,
            generierungen=client.app.state.generierungen,
            registry=getattr(client.app.state, "werkzeuge", None),
            agent=agent,
            task=task,
            endpoint_id=None,
            user_id="standard",
            sprache="de",
            cronjob_id=cronjob_id,
        )

    erster = anstossen("Ordner X aufräumen")
    await _bis_beendet(repositories, erster.id)
    (eintrag,) = repositories.cronjobs.auflisten()
    assert eintrag.basisaufgabe == "Ordner X aufräumen"
    assert eintrag.task.count("Original task:") == 1

    zweiter = anstossen(eintrag.task, cronjob_id=eintrag.id)
    await _bis_beendet(repositories, zweiter.id)
    aktualisiert = repositories.cronjobs.holen(eintrag.id)
    assert aktualisiert.basisaufgabe == "Ordner X aufräumen"
    assert aktualisiert.task.count("Original task:") == 1
    assert "Original task: Continue this job" not in aktualisiert.task


async def test_ein_vorhandener_termin_bleibt_unangetastet_bekommt_aber_eine_eigene_kette(
    config, client
):
    """A chain creating its own entry overturns what this test
    used to check: an entry the tool or a person already created
    (``basisaufgabe`` still NULL) is never adopted — that is someone's own
    schedule, not the program's bookkeeping. It keeps its own text and time
    untouched; the chain gets its own, separate entry instead, seeded from
    the same counters so the ceiling still applies."""
    agent_schreiben(config)
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000
    repositories = client.app.state.repositories
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    vorhandener = repositories.cronjobs.erstellen(
        agent="recherche", task="Ordner X aufräumen", zeitplan="08:00", herkunft="chat"
    )
    assert vorhandener.basisaufgabe is None

    def anstossen(task, cronjob_id):
        return auftrag_anstossen(
            config=client.app.state.config,
            repositories=repositories,
            discovery=client.app.state.discovery,
            generierungen=client.app.state.generierungen,
            registry=getattr(client.app.state, "werkzeuge", None),
            agent=agent,
            task=task,
            endpoint_id=None,
            user_id="standard",
            sprache="de",
            cronjob_id=cronjob_id,
        )

    erster = anstossen("Ordner X aufräumen", vorhandener.id)
    await _bis_beendet(repositories, erster.id)

    unveraendert = repositories.cronjobs.holen(vorhandener.id)
    assert unveraendert.task == "Ordner X aufräumen"
    assert unveraendert.zeitplan == "08:00"
    assert unveraendert.basisaufgabe is None

    (neue_kette,) = [
        eintrag for eintrag in repositories.cronjobs.auflisten() if eintrag.id != vorhandener.id
    ]
    assert neue_kette.basisaufgabe == "Ordner X aufräumen"
    assert neue_kette.neustarts == 1


async def test_berichtzeile_einer_fortsetzung_zeigt_die_ursprungsaufgabe(config, client):
    """A restart chain's own report line shows the chain's real task, not
    the wrapped restart prompt this one run's own row carries."""
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    repositories = client.app.state.repositories
    kette = repositories.cronjobs.erstellen(
        agent="recherche",
        task=(
            "Continue this job. Original task: Clean up folder X.\n\n"
            "Status from the previous run: …"
        ),
        zeitplan="08:00",
        herkunft="agent",
        basisaufgabe="Clean up folder X.",
    )
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]

    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task=kette.task,
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=kette.id,
    )
    await _bis_beendet(repositories, auftrag.id)

    liste = client.get("/api/v1/jobs").json()
    (zeile,) = [eintrag for eintrag in liste if eintrag["id"] == auftrag.id]
    assert zeile["task"] == "Clean up folder X."

    einzel = client.get(f"/api/v1/jobs/{auftrag.id}").json()
    assert einzel["task"] == "Clean up folder X."


async def test_ein_von_hand_gestarteter_lauf_zeigt_weiter_seinen_eigenen_text(config, client):
    """Schweigeprobe 1: a run nobody's chain claims shows its own task,
    exactly as before."""
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    repositories = client.app.state.repositories

    auftrag_id = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Ordner Y prüfen"}
    ).json()["id"]
    await _bis_beendet(repositories, auftrag_id)

    liste = client.get("/api/v1/jobs").json()
    (zeile,) = [eintrag for eintrag in liste if eintrag["id"] == auftrag_id]
    assert zeile["task"] == "Ordner Y prüfen"


async def test_ein_lauf_aus_einem_eigenen_termin_zeigt_weiter_seinen_eigenen_text(config, client):
    """Schweigeprobe 2: a run fired by somebody's own schedule (no
    ``basisaufgabe``, not a chain) shows its own task too."""
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))
    repositories = client.app.state.repositories
    termin = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="08:00", herkunft="chat",
    )
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]

    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task=termin.task,
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=termin.id,
    )
    await _bis_beendet(repositories, auftrag.id)

    liste = client.get("/api/v1/jobs").json()
    (zeile,) = [eintrag for eintrag in liste if eintrag["id"] == auftrag.id]
    assert zeile["task"] == "Water the plants"


async def _bis_beendet(repositories, auftrag_id: str, timeout: float = 5.0):
    """Awaits a job's own end — direct repository polling, on the SAME
    running loop the background run's task was created on. A synchronous
    ``asyncio.run(...)`` per call, as the alarm-clock tests use, would spin
    up and tear down its OWN loop each time and orphan that task instead."""
    frist = time.monotonic() + timeout
    while time.monotonic() < frist:
        auftrag = repositories.auftraege.holen(auftrag_id)
        if auftrag is not None and auftrag.zustand in ENDE:
            return auftrag
        await asyncio.sleep(0.01)
    raise AssertionError("the job reached no end state")


async def _run_through(client, auftrag_id: str, timeout: float = 5.0):
    """Awaits the job's end state and then the end of the run behind it —
    to be called right after the job was started, while its run is still
    registered. The row carries its end state before the run is through:
    the schedule's bookkeeping and the announcement, which goes out in a
    worker thread, come after it. A test that reads what the announcement
    noted, or that it stayed silent, has to wait for the run."""
    run = client.app.state.generierungen.fuer_chat(auftrag_id)
    assert run is not None, "the job's run is not registered any more"
    auftrag = await _bis_beendet(client.app.state.repositories, auftrag_id, timeout)
    await asyncio.wait_for(run.fertig.wait(), timeout)
    return auftrag


async def test_wachsende_erledigt_liste_setzt_denselben_cronjob_fort(config, client):
    """A second handoff on the SAME chain updates the existing entry rather
    than piling up a new one every restart."""
    agent_schreiben(config)
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000
    repositories = client.app.state.repositories
    vorheriger = repositories.cronjobs.erstellen(
        agent="recherche", task="weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe="weiter",
    )
    repositories.cronjobs.fortschritt_setzen(
        vorheriger.id, erledigt_anzahl=1, ohne_fortschritt=0, neustarts=1
    )

    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="weiter",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=vorheriger.id,
    )
    await _bis_beendet(repositories, auftrag.id)

    assert repositories.cronjobs.auflisten() == [repositories.cronjobs.holen(vorheriger.id)]
    aktualisiert = repositories.cronjobs.holen(vorheriger.id)
    assert aktualisiert.erledigt_anzahl == 2
    assert aktualisiert.ohne_fortschritt == 0
    assert aktualisiert.neustarts == 2
    assert aktualisiert.aktiv is True


async def test_stillstand_ueber_die_grenze_pausiert_den_cronjob(config, client):
    agent_schreiben(config)
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000
    repositories = client.app.state.repositories
    # Two done bullets already, twice in a row without growing — the next
    # non-growing handoff (also two bullets) is the third and trips the
    # breaker (app/zwischenstand.py, OHNE_FORTSCHRITT_GRENZE).
    vorheriger = repositories.cronjobs.erstellen(
        agent="recherche", task="weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe="weiter",
    )
    repositories.cronjobs.fortschritt_setzen(
        vorheriger.id, erledigt_anzahl=2, ohne_fortschritt=2, neustarts=5
    )

    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="weiter",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=vorheriger.id,
    )
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert beendet.ende_grund == "kein_fortschritt"
    aktualisiert = repositories.cronjobs.holen(vorheriger.id)
    assert aktualisiert.aktiv is False
    # Not rescheduled again — the task text on the entry is untouched.
    assert aktualisiert.task == "weiter"


async def test_stillstand_laesst_einen_fremden_termin_aktiv(config, client):
    """A daily reminder without basisaufgabe runs into the context
    limit, stalls, and must stay exactly as it was rather than getting
    switched off."""
    agent_schreiben(config)
    provider_setzen(
        client, NahezuVollerKontext(mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000
    repositories = client.app.state.repositories
    fremder_termin = repositories.cronjobs.erstellen(
        agent="recherche", task="Ordner X aufräumen", zeitplan="08:00", herkunft="chat",
    )
    repositories.cronjobs.fortschritt_setzen(
        fremder_termin.id, erledigt_anzahl=2, ohne_fortschritt=2, neustarts=5
    )

    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Ordner X aufräumen",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=fremder_termin.id,
    )
    await _bis_beendet(repositories, auftrag.id)

    unveraendert = repositories.cronjobs.holen(fremder_termin.id)
    assert unveraendert.aktiv is True
    assert unveraendert.task == "Ordner X aufräumen"
    assert unveraendert.zeitplan == "08:00"


# --- Compacting in place instead of restarting (app/verdichtung.py)


class UeberDerVerdichtungsschwelle(MockProvider):
    """Plays out enough real rounds first that the transcript has a genuine
    middle to compact — low token counts, so nothing but the transcript
    grows.

    Each build-up round carries real WEIGHT, because the verbatim tail is a
    token budget now and not a message count: a history of one-line rounds
    fits into the tail whole, however many of them there are, and then
    there is no middle at all. Fifteen rounds at this size run past the
    budget with room to spare. Once there is a middle, one round
    reports a reading between the compaction threshold (50%) and the
    handoff's own (90%), still with a tool call so the loop keeps going.
    The one request whose last message is the compaction prompt
    (app/verdichtung.ANFRAGE_TEXT) answers with ``zusammenfassung`` instead;
    every round after that answers with plain text, so the run finishes
    normally afterward."""

    def __init__(self, *args, zusammenfassung: str, aufbau_runden: int = 15, tokens: int = 600, **kwargs):
        super().__init__(*args, **kwargs)
        self.zusammenfassung = zusammenfassung
        self.aufbau_runden = aufbau_runden
        self.tokens = tokens
        self._echte_runden = 0
        # A round's own share of the verbatim tail. Sized so the build-up
        # runs well past the budget: what is pinned then covers only the
        # last few rounds and there is a real middle between them and the
        # pinned opening.
        self.fuellung = (verdichtung.LETZTE_ZEICHEN // aufbau_runden) * 2

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and letzte.content == verdichtung.ANFRAGE_TEXT:
            yield Stueck("content", text=self.zusammenfassung)
            return
        self._echte_runden += 1
        if self._echte_runden <= self.aufbau_runden:
            yield Stueck("content", text="x" * self.fuellung)
            yield Stueck("stats", daten={"nutzung": {"total_tokens": 10}})
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    # Different arguments every round — a rejected tool
                    # call repeated unchanged three times in a row ends the
                    # run on its own (app/schleifenwaechter.py),
                    # which this build-up must not trip.
                    Werkzeugaufruf(
                        id=f"w{self._echte_runden}", name="addieren",
                        argumente={"a": self._echte_runden, "b": 2},
                    )
                ],
            )
            return
        if self._echte_runden == self.aufbau_runden + 1:
            yield Stueck("stats", daten={"nutzung": {"total_tokens": self.tokens}})
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id="wx", name="addieren", argumente={"a": 1, "b": 2})],
            )
            return
        yield Stueck("content", text="fertig")


def test_unter_der_schwelle_wird_nicht_verdichtet(config, client):
    """A context reading below 50% must leave the history exactly as the
    round produced it — no summarizing request at all, however long the
    transcript already is."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    provider = provider_setzen(
        client,
        UeberDerVerdichtungsschwelle(
            mock_endpunkt("test"), zusammenfassung="gerafft", aufbau_runden=15,
            tokens=10_000,
        ),
    )
    # 10,000 of 100,000 is 10%. The window has to be wider than the
    # transcript as well: under it there is no room to write a summary in,
    # no summarizing request would go out whatever the reading said
    # (app/verdichtung.py), and this test would pass without measuring
    # anything.
    client.app.state.discovery.zustaende["test"].context_tokens = 100_000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "fertig"
    assert client.app.state.repositories.cronjobs.auflisten() == []
    assert all(
        n.content != verdichtung.ANFRAGE_TEXT
        for anfrage in provider.alle_anfragen
        for n in anfrage.nachrichten
    )


def test_eine_eingestellte_antwortlaenge_laesst_frueher_verdichten(config, client):
    """A ceiling set in the agent head is reserved out of the same window, so
    the threshold measures against what is left: a reading that stays under
    the threshold of the WHOLE window is over the threshold of the usable one."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 30\nmax_tokens: 60000")
    provider = provider_setzen(
        client,
        UeberDerVerdichtungsschwelle(
            mock_endpunkt("test"), zusammenfassung="gerafft", tokens=50_000
        ),
    )
    # 50,000 of 100,000 is half the window — under the shipped threshold. Of
    # the 40,000 left beside the ceiling it is far over it.
    client.app.state.discovery.zustaende["test"].context_tokens = 100_000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "fertig"
    assert any(
        n.content == verdichtung.ANFRAGE_TEXT
        for anfrage in provider.alle_anfragen
        for n in anfrage.nachrichten
    )


def test_ohne_eingestellte_laenge_bleibt_dieselbe_lesung_darunter(config, client):
    """The silence probe for the test above: the same reading, the same
    window, no ceiling — and nothing is summarized."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    provider = provider_setzen(
        client,
        UeberDerVerdichtungsschwelle(
            mock_endpunkt("test"), zusammenfassung="gerafft", tokens=50_000
        ),
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 100_000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "fertig"
    assert all(
        n.content != verdichtung.ANFRAGE_TEXT
        for anfrage in provider.alle_anfragen
        for n in anfrage.nachrichten
    )


def test_ueber_der_schwelle_verdichtet_und_laeuft_weiter(config, client):
    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    provider = provider_setzen(
        client,
        UeberDerVerdichtungsschwelle(
            mock_endpunkt("test"), zusammenfassung="gerafft", tokens=60_000
        ),
    )
    # 60,000/70,000 = 86%, over the shipped threshold. The ratio is what
    # this test is about, not the number it is compared against — and the
    # number has to be one a real server could have: a window UNDER the
    # transcript it is measuring has no room to write a summary in, and the
    # fold would go to the emergency text without a model ever being asked
    # (app/verdichtung.py).
    client.app.state.discovery.zustaende["test"].context_tokens = 70_000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    # Finished in the same pass — no restart, no cron entry.
    assert daten["state"] == "fertig"
    assert client.app.state.repositories.cronjobs.auflisten() == []
    # The compaction really ran — not just a coincidentally clean finish.
    assert any(
        n.content == verdichtung.ANFRAGE_TEXT
        for anfrage in provider.alle_anfragen
        for n in anfrage.nachrichten
    )


def test_die_faltbitte_eines_auftrags_traegt_keine_werkzeuge(config, mcp_client):
    """A job folding its own list asks for the summary without tools, as the
    fold of a chat's rows does. Offered the job's tools, the model could
    answer with a call, which the fold reads as an empty summary. Silence
    probe: every round of the job still carries the tools."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    provider = provider_setzen(
        mcp_client,
        UeberDerVerdichtungsschwelle(
            mock_endpunkt("test"), zusammenfassung="gerafft", tokens=60_000
        ),
    )
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = 70_000

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert daten["state"] == "fertig"
    faltungen = [
        a for a in provider.alle_anfragen
        if a.nachrichten[-1].content == verdichtung.ANFRAGE_TEXT
    ]
    runden = [a for a in provider.alle_anfragen if a not in faltungen]
    assert faltungen, "the job did not fold itself"
    assert all(a.werkzeuge == [] for a in faltungen), "the fold request offers tools"
    assert runden and all(a.werkzeuge for a in runden), "a round lost its tools"


def test_die_faltung_eines_auftrags_laesst_seine_denklaenge_zurueck(config, client):
    """A job with a thinking length, on a llama.cpp model whose thinking can
    be switched off: its fold asks with the switch alone, and every round of
    the job itself still carries the length."""
    from app.config import Capabilities, EndpointConfig

    agent_schreiben(config, kopf="model: test\nmax_rounds: 30\nreasoning_budget: 2048")
    provider = provider_setzen(
        client,
        UeberDerVerdichtungsschwelle(
            mock_endpunkt("test"), zusammenfassung="gerafft", tokens=60_000
        ),
    )
    zustand = client.app.state.discovery.zustaende["test"]
    # 60,000 of 70,000 is 86%, over the shipped threshold — and a window
    # wide enough to write the summary of this transcript inside.
    zustand.context_tokens = 70_000
    zustand.endpunkt = EndpointConfig(
        id="test",
        base_url="http://127.0.0.1:9/v1",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(thinking=True),
    )

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    assert auf_ende_warten(client, kennung)["state"] == "fertig"

    def ist_faltung(anfrage) -> bool:
        return anfrage.nachrichten[-1].content == verdichtung.ANFRAGE_TEXT

    faltungen = [a for a in provider.alle_anfragen if ist_faltung(a)]
    runden = [a for a in provider.alle_anfragen if not ist_faltung(a)]
    assert len(faltungen) == 1
    assert faltungen[0].zusatz == {"reasoning_effort": "none"}
    assert "reasoning_budget" not in faltungen[0].parameter
    assert runden
    assert all(a.parameter.get("reasoning_budget") == 2048 for a in runden)


def test_ein_auftrag_sendet_eine_gesperrte_denklaenge_nicht(config, client):
    """The lock is tested at the job path, not only on its own: a model that
    cannot think gets no thinking length, whatever the agent head names.
    Taken out of the job path, this test fails."""
    from app.config import Capabilities

    agent_schreiben(config, kopf="model: test\nmax_rounds: 3\nreasoning_budget: 2048")
    endpunkt = mock_endpunkt(
        "test",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(streaming=True, tool_calls=True, thinking=False),
    )
    provider = provider_setzen(client, MockProvider(endpunkt))
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt = endpunkt

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    assert auf_ende_warten(client, kennung)["state"] == "fertig"

    assert provider.alle_anfragen
    assert all("reasoning_budget" not in a.parameter for a in provider.alle_anfragen)


class FaltungAblehnend(UeberDerVerdichtungsschwelle):
    """Refuses the fold whenever it carries a thinking switch, with the
    sentence a server uses to refuse the field."""

    async def streamen(self, anfrage):
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and letzte.content == verdichtung.ANFRAGE_TEXT and anfrage.zusatz:
            self.letzte_anfrage = anfrage
            self.alle_anfragen.append(anfrage)
            raise ProviderFehler(
                "abgelehnt", status=400,
                rohtext="thinking: this parameter is not supported by this model",
            )
        async for stueck in super().streamen(anfrage):
            yield stueck


def test_ein_auftrag_lernt_die_ablehnung_seiner_faltung(config, client):
    """A job whose fold the server refuses writes the refusal down under the
    server's id — and the next job on that server folds without the switch.
    The same list a chat on that server reads (app/denkablehnung.py)."""
    from app import denkablehnung
    from app.config import Capabilities, EndpointConfig

    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    einstellungen = client.app.state.repositories.einstellungen
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 70_000
    zustand.endpunkt = EndpointConfig(
        id="test",
        base_url="http://127.0.0.1:9/v1",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(thinking=True),
    )

    def faltungen(provider):
        return [
            a for a in provider.alle_anfragen
            if a.nachrichten[-1].content == verdichtung.ANFRAGE_TEXT
        ]

    erster = provider_setzen(
        client,
        FaltungAblehnend(mock_endpunkt("test"), zusammenfassung="gerafft", tokens=60_000),
    )
    kennung = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    auf_ende_warten(client, kennung)
    assert faltungen(erster) and faltungen(erster)[0].zusatz, "no switch went out"
    assert denkablehnung.gemerkt(einstellungen, "test") == ["off"]

    zweiter = provider_setzen(
        client,
        FaltungAblehnend(mock_endpunkt("test"), zusammenfassung="gerafft", tokens=60_000),
    )
    kennung = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    assert auf_ende_warten(client, kennung)["state"] == "fertig"
    assert faltungen(zweiter) and all(a.zusatz == {} for a in faltungen(zweiter))


def test_a_job_keeps_its_fold_refusal_where_the_model_list_reads_it(config, client):
    """A job booked under a catalogue server alone (`test`) writes its fold's
    refusal under the id the model list reads (`test:m`), the list a chat
    on that model reads too — not under the booked id."""
    from app import denkablehnung
    from app.config import Capabilities, EndpointConfig

    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    einstellungen = client.app.state.repositories.einstellungen
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 70_000
    zustand.modelle = ["m"]
    zustand.gemeldeter_name = "m"
    zustand.endpunkt = EndpointConfig(
        id="test",
        base_url="http://127.0.0.1:9/v1",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(thinking=True),
    )
    provider = provider_setzen(
        client,
        FaltungAblehnend(mock_endpunkt("test"), zusammenfassung="gerafft", tokens=60_000),
    )
    kennung = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    auf_ende_warten(client, kennung)
    assert any(
        a.nachrichten[-1].content == verdichtung.ANFRAGE_TEXT and a.zusatz
        for a in provider.alle_anfragen
    ), "no switch went out"
    assert denkablehnung.gemerkt(einstellungen, "test:m") == ["off"]
    assert denkablehnung.gemerkt(einstellungen, "test") == []


def test_eine_im_chat_gelernte_ablehnung_gilt_auch_fuer_den_auftrag(config, client):
    """The silence probe: one list per server. A refusal the chat wrote
    down keeps the job's fold on the same server from sending the switch."""
    from app import denkablehnung
    from app.config import Capabilities, EndpointConfig

    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    denkablehnung.merken(client.app.state.repositories.einstellungen, "test", "off")
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = 70_000
    zustand.endpunkt = EndpointConfig(
        id="test",
        base_url="http://127.0.0.1:9/v1",
        parameter_dialect="llama_cpp",
        capabilities=Capabilities(thinking=True),
    )
    provider = provider_setzen(
        client,
        UeberDerVerdichtungsschwelle(mock_endpunkt("test"), zusammenfassung="gerafft", tokens=60_000),
    )
    kennung = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    assert auf_ende_warten(client, kennung)["state"] == "fertig"
    faltungen = [
        a for a in provider.alle_anfragen
        if a.nachrichten[-1].content == verdichtung.ANFRAGE_TEXT
    ]
    assert faltungen and all(a.zusatz == {} for a in faltungen)


class ZweimalUeberDerSchwelle(UeberDerVerdichtungsschwelle):
    """Crosses the compaction threshold twice in one run, with a genuine,
    real middle to fold each time — proving compaction keeps firing on
    every real threshold hit, not just the first one the compaction brake also has
    to leave alone."""

    async def streamen(self, anfrage):
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and letzte.content == verdichtung.ANFRAGE_TEXT:
            self.letzte_anfrage = anfrage
            self.alle_anfragen.append(anfrage)
            self.durchlaeufe += 1
            yield Stueck("content", text=self.zusammenfassung)
            return
        # Real rounds, cheap, past the point the base class would end the
        # run: keeps building a genuine second middle after the first
        # compaction, then crosses the threshold again to trigger it.
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        self._echte_runden += 1
        ueber_schwelle = self._echte_runden in (self.aufbau_runden, 2 * self.aufbau_runden)
        # Weight, for the same reason as the parent: the verbatim tail is a
        # token budget, and a transcript of one-line rounds has no middle
        # however many rounds it has.
        yield Stueck("content", text="x" * self.fuellung)
        yield Stueck(
            "stats",
            daten={"nutzung": {"total_tokens": self.tokens if ueber_schwelle else 10}},
        )
        if self._echte_runden <= 2 * self.aufbau_runden:
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"w{self._echte_runden}", name="addieren",
                        argumente={"a": self._echte_runden, "b": 2},
                    )
                ],
            )
            return
        yield Stueck("content", text="fertig")


def test_ueber_der_schwelle_verdichtet_bei_jedem_erreichen(config, client):
    """The opposite of the "no savings" case: real savings twice over must
    trigger compaction twice, not just once — success must not disable the
    rest of the run the way a no-savings attempt does."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 40")
    provider = provider_setzen(
        client,
        ZweimalUeberDerSchwelle(
            mock_endpunkt("test"), zusammenfassung="gerafft", tokens=60_000
        ),
    )
    # 60,000/70,000 = 86%, over the shipped threshold. The ratio is what
    # this test is about, not the number it is compared against — and the
    # number has to be one a real server could have: a window UNDER the
    # transcript it is measuring has no room to write a summary in, and the
    # fold would go to the emergency text without a model ever being asked
    # (app/verdichtung.py).
    client.app.state.discovery.zustaende["test"].context_tokens = 70_000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "fertig"
    versuche = [
        anfrage
        for anfrage in provider.alle_anfragen
        if anfrage.nachrichten[-1].content == verdichtung.ANFRAGE_TEXT
    ]
    assert len(versuche) == 2
    status_schritte = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    assert status_schritte.count("Der Verlauf wurde komprimiert, damit der Kontext nicht vollständig belegt wird.") == 2


class UeberDerSchwelleOhneErsparnis(MockProvider):
    """Every round reports a token count over the compaction threshold and
    keeps calling a tool, so the run keeps giving compaction more chances
    to run — but every summarizing answer is at least as long as what it
    would replace, so none of them ever actually shrinks the history. This
    is the case the compaction brake exists for: does the run keep paying for an
    attempt that never helps?"""

    def __init__(self, *args, runden: int = 20, tokens: int = 600, **kwargs):
        super().__init__(*args, **kwargs)
        self.runden = runden
        self.tokens = tokens
        self._echte_runden = 0
        # Weight per round, so the transcript runs past the verbatim tail
        # budget and there is a middle to refuse to shrink in the first
        # place — see the parent mock.
        self.fuellung = (verdichtung.LETZTE_ZEICHEN // runden) * 2

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and letzte.content == verdichtung.ANFRAGE_TEXT:
            # Never shorter than the middle it would replace. Sized off the
            # transcript rather than a fixed number, which stopped being
            # long enough once the rounds carried real weight.
            yield Stueck("content", text="x" * (self.fuellung * self.runden * 2))
            return
        self._echte_runden += 1
        yield Stueck("content", text="x" * self.fuellung)
        yield Stueck("stats", daten={"nutzung": {"total_tokens": self.tokens}})
        if self._echte_runden <= self.runden:
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"w{self._echte_runden}", name="addieren",
                        argumente={"a": self._echte_runden, "b": 2},
                    )
                ],
            )
            return
        yield Stueck("content", text="fertig")


def test_eine_verdichtung_ohne_ersparnis_wird_nicht_wiederholt(config, client):
    """The history stays over threshold for many rounds running — a
    compaction attempt gets ONE chance per run, not one every round."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 25")
    provider = provider_setzen(
        client, UeberDerSchwelleOhneErsparnis(mock_endpunkt("test"), tokens=60_000)
    )
    # 60,000/70,000 = 86%, over the shipped threshold. The ratio is what
    # this test is about, not the number it is compared against — and the
    # number has to be one a real server could have: a window UNDER the
    # transcript it is measuring has no room to write a summary in, and the
    # fold would go to the emergency text without a model ever being asked
    # (app/verdichtung.py).
    client.app.state.discovery.zustaende["test"].context_tokens = 70_000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "fertig"
    versuche = [
        anfrage
        for anfrage in provider.alle_anfragen
        if anfrage.nachrichten[-1].content == verdichtung.ANFRAGE_TEXT
    ]
    assert len(versuche) == 1
    status_schritte = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    assert any("nicht verkürzt" in s for s in status_schritte)


# --- The fold trigger counts what a round's own reading cannot yet know
# about: the round's own reading is one request behind, so it must
# be asked at the END of the round, with an estimate of what the round's
# own tool calls just added on top of it. ------------------------------


class _KonfigurierbaresWerkzeugergebnis(RegistryDouble):
    """Like ``RegistryDouble``, but ``riesig`` answers with a result of a
    size the test picks — the plain ``addieren`` stays fixed and small, for
    rounds that must not move the reading at all."""

    def __init__(self, gross: str) -> None:
        super().__init__()
        self._werkzeuge["riesig"] = (
            None, MCPWerkzeug(name="riesig", beschreibung="grosses ergebnis"), False,
        )
        self.gross = gross

    async def ausfuehren(
        self, name, argumente, bild_senke=None, ordner=None, chat_id=None,
        herkunft="chat", agent=None, shell_zeitgrenze=None,
    ):
        if name == "riesig":
            self.aufrufe.append((name, argumente))
            return self.gross
        return await super().ausfuehren(
            name, argumente, bild_senke, ordner=ordner, chat_id=chat_id,
            herkunft=herkunft, agent=agent, shell_zeitgrenze=shell_zeitgrenze,
        )


class _WerkzeugergebnisSchiebtUeberDieSchwelle(MockProvider):
    """A build-up like ``UeberDerVerdichtungsschwelle``, every round's OWN
    reading kept well under the threshold throughout — then one round whose
    tool result alone is large enough to push the NEXT request over it.

    ``anfrage`` is the SAME object for the whole run — the round loop
    mutates ``anfrage.nachrichten`` in place rather than rebuilding it, so
    ``self.alle_anfragen`` (a list of that one reference, appended again and
    again) shows every entry as the FINAL history once the run is over.
    ``aufzeichnung`` freezes what actually went out, one primitive snapshot
    per call, taken before anything later mutates the list further.
    """

    def __init__(self, *args, aufbau_runden: int = 15, stand: int = 500, **kwargs):
        super().__init__(*args, **kwargs)
        self.aufbau_runden = aufbau_runden
        # What the round before the big tool result reports. Paired with the
        # window the test sets: what matters is the share of it, never the
        # number.
        self.stand = stand
        self._echte_runden = 0
        self.fuellung = (verdichtung.LETZTE_ZEICHEN // aufbau_runden) * 2
        self.aufzeichnung: list[tuple[str, int]] = []

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        self.aufzeichnung.append((anfrage.nachrichten[-1].content, len(anfrage.nachrichten)))
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and letzte.content == verdichtung.ANFRAGE_TEXT:
            yield Stueck("content", text="gerafft")
            return
        self._echte_runden += 1
        if self._echte_runden <= self.aufbau_runden:
            yield Stueck("content", text="x" * self.fuellung)
            yield Stueck("stats", daten={"nutzung": {"total_tokens": 10}})
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"w{self._echte_runden}", name="addieren",
                        argumente={"a": self._echte_runden, "b": 2},
                    )
                ],
            )
            return
        if self._echte_runden == self.aufbau_runden + 1:
            # Half the window — well under the shipped 80%, on this round's
            # own reading alone.
            yield Stueck("stats", daten={"nutzung": {"total_tokens": self.stand}})
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id="wgross", name="riesig", argumente={})],
            )
            return
        yield Stueck("content", text="fertig")


def test_ein_grosses_werkzeugergebnis_faltet_vor_der_naechsten_runde(config, mcp_client):
    """Checked where it used to be, right after the round's own
    reading came back, the trigger never saw this round's own tool result
    at all: that number does not exist yet at that point in the round. Moved
    to the end of the round, it does — and folds before the next request
    goes out, not on the round after that one."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    # 120,000 characters is 30,000 tokens, on top of the round's own 50,000
    # of 100,000: half the window by itself, over the shipped 80% once the
    # result is counted too. The window is big enough to write the fold's
    # own summary inside — under the transcript it would have no room for
    # one and the fold would never ask a model at all (app/verdichtung.py).
    registry = _KonfigurierbaresWerkzeugergebnis(gross="y" * 120_000)
    mcp_client.app.state.werkzeuge = registry
    provider = provider_setzen(
        mcp_client,
        _WerkzeugergebnisSchiebtUeberDieSchwelle(mock_endpunkt("test"), stand=50_000),
    )
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = 100_000

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert daten["state"] == "fertig"
    inhalte = [inhalt for inhalt, _ in provider.aufzeichnung]
    laengen = [laenge for _, laenge in provider.aufzeichnung]
    # The compaction request is the only one whose last message is the
    # summarizing prompt itself.
    kompaktion_indizes = [i for i, inhalt in enumerate(inhalte) if inhalt == verdichtung.ANFRAGE_TEXT]
    assert len(kompaktion_indizes) == 1, "expected exactly one fold"
    kompaktion_index = kompaktion_indizes[0]
    # It sits directly between the round whose tool result pushed the
    # reading over and the round after it — folded before that next
    # request went out, not on the round after that one.
    ausloeser_laenge = laengen[kompaktion_index - 1]
    naechste_laenge = laengen[kompaktion_index + 1]
    # Without the fold, the next request would carry the triggering round's
    # own history plus the two rows (answer, tool result) that grew it —
    # folded, it carries less than that.
    assert naechste_laenge < ausloeser_laenge + 2


def test_die_antwort_der_runde_zaehlt_nicht_doppelt(config, mcp_client):
    """The round's own reading already carries the round's own
    answer, counted by the provider itself. Adding that answer's length a
    second time as 'new' would push a round just under the threshold over
    it for no reason; only what came after the reading — this round's own
    small tool result — may still be new."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 30")
    registry = _KonfigurierbaresWerkzeugergebnis(gross="y" * 4000)
    mcp_client.app.state.werkzeuge = registry
    aufbau_runden = 15

    class _LangeAntwortKnappUnterDerSchwelle(_WerkzeugergebnisSchiebtUeberDieSchwelle):
        async def streamen(self, anfrage):
            self.letzte_anfrage = anfrage
            self.alle_anfragen.append(anfrage)
            self.durchlaeufe += 1
            letzte = anfrage.nachrichten[-1]
            if letzte.role == "user" and letzte.content == verdichtung.ANFRAGE_TEXT:
                yield Stueck("content", text="gerafft")
                return
            self._echte_runden += 1
            if self._echte_runden <= self.aufbau_runden:
                yield Stueck("content", text="x" * self.fuellung)
                yield Stueck("stats", daten={"nutzung": {"total_tokens": 10}})
                yield Stueck(
                    "tool_call",
                    werkzeugaufrufe=[
                        Werkzeugaufruf(
                            id=f"w{self._echte_runden}", name="addieren",
                            argumente={"a": self._echte_runden, "b": 2},
                        )
                    ],
                )
                return
            if self._echte_runden == self.aufbau_runden + 1:
                # 780 of 1000 is 78% — just under the shipped 80%, and this
                # reading is the ROUND's own: a long answer text is already
                # inside it, counted once by the provider.
                yield Stueck("content", text="a" * 5000)
                yield Stueck("stats", daten={"nutzung": {"total_tokens": 78_000}})
                yield Stueck(
                    "tool_call",
                    werkzeugaufrufe=[
                        Werkzeugaufruf(id="wklein", name="addieren", argumente={"a": 1, "b": 2})
                    ],
                )
                return
            yield Stueck("content", text="fertig")

    provider = provider_setzen(
        mcp_client, _LangeAntwortKnappUnterDerSchwelle(
            mock_endpunkt("test"), aufbau_runden=aufbau_runden,
        )
    )
    # 78,000 of 100,000 is 78% — just under the shipped 80%, and the small
    # tool result after it does not reach the threshold either. Only adding
    # the round's own answer a SECOND time would. Same window as the test
    # above, and for the same reason: under the transcript there would be no
    # room to write a summary in, and no request would go out whatever this
    # test did.
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = 100_000

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert daten["state"] == "fertig"
    assert all(
        n.content != verdichtung.ANFRAGE_TEXT
        for anfrage in provider.alle_anfragen
        for n in anfrage.nachrichten
    ), "the round's own answer was counted a second time"


# --- A chain's cron entry does not outlive the chain --


async def test_eine_beendete_kette_schaltet_ihren_cronjob_ab(config, client):
    """The gap restart chains multiplied: a restart chain's entry kept
    firing daily forever, because nothing ever switched it off on a normal
    ending — only the restart ceiling or a stall did."""
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Fertig."]))
    repositories = client.app.state.repositories
    kette = repositories.cronjobs.erstellen(
        agent="recherche", task="weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Ordner aufräumen",
    )

    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="weiter",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=kette.id,
    )
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert beendet.zustand == "fertig"
    assert repositories.cronjobs.holen(kette.id).aktiv is False


async def test_eine_echte_wiederkehrende_erinnerung_bleibt_aktiv(config, client):
    """The marker is basisaufgabe, not merely "this run came from a cron
    entry" — a standing daily reminder the cronjob tool created is fired the
    exact same way, and must keep recurring after it finishes."""
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Erledigt."]))
    repositories = client.app.state.repositories
    erinnerung = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="08:00", herkunft="agent",
    )

    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Water the plants",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=erinnerung.id,
    )
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert beendet.zustand == "fertig"
    assert repositories.cronjobs.holen(erinnerung.id).aktiv is True


async def test_ein_faelliger_cronjob_meldet_sich_am_ende(config, client, monkeypatch):
    """An entry with ``deliver = 'announce'`` plays a sound and
    shows the task text once its run ends — checked here through the real
    end-of-run path, with ``cronmeldung.melden`` swapped out so nothing
    actually plays during the test."""
    aufrufe = []
    zustand_bei_aufruf = []
    auftrag_id = {}

    erfolge = []

    def _pruefe_und_merke(text, *, erfolgreich, sprache=None):
        aufrufe.append(text)
        erfolge.append(erfolgreich)
        # The announcement used to sit BEFORE the run's
        # own bookkeeping — a run could look "läuft" for as long as speaking
        # took, and a crash in that window would make a restart resume a run
        # that was already finished. By the time this fires, the row must
        # already carry its end state.
        zustand_bei_aufruf.append(repositories.auftraege.holen(auftrag_id["wert"]).zustand)

    monkeypatch.setattr(cronmeldung, "melden", _pruefe_und_merke)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Erledigt."]))
    repositories = client.app.state.repositories
    erinnerung = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="08:00", herkunft="agent",
        deliver="announce",
    )

    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Water the plants",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=erinnerung.id,
    )
    auftrag_id["wert"] = auftrag.id
    await _run_through(client, auftrag.id)

    assert aufrufe == ["Water the plants"]
    assert zustand_bei_aufruf == ["fertig"]
    assert erfolge == [True]


async def test_ein_gescheiterter_cronjob_meldet_sich_genau_einmal(
    config, client, monkeypatch
):
    """A failed run gets its own sound and notification too — the opposite of
    staying silent, and audibly different from a success. But **once**, at the
    end of the chain, not once per link (Fund `deliver`, entschieden 01.09.).

    What this test used to assert was the first half alone, written
    before a lost provider handed its work to a continuation at
    all. A dead provider now restarts the work every couple of minutes, and
    a chain inherits ``deliver`` since ``e0c82c8`` — so "every failed run
    announces" had become up to ten notifications in a day for ONE piece of
    work, and nine of them said "this ended" about work that was still
    running.

    So the assertion is sharpened rather than dropped: the run that hands its
    work on is not an ending and stays quiet, and the run that really ends —
    the one with nothing behind it — says it, exactly once, with the failure
    sound. Both halves are checked here, in that order, because the second
    without the first would pass on a program that never announces at all.
    """
    aufrufe = []
    erfolge = []

    def _pruefe_und_merke(text, *, erfolgreich, sprache=None):
        aufrufe.append(text)
        erfolge.append(erfolgreich)

    monkeypatch.setattr(cronmeldung, "melden", _pruefe_und_merke)
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="Kabelbrand"))
    repositories = client.app.state.repositories
    erinnerung = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="08:00", herkunft="agent",
        deliver="announce",
    )

    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]

    async def _lauf(cronjob_id):
        auftrag = auftrag_anstossen(
            config=client.app.state.config,
            repositories=repositories,
            discovery=client.app.state.discovery,
            generierungen=client.app.state.generierungen,
            registry=getattr(client.app.state, "werkzeuge", None),
            agent=agent,
            task="Water the plants",
            endpoint_id=None,
            user_id="standard",
            sprache="de",
            cronjob_id=cronjob_id,
        )
        return await _run_through(client, auftrag.id)

    # The first run loses the provider and writes a continuation. It failed,
    # but the work did not end — and nothing is said about it.
    beendet = await _lauf(erinnerung.id)
    # And it does not stand there as a failure either: the work is on the
    # clock, so the run is 'unterbrochen' — cut short, resumable, not a
    # result — and the reports row draws it quietly instead of in red.
    assert beendet.zustand == "unterbrochen"
    assert beendet.ende_grund == "anbieter_ausfall"
    ketten = [e for e in repositories.cronjobs.auflisten() if e.id != erinnerung.id]
    assert len(ketten) == 1
    kette = ketten[0]
    assert kette.deliver == "announce"
    assert aufrufe == []

    # The chain at its restart ceiling: this run has nothing behind it, so it
    # IS the ending — and it is the one that speaks.
    repositories.cronjobs.fortschritt_setzen(
        kette.id,
        erledigt_anzahl=None,
        ohne_fortschritt=0,
        neustarts=zwischenstand.MAX_NEUSTARTS,
    )
    beendet = await _lauf(kette.id)

    assert beendet.zustand == "gescheitert"
    # And it says WHY. The notification used to be "Failed — Water the
    # plants" and nothing more: the reason existed, in the run's `ende` step,
    # in a step log that only opens for a run still going — so it was written
    # in the same breath it became unreachable. It rides in this same
    # notification now (app/cronmeldung.mit_grund), which is what keeps it at
    # one message rather than two.
    assert aufrufe == ["Water the plants — Modell antwortet nicht mehr"]
    assert erfolge == [False]

    # --- And once at the failure limit too, which this did not reach -----
    #
    # The boundary the two halves above walk straight past: an entry that
    # breaks on its LAST allowed run has two things to say and two callers
    # ready to say them. ``ausgang_verbuchen`` announces "… — stopped after
    # N failed runs" itself, and ``melde_wenn_faellig`` went out right
    # behind it regardless — two notifications, a moment apart, about one
    # ending. Only ``ziel_verbuchen`` in between was ever told
    # (``schon_gemeldet``); the blanket announcement was not.
    #
    # Set up so that nothing is handed on — the restart ceiling is already
    # reached, so this run is a real ending with nothing behind it, which is
    # what makes the failure counter see it at all.
    aufrufe.clear()
    erfolge.clear()
    eigener = repositories.cronjobs.erstellen(
        agent="recherche", task="Post holen", zeitplan="08:00", herkunft="chat",
        deliver="announce", fehlergrenze=1,
    )
    repositories.cronjobs.fortschritt_setzen(
        eigener.id,
        erledigt_anzahl=None,
        ohne_fortschritt=0,
        neustarts=zwischenstand.MAX_NEUSTARTS,
    )

    beendet = await _lauf(eigener.id)

    assert beendet.zustand == "gescheitert"
    assert repositories.cronjobs.holen(eigener.id).aktiv is False
    # ONE notification, and it is the limit's: it carries the fact the other
    # does not — this schedule has stopped and will not run again by itself.
    # What the other one carried stands behind it: why the run failed.
    assert aufrufe == [
        "Post holen — nach 1 fehlgeschlagenen Durchläufen gestoppt — Modell antwortet nicht mehr"
    ]
    assert erfolge == [False]


async def test_ein_abgebrochener_lauf_meldet_sich_nicht(config, client, monkeypatch):
    """An abort is the user's own action a second ago —
    it gets no announcement, contradicting what they just did."""
    aufrufe = []
    monkeypatch.setattr(
        cronmeldung, "melden", lambda text, *, erfolgreich, sprache=None: aufrufe.append(text)
    )
    agent_schreiben(config)
    provider_setzen(
        client,
        MockProvider(mock_endpunkt("test"), haeppchen=[f"T{i} " for i in range(100)], verzoegerung=0.05),
    )
    repositories = client.app.state.repositories
    erinnerung = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="08:00", herkunft="agent",
        deliver="announce",
    )

    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Water the plants",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=erinnerung.id,
    )
    assert client.post(f"/api/v1/jobs/{auftrag.id}/cancel").status_code == 200
    beendet = await _run_through(client, auftrag.id)

    assert beendet.zustand == "abgebrochen"
    assert aufrufe == []


async def test_ein_cronjob_auf_log_meldet_sich_nicht(config, client, monkeypatch):
    """The default: an entry with no ``deliver`` setting (log only) shows no
    notification."""
    aufrufe = []
    monkeypatch.setattr(
        cronmeldung, "melden", lambda text, *, erfolgreich, sprache=None: aufrufe.append(text)
    )
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Erledigt."]))
    repositories = client.app.state.repositories
    erinnerung = repositories.cronjobs.erstellen(
        agent="recherche", task="Water the plants", zeitplan="08:00", herkunft="agent",
    )

    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Water the plants",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=erinnerung.id,
    )
    await _run_through(client, auftrag.id)

    assert aufrufe == []


async def test_ein_weitergereichter_lauf_behaelt_seine_kette(config, client, monkeypatch):
    """A chain row survives the run that handed its work on — that row IS
    the continuation, and switching it off would end the chain the run just
    wrote. Measured on the provider-outage path, which reaches that ending
    by rescheduling rather than by writing a handoff, and so is the other
    way in than tests/test_cronfunde.py's overflow case.

    The name and the sentence here used to say "a gescheiterter Lauf keeps
    its chain": only a NORMAL ending was supposed to switch the row off, so
    a run that failed outright had to leave it standing. A later fix
    turned that round — every ending that did not hand the work on retires
    the row, because ``bald()`` gave it a daily time and it would otherwise
    fire again tomorrow with stale handoff text (app/api/v1/auftraege.py).
    What this test always measured was the handed-on half, which is the
    half that survived; only its label was left over from before."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="Kabelbrand"))
    repositories = client.app.state.repositories
    kette = repositories.cronjobs.erstellen(
        agent="recherche", task="weiter", zeitplan="08:00", herkunft="agent",
        basisaufgabe="Ordner aufräumen",
    )

    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="weiter",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        cronjob_id=kette.id,
    )
    beendet = await _bis_beendet(repositories, auftrag.id)

    # Handed on rather than failed — the outage retry rescheduled it, which
    # is exactly what leaves the chain standing.
    assert beendet.zustand == "unterbrochen"
    assert beendet.ende_grund == "anbieter_ausfall"
    assert repositories.cronjobs.holen(kette.id).aktiv is True


# --- The report needs to land somewhere durable ---------------


def test_fehlende_berichtsdatei_wird_gemeldet(config, mcp_client_echt, tmp_path):
    """write_file was offered and simply never called — the run still ends
    "fertig" (nothing here should turn a working answer into a failure),
    but the gap is now visible in the transcript instead of passing for a
    normal, complete run."""
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    agent_schreiben(
        config, kopf=f"model: test\ntools:\n  - write_file\nfolders:\n  - {geteilt}",
    )
    provider_setzen(mcp_client_echt, MockProvider(mock_endpunkt("test"), haeppchen=["Fertig."]))

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    assert daten["state"] == "fertig"
    status_schritte = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    assert any("Dieser Durchlauf hat keine Datei geschrieben" in s for s in status_schritte)


def test_geschriebene_berichtsdatei_wird_nicht_gemeldet(config, mcp_client_echt, tmp_path):
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    agent_schreiben(
        config,
        kopf=f"model: test\ntools:\n  - write_file\nfolders:\n  - {geteilt}\nmax_rounds: 2",
    )
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Fertig."],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1", name="write_file",
                    argumente={"path": "bericht.md", "content": "x"},
                )
            ],
        ),
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    assert daten["state"] == "fertig"
    status_schritte = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    assert not any("Dieser Durchlauf hat keine Datei geschrieben" in s for s in status_schritte)


def test_ohne_schreibwerkzeug_wird_nichts_gemeldet(config, mcp_client_echt, tmp_path):
    """No write_file offered at all — nothing to report on a run that was
    never in a position to write a file."""
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    (geteilt / "notiz.md").write_text("x", encoding="utf-8")
    agent_schreiben(
        config, kopf=f"model: test\ntools:\n  - read_file\nfolders:\n  - {geteilt}",
    )
    provider_setzen(mcp_client_echt, MockProvider(mock_endpunkt("test"), haeppchen=["Fertig."]))

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    assert daten["state"] == "fertig"
    status_schritte = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    assert not any("Dieser Durchlauf hat keine Datei geschrieben" in s for s in status_schritte)


def test_auftrag_ohne_einstellung_bekommt_auto(config, client):
    """Nothing set anywhere: the run goes out with the largest ceiling that
    still fits — the model's window less this request's own input, less the
    margin (app/antwortgrenze.py). No shipped number is involved."""
    from app import antwortgrenze, kontextvoll

    agent_schreiben(config)
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    # On the wire that carries a number. On the OpenAI wire Auto is no
    # number at all — the test below it says so.
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt = mock_endpunkt("test", provider="anthropic")

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)

    fenster = zustand.context_tokens
    eingabe = antwortgrenze.eingabe_schaetzen(provider.letzte_anfrage.nachrichten)
    assert provider.letzte_anfrage.max_tokens == (
        fenster - eingabe - kontextvoll.SICHERHEITSABSTAND
    )


def test_auftrag_ohne_einstellung_traegt_auf_dem_openai_draht_keine_zahl(config, client):
    """Auto on the OpenAI wire: the round goes out without ``max_tokens``
    and the server decides how long the answer may be."""
    agent_schreiben(config)
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)

    assert provider.letzte_anfrage.max_tokens is None


def test_auftrag_nimmt_die_eingestellte_kaskade(config, client):
    agent_schreiben(config)
    client.app.state.repositories.einstellungen.setzen(
        "global", "parameter", {"max_tokens": 32_000}
    )
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)

    assert provider.letzte_anfrage.max_tokens == 32_000


def test_agentenkopf_ueberschreibt_die_kaskade_im_auftrag(config, client):
    agent_schreiben(config, kopf="model: test\nmax_tokens: 4096")
    client.app.state.repositories.einstellungen.setzen(
        "global", "parameter", {"max_tokens": 32_000}
    )
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)

    assert provider.letzte_anfrage.max_tokens == 4096


def test_abbrechen_beendet_den_lauf(config, client):
    agent_schreiben(config)
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"), haeppchen=[f"T{i} " for i in range(100)], verzoegerung=0.05
        ),
    )

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    antwort = client.post(f"/api/v1/jobs/{kennung}/cancel")
    assert antwort.status_code == 200
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "abgebrochen"
    assert daten["end_reason"] == "benutzer_abbruch"


class StreamtDannWartetAufAbbruch(MockProvider):
    """Yields one chunk, then blocks until the test has already cancelled —
    the deterministic version of "the user stops mid-answer", with no race
    between the cancel landing and the next chunk being asked for."""

    def __init__(self, *args, bereit: threading.Event, weiter: threading.Event, **kwargs):
        super().__init__(*args, **kwargs)
        self._bereit = bereit
        self._weiter = weiter

    async def streamen(self, anfrage):
        yield Stueck("content", text="Angefangener Text.")
        self._bereit.set()
        await asyncio.get_event_loop().run_in_executor(None, self._weiter.wait)
        yield Stueck("content", text=" mehr, das nie ankommen sollte")


def test_abbruch_mitten_im_strom_behaelt_den_bisherigen_text(config, client):
    """What already streamed before a stop must survive it — cutting a run
    off mid-answer is not the same as it never having answered at all."""
    agent_schreiben(config)
    bereit, weiter = threading.Event(), threading.Event()
    provider_setzen(
        client, StreamtDannWartetAufAbbruch(mock_endpunkt("test"), bereit=bereit, weiter=weiter)
    )

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    assert bereit.wait(timeout=2.0)
    assert client.post(f"/api/v1/jobs/{kennung}/cancel").status_code == 200
    weiter.set()

    daten = auf_ende_warten(client, kennung)
    assert daten["state"] == "abgebrochen"
    assert daten["result"] == "Angefangener Text."
    assert any(s["typ"] == "text" for s in daten["schritte"])


def test_auftragsliste_zeigt_den_neuen_auftrag(config, client):
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)
    liste = client.get("/api/v1/jobs").json()
    assert [eintrag["id"] for eintrag in liste] == [kennung]


# --- Reading, writing, deleting agent files (6.6) --------------------------


def test_agentendatei_lesen(config, client):
    agent_schreiben(config)
    daten = client.get("/api/v1/agents/recherche").json()
    assert daten["name"] == "recherche"
    assert "Du bist der Rechercheur." in daten["content"]
    assert daten["kaputt"] is None


def test_fehlende_agentendatei_gibt_404(client):
    assert client.get("/api/v1/agents/phantom").status_code == 404


def test_agentendatei_speichern(config, client):
    inhalt = "---\nmodel: test\n---\n\nNeuer Prompt.\n"
    antwort = client.put("/api/v1/agents/neuling", json={"content": inhalt})
    assert antwort.status_code == 200
    assert antwort.json()["kaputt"] is None
    namen = [agent["name"] for agent in client.get("/api/v1/agents").json()]
    assert "neuling" in namen


def test_kaputte_datei_wird_gespeichert_aber_gemeldet(config, client):
    """It is the user's file: save it, yes — hide the problem, no."""
    antwort = client.put("/api/v1/agents/krank", json={"content": "kein kopfteil"})
    assert antwort.status_code == 200
    assert "Kopfteil" in antwort.json()["kaputt"]
    # It is saved — readable via the file API …
    assert client.get("/api/v1/agents/krank").status_code == 200
    # … but the agent is not in play.
    namen = [agent["name"] for agent in client.get("/api/v1/agents").json()]
    assert "krank" not in namen


def test_agentendatei_loeschen(config, client):
    agent_schreiben(config)
    assert client.delete("/api/v1/agents/recherche").status_code == 204
    assert client.get("/api/v1/agents/recherche").status_code == 404
    assert client.delete("/api/v1/agents/recherche").status_code == 404


def test_dateiliste_zeigt_auch_kaputte(config, client):
    """What is missing from the agent list must still be fixable in the dialog."""
    agent_schreiben(config)
    client.put("/api/v1/agents/krank", json={"content": "kein kopfteil"})
    eintraege = {e["name"]: e["kaputt"] for e in client.get("/api/v1/agent-files").json()}
    assert eintraege["recherche"] is None
    assert "Kopfteil" in eintraege["krank"]


def test_pfad_tricks_werden_abgewiesen(client):
    """Agent names are file names — dots and slashes do not get through."""
    assert client.put("/api/v1/agents/a.b", json={"content": "x"}).status_code == 400
    assert client.get("/api/v1/agents/..%2Fsystem").status_code in (400, 404)


# --- The form's field route -------------------------------------------------


def test_felder_route_verliert_kein_feld(config, client, tmp_path):
    """The guard at the HTTP layer: a full file survives a form save."""
    agent_schreiben(
        config,
        kopf=(
            "model: test\n"
            "folders:\n"
            f"  - {tmp_path}\n"
            "max_tokens: 9000\n"
            "permissions:\n"
            "  run_command: nein"
        ),
    )
    antwort = client.put(
        "/api/v1/agents/recherche/fields", json={"max_rounds": 4, "model": "test"}
    )
    assert antwort.status_code == 200
    inhalt = antwort.json()["content"]
    assert "max_rounds: 4" in inhalt
    assert "max_tokens: 9000" in inhalt
    assert "run_command: nein" in inhalt
    assert "Du bist der Rechercheur." in inhalt


def test_felder_route_legt_neue_datei_an(config, client):
    antwort = client.put(
        "/api/v1/agents/frisch/fields",
        json={"model": "test", "tools": ["web_search"], "prompt": "Do research."},
    )
    assert antwort.status_code == 200
    namen = [agent["name"] for agent in client.get("/api/v1/agents").json()]
    assert "frisch" in namen


def test_felder_route_ohne_prompt_fuer_neue_datei(client):
    assert (
        client.put("/api/v1/agents/leer/fields", json={"model": "test"}).status_code
        == 422
    )


def test_felder_route_weist_kaputtes_ab(config, client):
    """Unlike the raw editor the form validates before writing: a share that
    is not a complete path would break the file."""
    agent_schreiben(config)
    antwort = client.put(
        "/api/v1/agents/recherche/fields", json={"folders": ["~/code"]}
    )
    assert antwort.status_code == 422
    assert "folders" in antwort.text
    # The file on disk is untouched.
    assert "folders" not in client.get("/api/v1/agents/recherche").json()["content"]


def test_felder_route_beschattet_mitgelieferte(config, client, tmp_path):
    """Editing a shipped agent through the form shadows it, base included."""
    ausgeliefert = tmp_path / "mitgeliefert"
    ausgeliefert.mkdir()
    (ausgeliefert / "bote.md").write_text(
        "---\nmodel: test\nmax_tokens: 500\n---\n\nDeliver.\n", encoding="utf-8"
    )
    config.app.agenten_mitgeliefert = str(ausgeliefert)
    antwort = client.put("/api/v1/agents/bote/fields", json={"max_rounds": 3})
    assert antwort.status_code == 200
    inhalt = antwort.json()["content"]
    assert "max_tokens: 500" in inhalt
    assert "max_rounds: 3" in inhalt
    eigene = Path(config.app.agenten_verzeichnis) / "bote.md"
    assert eigene.is_file()
    assert "max_rounds: 3" in eigene.read_text(encoding="utf-8")
    assert "max_rounds" not in (ausgeliefert / "bote.md").read_text(encoding="utf-8")


AGENTENMASKE = Path(__file__).resolve().parents[1] / "frontend/src/teile/Agentenmaske.svelte"


def _zahlenfeld(quelle: str, variable: str) -> str:
    """The ``<Zahlenfeld …/>`` tag of the agent mask bound to ``variable``."""
    bindung = quelle.index(f"bind:wert={{{variable}}}")
    return quelle[quelle.rindex("<Zahlenfeld", 0, bindung) : quelle.index("/>", bindung)]


def test_maske_eine_anzahl_beginnt_bei_eins():
    """The mask says what the file loader and the run say: a count starts at
    1, so a zero cannot be typed into a field the save would refuse it for.
    The thinking budget keeps its zero — there it means "do not think"."""
    quelle = AGENTENMASKE.read_text(encoding="utf-8")
    assert "min={1}" in _zahlenfeld(quelle, "maxTokens")
    assert "min={1}" in _zahlenfeld(quelle, "maxBefehlssekunden")
    assert "min={0}" in _zahlenfeld(quelle, "denklaenge")
    # Rounds and minutes start at 1 as well, so a branch turning their zero
    # into "unset" could never run.
    assert "maxRunden > 0" not in quelle
    assert "maxMinuten > 0" not in quelle


def test_the_mask_reports_the_sentence_of_a_broken_file_and_gives_way():
    """The success branch of the load reads ``kaputt`` before it reads the
    prompt: the sentence is reported and the mask gives way to the list,
    where the fields would otherwise open empty over the list's old values."""
    source = AGENTENMASKE.read_text(encoding="utf-8")
    branch = source[source.index(".then((datei) =>") : source.index(".catch((fehler)")]
    assert "datei.kaputt" in branch
    assert branch.index("datei.kaputt") < branch.index("felderSetzen(agent")
    reported = branch[branch.index("datei.kaputt") : branch.index("felderSetzen(agent")]
    assert "melde(datei.kaputt, 'fehler')" in reported
    assert "onabbrechen?.()" in reported and "return" in reported
    # Silence: the stale answer is still thrown away first, and the 422 branch
    # of the load is untouched.
    assert branch.index("if (verworfen) return") < branch.index("datei.kaputt")
    assert "fehler?.status && fehler.message" in source


def test_the_route_answers_200_with_the_sentence_for_a_broken_head(config, client):
    """What the mask reads: a file with a broken head answers 200 with the
    sentence in ``kaputt`` and ``prompt`` null; a healthy file has no
    ``kaputt`` and carries its instruction."""
    agent_schreiben(config)
    healthy = client.get("/api/v1/agents/recherche")
    assert healthy.status_code == 200
    assert healthy.json()["kaputt"] is None
    assert healthy.json()["prompt"]
    file = Path(config.app.agenten_verzeichnis) / "recherche.md"
    file.write_text("---\nname: [kaputt\n---\nText\n", encoding="utf-8")
    broken = client.get("/api/v1/agents/recherche")
    assert broken.status_code == 200
    assert broken.json()["kaputt"]
    assert broken.json()["prompt"] is None


def test_felder_route_speichert_ein_leeres_feld_als_auto(config, client):
    """What the mask sends for an empty field is a null: the line leaves the
    file and the settings cascade decides again. A stated zero thinking
    budget goes through as the zero it is."""
    agent_schreiben(config, kopf="model: test\nmax_tokens: 9000\nmax_command_seconds: 60")
    antwort = client.put(
        "/api/v1/agents/recherche/fields",
        json={"max_tokens": None, "max_command_seconds": None, "reasoning_budget": 0},
    )
    assert antwort.status_code == 200
    inhalt = antwort.json()["content"]
    assert "max_tokens" not in inhalt
    assert "max_command_seconds" not in inhalt
    assert "reasoning_budget: 0" in inhalt


@pytest.mark.parametrize("feld", ["max_tokens", "max_command_seconds"])
def test_felder_route_nimmt_eine_eins_und_weist_eine_null_ab(config, client, feld):
    """The server's side of the mask's minimum: 1 is the first value that
    saves, a zero is refused before anything is written."""
    agent_schreiben(config)
    assert client.put("/api/v1/agents/recherche/fields", json={feld: 0}).status_code == 422
    assert f"{feld}:" not in client.get("/api/v1/agents/recherche").json()["content"]
    antwort = client.put("/api/v1/agents/recherche/fields", json={feld: 1})
    assert antwort.status_code == 200
    assert f"{feld}: 1" in antwort.json()["content"]


# --- Tools: filter and approval ---------------------------------------------


def test_filter_bietet_nur_den_schnitt_an():
    registry = RegistryDouble()
    namen = [
        werkzeug["function"]["name"]
        for werkzeug in registry.als_openai_werkzeuge(nur={"addieren", "erfunden"})
    ]
    assert namen == ["addieren"]
    # The two of the double, plus `goal` and the clock, which depend on
    # nothing and are therefore always in the offering (app/tools/ziel_werkzeug.py,
    # app/tools/uhr.py).
    assert len(registry.als_openai_werkzeuge()) == 4


def test_agentenwerkzeug_laeuft_ohne_rueckfrage(config, mcp_client):
    """What is listed in the agent runs — nobody gets asked."""
    agent_schreiben(config, kopf="model: test\ntools:\n  - addieren\nmax_rounds: 3")
    provider_setzen(
        mcp_client,
        ImmerWerkzeuge(mock_endpunkt("test")),
    )

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Rechne"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    registry = mcp_client.app.state.werkzeuge
    assert registry.aufrufe, "the tool was never run"
    typen = [schritt["typ"] for schritt in daten["schritte"]]
    assert "tool_call" in typen and "tool_result" in typen
    # No tool_confirm — neither in the log nor as a waiting state.
    assert "tool_confirm" not in typen


def test_ein_langes_ergebnis_kommt_auch_im_auftrag_gekuerzt_an(config, mcp_client):
    """A job's tool result reaches the window cut at the ceiling, exactly as
    the chat's does.

    A job cuts its own results in `app/api/v1/auftraege.py`
    (`ERGEBNIS_KUERZUNG`), and no test held that before. An MCP server of
    somebody else cuts nothing itself: without the cut the whole answer
    (~32,000 characters) would stand in the window.
    """
    from app.api.v1.auftraege import ERGEBNIS_KUERZUNG
    from app.api.v1.generierung import WERKZEUGERGEBNIS_GRENZE

    # The two ceilings are one number in the product: what a job shows is
    # cut where a chat's result is. Should they ever drift apart, this says
    # so rather than quietly watching the wrong one.
    assert ERGEBNIS_KUERZUNG == WERKZEUGERGEBNIS_GRENZE

    class _Riesig(RegistryDouble):
        async def ausfuehren(self, name, argumente, bild_senke=None, **_rest):
            # The same guard the plain double keeps: a call that got past the
            # filter must not slip through here unnoticed.
            if name not in self._werkzeuge:
                raise AssertionError("the filter failed")
            return "\n".join(f"Zeile {n}: {'x' * 60}" for n in range(1, 451))

    mcp_client.app.state.werkzeuge = _Riesig()
    agent_schreiben(config, kopf="model: test\ntools:\n  - addieren\nmax_rounds: 2")
    provider_setzen(mcp_client, ImmerWerkzeuge(mock_endpunkt("test")))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Rechne"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    # The step carries its payload as JSON text, like every other step
    # of a job (the window parses it the same way).
    schritt = next(s for s in daten["schritte"] if s["typ"] == "tool_result")
    assert len(json.loads(schritt["inhalt"])["text"]) == WERKZEUGERGEBNIS_GRENZE


def test_der_auftragsstrom_traegt_die_felder_des_chatstroms(config, mcp_client, monkeypatch):
    """A job's stream names a call and its result with the same fields the
    chat's stream does: the server beside the call, the picture field and
    the measured time beside the result. The picture is always empty here —
    a job never sends one to a window."""
    from app.generationen import Generierung

    gemeldet: list[dict] = []
    original = Generierung.melden

    def mitschreiben(self, zeile):
        gemeldet.append(json.loads(zeile.removeprefix("data: ").strip()))
        original(self, zeile)

    monkeypatch.setattr(Generierung, "melden", mitschreiben)
    registry = mcp_client.app.state.werkzeuge
    registry._werkzeuge["addieren"] = (
        None, MCPWerkzeug(name="addieren", beschreibung="addiert", server="rechner"), False
    )
    agent_schreiben(config, kopf="model: test\ntools:\n  - addieren\nmax_rounds: 2")
    provider_setzen(mcp_client, ImmerWerkzeuge(mock_endpunkt("test")))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Rechne"}
    ).json()["id"]
    auf_ende_warten(mcp_client, kennung)

    aufruf = next(e for e in gemeldet if e["typ"] == "tool_call")
    ergebnis = next(e for e in gemeldet if e["typ"] == "tool_result")
    # Every event carries the moment it was reported, as the chat's do: a
    # reattach replays the history and the tool clock starts from this.
    assert all(isinstance(e.get("zeitpunkt_ms"), int) for e in gemeldet)
    assert aufruf.pop("zeitpunkt_ms") > 1_600_000_000_000
    assert aufruf == {
        "typ": "tool_call", "name": "addieren", "server": "rechner",
        "argumente": {"a": 1, "b": 2}, "aufruf_id": "w1",
    }
    assert set(ergebnis) == {
        "typ", "name", "aufruf_id", "fehlgeschlagen", "text", "bild", "dauer_sekunden",
        "zeitpunkt_ms",
    }
    assert ergebnis["bild"] is None
    assert isinstance(ergebnis["dauer_sekunden"], float) and ergebnis["dauer_sekunden"] >= 0
    assert (ergebnis["name"], ergebnis["aufruf_id"], ergebnis["fehlgeschlagen"], ergebnis["text"]) == (
        "addieren", "w1", False, "3"
    )


def test_rundengrenze_beendet_mit_lesbarem_grund(config, mcp_client):
    agent_schreiben(config, kopf="model: test\ntools:\n  - addieren\nmax_rounds: 2")
    provider_setzen(mcp_client, ImmerWerkzeuge(mock_endpunkt("test")))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Rechne"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert daten["state"] == "gescheitert"
    assert daten["end_reason"] == "rundengrenze"
    assert len(mcp_client.app.state.werkzeuge.aufrufe) == 2


def test_zeitgrenze_beendet_mit_lesbarem_grund(config, mcp_client):
    agent_schreiben(
        config,
        kopf="model: test\ntools:\n  - addieren\nmax_rounds: 50\nmax_minutes: 0.0001",
    )
    provider_setzen(
        mcp_client, ImmerWerkzeuge(mock_endpunkt("test"), verzoegerung=0.05)
    )

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Rechne"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert daten["state"] == "gescheitert"
    assert daten["end_reason"] == "zeitgrenze"


def test_agent_ohne_werkzeugliste_bekommt_alle_werkzeuge(config, mcp_client):
    """tools: left out entirely means every approved tool runs —
    the trap of a forgotten field silencing an unattended agent is closed
    now that every call is checked against the rule file besides."""
    agent_schreiben(config, kopf="model: test")
    provider = provider_setzen(mcp_client, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(mcp_client, kennung)

    namen = {w["function"]["name"] for w in provider.letzte_anfrage.werkzeuge}
    # `goal` and the clock depend on nothing and are therefore in every run
    # with tools (app/tools/ziel_werkzeug.py, app/tools/uhr.py).
    assert namen == {"addieren", "verboten", "goal", "get_current_time"}


def test_agent_mit_leerer_werkzeugliste_bekommt_keine(config, mcp_client):
    """The opposite, explicit case: tools: [] still means none — an empty
    list is a deliberate choice, not a forgotten field."""
    agent_schreiben(config, kopf="model: test\ntools: []")
    provider = provider_setzen(mcp_client, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(mcp_client, kennung)

    assert provider.letzte_anfrage.werkzeuge == []


def test_ein_erfundenes_werkzeug_verhindert_den_start(config, mcp_client):
    """An agent that names a tool nothing here carries starts no run at all.

    The offer would come out without that tool — and, once the always-offered
    ones are widened in, WITH a tool the agent never meant: a typo would
    quietly turn the run into a different one. The refusal names the name,
    and only the name that is really missing.
    """
    agent_schreiben(
        config, kopf="model: test\ntools:\n  - addieren\n  - erfunden"
    )
    provider = provider_setzen(mcp_client, MockProvider(mock_endpunkt("test")))

    antwort = mcp_client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"})

    assert antwort.status_code == 400
    assert "erfunden" in antwort.json()["detail"]
    assert "addieren" not in antwort.json()["detail"]
    # No run was started at all — the model was never asked.
    assert mcp_client.get("/api/v1/jobs").json() == []
    assert provider.letzte_anfrage is None


def _angeboten_schritte(daten: dict) -> list[str]:
    return [
        s["inhalt"]
        for s in daten["schritte"]
        if s["typ"] == "status" and s["inhalt"].startswith("Werkzeuge angeboten:")
    ]


def test_angebotene_werkzeuge_stehen_im_protokoll(config, mcp_client):
    """The counterpart to the missing-tools step: what the run actually HAS.
    An agent without a tools: list gets no missing-report by design — this
    step is the only place a silently absent search server becomes visible
    on the job itself."""
    agent_schreiben(config, kopf="model: test")
    provider_setzen(mcp_client, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    schritte = _angeboten_schritte(daten)
    assert schritte == [
        "Werkzeuge angeboten: addieren, get_current_time, goal, verboten"
    ]


def test_angebotene_werkzeuge_nur_der_schnitt_steht_im_protokoll(config, mcp_client):
    """With a list, the step names what is actually offered — the cut of the
    agent's list and the registry, not the wishes.

    An invented name never gets this far any more — the run does not start
    with one (app/api/v1/auftraege.py) — so the cut is measured with names
    that exist. The clock is in it: every run whose list is not empty gets
    it (app/api/v1/auftraege.py).
    """
    agent_schreiben(config, kopf="model: test\ntools:\n  - addieren")
    provider_setzen(mcp_client, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert _angeboten_schritte(daten) == [
        "Werkzeuge angeboten: addieren, get_current_time"
    ]


def test_ohne_werkzeuge_meldet_der_schritt_keine(config, client):
    """Every run carries the step — also one that offers nothing at all, so
    'nothing was on offer' can never be mistaken for 'nothing was logged'."""
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Ok."]))

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert _angeboten_schritte(daten) == ["Werkzeuge angeboten: keine"]


def test_kein_werkzeughinweis_im_prompt_wenn_nichts_angeboten_wird(config, mcp_client):
    """A run with no tools keeps saying so — the prompt must not tell the
    model it has tools to reach for, or it asks for calls that can never
    appear.

    Written out as an empty list, because that is the one way to a run
    without tools now: an agent that names tools gets the missing ones
    reported and no run at all (app/api/v1/auftraege.py), and an empty list
    stays empty — `[]` is somebody saying "none of them". The clock is
    switched off as well: it would otherwise stand in every run whose list
    is not empty. A window's off-switch outranks the widening.
    """
    agent_schreiben(config, kopf="model: test\ntools: []")
    mcp_client.app.state.repositories.einstellungen.setzen(
        "global", werkzeugwahl.SCHLUESSEL, ["get_current_time"]
    )
    provider = provider_setzen(mcp_client, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(mcp_client, kennung)

    assert provider.letzte_anfrage.werkzeuge == []
    system = provider.letzte_anfrage.nachrichten[0]
    assert "You have tools." not in system.content


# --- Tor 3, end to end (app/berechtigungen.py) ------------------------------


def _tool_ergebnisse(daten: dict) -> list[dict]:
    return [json.loads(s["inhalt"]) for s in daten["schritte"] if s["typ"] == "tool_result"]


def test_agent_ausserhalb_ordner_wird_im_auftrag_abgelehnt(config, mcp_client_echt, tmp_path):
    """Hole A, through the real jobs route: a job never asks, so a path
    outside its shared folder must be refused outright, not just executed."""
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    agent_schreiben(
        config,
        kopf=f"model: test\ntools:\n  - read_file\nfolders:\n  - {geteilt}\nmax_rounds: 2",
    )
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="read_file", argumente={"path": "/etc/hosts"})
            ],
        ),
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "lies /etc/hosts"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    ergebnisse = _tool_ergebnisse(daten)
    assert ergebnisse, "no tool_result in the log"
    assert ergebnisse[0]["fehlgeschlagen"] is True
    assert "outside the shared folders" in ergebnisse[0]["text"]


def test_leere_ordnerliste_im_auftrag_wird_nicht_wie_keine_behandelt(
    config, mcp_client_echt, tmp_path
):
    """An explicitly empty ``folders`` pick in the start window must mean no
    folders at all, not "nothing was picked" — else deselecting every folder
    silently falls back to the agent's own shared folder.

    The shelf is the one exception and is shared with every run regardless
    (it is where deliveries land, and an agent has to be able to look at its
    own shelf). So an empty pick leaves the dock and nothing else — which is
    exactly what the refusal below names."""
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    datei = geteilt / "notiz.md"
    datei.write_text("hallo", encoding="utf-8")
    agent_schreiben(
        config,
        kopf=f"model: test\ntools:\n  - read_file\nfolders:\n  - {geteilt}\nmax_rounds: 2",
    )
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="read_file", argumente={"path": str(datei)})
            ],
        ),
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "lies", "folders": []}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    ergebnisse = _tool_ergebnisse(daten)
    assert ergebnisse, "no tool_result in the log"
    assert ergebnisse[0]["fehlgeschlagen"] is True
    assert "outside the shared folders" in ergebnisse[0]["text"]
    # And the agent's own folder is what an empty pick took away: it must
    # not be back among the shares the refusal lists.
    assert str(geteilt) not in ergebnisse[0]["text"].split("\n", 1)[1]
    assert "agent_dock" in ergebnisse[0]["text"]


def test_a_start_window_pick_stays_the_runs_folders(config, client, tmp_path, monkeypatch):
    """The silence probe for the chat's folders: a run started by hand has
    no chat, so the folders picked for it are its folders — the dock and the
    picture folder behind them, and no folder named as a chat's own."""
    from app import dokumentablage
    from app.api.v1 import auftraege
    from tests.test_helper import PromptSeen

    seen = PromptSeen()
    monkeypatch.setattr(auftraege, "grundprompt", seen)
    picked = tmp_path / "picked"
    picked.mkdir()
    agents_own = tmp_path / "agents-own"
    agents_own.mkdir()
    agent_schreiben(config, kopf=f"model: test\nfolders:\n  - {agents_own}")
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["done"]))

    job_id = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "go", "folders": [str(picked)]}
    ).json()["id"]
    auf_ende_warten(client, job_id)

    dock, pictures = dokumentablage.program_folders(config)
    (parts,) = seen.calls
    assert parts["ordner"] == [str(picked), dock, pictures]
    assert parts.get("own_folder") is None


def _sending_chat(chat_id: str, shared: list[str] | None = None):
    """What ``chat_run_folders`` reads of a chat: its id and its shares."""
    from types import SimpleNamespace

    return SimpleNamespace(id=chat_id, working_dirs=list(shared or []))


def test_an_agent_with_folders_of_its_own_gets_the_chats_folder_behind_them(tmp_path):
    """A chat that shares nothing sends an agent off whose file names its
    own folders: the chat's uploads lie in the chat's folder, and the run's
    delivery goes there — it has to reach it. The agent's folders stay in
    front, so a relative path lands where the agent's file says."""
    from types import SimpleNamespace

    from app import dokumentablage
    from app.api.v1.auftraege import chat_run_folders, run_folders

    agents_own = tmp_path / "agents-own"
    agents_own.mkdir()
    agent = SimpleNamespace(ordner=[str(agents_own)])
    chat_folder = dokumentablage.chatordner(tmp_path, "c1")
    chat_folder.mkdir(parents=True)

    folders, own_folder = chat_run_folders(tmp_path, _sending_chat("c1"), agent)

    assert folders == [str(agents_own), str(chat_folder)]
    assert own_folder == str(chat_folder)
    assert run_folders(folders, agent) == folders


def test_the_prompt_names_the_chats_folder_as_the_chats_own_beside_the_agents(tmp_path):
    from types import SimpleNamespace

    from app import dokumentablage, grundprompt
    from app.api.v1.auftraege import chat_run_folders
    from app.own_folder_line import own_folder_line

    agents_own = tmp_path / "agents-own"
    agents_own.mkdir()
    chat_folder = dokumentablage.chatordner(tmp_path, "c1")
    chat_folder.mkdir(parents=True)
    folders, own_folder = chat_run_folders(
        tmp_path, _sending_chat("c1"), SimpleNamespace(ordner=[str(agents_own)])
    )

    text = grundprompt.bauen(
        werkzeuge=True, ordner=folders, own_folder=own_folder, dateiwerkzeuge=["read_file"]
    )
    paragraph = own_folder_line(folders, own_folder, None, None)

    # The agent's folder is the share a relative path starts from; the chat's
    # folder is named apart, as the chat's own, in the paragraph that closes
    # the system message.
    assert f"- {agents_own}" in text
    assert "Relative paths resolve against the first one." in text
    assert f"- {chat_folder}" not in text
    assert "This conversation also has a folder of its own" in paragraph
    assert f"- {chat_folder}" in paragraph


def test_silence_a_chat_folder_that_is_not_there_yet_is_not_put_into_the_list(tmp_path):
    from types import SimpleNamespace

    from app.api.v1.auftraege import chat_run_folders, run_folders

    agents_own = tmp_path / "agents-own"
    agents_own.mkdir()
    agent = SimpleNamespace(ordner=[str(agents_own)])

    folders, own_folder = chat_run_folders(tmp_path, _sending_chat("c1"), agent)

    assert (folders, own_folder) == (None, None)
    assert run_folders(folders, agent) == [str(agents_own)]


def test_silence_a_chat_that_shares_a_folder_gives_the_run_that_folder(tmp_path):
    """The chat's shares come first and win over the agent's own, as they
    did; the chat's folder follows once it exists."""
    from types import SimpleNamespace

    from app import dokumentablage
    from app.api.v1.auftraege import chat_run_folders

    shared = tmp_path / "shared"
    shared.mkdir()
    agents_own = tmp_path / "agents-own"
    agents_own.mkdir()
    chat_folder = dokumentablage.chatordner(tmp_path, "c1")
    chat_folder.mkdir(parents=True)

    folders, own_folder = chat_run_folders(
        tmp_path, _sending_chat("c1", [str(shared)]), SimpleNamespace(ordner=[str(agents_own)])
    )

    assert folders == [str(shared), str(chat_folder)]
    assert own_folder == str(chat_folder)


def test_silence_an_agent_without_folders_begins_in_the_chats_folder(tmp_path):
    from types import SimpleNamespace

    from app import dokumentablage
    from app.api.v1.auftraege import chat_run_folders

    folders, own_folder = chat_run_folders(
        tmp_path, _sending_chat("c1"), SimpleNamespace(ordner=[])
    )

    chat_folder = str(dokumentablage.chatordner(tmp_path, "c1"))
    assert folders == [chat_folder]
    assert own_folder == chat_folder


def test_agent_ungenanntes_werkzeug_wird_im_auftrag_abgelehnt(config, mcp_client_echt, tmp_path):
    """Hole B, through the real jobs route: a tool the agent did not name in
    tools: must be refused at execution time, not only left unoffered."""
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    (geteilt / "notiz.md").write_text("hallo", encoding="utf-8")
    agent_schreiben(
        config,
        kopf=f"model: test\ntools:\n  - get_current_time\nfolders:\n  - {geteilt}\nmax_rounds: 2",
    )
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="read_file", argumente={"path": "notiz.md"})
            ],
        ),
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "lies notiz.md"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    ergebnisse = _tool_ergebnisse(daten)
    assert ergebnisse, "no tool_result in the log"
    assert ergebnisse[0]["fehlgeschlagen"] is True
    assert "not in this agent's tool list" in ergebnisse[0]["text"]


# --- The loop guard, end to end (app/schleifenwaechter.py) -----------------


class _WiederholtGleicherAufruf(MockProvider):
    """Requests the exact same, rejected call every round — the base
    MockProvider only requests tools on the first round and answers with
    text afterwards, which can never show three rejections in a row."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id=f"w{self.durchlaeufe}", name="read_file",
                    argumente={"path": "notiz.md"},
                )
            ],
        )


def test_drei_gleiche_ablehnungen_beenden_den_lauf(config, mcp_client_echt, tmp_path):
    """Hole B, three times running: ``read_file`` is not in the agent's
    tools list, so every attempt is refused — the run must end on the
    third, not run out the round limit."""
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    (geteilt / "notiz.md").write_text("hallo", encoding="utf-8")
    agent_schreiben(
        config,
        kopf=f"model: test\ntools:\n  - get_current_time\nfolders:\n  - {geteilt}\nmax_rounds: 6",
    )
    provider_setzen(mcp_client_echt, _WiederholtGleicherAufruf(mock_endpunkt("test")))

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "lies notiz.md"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    assert daten["state"] == "gescheitert"
    assert daten["end_reason"] == "wiederholte_ablehnung"
    ergebnisse = _tool_ergebnisse(daten)
    # Exactly three attempts — the run ends right after the third, not
    # after burning through the whole round budget.
    assert len(ergebnisse) == 3
    assert all(e["fehlgeschlagen"] for e in ergebnisse)


class _AbgewandelterAufrufDazwischen(MockProvider):
    """Two rejections of the same call, then a differently-shaped one
    (still rejected — the arguments changed, not the outcome), then two
    more of the first — never three of the SAME rejection in a row."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._pfade = ["notiz.md", "notiz.md", "anders.md", "notiz.md", "notiz.md"]

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if self.durchlaeufe > len(self._pfade):
            yield Stueck("text", text="fertig")
            return
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id=f"w{self.durchlaeufe}", name="read_file",
                    argumente={"path": self._pfade[self.durchlaeufe - 1]},
                )
            ],
        )


def test_ein_abgewandelter_aufruf_dazwischen_beendet_den_lauf_nicht(
    config, mcp_client_echt, tmp_path
):
    geteilt = tmp_path / "geteilt"
    geteilt.mkdir()
    (geteilt / "notiz.md").write_text("hallo", encoding="utf-8")
    agent_schreiben(
        config,
        kopf=f"model: test\ntools:\n  - get_current_time\nfolders:\n  - {geteilt}\nmax_rounds: 6",
    )
    provider_setzen(mcp_client_echt, _AbgewandelterAufrufDazwischen(mock_endpunkt("test")))

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "lies notiz.md"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    assert daten["state"] == "fertig"
    ergebnisse = _tool_ergebnisse(daten)
    assert len(ergebnisse) == 5
    assert all(e["fehlgeschlagen"] for e in ergebnisse)


# --- Skills for an agent run -----------------------------------
# The same catalogue-then-load shape as the chat (tests/test_skillwahl.py):
# names and one-line descriptions travel with every request, the full
# instruction only once the model actually asks for it.


def _mit_skills(config, client):
    """A registry that actually offers skill_load/skill_save — the fixture
    ``mcp_client_echt`` builds one without ``skills_orte``, so it has none."""
    client.app.state.werkzeuge = WerkzeugRegistry(
        [], shell_an=True, skills_orte=config.skillverzeichnisse
    )
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt.capabilities.tool_calls = True
    return config


def _skill_schreiben(config, name, beschreibung="Da", auto=True):
    _, eigen = config.skillverzeichnisse
    ordner = eigen / name
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / skills.SKILL_DATEI).write_text(
        f"---\ndescription: {beschreibung}\nauto: {str(auto).lower()}\n---\n\nTu es.\n",
        encoding="utf-8",
    )


def _system_von(provider) -> str:
    system = [n for n in provider.letzte_anfrage.nachrichten if n.role == "system"]
    assert len(system) == 1
    return system[0].content


def test_ein_agent_sieht_die_automatische_skill_liste(config, mcp_client_echt):
    _mit_skills(config, mcp_client_echt)
    _skill_schreiben(config, "handoff", "Fasst das Gespräch zusammen")
    agent_schreiben(config, kopf="model: test\ntools:\n  - skill_load\nmax_rounds: 2")
    provider = provider_setzen(
        mcp_client_echt, MockProvider(mock_endpunkt("test"), haeppchen=["ok"])
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "x"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    assert "handoff — Fasst das Gespräch zusammen" in _system_von(provider)


def test_der_volle_skill_text_steht_nicht_von_anfang_an_im_prompt(config, mcp_client_echt):
    _mit_skills(config, mcp_client_echt)
    _skill_schreiben(config, "handoff")
    agent_schreiben(config, kopf="model: test\ntools:\n  - skill_load\nmax_rounds: 2")
    provider = provider_setzen(
        mcp_client_echt, MockProvider(mock_endpunkt("test"), haeppchen=["ok"])
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "x"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    # The name and its one line are there; the instruction body is not.
    assert "Tu es." not in _system_von(provider)


def test_ohne_skill_load_im_gepaeck_gibt_es_kein_verzeichnis(config, mcp_client_echt):
    """A catalogue without skill_load names doors this run could never open.
    Leaving out ``tools:`` entirely means every approved tool — the agent
    has to name something ELSE to actually exclude skill_load."""
    _mit_skills(config, mcp_client_echt)
    _skill_schreiben(config, "handoff")
    agent_schreiben(config, kopf="model: test\ntools:\n  - get_current_time\nmax_rounds: 2")
    provider = provider_setzen(
        mcp_client_echt, MockProvider(mock_endpunkt("test"), haeppchen=["ok"])
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "x"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    assert "handoff" not in _system_von(provider)


def test_ein_agent_kann_die_skill_per_skill_load_nachladen(config, mcp_client_echt):
    """The whole point of the catalogue: the model can actually open the
    door it named."""
    _mit_skills(config, mcp_client_echt)
    _skill_schreiben(config, "handoff", auto=True)
    agent_schreiben(config, kopf="model: test\ntools:\n  - skill_load\nmax_rounds: 2")
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="skill_load", argumente={"name": "handoff"})
            ],
        ),
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "x"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    ergebnisse = _tool_ergebnisse(daten)
    assert ergebnisse, "no tool_result in the log"
    assert ergebnisse[0]["fehlgeschlagen"] is False
    assert "Tu es." in ergebnisse[0]["text"]


def test_eine_getippte_skill_kostet_nichts(config, mcp_client_echt):
    """A skill with ``auto: false`` is reachable by
    name the whole time — it must not spend a line of every job's prompt."""
    _mit_skills(config, mcp_client_echt)
    _skill_schreiben(config, "handoff", auto=False)
    agent_schreiben(config, kopf="model: test\ntools:\n  - skill_load\nmax_rounds: 2")
    provider = provider_setzen(
        mcp_client_echt, MockProvider(mock_endpunkt("test"), haeppchen=["ok"])
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "x"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    assert "handoff" not in _system_von(provider)


def test_abgeschaltet_steht_gar_kein_verzeichnis_im_auftrag(config, mcp_client_echt):
    """The per-model switch (app/skillwahl.py) must
    hold for a job the same way it holds for the chat — the job is the one
    that runs fifty rounds and has the most to lose from a wasted prompt."""
    _mit_skills(config, mcp_client_echt)
    _skill_schreiben(config, "handoff")
    agent_schreiben(config, kopf="model: test\ntools:\n  - skill_load\nmax_rounds: 2")
    mcp_client_echt.put(
        f"/api/v1/settings/global/{skillwahl.SCHLUESSEL}", json={"wert": {"an": False}}
    )
    provider = provider_setzen(
        mcp_client_echt, MockProvider(mock_endpunkt("test"), haeppchen=["ok"])
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "x"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    assert "skill_load" not in _system_von(provider)


# --- A run that ends far under budget ---------------------------


def test_ein_weit_unterschrittener_lauf_hinterlaesst_einen_hinweis(config, client):
    """An overnight run that used 12 of 400 rounds and 35 of 420 minutes
    finished silently — a big budget, barely touched, is the signal worth
    surfacing."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 400\nmax_minutes: 420")
    provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["Fertig."]))

    kennung = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "fertig"
    hinweise = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    treffer = [h for h in hinweise if "deutlich unter dem üblichen Rahmen" in h]
    assert len(treffer) == 1
    # The numbers ARE the hint — a single round used against 400 allowed,
    # not the off-by-one "0 of 400" a shifted counter would produce.
    assert "1 von 400 erlaubten Runden" in treffer[0]


def test_ein_abgebrochener_lauf_bekommt_keinen_kurzlauf_hinweis(config, client):
    """Befund: a cancelled run is not one that 'considered itself
    finished' — without the fertig-only guard, the arithmetic alone would
    still call it far under budget, which contradicts what actually ended it."""
    agent_schreiben(config, kopf="model: test\nmax_rounds: 400\nmax_minutes: 420")
    provider_setzen(
        client,
        MockProvider(mock_endpunkt("test"), haeppchen=[f"T{i} " for i in range(100)], verzoegerung=0.05),
    )

    kennung = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    antwort = client.post(f"/api/v1/jobs/{kennung}/cancel")
    assert antwort.status_code == 200
    daten = auf_ende_warten(client, kennung)

    assert daten["state"] == "abgebrochen"
    hinweise = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    assert not any("deutlich unter dem üblichen Rahmen" in h for h in hinweise)


def test_ein_normal_ausgelaufener_lauf_bekommt_keinen_hinweis(config, mcp_client):
    """A run that used essentially all of its (small) round budget is not
    'far under' in the round dimension — no hint, regardless of how quick
    the wall-clock time was."""
    agent_schreiben(config, kopf="model: test\ntools:\n  - addieren\nmax_rounds: 2")
    provider_setzen(
        mcp_client,
        MockProvider(
            mock_endpunkt("test"),
            werkzeugaufrufe=[Werkzeugaufruf(id="w1", name="addieren", argumente={"a": 1, "b": 2})],
            haeppchen=["Fertig."],
        ),
    )

    kennung = mcp_client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Rechne"}).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    assert daten["state"] == "fertig"
    hinweise = [s["inhalt"] for s in daten["schritte"] if s["typ"] == "status"]
    assert not any("deutlich unter dem üblichen Rahmen" in h for h in hinweise)


# --- The shelf is shared with every run -------------------------------------


def test_der_dockordner_ist_ab_werk_freigegeben(config, mcp_client_echt):
    """An agent could deliver onto the shelf and not look inside it.

    Nothing has to be picked and the agent names no folders of its own: the
    dock is on every run, so a file written there goes through instead of
    being refused as outside the shares."""
    from app import agentendock, speicherorte

    ziel = speicherorte.ort(config, agentendock.ORT_NAME) / "neu.md"
    agent_schreiben(config, kopf="model: test\ntools:\n  - write_file\nmax_rounds: 2")
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1",
                    name="write_file",
                    argumente={"path": str(ziel), "content": "hallo"},
                )
            ],
        ),
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "leg etwas ab"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    ergebnisse = _tool_ergebnisse(daten)
    assert ergebnisse, "no tool_result in the log"
    assert ergebnisse[0]["fehlgeschlagen"] is False, ergebnisse[0]["text"]
    assert ziel.read_text(encoding="utf-8") == "hallo"


def test_ueber_dem_dockordner_bleibt_zu(config, mcp_client_echt):
    """Only the shelf itself. The directory above it holds the chats, the
    keys and the configuration, and sharing the shelf must not open that."""
    from app import agentendock, speicherorte

    darueber = speicherorte.ort(config, agentendock.ORT_NAME).parent / "geheim.md"
    darueber.parent.mkdir(parents=True, exist_ok=True)
    darueber.write_text("nicht fuer den Agenten", encoding="utf-8")
    agent_schreiben(config, kopf="model: test\ntools:\n  - read_file\nmax_rounds: 2")
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="read_file", argumente={"path": str(darueber)})
            ],
        ),
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "lies"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    ergebnisse = _tool_ergebnisse(daten)
    assert ergebnisse, "no tool_result in the log"
    assert ergebnisse[0]["fehlgeschlagen"] is True
    assert "private place" in ergebnisse[0]["text"]


def test_die_ablage_bekommt_keine_ordnernotiz(config, mcp_client_echt):
    """The shelf is where agents PUT things, not a folder somebody keeps
    notes about — so no exe.md is laid into it."""
    from app import agentendock, ordnerwissen, speicherorte

    agent_schreiben(config, kopf="model: test\nmax_rounds: 1")
    provider_setzen(
        mcp_client_echt, MockProvider(mock_endpunkt("test"), haeppchen=["fertig"])
    )
    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "nichts"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    dock = speicherorte.ort(config, agentendock.ORT_NAME)
    assert not (dock / ordnerwissen.DATEINAME).exists()


# --- A run may start a run ---------------------------------------------------


def test_ein_agent_darf_einen_zweiten_beauftragen(config, mcp_client_echt):
    """The confirmation of the parent covers its children: a run an agent
    asks for is a PART of the assignment the user already agreed to, so it
    starts — and says which run it hangs from."""
    agent_schreiben(config, kopf="model: test\ntools:\n  - start_job\nmax_rounds: 2")
    agent_schreiben(config, name="schreiber", kopf="model: test\nmax_rounds: 1")
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1",
                    name="start_job",
                    argumente={"agent": "schreiber", "task": "Schreib eine Notiz."},
                )
            ],
        ),
    )

    eltern = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "gib etwas ab"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, eltern)

    ergebnisse = _tool_ergebnisse(daten)
    assert ergebnisse, "no tool_result in the log"
    assert ergebnisse[0]["fehlgeschlagen"] is False, ergebnisse[0]["text"]

    alle = mcp_client_echt.get("/api/v1/jobs").json()
    kinder = [a for a in alle if a["parent_id"] == eltern]
    assert len(kinder) == 1
    assert kinder[0]["agent"] == "schreiber"


def test_der_auftrag_eines_agenten_steht_im_strom_wie_im_chat(config, mcp_client_echt, monkeypatch):
    """A child started by start_job reaches the parent's stream with the
    chat's fields: the server beside the call, the picture field and the
    time beside the result."""
    from app.generationen import Generierung

    gemeldet: list[dict] = []
    original = Generierung.melden

    def mitschreiben(self, zeile):
        gemeldet.append(json.loads(zeile.removeprefix("data: ").strip()))
        original(self, zeile)

    monkeypatch.setattr(Generierung, "melden", mitschreiben)
    agent_schreiben(config, kopf="model: test\ntools:\n  - start_job\nmax_rounds: 2")
    agent_schreiben(config, name="schreiber", kopf="model: test\nmax_rounds: 1")
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1",
                    name="start_job",
                    argumente={"agent": "schreiber", "task": "Schreib eine Notiz."},
                )
            ],
        ),
    )

    eltern = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "gib etwas ab"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, eltern)

    aufruf = next(e for e in gemeldet if e["typ"] == "tool_call" and e["name"] == "start_job")
    ergebnis = next(e for e in gemeldet if e["typ"] == "tool_result" and e["name"] == "start_job")
    assert aufruf["server"] == mcp_client_echt.app.state.werkzeuge.server_von("start_job")
    assert ergebnis["bild"] is None
    assert isinstance(ergebnis["dauer_sekunden"], float) and ergebnis["dauer_sekunden"] >= 0
    assert ergebnis["fehlgeschlagen"] is False


def test_das_kind_laeuft_auf_dem_server_seines_elternlaufs(config, mcp_client_echt):
    """A parent started by hand on a second server: its child runs there
    too, not on the server the settings name for runs without a pick."""
    from tests.conftest import lokaler_endpunkt

    agent_schreiben(config, kopf="model: test\ntools:\n  - start_job\nmax_rounds: 2")
    agent_schreiben(config, name="schreiber", kopf="model: test\nmax_rounds: 1")
    # The one field points at "test" — where a child would land on its own.
    provider_setzen(mcp_client_echt, MockProvider(mock_endpunkt("test"), haeppchen=["fertig"]))
    lokaler_endpunkt(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("zweit"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1",
                    name="start_job",
                    argumente={"agent": "schreiber", "task": "Schreib eine Notiz."},
                )
            ],
        ),
        endpoint_id="zweit",
    )

    eltern = mcp_client_echt.post(
        "/api/v1/jobs",
        json={"agent": "recherche", "task": "gib etwas ab", "endpoint_id": "zweit"},
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, eltern)
    ergebnisse = _tool_ergebnisse(daten)
    assert ergebnisse and ergebnisse[0]["fehlgeschlagen"] is False, ergebnisse

    repos = mcp_client_echt.app.state.repositories
    alle = mcp_client_echt.get("/api/v1/jobs").json()
    kind = [a for a in alle if a["parent_id"] == eltern][0]
    assert repos.auftraege.holen(eltern).endpoint_id == "zweit"
    assert repos.auftraege.holen(kind["id"]).endpoint_id == "zweit"


def test_ein_kind_vom_hauptserver_nimmt_dessen_heutiges_modell(config, mcp_client_echt):
    """A parent on the main server carries the model loaded when it started
    (`runner:alt`). The child inherits the server, not that model: switched
    to `neu` meanwhile, the main server runs the child on `neu`."""
    from app import agentenmodellwahl
    from tests.conftest import lokaler_endpunkt

    agent_schreiben(config, kopf="model: test\ntools:\n  - start_job\nmax_rounds: 2")
    agent_schreiben(config, name="schreiber", kopf="model: test\nmax_rounds: 1")
    agentenmodell_leer(mcp_client_echt)
    discovery = mcp_client_echt.app.state.discovery

    class Wechselnd(MockProvider):
        async def streamen(self, anfrage):
            if self.durchlaeufe == 0:
                # The model on the main server changes while the parent runs.
                discovery.zustaende[agentenmodellwahl.HAUPTMODELL].gemeldeter_name = "neu"
            async for stueck in super().streamen(anfrage):
                yield stueck

    endpunkt = mock_endpunkt(agentenmodellwahl.HAUPTMODELL)
    endpunkt.capabilities.tool_calls = True
    lokaler_endpunkt(
        mcp_client_echt,
        Wechselnd(
            endpunkt,
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1",
                    name="start_job",
                    argumente={"agent": "schreiber", "task": "Schreib eine Notiz."},
                )
            ],
        ),
    )
    zustand = discovery.zustaende[agentenmodellwahl.HAUPTMODELL]
    zustand.gemeldeter_name = "alt"
    zustand.modelle = ["alt", "neu"]

    eltern = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "gib etwas ab"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, eltern)

    repos = mcp_client_echt.app.state.repositories
    alle = mcp_client_echt.get("/api/v1/jobs").json()
    kind = [a for a in alle if a["parent_id"] == eltern][0]
    assert repos.auftraege.holen(eltern).endpoint_id == "runner:alt"
    assert repos.auftraege.holen(kind["id"]).endpoint_id == "runner:neu"


def test_ohne_eigene_wahl_laeuft_das_kind_wie_der_elternlauf(config, mcp_client_echt):
    """The silence probe: a parent that took the settings' server hands the
    same one on — nothing changes for a chain nobody picked a server for."""
    agent_schreiben(config, kopf="model: test\ntools:\n  - start_job\nmax_rounds: 2")
    agent_schreiben(config, name="schreiber", kopf="model: test\nmax_rounds: 1")
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1",
                    name="start_job",
                    argumente={"agent": "schreiber", "task": "Schreib eine Notiz."},
                )
            ],
        ),
    )
    eltern = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "gib etwas ab"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, eltern)

    repos = mcp_client_echt.app.state.repositories
    alle = mcp_client_echt.get("/api/v1/jobs").json()
    kind = [a for a in alle if a["parent_id"] == eltern][0]
    assert repos.auftraege.holen(kind["id"]).endpoint_id == "test"


async def test_start_job_ohne_lauf_dahinter_bleibt_verboten(config, tmp_path):
    """The silence test. Two runs start a job, and both do it before the
    call reaches the registry — the chat through its window, a job under
    itself. A call that gets HERE has neither behind it, and is refused with
    the sentence it always gave."""
    from app.tools import auftrag_werkzeug
    from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten

    registry = WerkzeugRegistry(
        [], agenten_orte=(tmp_path / "mitgeliefert", tmp_path / "eigen")
    )
    with pytest.raises(WerkzeugVerboten) as fehler:
        await registry.ausfuehren(
            auftrag_werkzeug.WERKZEUG_NAME,
            {"agent": "recherche", "task": "irgendwas"},
            herkunft="agent",
        )
    assert str(fehler.value) == auftrag_werkzeug.NUR_IM_CHAT


def test_der_elternabbruch_beendet_das_kind(config, mcp_client_echt):
    """Cancelling walks down: a branch that keeps working for a run that is
    already over is a branch nobody can stop."""
    agent_schreiben(config, kopf="model: test\ntools:\n  - start_job\nmax_rounds: 2")
    agent_schreiben(config, name="schreiber", kopf="model: test\nmax_rounds: 1")
    provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id="a1",
                    name="start_job",
                    argumente={"agent": "schreiber", "task": "Schreib eine Notiz."},
                )
            ],
        ),
    )
    eltern = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "gib etwas ab"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, eltern)

    alle = mcp_client_echt.get("/api/v1/jobs").json()
    kind = [a for a in alle if a["parent_id"] == eltern][0]
    # Put the child back into a live state so the cancel has something to do.
    repos = mcp_client_echt.app.state.repositories
    repos.auftraege.zustand_setzen(kind["id"], "wartet")

    mcp_client_echt.post(f"/api/v1/jobs/{eltern}/cancel")
    nachher = mcp_client_echt.get(f"/api/v1/jobs/{kind['id']}").json()
    assert nachher["state"] == "abgebrochen"
    assert nachher["end_reason"] == "eltern_abbruch"


def test_jeder_agentenlauf_bekommt_die_ablage_dazu(config, mcp_client_echt, tmp_path):
    """The shelf is the way OUT of a job, not a capability to switch on per
    agent. An agent that named its tools without it delivers into a folder
    nobody opens — which is exactly what the shipped research agent did."""
    from app.agentendock import AgentenDock
    from app.tools.registry import WerkzeugRegistry

    mcp_client_echt.app.state.werkzeuge = WerkzeugRegistry(
        [], shell_an=True, agentendock=AgentenDock(tmp_path / "dock")
    )
    agent_schreiben(config, kopf="model: test\ntools:\n  - read_file")
    provider = provider_setzen(mcp_client_echt, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    namen = {w["function"]["name"] for w in provider.letzte_anfrage.werkzeuge}
    assert "deliver_file" in namen
    # And the paragraph that explains it travels with the tool.
    assert "deliver_file" in provider.letzte_anfrage.nachrichten[0].content


def test_ein_agent_ohne_werkzeuge_bekommt_auch_die_ablage_nicht(
    config, mcp_client_echt, tmp_path
):
    """The silence test, and it caught the first build of this.

    An explicit empty list is somebody saying "none of them" on purpose. The
    shelf is not the exception that reopens it — and widening `[]` would not
    merely add one tool, it would turn a run that uses no tools at all into
    one that does."""
    from app.agentendock import AgentenDock
    from app.tools.registry import WerkzeugRegistry

    mcp_client_echt.app.state.werkzeuge = WerkzeugRegistry(
        [], shell_an=True, agentendock=AgentenDock(tmp_path / "dock")
    )
    agent_schreiben(config, kopf="model: test\ntools: []")
    provider = provider_setzen(mcp_client_echt, MockProvider(mock_endpunkt("test")))

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(mcp_client_echt, kennung)

    assert not (provider.letzte_anfrage.werkzeuge or [])


class HandoffOnlyKeepalives(NahezuVollerKontext):
    """The handoff request gets nothing but keepalives: no piece at all
    arrives, for as long as the connection stays open."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, handoff_text="", **kwargs)
        self.handoff_started = False
        self.handoff_closed = False

    async def streamen(self, anfrage):
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and letzte.content == zwischenstand.ANFRAGE_TEXT:
            self.letzte_anfrage = anfrage
            self.handoff_started = True
            try:
                await asyncio.sleep(3600)
                yield Stueck("content", text="never")
            finally:
                self.handoff_closed = True
            return
        async for stueck in super().streamen(anfrage):
            yield stueck


class RecordingRounds(NahezuVollerKontext):
    """Remembers whether a handoff was ever asked for."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handoff_asked = False

    async def streamen(self, anfrage):
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and letzte.content == zwischenstand.ANFRAGE_TEXT:
            self.handoff_asked = True
        async for stueck in super().streamen(anfrage):
            yield stueck


def test_a_stop_before_the_handoff_asks_for_no_handoff(config, client, monkeypatch):
    """The stop lands exactly where the branch under test lives: the round is
    over and its pressure is about to be read, so the handoff below it is
    never asked for and the run ends as stopped. The test beside this one
    stops once the request is already on its way — this branch had none."""
    agent_schreiben(config)
    provider = provider_setzen(
        client, RecordingRounds(mock_endpunkt("test"), handoff_text=HANDOFF_ZWEI_PUNKTE)
    )
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    echt = kontextdruck.stand
    stopped: list[int] = []

    def stopping(*args, **kwargs):
        # Right before the pressure is read: the stop is set, and the value
        # the loop reads is the real one.
        if not stopped:
            stopped.append(1)
            for lauf in client.app.state.generierungen.laufende():
                lauf.signal.set()
        return echt(*args, **kwargs)

    monkeypatch.setattr(kontextdruck, "stand", stopping)
    job_id = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    data = auf_ende_warten(client, job_id)

    assert stopped == [1]
    assert data["state"] == "abgebrochen"
    assert provider.handoff_asked is False
    assert client.app.state.repositories.cronjobs.auflisten() == []


def test_a_stop_ends_a_handoff_that_only_gets_keepalives(config, client):
    agent_schreiben(config)
    provider = provider_setzen(client, HandoffOnlyKeepalives(mock_endpunkt("test")))
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    job_id = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    deadline = time.monotonic() + 8
    while not provider.handoff_started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert provider.handoff_started
    assert client.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 200
    data = auf_ende_warten(client, job_id)

    assert data["state"] == "abgebrochen"
    assert client.app.state.repositories.cronjobs.auflisten() == []
    assert provider.handoff_closed


async def _lauf_mit_bildfenster(
    config, client, tmp_path, monkeypatch, familie, aus=None
):
    """One job whose picture server's default model is of ``familie``.

    Returns the run's status steps and the request the model was offered —
    the two readings the notice and the offer are about.
    """
    from app import bildstandardmodell
    from app.tools import bild_werkzeug

    ordner = tmp_path / "bilder"
    ordner.mkdir()
    (ordner / "malen.safetensors").write_bytes(b"x")
    monkeypatch.setattr(bild_werkzeug, "ort", lambda config, was: ordner)
    # What the file's header would name.
    monkeypatch.setattr(bild_werkzeug.bildinhalt, "family", lambda pfad: familie)
    agent_schreiben(config, kopf="model: test\ntools:\n  - draw_image")
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    chat_id = client.post("/api/v1/chats", json={"title": "Bild"}).json()["id"]
    repositories.einstellungen.setzen(
        "global", bildstandardmodell.SCHLUESSEL, "malen.safetensors",
    )
    if aus:
        repositories.einstellungen.setzen(
            "global", werkzeugwahl.SCHLUESSEL, list(aus)
        )
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]

    auftrag = auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="mal mir was",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        chat_id=chat_id,
    )
    await _bis_beendet(repositories, auftrag.id)

    schritte = [
        schritt.inhalt
        for schritt in repositories.auftraege.schritte(auftrag.id)
        if schritt.typ == "status"
    ]
    angeboten = {w["function"]["name"] for w in provider.letzte_anfrage.werkzeuge}
    # The notice by its exact names, not by a substring: a step that lists
    # one name too many is the false alarm this test is here for.
    fehlend = [
        name.strip()
        for zeile in schritte
        if zeile.startswith("Werkzeuge nicht verfügbar")
        for name in zeile.split(":", 1)[1].split(",")
    ]
    return schritte, angeboten, fehlend


async def test_ein_draw_image_das_der_lauf_nicht_bekommt_steht_als_schritt_da(
    config, mcp_client_echt, tmp_path, monkeypatch
):
    """An agent that names a tool the run does not get has to show it.

    `draw_image` is offered only where the default model draws from text;
    at a family that cannot (editing, video) the run starts without
    it. The notice measured the agent's list against every name the program
    KNOWS (app/api/v1/auftraege.py) — so it stayed silent exactly there: a
    run with one tool less, and nothing saying so.
    """
    schritte, angeboten, fehlend = await _lauf_mit_bildfenster(
        config, mcp_client_echt, tmp_path, monkeypatch, "wan"
    )

    assert "draw_image" not in angeboten
    assert fehlend == ["draw_image"], schritte


async def test_bei_einem_malenden_fenster_bleibt_der_schritt_aus(
    config, mcp_client_echt, tmp_path, monkeypatch
):
    """Silence probe: a default model that draws from text keeps the tool,
    and the notice says nothing — exactly as before."""
    schritte, angeboten, fehlend = await _lauf_mit_bildfenster(
        config, mcp_client_echt, tmp_path, monkeypatch, "sdxl"
    )

    assert "draw_image" in angeboten
    assert fehlend == [], schritte


async def test_ein_abgeschaltetes_werkzeug_gilt_nicht_als_fehlend(
    config, mcp_client_echt, tmp_path, monkeypatch
):
    """A tool switched off on purpose is a configuration, not a missing one.

    Every run widens its own list with the clock (app/api/v1/auftraege.py),
    and the notice must not turn that into a "tools not available" line
    naming get_current_time on every start — the user switched it off, and
    no agent file ever named it. The same holds for a name the start itself
    adds, like the shelf.
    """
    schritte, angeboten, fehlend = await _lauf_mit_bildfenster(
        config, mcp_client_echt, tmp_path, monkeypatch, "sdxl", aus=["get_current_time"]
    )

    assert "get_current_time" not in angeboten
    assert "draw_image" in angeboten
    assert fehlend == [], schritte


# --- What the stored log carries for a call --------------------------------


class ShellAndAdd(MockProvider):
    """Starts a shell command and calls a plain tool in one round, then ends."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if self.durchlaeufe == 1:
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id="s1", name="run_command",
                        argumente={"command": "npm install\n", "background": True},
                    ),
                    Werkzeugaufruf(id="r1", name="addieren", argumente={"a": 1, "b": 2}),
                ],
            )
            return
        yield Stueck("content", text="Fertig.")


class ShellDouble(RegistryDouble):
    """The double plus a shell that registers its run the way the real tool
    does — under the id it is called with, the command stripped — and runs
    nothing."""

    def __init__(self, refuse_shell: bool = False) -> None:
        super().__init__()
        self.refuse_shell = refuse_shell
        self._werkzeuge["run_command"] = (
            None, MCPWerkzeug(name="run_command", beschreibung="shell"), False
        )

    def server_von(self, name):
        return "shell" if name == "run_command" else "rechner"

    async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None, chat_id=None, **_rest):
        from app.tools import hintergrund

        if name == "run_command" and self.refuse_shell:
            # A run of the same command begins during this very call — so
            # only the refusal itself, not the time filter, may keep the
            # number off the result — and the call is then refused.
            hintergrund.laeufe.anlegen(chat_id, str(argumente["command"]).strip(), True)
            raise WerkzeugVerboten("not in a shared folder")
        if name == "run_command":
            run = hintergrund.laeufe.anlegen(chat_id, str(argumente["command"]).strip(), True)
            return f"Started in the background as run #{run.nummer}."
        return "3"


def test_a_shell_call_in_a_job_names_its_run(config, mcp_client, monkeypatch):
    """The shell call's result carries the number of the run it started, in
    the stream and in the stored log, as the chat's does; the stored call
    carries its server and every stored result its time. The plain tool
    beside it gets no run number."""
    from app.generationen import Generierung

    reported: list[dict] = []
    original = Generierung.melden

    def record(self, line):
        reported.append(json.loads(line.removeprefix("data: ").strip()))
        original(self, line)

    monkeypatch.setattr(Generierung, "melden", record)
    mcp_client.app.state.werkzeuge = ShellDouble()
    agent_schreiben(config)
    provider_setzen(mcp_client, ShellAndAdd(mock_endpunkt("test")))
    job_id = mcp_client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    data = auf_ende_warten(mcp_client, job_id)

    stream = {e["aufruf_id"]: e for e in reported if e["typ"] == "tool_result"}
    assert stream["s1"]["lauf_nummer"] == 1
    assert "lauf_nummer" not in stream["r1"]

    calls = [json.loads(s["inhalt"]) for s in data["schritte"] if s["typ"] == "tool_call"]
    assert [(a["name"], a["server"]) for a in calls] == [
        ("run_command", "shell"), ("addieren", "rechner"),
    ]
    stored = {
        e["name"]: e
        for e in (json.loads(s["inhalt"]) for s in data["schritte"] if s["typ"] == "tool_result")
    }
    assert stored["run_command"]["lauf_nummer"] == 1
    assert stored["run_command"]["server"] == "shell"
    assert stored["addieren"]["server"] == "rechner"
    assert "lauf_nummer" not in stored["addieren"]
    for entry in stored.values():
        assert isinstance(entry["dauer_sekunden"], float) and entry["dauer_sekunden"] >= 0


def test_a_refused_shell_call_in_a_job_names_no_run(config, mcp_client, monkeypatch):
    """Silence probe: a refused shell call gets no number — not even that of
    a run of the same command that began while it was being refused."""
    mcp_client.app.state.werkzeuge = ShellDouble(refuse_shell=True)
    agent_schreiben(config)
    provider_setzen(mcp_client, ShellAndAdd(mock_endpunkt("test")))
    job_id = mcp_client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    data = auf_ende_warten(mcp_client, job_id)

    shell = next(
        e for e in (json.loads(s["inhalt"]) for s in data["schritte"] if s["typ"] == "tool_result")
        if e["name"] == "run_command"
    )
    assert shell["fehlgeschlagen"] is True
    assert "lauf_nummer" not in shell


def test_an_old_log_without_the_new_fields_still_reads(config, client):
    """Silence probe: a log written before the fields existed is read as it
    was — the transcript shows its lines, nothing asks for the new keys."""
    agent_schreiben(config)
    provider_setzen(client, MockProvider(mock_endpunkt("test")))
    job_id = client.post("/api/v1/jobs", json={"agent": "recherche", "task": "Los"}).json()["id"]
    auf_ende_warten(client, job_id)
    repositories = client.app.state.repositories
    repositories.auftraege.schritt_anlegen(
        job_id, "tool_call", json.dumps({"name": "addieren", "argumente": {}})
    )
    repositories.auftraege.schritt_anlegen(
        job_id, "tool_result",
        json.dumps({"name": "addieren", "fehlgeschlagen": False, "text": "3"}),
    )

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    old = [s for s in response.json()["schritte"] if s["typ"] == "tool_result"]
    assert json.loads(old[-1]["inhalt"]) == {"name": "addieren", "fehlgeschlagen": False, "text": "3"}


def test_a_job_reads_the_image_folder_and_its_prompt_names_it(config, mcp_client_echt):
    """A picture is handed to a job by its path, so the picture folder is on
    every run beside the dock — read without a question, and named in the
    prompt as the program's own place."""
    from app import speicherorte

    images = speicherorte.ort(config, "images")
    images.mkdir(parents=True, exist_ok=True)
    note = images / "caption.txt"
    note.write_text("a cat on a roof", encoding="utf-8")
    agent_schreiben(config, kopf="model: test\ntools:\n  - read_file\nmax_rounds: 2")
    provider = provider_setzen(
        mcp_client_echt,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="read_file", argumente={"path": str(note)})
            ],
        ),
    )

    kennung = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "lies"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, kennung)

    results = _tool_ergebnisse(daten)
    assert results, "no tool_result in the log"
    assert results[0]["fehlgeschlagen"] is False, results[0]["text"]
    assert "a cat on a roof" in results[0]["text"]
    system_text = provider.letzte_anfrage.nachrichten[0].content
    assert "The image folder contains all images" in system_text
    assert f"- {images}" in system_text


# --- A 400 the server answers five times: a report that names it ------------


class Answers400(MockProvider):
    """The server answers with an error status (400 by default) and its own
    sentence to the first ``failures`` attempts (all of them by default),
    then answers."""

    def __init__(
        self, *args, failures: int | None = None, status: int = 400,
        sentence: str = "unsupported value for 'temperature'", **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.failures = failures
        self.status = status
        self.sentence = sentence
        self.calls = 0

    async def streamen(self, anfrage):
        self.calls += 1
        if self.failures is None or self.calls <= self.failures:
            raise ProviderFehler(
                f"test answered with {self.status}: {self.sentence}",
                status=self.status,
                rohtext=self.sentence,
            )
        async for stueck in super().streamen(anfrage):
            yield stueck


def _start_in_chat(config, client, repositories, chat_id):
    agent_schreiben(config)
    agent = agenten_laden(Path(config.app.agenten_verzeichnis))["recherche"]
    return auftrag_anstossen(
        config=client.app.state.config,
        repositories=repositories,
        discovery=client.app.state.discovery,
        generierungen=client.app.state.generierungen,
        registry=getattr(client.app.state, "werkzeuge", None),
        agent=agent,
        task="Los",
        endpoint_id=None,
        user_id="standard",
        sprache="de",
        chat_id=chat_id,
    )


def _report_row(repositories, chat_id):
    rows = [r for r in repositories.messages.auflisten(chat_id=chat_id) if r.art == "werkzeugmeldung"]
    return rows[0] if rows else None


async def test_five_400s_end_the_run_with_a_report_that_names_the_error(
    config, client, chat_id, monkeypatch
):
    """The server answered every attempt and said the request is wrong. The
    five attempts stay; after the fifth the run ends — not handed on as
    'unterbrochen' — and the chat gets a report whose last line is the code
    and the server's own sentence."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    repositories = client.app.state.repositories
    provider = provider_setzen(client, Answers400(mock_endpunkt("test")))
    auftrag = _start_in_chat(config, client, repositories, chat_id)
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert provider.calls == wiederversuch.VERSUCHE
    assert beendet.zustand == "gescheitert"
    assert beendet.ende_grund.startswith("fehler:")
    assert repositories.cronjobs.auflisten() == []
    last_line = beendet.ergebnis.splitlines()[-1]
    assert "400" in last_line and "unsupported value for 'temperature'" in last_line

    deadline = time.monotonic() + 5
    while _report_row(repositories, chat_id) is None and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    report = _report_row(repositories, chat_id)
    assert report is not None, "the chat got no report"
    assert report.content.startswith("[Agent 'recherche' failed")
    final = report.content.splitlines()[-1]
    assert "400" in final and "unsupported value for 'temperature'" in final


async def test_a_400_that_goes_away_leaves_no_error_line(config, client, chat_id, monkeypatch):
    """The silence probe: a 400 on the first attempt, an answer on the
    second — the run ends as it always did, with no error line."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    repositories = client.app.state.repositories
    provider = provider_setzen(
        client, Answers400(mock_endpunkt("test"), failures=1, haeppchen=["fertig"])
    )
    auftrag = _start_in_chat(config, client, repositories, chat_id)
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert provider.calls == 2
    assert beendet.zustand == "fertig"
    assert "400" not in (beendet.ergebnis or "")


async def test_a_400_names_nothing_for_a_server_that_does_not_answer(
    config, client, chat_id, monkeypatch
):
    """The silence probe the other way round: no status at all is still the
    outage it was — handed on, no error line in a report."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    repositories = client.app.state.repositories
    provider_setzen(client, MockProvider(mock_endpunkt("test"), fehler="Kabelbrand"))
    auftrag = _start_in_chat(config, client, repositories, chat_id)
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert beendet.zustand == "unterbrochen"
    assert beendet.ende_grund == "anbieter_ausfall"


async def test_five_500s_end_the_run_with_a_report_that_names_the_error(
    config, client, chat_id, monkeypatch
):
    """Any error the server answers five times ends the run the way 400 does:
    not handed on as 'unterbrochen', and the chat gets a report whose last
    line is the code and the server's own sentence."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    repositories = client.app.state.repositories
    provider = provider_setzen(
        client,
        Answers400(mock_endpunkt("test"), status=500, sentence="the backend is overloaded"),
    )
    auftrag = _start_in_chat(config, client, repositories, chat_id)
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert provider.calls == wiederversuch.VERSUCHE
    assert beendet.zustand == "gescheitert"
    assert beendet.ende_grund.startswith("fehler:")
    assert repositories.cronjobs.auflisten() == []
    last_line = beendet.ergebnis.splitlines()[-1]
    assert "500" in last_line and "the backend is overloaded" in last_line

    deadline = time.monotonic() + 5
    while _report_row(repositories, chat_id) is None and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    report = _report_row(repositories, chat_id)
    assert report is not None, "the chat got no report"
    assert report.content.startswith("[Agent 'recherche' failed")
    final = report.content.splitlines()[-1]
    assert "500" in final and "the backend is overloaded" in final


async def test_a_500_that_goes_away_leaves_no_error_line(config, client, chat_id, monkeypatch):
    """The silence probe: a 500 on the first attempt, an answer on the second
    — the run ends as it always did, with no error line."""
    monkeypatch.setattr(wiederversuch, "abstand", lambda versuch: 0)
    repositories = client.app.state.repositories
    provider = provider_setzen(
        client,
        Answers400(
            mock_endpunkt("test"), failures=1, status=500, sentence="try again",
            haeppchen=["fertig"],
        ),
    )
    auftrag = _start_in_chat(config, client, repositories, chat_id)
    beendet = await _bis_beendet(repositories, auftrag.id)

    assert provider.calls == 2
    assert beendet.zustand == "fertig"
    assert "500" not in (beendet.ergebnis or "")


# --- A run another run started starts no run --------------------------------


class StartsAJobEveryRun(MockProvider):
    """Every run's first round calls start_job; once a tool result is back,
    the run answers. So a run asked for by a run calls it as well."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if any(n.role == "tool" for n in anfrage.nachrichten):
            yield Stueck("content", text="fertig")
            return
        yield Stueck(
            "tool_call",
            werkzeugaufrufe=[
                Werkzeugaufruf(
                    id=f"w{self.durchlaeufe}",
                    name="start_job",
                    argumente={"agent": "schreiber", "task": "Schreib eine Notiz."},
                )
            ],
        )


def _child_chain(config, client):
    """A parent whose model calls start_job, and a child whose model calls it
    again: the call every run's first round makes."""
    agent_schreiben(config, kopf="model: test\ntools:\n  - start_job\nmax_rounds: 3")
    agent_schreiben(config, name="schreiber", kopf="model: test\nmax_rounds: 3")
    provider = provider_setzen(client, StartsAJobEveryRun(mock_endpunkt("test")))
    parent = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "gib etwas ab"}
    ).json()["id"]
    auf_ende_warten(client, parent)
    return provider, parent


def test_a_run_under_a_run_starts_no_further_run(config, mcp_client_echt):
    """The chain stops at the child: its own call is refused with a sentence
    to the model, and no grandchild exists."""
    from app import run_chain

    _, parent = _child_chain(config, mcp_client_echt)
    (child,) = [
        a for a in mcp_client_echt.get("/api/v1/jobs").json() if a["parent_id"] == parent
    ]
    daten = auf_ende_warten(mcp_client_echt, child["id"])

    assert len(mcp_client_echt.get("/api/v1/jobs").json()) == 2
    results = _tool_ergebnisse(daten)
    assert results and results[0]["fehlgeschlagen"] is True
    assert results[0]["text"] == run_chain.NO_RUN_UNDER_A_RUN


def test_a_run_under_a_run_is_not_offered_start_job(config, mcp_client_echt):
    """The offer leaves the tool out; the chat's own run keeps it."""
    provider, parent = _child_chain(config, mcp_client_echt)
    (child,) = [
        a for a in mcp_client_echt.get("/api/v1/jobs").json() if a["parent_id"] == parent
    ]
    auf_ende_warten(mcp_client_echt, child["id"])

    def offered(request) -> set[str]:
        return {w["function"]["name"] for w in request.werkzeuge}

    parent_requests = [
        r for r in provider.alle_anfragen if "gib etwas ab" in str(r.nachrichten[1].content)
    ]
    child_requests = [
        r for r in provider.alle_anfragen if "Schreib eine Notiz." in str(r.nachrichten[1].content)
    ]
    assert parent_requests and child_requests
    assert all("start_job" in offered(r) for r in parent_requests)
    assert all("start_job" not in offered(r) for r in child_requests)


def test_a_run_without_a_parent_starts_a_run_as_before(config, mcp_client_echt):
    """The silence probe: the first level — a run nobody's run started —
    starts its child exactly as it did."""
    _, parent = _child_chain(config, mcp_client_echt)
    children = [
        a for a in mcp_client_echt.get("/api/v1/jobs").json() if a["parent_id"] == parent
    ]
    assert len(children) == 1
    assert children[0]["agent"] == "schreiber"


class CreatesAScheduleBelowTheFirstRun(MockProvider):
    """The first run starts a child; the child's model reaches for
    ``cronjob`` in its first round. Once a tool result is back, a run
    answers."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.durchlaeufe += 1
        if any(n.role == "tool" for n in anfrage.nachrichten):
            yield Stueck("content", text="fertig")
            return
        if "Schreib eine Notiz." in str(anfrage.nachrichten[1].content):
            aufruf = Werkzeugaufruf(
                id=f"w{self.durchlaeufe}",
                name="cronjob",
                argumente={"action": "create", "time": "08:00", "task": "Notiz schreiben"},
            )
        else:
            aufruf = Werkzeugaufruf(
                id=f"w{self.durchlaeufe}",
                name="start_job",
                argumente={"agent": "schreiber", "task": "Schreib eine Notiz."},
            )
        yield Stueck("tool_call", werkzeugaufrufe=[aufruf])


def _schedule_chain(config, client):
    agent_schreiben(config, kopf="model: test\ntools:\n  - start_job\n  - cronjob\nmax_rounds: 3")
    agent_schreiben(config, name="schreiber", kopf="model: test\nmax_rounds: 3")
    provider = provider_setzen(client, CreatesAScheduleBelowTheFirstRun(mock_endpunkt("test")))
    parent = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "gib etwas ab"}
    ).json()["id"]
    auf_ende_warten(client, parent)
    return provider, parent


def test_a_run_under_a_run_creates_no_schedule(config, mcp_client_echt):
    """The call is refused with a sentence to the model, and no schedule
    exists afterwards."""
    from app import run_chain

    _, parent = _schedule_chain(config, mcp_client_echt)
    (child,) = [
        a for a in mcp_client_echt.get("/api/v1/jobs").json() if a["parent_id"] == parent
    ]
    daten = auf_ende_warten(mcp_client_echt, child["id"])

    results = _tool_ergebnisse(daten)
    assert results and results[0]["fehlgeschlagen"] is True
    assert results[0]["text"] == run_chain.NO_SCHEDULE_UNDER_A_RUN
    assert mcp_client_echt.app.state.repositories.cronjobs.auflisten() == []


def test_a_run_under_a_run_is_not_offered_cronjob(config, mcp_client_echt):
    """The offer leaves the tool out; the first run keeps it."""
    provider, parent = _schedule_chain(config, mcp_client_echt)
    (child,) = [
        a for a in mcp_client_echt.get("/api/v1/jobs").json() if a["parent_id"] == parent
    ]
    auf_ende_warten(mcp_client_echt, child["id"])

    def offered(request) -> set[str]:
        return {w["function"]["name"] for w in request.werkzeuge}

    parent_requests = [
        r for r in provider.alle_anfragen if "gib etwas ab" in str(r.nachrichten[1].content)
    ]
    child_requests = [
        r for r in provider.alle_anfragen if "Schreib eine Notiz." in str(r.nachrichten[1].content)
    ]
    assert parent_requests and child_requests
    assert all("cronjob" in offered(r) for r in parent_requests)
    assert all("cronjob" not in offered(r) for r in child_requests)


def test_a_run_without_a_parent_creates_a_schedule_as_before(config, mcp_client_echt):
    """The silence probe: a run nobody's run started keeps ``cronjob`` and
    its call creates the schedule."""
    agent_schreiben(config, name="schreiber", kopf="model: test\nmax_rounds: 3")
    provider_setzen(mcp_client_echt, CreatesAScheduleBelowTheFirstRun(mock_endpunkt("test")))
    run = mcp_client_echt.post(
        "/api/v1/jobs", json={"agent": "schreiber", "task": "Schreib eine Notiz."}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client_echt, run)

    results = _tool_ergebnisse(daten)
    assert results and results[0]["fehlgeschlagen"] is False
    assert len(mcp_client_echt.app.state.repositories.cronjobs.auflisten()) == 1


# --- A job's stream carries the live context and speed, as the chat's does --


class WithLivePieces(MockProvider):
    """One round that reports, on its way, how full the context is and how
    fast the model thinks — and then ends with its own count of 150."""

    async def streamen(self, anfrage):
        yield kontext_stueck(100, True, 20)
        yield Stueck("denktempo", daten={"tokens_pro_sekunde": 12.5, "tempo_quelle": "server"})
        yield Stueck("content", "Done")
        yield kontext_stueck(100, True, 30)
        yield Stueck(
            "stats",
            daten={
                "dauer_sekunden": 0.0,
                "nutzung": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            },
        )


@pytest.fixture
def run_events(monkeypatch):
    """Every event a run puts on its stream, in order."""
    ereignisse: list[dict] = []
    original = Generierung.melden

    def erfassen(self, zeile):
        try:
            ereignisse.append(json.loads(zeile.removeprefix("data: ")))
        except ValueError:
            pass
        return original(self, zeile)

    monkeypatch.setattr(Generierung, "melden", erfassen)
    return ereignisse


def _context_numbers(daten: dict) -> list[int]:
    return [
        json.loads(schritt["inhalt"])["tokens"]
        for schritt in daten["schritte"]
        if schritt["typ"] == "kontext"
    ]


def test_a_job_forwards_context_and_thinking_speed_on_its_stream(
    config, client, run_events
):
    agent_schreiben(config)
    provider_setzen(client, WithLivePieces(mock_endpunkt("test")))
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    auf_ende_warten(client, kennung)

    kontext = [e["gesamt_tokens"] for e in run_events if e["typ"] == "kontext"]
    assert kontext == [120, 130]
    tempo = [e for e in run_events if e["typ"] == "denktempo"]
    assert [e["tokens_pro_sekunde"] for e in tempo] == [12.5]
    # The kinds that were already forwarded are unchanged.
    assert [e["text"] for e in run_events if e["typ"] == "content"] == ["Done"]


def test_the_context_bar_of_a_job_moves_while_the_round_is_written(
    config, client
):
    """The bar reads the newest ``kontext`` line. The first live reading opens
    a line at once and later ones rewrite it (at the autosave's pace, so the
    second one, a moment later, does not); the round's own count follows as a
    line of its own — two lines for the round, not one per reading."""
    agent_schreiben(config)
    provider_setzen(client, WithLivePieces(mock_endpunkt("test")))
    client.app.state.discovery.zustaende["test"].context_tokens = 1000

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert _context_numbers(daten) == [120, 150]
    assert json.loads(
        [s for s in daten["schritte"] if s["typ"] == "kontext"][0]["inhalt"]
    ) == {"tokens": 120, "kontextgroesse": 1000, "prozent": 12.0}


def test_silence_a_live_reading_without_a_count_reports_and_writes_nothing(
    config, client, run_events
):
    """A provider that cannot count the prompt, in a run with nothing known
    before it: a count of the output alone is no context reading."""
    agent_schreiben(config)
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"), kontext_melden=True, kontext_prompt=None,
            haeppchen=["One ", "Satz"],
        ),
    )

    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Los"}
    ).json()["id"]
    daten = auf_ende_warten(client, kennung)

    assert [e for e in run_events if e["typ"] in ("kontext", "denktempo")] == []
    assert _context_numbers(daten) == []


def test_a_live_reading_of_the_second_round_builds_on_the_first(
    config, mcp_client, run_events
):
    """Round two names no prompt count: the reading stands on the count round
    one ended with, plus what round two has written so far."""

    class TwoRounds(MockProvider):
        async def streamen(self, anfrage):
            self.durchlaeufe += 1
            if self.durchlaeufe == 1:
                yield Stueck(
                    "tool_call",
                    werkzeugaufrufe=[Werkzeugaufruf(id="w1", name="addieren", argumente={"a": 1, "b": 2})],
                )
                yield Stueck("stats", daten={"nutzung": {"total_tokens": 150}})
                return
            yield kontext_stueck(None, False, 10)
            yield Stueck("content", "Done")
            yield Stueck("stats", daten={"nutzung": {"total_tokens": 170}})

    agent_schreiben(config, kopf="model: test\ntools:\n  - addieren\nmax_rounds: 3")
    provider_setzen(mcp_client, TwoRounds(mock_endpunkt("test")))

    kennung = mcp_client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Rechne"}
    ).json()["id"]
    daten = auf_ende_warten(mcp_client, kennung)

    # 151 is the estimate between the rounds (the tool result added to
    # round one's count); the live reading of round two builds on it.
    assert [e["gesamt_tokens"] for e in run_events if e["typ"] == "kontext"] == [161]
    assert _context_numbers(daten) == [150, 151, 161, 170]


# --- The name of the model a run takes, as the model list names it ----------


async def test_the_run_model_is_named_after_the_model_not_the_endpoint(client):
    """A model the endpoint does not list and the server does not report:
    the name under the row is the model's own, the way the model list names
    it — not the name the configuration gives the server."""
    await client.app.state.discovery.anmelden(
        mock_endpunkt("foreign", name="Server name X")
    )
    client.app.state.repositories.einstellungen.setzen(
        "global", agentenmodellwahl.SCHLUESSEL, {"sorte": "kennung", "wert": "foreign:Model-Y"},
    )

    antwort = client.get("/api/v1/jobs/laufmodell").json()

    assert antwort["endpoint_id"] == "foreign:Model-Y"
    assert antwort["name"] == "Model-Y"


async def test_silence_a_run_model_without_a_model_name_is_named_after_its_endpoint(client):
    await client.app.state.discovery.anmelden(
        mock_endpunkt("foreign", name="Server name X")
    )
    client.app.state.repositories.einstellungen.setzen(
        "global", agentenmodellwahl.SCHLUESSEL, {"sorte": "kennung", "wert": "foreign"},
    )

    assert client.get("/api/v1/jobs/laufmodell").json()["name"] == "Server name X"
