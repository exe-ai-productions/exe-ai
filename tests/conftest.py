"""Shared test fixtures.

Every test gets a fresh in-memory database — no test data ever ends up
in the real file. The model is the dummy (``MockProvider``) so the whole
chain can be checked without a running model server.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app import agentenmodellwahl, verdichtung, wachhalten
from app.config import Config
from app.db import Database, repositories_erstellen
from app.events import bus
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from app.tools.mcp_client import MCPWerkzeug
from app.tools.registry import WerkzeugRegistry


# --- Which system a test belongs to ------------------------------------------
#
# The suite runs on macOS and on Windows. A test that checks something the
# other system simply does not have — the execute bit, process groups and
# ``killpg``, a Unix signal — is marked with the systems it belongs
# to and skipped elsewhere, with the reason on the skip line. Everything else
# runs everywhere: a test is marked only when the behaviour does not exist on
# the other system, never because it would need rewriting there.
#
#     @pytest.mark.platforms("posix", reason="the execute bit")
#     pytestmark = pytest.mark.platforms("darwin", reason="the Keychain")

PLATFORM_NAMES = {"posix": "a POSIX system", "darwin": "macOS", "win32": "Windows"}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "platforms(*names, reason=''): run only on these systems — "
        "'posix', 'darwin' or 'win32'; skipped elsewhere with the reason",
    )


def _this_system() -> set[str]:
    names = {sys.platform}
    if os.name == "posix":
        names.add("posix")
    return names


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    here = _this_system()
    for item in items:
        mark = item.get_closest_marker("platforms")
        if mark is None:
            continue
        wanted = set(mark.args)
        unknown = wanted - PLATFORM_NAMES.keys()
        if not wanted or unknown:
            raise pytest.UsageError(
                f"{item.nodeid}: platforms() takes {sorted(PLATFORM_NAMES)}, got {sorted(wanted) or 'nothing'}"
            )
        if wanted & here:
            continue
        where = ", ".join(PLATFORM_NAMES[name] for name in sorted(wanted))
        reason = mark.kwargs.get("reason", "")
        item.add_marker(pytest.mark.skip(reason=f"only on {where}" + (f": {reason}" if reason else "")))


@pytest.fixture(autouse=True)
def sauberer_eventbus():
    """Subscribers from one test must not leak into the next."""
    bus.alles_loeschen()
    yield
    bus.alles_loeschen()


@pytest.fixture(autouse=True)
def frisch_gelesene_pdfs():
    """The last PDF read stays in app/pdfseiten.py for the process, keyed on
    its bytes — a walk through one document is taken apart once instead of
    once per page. In a test session that memory travels: a test that fakes
    a reader whose second page throws stores THOSE pages under the digest of
    an ordinary file, and the next test reading the same bytes is handed the
    broken reading. Cleared around every test, like the bus above."""
    from app import pdfseiten

    pdfseiten._ZULETZT = None
    yield
    pdfseiten._ZULETZT = None


@pytest.fixture(autouse=True)
def saubere_laeufe():
    """The run manager is one instance for the process (app/tools/
    hintergrund.py). Left as a test found it, its runs pile up over the
    session, and its closing handler keeps pointing at a database the
    test that hung it in has long closed — called for every later
    shutdown, failing quietly into that test's log."""
    from app.tools import hintergrund

    def leeren():
        hintergrund.laeufe._laeufe.clear()
        hintergrund.laeufe._startnummer.clear()
        hintergrund.laeufe._ereignisse.clear()
        hintergrund.laeufe._ereignisstand.clear()
        hintergrund.laeufe.abschluss = None
        hintergrund.laeufe.nummernstart = None

    leeren()
    yield
    leeren()


@pytest.fixture(autouse=True)
def kein_echtes_caffeinate(monkeypatch):
    """A job run in a test must not spawn a real caffeinate process
    (app/wachhalten.py) — every job test would otherwise leave one behind.
    Patches only this module's own bound name, not the shared ``subprocess``
    module every other caller's Popen call also goes through."""
    monkeypatch.setattr(wachhalten, "Popen", lambda *a, **k: None)


class MitNutzung(MockProvider):
    """Adds a usage block to the stats chunk, like an OpenAI-compatible
    server that was asked for it (``send_usage_option``)."""

    def __init__(self, *args, nutzung: dict, **kwargs):
        super().__init__(*args, **kwargs)
        self._nutzung = nutzung

    async def streamen(self, anfrage):
        async for stueck in super().streamen(anfrage):
            if stueck.sorte == "stats":
                stueck.daten["nutzung"] = self._nutzung
            yield stueck


@pytest.fixture(autouse=True)
def isolierte_berechtigungsdatei(tmp_path, monkeypatch):
    """No test may create or read the project's own berechtigungen.json.

    The ``config`` fixture below redirects ``berechtigungen_datei`` for
    tests that go through a real ``Config`` — but several tests build a
    ``WerkzeugRegistry`` directly, without one, and the registry then falls
    back to this exact function (see ``app/berechtigungsregeln.py``). One
    autouse fixture covers both paths instead of a path being threaded
    through every such test file by hand.
    """
    import app.berechtigungsregeln as berechtigungsregeln

    monkeypatch.setattr(
        berechtigungsregeln, "_pfad_nutzer", lambda: tmp_path / "berechtigungen.json"
    )


@pytest.fixture
def db() -> Iterator[Database]:
    """The in-memory database this test writes into — the fixture's own
    return is the ``yield``, so its type is what the test gets handed."""
    datenbank = Database(":memory:")
    datenbank.schema_einrichten()
    yield datenbank
    datenbank.schliessen()


@pytest.fixture
def repos(db: Database):
    return repositories_erstellen(db)


@pytest.fixture
def config(tmp_path) -> Config:
    return Config.model_validate(
        {
            "app": {
                "host": "127.0.0.1",
                "port": 8090,
                "language": "de",
                "data_dir": str(tmp_path / "data"),
                "log_dir": str(tmp_path / "logs"),
                # Must point into the test directory. Otherwise tests that
                # save the system prompt write to the project's real file.
                "system_prompt_file": str(tmp_path / "prompts" / "system.md"),
                # Same story for the memory: a test that saves one must not
                # write into the project's real prompts folder.
                "memory_file": str(tmp_path / "prompts" / "memory.md"),
                # Same story for the agents (6.3): never the real folder.
                # The shipped layer is redirected too — a test must not
                # depend on which agents happen to ship at the time.
                "agenten_verzeichnis": str(tmp_path / "prompts" / "agenten"),
                "agenten_mitgeliefert": str(tmp_path / "agenten"),
                # And the models: startup runs modellrunner.aufraeumen() against
                # this folder, which can delete a real .modellserver.pid note
                # and kill a real running server if left pointing at the
                # installed default.
                "modelle_verzeichnis": str(tmp_path / "modelle"),
                "bildmodelle_verzeichnis": str(tmp_path / "bildmodelle"),
                # Three cleanups run at startup, not two: the embedding runner
                # (app/main.py:211-216) is built the same way and does the same
                # deletion. Measured: with this line missing, a full run
                # deleted a real .einbettungsserver.pid note.
                "einbettungsmodelle_verzeichnis": str(tmp_path / "einbettungsmodelle"),
                # Five cleanups run at startup now, and the speech folder is
                # also SORTED at startup (projectors move into vision/).
                # Measured: with this line missing, a test run reached into a
                # real speech folder and moved files around in it.
                "sprachmodelle_verzeichnis": str(tmp_path / "sprachmodelle"),
                # And the permission rules (Tor 3): a test that runs a real
                # tool call must not create/read the project's own
                # berechtigungen.json.
                "berechtigungen_datei": str(tmp_path / "berechtigungen.json"),
                # And the skills, both places. The shipped folder is
                # redirected as well: a test that reads it must not depend on
                # what happens to be shipped at the time.
                "skills_mitgeliefert": str(tmp_path / "skills"),
                "skills_verzeichnis": str(tmp_path / "prompts" / "skills"),
            },
            "database": {"backend": "sqlite", "path": str(tmp_path / "test.db")},
            # Both MCP files point into the test directory. Otherwise a
            # test that registers servers or stores credentials writes to
            # the project's real files (the paths are relative to the
            # project root!).
            "mcp": {
                "servers_file": str(tmp_path / "mcp_servers.json"),
                "auth_file": str(tmp_path / "mcp_auth.json"),
            },
            "features": {"mcp": False, "document_upload": True},
            "discovery": {"interval_seconds": 3600, "timeout_seconds": 1},
            "endpoints": [
                {
                    "id": "test",
                    "name": "Testendpunkt",
                    "provider": "mock",
                    "base_url": "http://127.0.0.1:9/v1/",
                    "reasoning_format": "think",
                },
                {
                    "id": "abwesend",
                    "name": "Nicht erreichbar",
                    "provider": "openai_compatible",
                    # Port 9 (discard) accepts no HTTP connections.
                    "base_url": "http://127.0.0.1:9/v1",
                },
            ],
        }
    )


@pytest.fixture
def client(config: Config) -> TestClient:
    from app.main import app_erstellen

    app = app_erstellen(config)
    with TestClient(app) as testclient:
        # Every /api/v1 call needs this run's own session key —
        # carried as a default header so the hundreds of existing tests
        # calling the API directly do not each have to attach it by hand.
        testclient.headers["X-Sitzungsschluessel"] = app.state.sitzungsschluessel
        yield testclient


@pytest.fixture
async def laufender_server(config: Config):
    """A real uvicorn on a free port.

    Needed for anything where the response really has to arrive in
    chunks — the ASGI test transport collects it all up front.
    """
    import asyncio
    import socket

    import uvicorn

    from app.main import app_erstellen

    lauscher = socket.socket()
    lauscher.bind(("127.0.0.1", 0))
    port = lauscher.getsockname()[1]
    lauscher.close()

    app = app_erstellen(config)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    aufgabe = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)

    try:
        yield app, f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await aufgabe


@pytest.fixture
def chat_id(client: TestClient) -> str:
    antwort = client.post("/api/v1/chats", json={"title": "Testchat"})
    assert antwort.status_code == 201
    return antwort.json()["id"]


def lokaler_endpunkt(
    client: TestClient,
    provider: MockProvider,
    endpoint_id: str | None = None,
):
    """One of the two servers this program starts ITSELF, up and answering.

    The only kind the memory travels to unasked (app/gedaechtnis.py): an entry
    from the configuration is a provider, whatever its address reads, and to a
    provider the memory goes only when somebody switched that on
    (app/config.py LOKALE_ENDPUNKTE).

    Registered the way the program registers a server it started: through the
    discovery, under the endpoint's own id, with its check — a reachable
    endpoint without a resolved window is not a state the program knows, and
    the routes assert on it (app/fenstergroesse.py). The stand-in then answers
    in its place, as ``provider_setzen`` does for the test endpoint.
    """
    import asyncio

    endpunkt_id = endpoint_id or agentenmodellwahl.HAUPTMODELL
    endpunkt = provider.endpunkt
    assert endpunkt.id == endpunkt_id, "The endpoint carries the wrong id"
    # ``local`` is what makes the difference here, and the program's own
    # builders set it the same way (app/api/v1/runner.py,
    # app/agentenserver.py): a configuration entry cannot carry it, which is
    # exactly the rule under test.
    endpunkt.group = "local"
    asyncio.run(client.app.state.discovery.anmelden(endpunkt))
    zustand = client.app.state.discovery.zustaende[endpunkt_id]
    zustand.provider = provider
    zustand.erreichbar = True
    return provider


NOT_JSON = object()
"""A body that is not JSON: ``Antwort.json`` raises, as ``httpx`` does."""


class Antwort:
    """What the picture service's routes hand back: the JSON body and the
    status code, as ``httpx`` delivers them.

    ``text`` is the raw body; left out, it is the JSON body written out the
    way the route sends it. With ``NOT_JSON`` as the body, ``json()``
    raises ``ValueError`` and only ``text`` is left to read.
    """

    def __init__(self, daten, status: int = 200, text: str | None = None):
        self._daten = daten
        self.status_code = status
        if text is None:
            text = "" if daten is NOT_JSON else json.dumps(daten, default=str)
        self.text = text

    @property
    def reason_phrase(self) -> str:
        from http import HTTPStatus

        try:
            return HTTPStatus(self.status_code).phrase
        except ValueError:
            return ""

    def json(self):
        if self._daten is NOT_JSON:
            raise ValueError("the body is not JSON")
        return self._daten


class Bilddienst:
    """The picture service as the drawing tool calls it, answered from a table.

    One stand-in for every test file that drives ``app/tools/bild_werkzeug.py``:
    a change at the route is carried over HERE once and reaches all of them.
    That is why ``families`` stands in it — the model list reports what the
    folder's headers say (``app/api/v1/bild.py``), and a stand-in that does not
    know the field answers a request the tool never made.

    What each test brings itself:
    * ``fenster`` — the picture window per chat id (``/settings/resolved/bildfenster``).
    * ``jobs`` — job id to the chat it came from (the tool asks before it draws).
    * ``familien`` — file name to family, the folder's headers.
    * ``modelle`` — the file names the folder holds.
    * ``standardmodell`` — the picture server's default model; left out, the
      first file of ``modelle`` stands chosen, and "" is none chosen.
    * ``vorgaben`` — what ``/bild/vorgaben`` answers: a dict, a callable taking
      the model name, or nothing at all (then the route says nothing).
    * ``vorgaben_status`` — the status that answer comes with, for the case of
      a route that fails.
    * ``model_list_status`` — the status the model list comes with; a failed one
      carries only a ``detail``, the way a rejected session key answers.
    * ``aufbereitung`` — what the prompt preparation (``/bild/prompt``) answers:
      a callable taking the request body; without it the request comes back
      as it went, prompt and negative unchanged. ``aufbereitung_status`` is
      the status it comes with, for a preparation that does not answer.
    * ``answers`` — route ending to a fixed ``Antwort`` that wins over the
      table: for a body the table cannot say (plain text, a list, null). An
      exception instead of an ``Antwort`` is raised, as ``httpx`` raises a
      call that got no answer (GET and POST alike).

    ``gezeichnet`` holds every body that reached the picture route and
    ``aufrufe`` every call with the address it went to — the prompt
    preparation's among them, but not in ``gezeichnet``: it draws nothing.
    """

    def __init__(
        self,
        fenster=None,
        *,
        jobs=None,
        familien=None,
        modelle=None,
        vorgaben=None,
        vorgaben_status: int = 200,
        model_list_status: int = 200,
        programm_da: bool = True,
        standardmodell: str | None = None,
        answers: dict[str, Antwort | Exception] | None = None,
        aufbereitung=None,
        aufbereitung_status: int = 200,
    ):
        self._fenster = fenster or {}
        self._jobs = jobs or {}
        self._familien = familien or {}
        self._modelle = list(modelle) if modelle is not None else ["a.safetensors", "b.safetensors"]
        self._standardmodell = (
            standardmodell if standardmodell is not None else (self._modelle or [""])[0]
        )
        self._vorgaben = vorgaben
        self._vorgaben_status = vorgaben_status
        self._model_list_status = model_list_status
        self._answers = answers or {}
        self._programm_da = programm_da
        self._aufbereitung = aufbereitung
        self._aufbereitung_status = aufbereitung_status
        self.gezeichnet: list[dict] = []
        self.aufrufe: list[tuple[str, dict]] = []
        # The pictures handed in to draw from, each as the bytes that came.
        self.handed_in: list[bytes | None] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *ausnahme):
        return False

    async def get(self, url, params=None, **_):
        fixed = self._fixed(url)
        if fixed is not None:
            return fixed
        if url.endswith("/bild/modelle"):
            if self._model_list_status >= 400:
                return Antwort({"detail": "Invalid session key."}, self._model_list_status)
            return Antwort(
                {
                    "programm_da": self._programm_da,
                    "modelle": self._modelle,
                    "families": self._familien,
                    "standardmodell": self._standardmodell,
                }
            )
        if url.endswith("/bild/vorgaben"):
            # Without ``vorgaben`` the route says nothing. A failed answer
            # (``vorgaben_status``) is not read as nothing: the tool refuses
            # to draw and hands the reason on (app/tools/bild_werkzeug.py).
            antwort = self._vorgaben
            if callable(antwort):
                antwort = antwort((params or {}).get("modell"))
            return Antwort(antwort or {}, self._vorgaben_status)
        if url.endswith("/settings/resolved/bildfenster"):
            return Antwort({"wert": self._fenster.get((params or {}).get("chat"), {})})
        if "/jobs/" in url:
            kennung = url.rsplit("/", 1)[-1]
            if kennung in self._jobs:
                return Antwort({"id": kennung, "chat_id": self._jobs[kennung]})
            return Antwort({"detail": "no such job"}, 404)
        return Antwort({})

    def _fixed(self, url):
        """The fixed answer for this address, raised when it is an exception."""
        for ending, fixed in self._answers.items():
            if url.endswith(ending):
                if isinstance(fixed, Exception):
                    raise fixed
                return fixed
        return None

    async def post(self, url, json=None, **_):
        """A FIXED seed, like the route: the answer carries the seed that was
        used, and the reply has to take it from there — not from what the
        caller asked for (the route turns -1 into a real number).

        The call is noted BEFORE a fixed answer goes back: the body reached
        the route either way, and a test that checks nothing was drawn must
        see it."""
        if url.endswith("/bild/prompt"):
            self.aufrufe.append((url, json or {}))
            fixed = self._fixed(url)
            if fixed is not None:
                return fixed
            koerper = json or {}
            if self._aufbereitung is not None:
                return Antwort(self._aufbereitung(koerper), self._aufbereitung_status)
            return Antwort(
                {"prompt": koerper.get("prompt", ""), "negativ": koerper.get("negativ", "")},
                self._aufbereitung_status,
            )
        if url.endswith("/images"):
            # A picture handed in as its content, to draw from: noted with
            # its bytes, answered with the name the service gives it.
            self.handed_in.append(_.get("content"))
            self.aufrufe.append((url, {}))
            fixed = self._fixed(url)
            return fixed if fixed is not None else Antwort({"bild": "handed-in.png"}, 201)
        self.gezeichnet.append(json)
        self.aufrufe.append((url, json or {}))
        fixed = self._fixed(url)
        if fixed is not None:
            return fixed
        # A real file name: an empty one is no picture (the tool says so).
        return Antwort({"bild": "out.png", "seed": (json or {}).get("seed", 7)})


# --- A chain of tool rounds with large results --------------------------------
#
# Shared, because more than one test file builds this chain: the tool
# shortening and the in-chat compaction both need rounds whose results carry
# weight, and a second copy of the chain would drift from the first.

# Long enough to be shortened, in a shape a test can recognize again. Every
# call gets its own number in front of it: byte-identical results are caught by
# the duplicate pass instead, which is a different thing being measured.
GROSS = "y" * 130_000
KLEIN = "3"
# What a build-up round writes itself — enough that the middle has weight of
# its own once every tool result in it has become one line.
RUNDENTEXT = "s" * 4_000
# A round that writes this much of its own, for the test about the FOLD: the
# free step clears tool RESULTS only, so a request that is still too full
# afterwards is one whose weight sits in what the rounds themselves said.
# With results capped at the house's ceiling (app/api/v1/generierung.py,
# ``WERKZEUGERGEBNIS_GRENZE``) the cleared request fits the tail comfortably
# and there is no middle left at all — this text IS that middle.
RUNDENTEXT_GROSS = "s" * 130_000

FENSTER = 100_000
UNTER_DER_SCHWELLE = 50_000
UEBER_DER_SCHWELLE = 85_000
# Close enough to the line that one round's tool result tips it over. A
# result travels cut at the house's ceiling now — the run, the row and the
# rebuild all carry the same 20,000 characters (app/api/v1/generierung.py,
# ``WERKZEUGERGEBNIS_GRENZE``), where the request used to hold the whole
# 130,000 — so what one round adds to the reading is about a SIXTH of what
# it was (measured: 4,995 against 32,503 tokens). The two chat tests about
# the CLEARING therefore need a reading close to the line for that step to
# be reached at all, and a few more rounds for it to find older results to
# clear: the tail it protects is measured in characters, and with realistic
# sizes a handful of rounds fit inside it.
KNAPP_UNTER_DER_SCHWELLE = 76_000


class GrosseWerkzeugkette(MockProvider):
    """``runden`` tool rounds with a result of the test's choosing, then one
    last answer. Every round reports the same reading, so what moves the
    trigger is only what the tools printed.

    ``anfrage.nachrichten`` is the same list for the whole answer and is
    mutated in place, so what actually went out is frozen per request.
    """

    def __init__(self, *args, runden: int = 3, stand: int = UNTER_DER_SCHWELLE,
                 rundentext: str = RUNDENTEXT, **kwargs):
        super().__init__(*args, **kwargs)
        self.runden = runden
        self.stand = stand
        self.rundentext = rundentext
        self.echte_runden = 0
        self.faltungen = 0
        # One snapshot per answer request: role and content of every message.
        self.aufzeichnung: list[list[tuple[str, str]]] = []

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        letzte = anfrage.nachrichten[-1]
        if letzte.role == "user" and (letzte.content or "").startswith(
            verdichtung.ANFRAGE_TEXT
        ):
            self.faltungen += 1
            yield Stueck("content", text="summary")
            return
        self.aufzeichnung.append(
            [(n.role, n.content or "") for n in anfrage.nachrichten]
        )
        self.echte_runden += 1
        if self.echte_runden <= self.runden:
            yield Stueck("content", text=f"step {self.echte_runden} {self.rundentext}")
            yield Stueck("stats", daten={"nutzung": {"total_tokens": self.stand}})
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"w{self.echte_runden}", name="riesig", argumente={}
                    )
                ],
            )
            return
        yield Stueck("content", text="done")
        yield Stueck("stats", daten={"nutzung": {"total_tokens": self.stand}})


class GrossesErgebnis(WerkzeugRegistry):
    """A registry whose one tool answers with a result of the size the test
    picks — the name ``GrosseWerkzeugkette`` calls every round.

    That one name is the whole table: a round that reached for another would
    be a request this stand-in never promised to answer.
    """

    def __init__(self, gross: str) -> None:
        super().__init__([])
        # ``None`` stands in the client slot: this table answers without a
        # connection behind it — there is no server to talk to.
        self._werkzeuge = cast(
            Any,
            {"riesig": (None, MCPWerkzeug(name="riesig", beschreibung="a large result"), False)},
        )
        self.aufrufe: list[tuple[str, dict]] = []
        self.gross = gross

    async def ausfuehren(
        self, name, argumente, bild_senke=None, ordner=None, chat_id=None,
        herkunft="chat", agent=None, shell_zeitgrenze=None,
    ):
        if name not in self._werkzeuge:
            raise AssertionError("the filter failed")
        self.aufrufe.append((name, argumente))
        return f"result {len(self.aufrufe)} {self.gross}"


def senden(client, chat_id: str, **felder) -> list[dict]:
    """One message through the chat route, and the events it answered with."""
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Question", **felder},
    )
    assert antwort.status_code == 200
    return [
        json.loads(zeile[5:].strip())
        for zeile in antwort.text.splitlines()
        if zeile.startswith("data:")
    ]


def chatkette(mcp_client, *, runden: int, stand: int, ergebnis: str,
              rundentext: str = RUNDENTEXT):
    """The tool-enabled client, put behind a chain of ``runden`` tool rounds
    whose result is ``ergebnis`` — and the chain itself, for its record."""
    registry = GrossesErgebnis(gross=ergebnis)
    mcp_client.app.state.werkzeuge = registry
    provider = provider_setzen(
        mcp_client,
        GrosseWerkzeugkette(
            mock_endpunkt("test"), runden=runden, stand=stand, rundentext=rundentext
        ),
    )
    mcp_client.app.state.discovery.zustaende["test"].context_tokens = FENSTER
    return provider


def provider_setzen(client: TestClient, provider: MockProvider, endpoint_id: str = "test"):
    """Swaps out the dummy behind an endpoint, reports it as reachable, and
    points the one field at it.

    The third part is new and is what makes this "the model this test runs
    on" rather than merely "an endpoint that answers". Agent and cron runs
    resolve their model through that field now
    (app/api/v1/auftraege.py) — before, they read it off each agent
    file's ``model:`` head, which is why nearly every agent written in these
    tests carried one. That key is retired; the field replaces it, and
    pointing it here keeps the setup in ONE place instead of in every agent
    file the tests write.

    Not done by making the test endpoint tool-capable instead: it is
    deliberately not, so that the runs which must not be handed tools stay
    testable (tests/test_werkzeuge.py).

    A test that wants the field EMPTY — "nothing chosen", the state every
    fresh installation is in — writes that setting itself; see
    ``agentenmodell_leer``.
    """
    zustand = client.app.state.discovery.zustaende[endpoint_id]
    zustand.provider = provider
    zustand.erreichbar = True
    agentenmodell_setzen(client, endpoint_id)
    return provider


def agentenmodell_setzen(client: TestClient, wert: str, sorte: str = "kennung") -> None:
    """The one field (app/agentenmodellwahl.py), pointed somewhere."""
    client.app.state.repositories.einstellungen.setzen(
        "global", agentenmodellwahl.SCHLUESSEL,
        {"sorte": sorte, "wert": wert},
    )


def agentenmodell_leer(client: TestClient) -> None:
    """The field with nothing chosen — the state every fresh installation
    starts in. A run then takes the MAIN model (`agentenmodellwahl.HAUPTMODELL`,
    app/api/v1/auftraege.py), and if that server is not up, the next reachable
    LOCAL one. It used to be the first reachable endpoint, and
    first was the order of a list, not a decision."""
    client.app.state.repositories.einstellungen.setzen(
        "global", agentenmodellwahl.SCHLUESSEL, {"sorte": "", "wert": ""},
    )


def pdf_mit_seiten(texte: list[str]) -> bytes:
    """A real PDF with a text layer, one page per entry.

    pypdf reads PDFs and does not write text into them. write_file does
    write them, with reportlab, but a fixture that leans on the code under
    test proves nothing — so the way to test page-wise reading
    (app/pdfseiten.py, read_file) against a genuine file is to assemble the
    smallest valid one here: catalogue, page tree, one content stream per
    page, one font, and a correct cross-reference table, which pypdf insists
    on. Latin-1 because that is what a PDF's own syntax is written in.
    """
    seiten_ids = [3 + 2 * i for i in range(len(texte))]
    schrift_id = 3 + 2 * len(texte)
    objekte = {1: "<< /Type /Catalog /Pages 2 0 R >>"}
    kinder = " ".join(f"{i} 0 R" for i in seiten_ids)
    objekte[2] = f"<< /Type /Pages /Kids [{kinder}] /Count {len(texte)} >>"
    for kennung, text in zip(seiten_ids, texte, strict=True):
        inhalt = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET\n"
        objekte[kennung] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            f"/Resources << /Font << /F1 {schrift_id} 0 R >> >> "
            f"/Contents {kennung + 1} 0 R >>"
        )
        objekte[kennung + 1] = f"<< /Length {len(inhalt)} >>\nstream\n{inhalt}endstream"
    objekte[schrift_id] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    teile = [b"%PDF-1.4\n"]
    stellen: dict[int, int] = {}
    stand = len(teile[0])
    for nummer in sorted(objekte):
        block = f"{nummer} 0 obj\n{objekte[nummer]}\nendobj\n".encode("latin-1")
        stellen[nummer] = stand
        teile.append(block)
        stand += len(block)
    xref_stelle = stand
    zeilen = [f"xref\n0 {schrift_id + 1}\n", "0000000000 65535 f \n"]
    zeilen += [f"{stellen[nummer]:010d} 00000 n \n" for nummer in range(1, schrift_id + 1)]
    teile.append("".join(zeilen).encode("latin-1"))
    teile.append(
        f"trailer\n<< /Size {schrift_id + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_stelle}\n%%EOF\n".encode("latin-1")
    )
    return b"".join(teile)


def png_bytes() -> bytes:
    """The smallest valid PNG — one opaque pixel.

    Enough for every question the image path asks: is it read as an image at
    all, does it reach the model as a data URL, does a model without vision
    get a plain sentence instead. What the pixel looks like matters to
    nobody here.
    """
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
        "DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
    )


def jpeg_mit_exif(geheimnis: bytes) -> bytes:
    """The smallest JPEG that carries a comment segment, holding ``geheimnis``.

    A real photo's EXIF is a stream of tags; what every scrubber has to do
    with it is the same as with a COM segment — drop it. So the test uses the
    segment that is trivial to build and trivial to look for afterwards, and
    asks the one question that matters: does what was in the file still travel?
    """
    marke = b"\xff\xd8"                                  # SOI
    kommentar = b"\xff\xfe" + (len(geheimnis) + 2).to_bytes(2, "big") + geheimnis
    # A 1x1 grey frame: SOF0, no scan data. Nothing decodes it, and nothing
    # here needs to — the bytes only have to be recognisably a JPEG.
    rahmen = b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    return marke + kommentar + rahmen + b"\xff\xd9"      # EOI


# --- Helpers for tests that leave the process --------------------------------


def node_script(script: str, *, cwd: Path | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    """Runs ``script`` in node and hands back the completed process, output
    decoded as UTF-8.

    Through a file, not ``node -e``: a test script carries whole modules of
    the frontend, and a command line of that length is refused on Windows
    (``WinError 206``). Node writes UTF-8 whatever the console's code page
    is, so the output is read as that and never as the system's own. The
    file lies in a folder of its own, so the script has to carry everything
    it needs: an import from the frontend's ``node_modules`` is not found
    from there."""
    with tempfile.TemporaryDirectory(prefix="node-") as folder:
        file = Path(folder) / "pruefung.mjs"
        file.write_text(script, encoding="utf-8")
        return subprocess.run(
            ["node", str(file)],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )


def fake_server(path: Path, *, says: Sequence[str] = (), seconds: int = 30) -> Path:
    """A stand-in for a server binary: prints ``says`` and stays for
    ``seconds``. Returns the path that exists — on Windows a batch file,
    because a shell script cannot be started there at all (``WinError 193``),
    and on a POSIX system the shell script with its execute bit set."""
    # A line goes into an unquoted `echo` on both systems: no character
    # either shell would read as syntax.
    assert not any(set(line) & set("&|<>%'\"^$`") for line in says), says
    if sys.platform == "win32":
        file = path.with_suffix(".bat")
        lines = ["@echo off"] + [f"echo {line}" for line in says]
        # `ping` is the one sleep every Windows has; `timeout` wants a console.
        lines.append(f"ping -n {seconds + 1} 127.0.0.1 >nul")
        file.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
        return file
    lines = ["#!/bin/sh"] + [f"echo '{line}'" for line in says] + [f"sleep {seconds}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def llama_server_name() -> str:
    """The file name of the model server on this system, as the program
    looks for it (app/serverdownload.py, ``gefundener_server``): Windows
    adds ``.exe``. The program keeps that line inside the finder, so a test
    that lays the binary down says the name the same way here."""
    return "llama-server.exe" if sys.platform == "win32" else "llama-server"


def python_command(code: str) -> str:
    """``code`` as a one-line command for the shell tool — the same on every
    system, where ``ls`` or ``sleep`` is not. The interpreter by its name,
    not by ``sys.executable``: the tool's guard reads a full path in a
    command as a reach outside the shared folder and asks first. ``python3``
    on a POSIX system, ``python`` on Windows, the name its installer puts on
    the PATH. The code must not contain a double quote."""
    assert '"' not in code, "the code must do without double quotes"
    name = "python" if sys.platform == "win32" else "python3"
    return f'{name} -c "{code}"'


def cwd_command() -> str:
    """The command that prints the working folder through the shell tool on
    this system: ``cd`` on Windows, where cmd.exe prints its folder when
    given no argument and ``pwd`` is not its own (a ``pwd.exe`` from a Git
    install on the PATH answers in POSIX spelling, ``/tmp/…`` for the temp
    folder — measured); ``pwd`` everywhere else."""
    return "cd" if sys.platform == "win32" else "pwd"


def process_alive(pid: int) -> bool:
    """Whether a process of this id is still running.

    Signal 0 asks a POSIX system without sending anything; a process that
    exists but is not ours answers with a permission error, which is still
    "there". On Windows ``os.kill`` with any signal ENDS the process (it is
    ``TerminateProcess`` underneath), so the question goes to a handle on
    it instead: waiting on that handle for no time at all says whether the
    process has ended."""
    if sys.platform == "win32":
        import ctypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        kernel32 = ctypes.windll.kernel32
        # A HANDLE is pointer-sized; left undeclared, ctypes would hand it
        # back as a C int.
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def script_file(folder: Path, name: str, code: str) -> Path:
    """A startable script for a cron entry: a Python file that every system
    can start — on Windows through the interpreter the program names
    (``app/skriptlauf.py``), on a POSIX system by itself, so it gets the
    shebang line and the execute bit there. ``name`` ends in ``.py``."""
    assert name.endswith(".py"), name
    path = folder / name
    path.write_text("#!/usr/bin/env python3\n" + code, encoding="utf-8")
    path.chmod(0o755)
    return path


async def wakes_settled(timeout: float = 5.0) -> None:
    """Waits until every wake a finished job filed has run its course.

    A job sent off from a chat wakes that chat when it ends
    (``app/hintergrundwecken.py``); the wake is a task on the loop the test
    runs on. The test client's shutdown gathers what is still open — from
    its own loop, which is another one — and a task that is still pending
    there is a ``RuntimeError`` at teardown ("attached to a different loop").
    Measured on Windows, where the wake is slower to run than the test is
    to return. So a test that sent a job off from a chat waits here before
    it ends."""
    from app import hintergrundwecken

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = [task for task in hintergrundwecken._aufgaben if not task.done()]
        if not pending:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"a wake is still running after {timeout} s: {pending}")
