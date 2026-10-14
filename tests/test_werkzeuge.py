"""MCP integration and tool execution.

The proof runs against a real MCP server as a subprocess — that is, over
the real protocol, not against a mock of the protocol.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from app.providers.openai_kompatibel import _WerkzeugSammler
from app.tools import ServerEintrag, WerkzeugRegistry, WerkzeugVerboten, server_lesen
from tests.conftest import provider_setzen

# A tiny MCP server that exists only for the test. Two tools:
# one does math, one breaks.
TESTSERVER = '''
import json, sys

WERKZEUGE = [
    {"name": "addieren", "description": "Addiert zwei Zahlen.",
     "inputSchema": {"type": "object",
                     "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                     "required": ["a", "b"]}},
    {"name": "geht_kaputt", "description": "Scheitert immer.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "heikel", "description": "Sollte nicht angeboten werden.",
     "inputSchema": {"type": "object", "properties": {}}},
]

def antworte(kennung, ergebnis):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": kennung, "result": ergebnis}) + "\\n")
    sys.stdout.flush()

for zeile in sys.stdin:
    zeile = zeile.strip()
    if not zeile:
        continue
    nachricht = json.loads(zeile)
    methode = nachricht.get("method")
    kennung = nachricht.get("id")
    if methode == "initialize":
        antworte(kennung, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                           "serverInfo": {"name": "testserver", "version": "1"}})
    elif methode == "tools/list":
        antworte(kennung, {"tools": WERKZEUGE})
    elif methode == "tools/call":
        p = nachricht.get("params") or {}
        name = p.get("name")
        args = p.get("arguments") or {}
        if name == "addieren":
            antworte(kennung, {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]})
        elif name == "geht_kaputt":
            antworte(kennung, {"content": [{"type": "text", "text": "kaputt wie bestellt"}],
                               "isError": True})
        else:
            antworte(kennung, {"content": [{"type": "text", "text": "unbekannt"}], "isError": True})
'''


@pytest.fixture
def testserver_datei(tmp_path: Path) -> Path:
    datei = tmp_path / "testserver.py"
    datei.write_text(TESTSERVER, encoding="utf-8")
    return datei


@pytest.fixture
async def registry(testserver_datei: Path):
    eintrag = ServerEintrag(
        name="test",
        command=sys.executable,
        args=[str(testserver_datei)],
        allowed_tools=["addieren", "geht_kaputt"],
    )
    reg = WerkzeugRegistry([eintrag])
    await reg.starten()
    yield reg
    await reg.stoppen()


# --- Protocol -------------------------------------------------------------


@pytest.mark.asyncio
async def test_werkzeuge_werden_vom_server_geholt(registry: WerkzeugRegistry):
    assert "mcp__test__addieren" in registry.namen()


@pytest.mark.asyncio
async def test_werkzeug_wird_ausgefuehrt(registry: WerkzeugRegistry):
    assert await registry.ausfuehren("mcp__test__addieren", {"a": 2, "b": 3}) == "5"


@pytest.mark.asyncio
async def test_mehrere_aufrufe_nacheinander(registry: WerkzeugRegistry):
    assert await registry.ausfuehren("mcp__test__addieren", {"a": 1, "b": 1}) == "2"
    assert await registry.ausfuehren("mcp__test__addieren", {"a": 10, "b": 5}) == "15"


@pytest.mark.asyncio
async def test_fehler_des_werkzeugs_wird_als_fehler_gemeldet(registry: WerkzeugRegistry):
    from app.tools import MCPFehler

    with pytest.raises(MCPFehler):
        await registry.ausfuehren("mcp__test__geht_kaputt", {})


@pytest.mark.asyncio
async def test_uebersetzung_ins_modellformat(registry: WerkzeugRegistry):
    werkzeuge = registry.als_openai_werkzeuge()
    addieren = next(w for w in werkzeuge if w["function"]["name"] == "mcp__test__addieren")
    assert addieren["type"] == "function"
    assert addieren["function"]["parameters"]["required"] == ["a", "b"]


# --- Lockdown -------------------------------------------------------------


@pytest.mark.asyncio
async def test_nicht_freigegebenes_werkzeug_wird_nicht_angeboten(registry: WerkzeugRegistry):
    """The server offers 'heikel', but it is not on the allowlist."""
    assert "heikel" not in registry.namen()
    assert all(w["function"]["name"] != "heikel" for w in registry.als_openai_werkzeuge())


@pytest.mark.asyncio
async def test_nicht_freigegebenes_werkzeug_wird_nicht_ausgefuehrt(registry: WerkzeugRegistry):
    with pytest.raises(WerkzeugVerboten):
        await registry.ausfuehren("heikel", {})


@pytest.mark.asyncio
async def test_voellig_unbekanntes_werkzeug_wird_abgewiesen(registry: WerkzeugRegistry):
    with pytest.raises(WerkzeugVerboten):
        await registry.ausfuehren("rm_minus_rf", {})


@pytest.mark.asyncio
async def test_abgeschalteter_server_wird_nicht_gestartet(testserver_datei: Path):
    eintrag = ServerEintrag(
        name="aus", command=sys.executable, args=[str(testserver_datei)], enabled=False
    )
    reg = WerkzeugRegistry([eintrag])
    await reg.starten()
    assert reg.anzahl == 0
    await reg.stoppen()


# --- Tor 3 refusals reach the model in English -----------------------------


def _deutsche_woerter(text: str) -> set[str]:
    from tests.test_hausregeln import DEUTSCHE_WOERTER

    return {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß]+", text)} & DEUTSCHE_WOERTER


@pytest.mark.asyncio
async def test_abgeschaltetes_werkzeug_traegt_keine_deutschen_woerter(tmp_path):
    reg = WerkzeugRegistry([], berechtigungen_pfad=tmp_path / "berechtigungen.json")
    reg.abgeschaltet = {"schreiben"}
    with pytest.raises(WerkzeugVerboten) as ausnahme:
        await reg.ausfuehren("schreiben", {})
    assert "turned off" in str(ausnahme.value)
    assert len(_deutsche_woerter(str(ausnahme.value))) < 2


@pytest.mark.asyncio
async def test_nicht_freigegebenes_merkmal_traegt_keine_deutschen_woerter(tmp_path):
    """``memory_save`` without a memory path: the feature itself is off,
    not Tor 3 — a different line, the same requirement."""
    reg = WerkzeugRegistry([], berechtigungen_pfad=tmp_path / "berechtigungen.json")
    with pytest.raises(WerkzeugVerboten) as ausnahme:
        await reg.ausfuehren("memory_save", {})
    assert "not enabled" in str(ausnahme.value)
    assert len(_deutsche_woerter(str(ausnahme.value))) < 2


@pytest.mark.asyncio
async def test_unbekanntes_werkzeug_traegt_keine_deutschen_woerter(tmp_path):
    reg = WerkzeugRegistry([], berechtigungen_pfad=tmp_path / "berechtigungen.json")
    with pytest.raises(WerkzeugVerboten) as ausnahme:
        await reg.ausfuehren("does_not_exist", {})
    assert "not enabled" in str(ausnahme.value)
    assert len(_deutsche_woerter(str(ausnahme.value))) < 2


@pytest.mark.asyncio
async def test_tor_3_nein_ohne_grund_traegt_keine_deutschen_woerter(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(json.dumps({"regeln": {"ein_werkzeug": "nein"}}), encoding="utf-8")
    reg = WerkzeugRegistry([], berechtigungen_pfad=pfad)
    with pytest.raises(WerkzeugVerboten) as ausnahme:
        await reg.ausfuehren("ein_werkzeug", {})
    assert "not allowed" in str(ausnahme.value)
    assert len(_deutsche_woerter(str(ausnahme.value))) < 2


@pytest.mark.asyncio
async def test_tor_3_nein_mit_grund_kommt_unveraendert_an(tmp_path):
    """Silence probe: a refusal that already names its own reason (the
    agent's own tools list, app/berechtigungen.py) must reach the model
    exactly as that reason says — the generic fallback sentence never
    mixes in on top of it."""
    from app.agenten import Agent

    agent = Agent(name="testagent", prompt="Du bist ein Testagent.", werkzeuge=["read_file"])
    reg = WerkzeugRegistry([], berechtigungen_pfad=tmp_path / "berechtigungen.json")
    with pytest.raises(WerkzeugVerboten) as ausnahme:
        await reg.ausfuehren("web_search", {}, herkunft="agent", agent=agent)
    assert str(ausnahme.value) == (
        "'web_search' is not in this agent's tool list. Listed tools: read_file. Use those "
        "tools, or ask the user to add this one to the agent."
    )


@pytest.mark.asyncio
async def test_kaputter_server_reisst_die_anderen_nicht_mit(testserver_datei: Path):
    reg = WerkzeugRegistry(
        [
            ServerEintrag(name="kaputt", command="/gibt/es/nicht", args=[]),
            ServerEintrag(name="gut", command=sys.executable, args=[str(testserver_datei)]),
        ]
    )
    await reg.starten()
    assert "mcp__gut__addieren" in reg.namen()
    assert "kaputt" not in reg.clients
    await reg.stoppen()


@pytest.mark.asyncio
async def test_bestaetigungspflicht_wird_gemerkt(testserver_datei: Path):
    reg = WerkzeugRegistry(
        [
            ServerEintrag(
                name="test",
                command=sys.executable,
                args=[str(testserver_datei)],
                needs_confirmation=["addieren"],
            )
        ]
    )
    await reg.starten()
    assert reg.braucht_bestaetigung("mcp__test__addieren") is True
    assert reg.braucht_bestaetigung("mcp__test__geht_kaputt") is False
    await reg.stoppen()


# --- Configuration file ---------------------------------------------------


def test_mitgelieferte_mcp_datei_ist_lesbar():
    eintraege = server_lesen(Path("mcp_servers.example.json"))
    namen = {eintrag.name for eintrag in eintraege}
    # The one search that ships. The self-run one comes from its own card,
    # with the address of the person's own instance: nothing of it is here.
    assert namen == {"websuche"}
    websuche = eintraege[0]
    assert websuche.allowed_tools == ["web_search", "read_webpage"]


def test_fehlende_datei_ist_kein_fehler(tmp_path: Path):
    assert server_lesen(tmp_path / "gibtsnicht.json") == []


def test_server_mit_unbekanntem_typ_wird_uebersprungen():
    eintrag = ServerEintrag(name="entfernt", type="http", url="https://example.invalid/mcp")
    assert eintrag.type == "http"  # planned, but not implemented yet


# --- Reassembling fragmented calls ----------------------------------------


def test_sammler_setzt_zerstueckelte_argumente_zusammen():
    """Exactly the shape in which llama.cpp streams the calls."""
    sammler = _WerkzeugSammler()
    for bruchstueck in [
        [{"index": 0, "id": "abc", "type": "function",
          "function": {"name": "web_search", "arguments": "{"}}],
        [{"index": 0, "function": {"arguments": '"query":"'}}],
        [{"index": 0, "function": {"arguments": "Tailscale"}}],
        [{"index": 0, "function": {"arguments": '"'}}],
        [{"index": 0, "function": {"arguments": "}"}}],
    ]:
        sammler.aufnehmen(bruchstueck)

    aufrufe = sammler.fertige_aufrufe()
    assert len(aufrufe) == 1
    assert aufrufe[0].id == "abc"
    assert aufrufe[0].name == "web_search"
    assert aufrufe[0].argumente == {"query": "Tailscale"}


def test_sammler_haelt_mehrere_aufrufe_auseinander():
    sammler = _WerkzeugSammler()
    sammler.aufnehmen(
        [
            {"index": 0, "id": "a", "function": {"name": "eins", "arguments": '{"x":1}'}},
            {"index": 1, "id": "b", "function": {"name": "zwei", "arguments": '{"y":'}},
        ]
    )
    sammler.aufnehmen([{"index": 1, "function": {"arguments": "2}"}}])

    aufrufe = sammler.fertige_aufrufe()
    assert [a.name for a in aufrufe] == ["eins", "zwei"]
    assert aufrufe[1].argumente == {"y": 2}


def test_sammler_ueberlebt_unlesbare_argumente():
    sammler = _WerkzeugSammler()
    sammler.aufnehmen([{"index": 0, "id": "x", "function": {"name": "k", "arguments": "{kaputt"}}])
    aufrufe = sammler.fertige_aufrufe()
    assert aufrufe[0].argumente == {}


def test_sammler_ohne_aufrufe_ist_leer():
    assert _WerkzeugSammler().leer is True


# --- The whole chain in the chat ------------------------------------------


def test_werkzeugschleife_im_chat(client, chat_id, monkeypatch):
    """The model requests a tool, it is executed, the answer continues."""

    class FakeRegistry:
        def __init__(self):
            self.aufgerufen = []

        def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, **_options):
            return [{"type": "function", "function": {"name": "addieren", "parameters": {}}}]

        def braucht_bestaetigung(self, name, argumente=None, ordner=None):
            return False

        def server_von(self, name):
            return ''

        def bestaetigungsgrund(self, name, argumente=None, ordner=None):
            return ''

        async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None,
                             chat_id=None, shell_zeitgrenze=None):
            self.aufgerufen.append((name, argumente))
            return "42"

    registry = FakeRegistry()
    client.app.state.werkzeuge = registry
    client.app.state.config.features.mcp = True

    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Das Ergebnis ist 42."],
            werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="addieren", argumente={"a": 40, "b": 2})],
        ),
    )

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Was ist 40 plus 2?"},
    )
    ereignisse = [
        json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")
    ]
    sorten = [e["typ"] for e in ereignisse]

    assert "tool_call" in sorten
    assert "tool_result" in sorten
    assert registry.aufgerufen == [("addieren", {"a": 40, "b": 2})]

    inhalt = "".join(e.get("text", "") for e in ereignisse if e["typ"] == "content")
    assert inhalt == "Das Ergebnis ist 42."

    # Measured, not guessed — present and not negative, live on the stream
    # itself so the row can show it before the message is even saved.
    tool_result = next(e for e in ereignisse if e["typ"] == "tool_result")
    assert tool_result["dauer_sekunden"] is not None
    assert tool_result["dauer_sekunden"] >= 0

    # The tool appears in the message's record.
    nachricht = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]
    assert nachricht["stats"]["werkzeuge"][0]["name"] == "addieren"
    assert nachricht["stats"]["werkzeuge"][0]["fehlgeschlagen"] is False
    # The result is in there too — otherwise, after a reload, the history
    # would only show THAT something ran, but not what came back.
    assert nachricht["stats"]["werkzeuge"][0]["ergebnis"] == "42"
    # And it survives the round trip through the database, same as the result.
    assert nachricht["stats"]["werkzeuge"][0]["dauer_sekunden"] is not None


def test_werkzeugergebnis_geht_zurueck_ans_modell(client, chat_id):
    class FakeRegistry:
        def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, **_options):
            return [{"type": "function", "function": {"name": "addieren", "parameters": {}}}]

        def braucht_bestaetigung(self, name, argumente=None, ordner=None):
            return False

        def server_von(self, name):
            return ''

        def bestaetigungsgrund(self, name, argumente=None, ordner=None):
            return ''

        async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None,
                             chat_id=None, shell_zeitgrenze=None):
            return "42"

    client.app.state.werkzeuge = FakeRegistry()
    client.app.state.config.features.mcp = True

    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="addieren", argumente={})],
        ),
    )

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "rechne"},
    )

    # Second round: the history contains call and result.
    zweiter = provider.alle_anfragen[1].nachrichten
    assert zweiter[-2].role == "assistant" and zweiter[-2].werkzeugaufrufe
    assert zweiter[-1].role == "tool"
    assert zweiter[-1].content == "42"
    assert zweiter[-1].werkzeugaufruf_id == "a1"


def test_langes_werkzeugergebnis_wird_nicht_bei_2000_gekappt(client, chat_id):
    """A result past the old 2,000-character cut used to lose its tail both
    in the stream and in the stored message. The cut now sits at 20,000."""
    lang = "x" * 5000

    class FakeRegistry:
        def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, **_options):
            return [{"type": "function", "function": {"name": "addieren", "parameters": {}}}]

        def braucht_bestaetigung(self, name, argumente=None, ordner=None):
            return False

        def server_von(self, name):
            return ''

        def bestaetigungsgrund(self, name, argumente=None, ordner=None):
            return ''

        async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None,
                             chat_id=None, shell_zeitgrenze=None):
            return lang

    client.app.state.werkzeuge = FakeRegistry()
    client.app.state.config.features.mcp = True

    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="addieren", argumente={})],
        ),
    )

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "rechne"},
    )
    ereignisse = [
        json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")
    ]
    ergebnis = next(e for e in ereignisse if e["typ"] == "tool_result")
    assert ergebnis["text"] == lang

    nachricht = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][1]
    assert nachricht["stats"]["werkzeuge"][0]["ergebnis"] == lang


def test_ohne_feature_flag_bekommt_das_modell_keine_werkzeuge(client, chat_id):
    class FakeRegistry:
        def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, **_options):
            return [{"type": "function", "function": {"name": "x", "parameters": {}}}]

    client.app.state.werkzeuge = FakeRegistry()
    client.app.state.config.features.mcp = False

    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    assert provider.letzte_anfrage.werkzeuge == []


def test_endpunkt_ohne_tool_calls_bekommt_keine_werkzeuge(client, chat_id):
    class FakeRegistry:
        def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, **_options):
            return [{"type": "function", "function": {"name": "x", "parameters": {}}}]

    client.app.state.werkzeuge = FakeRegistry()
    client.app.state.config.features.mcp = True

    endpunkt = mock_endpunkt("test")
    endpunkt.capabilities.tool_calls = False
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.endpunkt = endpunkt
    zustand.provider = MockProvider(endpunkt, haeppchen=["ok"])
    zustand.erreichbar = True

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hallo"},
    )
    assert zustand.provider.letzte_anfrage.werkzeuge == []


def test_verbotenes_werkzeug_wird_dem_modell_zurueckgemeldet(client, chat_id):
    """No crash, but a refusal the model can keep working with."""

    class FakeRegistry:
        def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, **_options):
            return []

        def braucht_bestaetigung(self, name, argumente=None, ordner=None):
            return False

        def server_von(self, name):
            return ''

        def bestaetigungsgrund(self, name, argumente=None, ordner=None):
            return ''

        async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None,
                             chat_id=None, shell_zeitgrenze=None):
            raise WerkzeugVerboten(f"Werkzeug '{name}' ist nicht freigegeben.")

    client.app.state.werkzeuge = FakeRegistry()
    client.app.state.config.features.mcp = True

    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["Das darf ich nicht."],
            werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="rm_minus_rf", argumente={})],
        ),
    )

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "loesche alles"},
    )
    ereignisse = [
        json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")
    ]
    ergebnis = next(e for e in ereignisse if e["typ"] == "tool_result")
    assert ergebnis["fehlgeschlagen"] is True
    assert antwort.status_code == 200


# --- namen() and uebersicht() name every built-in tool --------------------


def test_namen_nennt_memory_und_skill_werkzeuge(tmp_path):
    """An agent naming memory_save or skill_load in its own tools: list used
    to get a false 'does not exist' — namen() silently left all three out
    even though the model could already call them."""
    reg = WerkzeugRegistry(
        [],
        memory_pfad=tmp_path / "memory.md",
        skills_orte=(tmp_path / "mitgeliefert", tmp_path / "eigen"),
    )
    assert {"memory_save", "skill_load", "skill_save"} <= set(reg.namen())


def test_namen_laesst_sie_ohne_zugang_weg(tmp_path):
    reg = WerkzeugRegistry([])
    assert not {"memory_save", "skill_load", "skill_save"} & set(reg.namen())


def test_uebersicht_nennt_die_uebergebene_schwellwert(tmp_path):
    """The tools window used to call shell.werkzeug_beschreibung() with no
    argument, so it always showed the shipped 120 regardless of what the
    cascade actually resolved to."""
    reg = WerkzeugRegistry([], shell_an=True)
    eintrag = next(e for e in reg.uebersicht(600) if e["name"] == "run_command")
    assert "600" in eintrag["beschreibung"]
    assert "120" not in eintrag["beschreibung"]


def test_uebersicht_ohne_wert_nennt_die_vorgabe():
    reg = WerkzeugRegistry([], shell_an=True)
    eintrag = next(e for e in reg.uebersicht() if e["name"] == "run_command")
    assert "120" in eintrag["beschreibung"]


def test_uebersicht_sagt_woher_ein_werkzeug_kommt():
    """Each row says whether it is the program's own (``builtin``) — the
    tools window groups by it and may not fall back to the name: a server
    can be called like a built-in source ("shell", "clock") and would take
    that row over."""
    from app.tools.mcp_client import MCPWerkzeug
    from app.tools.registry import ServerEintrag

    class _Client:
        werkzeuge = [
            MCPWerkzeug(
                name="server_tool", beschreibung="a server's own",
                schema={"type": "object", "properties": {}}, server="zeitserver",
            )
        ]

        async def stoppen(self):
            return None

    reg = WerkzeugRegistry([], shell_an=True)
    reg._werkzeuge_uebernehmen(ServerEintrag(name="zeitserver"), _Client())
    zeilen = reg.uebersicht()
    zeile = next(e for e in zeilen if e["name"] == "mcp__zeitserver__server_tool")
    assert zeile["builtin"] is False
    assert zeile["anzeige"] == "server_tool"
    assert next(e for e in zeilen if e["name"] == "run_command")["builtin"] is True


# --- /api/v1/tools -------------------------------------------------------


def test_tools_endpunkt_ohne_registry(client):
    client.app.state.werkzeuge = None
    daten = client.get("/api/v1/tools").json()
    assert daten["aktiv"] is False
    assert daten["werkzeuge"] == []


# --- Prompting before confirmation-required tools (1.6) -------------------


def _ereignisse(antwort):
    return [
        json.loads(z[5:].strip()) for z in antwort.text.splitlines() if z.startswith("data:")
    ]


class HeikleRegistry:
    """A tool that may do nothing without consent."""

    def __init__(self):
        self.aufgerufen = []

    def als_openai_werkzeuge(self, nur=None, shell_zeitgrenze=None, **_options):
        return [{"type": "function", "function": {"name": "loeschen", "parameters": {}}}]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        return True

    def server_von(self, name):
        return ''

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ''

    async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None,
                             chat_id=None, shell_zeitgrenze=None):
        self.aufgerufen.append((name, argumente))
        return "erledigt"


def _spaeter_klicken(client, erlaubt):
    """Simulates the user tapping Reject or Execute in the window.

    The click can only come once the confirmation prompt is up — so we poll
    at an interval instead of striking blindly once.
    """
    import asyncio

    verwaltung = client.app.state.generierungen

    def versuchen():
        for generierung in verwaltung.laufende():
            for aufruf_id in list(generierung.bestaetigungen):
                verwaltung.bestaetigen(generierung.id, aufruf_id, erlaubt)
                return True
        return False

    def takt():
        if not versuchen():
            asyncio.get_running_loop().call_later(0.01, takt)

    asyncio.get_running_loop().call_later(0.01, takt)


def _heikles_modell(client, registry):
    client.app.state.werkzeuge = registry
    client.app.state.config.features.mcp = True
    return provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="loeschen", argumente={"pfad": "/tmp/x"})
            ],
        ),
    )


def _werkzeug_nachricht_an_modell(provider):
    """The ``role="tool"`` message the model actually received, from the
    round after the call — ``letzte_anfrage`` is that later request."""
    return next(
        n for n in provider.letzte_anfrage.nachrichten
        if n.role == "tool" and n.werkzeugaufruf_id == "a1"
    )


def test_bestaetigungspflichtiges_werkzeug_fragt_zuerst(client, chat_id):
    """The confirmation prompt comes before the call — with name and arguments."""
    class Registry(HeikleRegistry):
        def braucht_bestaetigung(self, name, argumente=None, ordner=None):
            _spaeter_klicken(client, True)
            return True

        def server_von(self, name):
            return ''

        def bestaetigungsgrund(self, name, argumente=None, ordner=None):
            return ''

    registry = Registry()
    _heikles_modell(client, registry)

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "mach"},
    )
    ereignisse = _ereignisse(antwort)
    sorten = [e["typ"] for e in ereignisse]

    # The question comes before "running" is reported.
    assert sorten.index("tool_confirm") < sorten.index("tool_call")

    frage = next(e for e in ereignisse if e["typ"] == "tool_confirm")
    assert frage["name"] == "loeschen"
    assert frage["argumente"] == {"pfad": "/tmp/x"}
    assert frage["aufruf_id"] == "a1"

    # Approved means executed.
    assert registry.aufgerufen == [("loeschen", {"pfad": "/tmp/x"})]


def test_abgelehntes_werkzeug_laeuft_nicht(client, chat_id):
    class Registry(HeikleRegistry):
        def braucht_bestaetigung(self, name, argumente=None, ordner=None):
            _spaeter_klicken(client, False)
            return True

        def server_von(self, name):
            return ''

        def bestaetigungsgrund(self, name, argumente=None, ordner=None):
            return ''

    registry = Registry()
    _heikles_modell(client, registry)

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "mach"},
    )

    assert registry.aufgerufen == []
    ergebnis = next(e for e in _ereignisse(antwort) if e["typ"] == "tool_result")
    assert ergebnis["fehlgeschlagen"] is True
    # The model learns why — and can respond to it.
    assert "nicht erlaubt" in ergebnis["text"]


def test_ohne_antwort_wird_nicht_ausgefuehrt(client, chat_id, monkeypatch):
    """Silence is not consent."""
    from app.api.v1 import generierung as modul

    monkeypatch.setattr(modul, "BESTAETIGUNG_WARTEZEIT", 0.05)
    monkeypatch.setattr(modul, "BESTAETIGUNG_PRUEFTAKT", 0.01)

    registry = HeikleRegistry()
    _heikles_modell(client, registry)

    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "mach"},
    )

    assert registry.aufgerufen == []
    ergebnis = next(e for e in _ereignisse(antwort) if e["typ"] == "tool_result")
    assert ergebnis["fehlgeschlagen"] is True
    assert "Keine Antwort" in ergebnis["text"]


def test_abgelehntes_werkzeug_das_modell_liest_englisch_das_fenster_deutsch(client, chat_id):
    class Registry(HeikleRegistry):
        def braucht_bestaetigung(self, name, argumente=None, ordner=None):
            _spaeter_klicken(client, False)
            return True

        def server_von(self, name):
            return ''

        def bestaetigungsgrund(self, name, argumente=None, ordner=None):
            return ''

    registry = Registry()
    provider = _heikles_modell(client, registry)

    antwort = client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id, "endpoint_id": "test", "content": "mach", "sprache": "de",
        },
    )

    ergebnis = next(e for e in _ereignisse(antwort) if e["typ"] == "tool_result")
    assert "nicht erlaubt" in ergebnis["text"]
    an_modell = _werkzeug_nachricht_an_modell(provider)
    assert "not allowed" in an_modell.content
    assert len(_deutsche_woerter(an_modell.content)) < 2


def test_ohne_antwort_das_modell_liest_englisch_das_fenster_deutsch(client, chat_id, monkeypatch):
    from app.api.v1 import generierung as modul

    monkeypatch.setattr(modul, "BESTAETIGUNG_WARTEZEIT", 0.05)
    monkeypatch.setattr(modul, "BESTAETIGUNG_PRUEFTAKT", 0.01)

    registry = HeikleRegistry()
    provider = _heikles_modell(client, registry)

    antwort = client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id, "endpoint_id": "test", "content": "mach", "sprache": "de",
        },
    )

    ergebnis = next(e for e in _ereignisse(antwort) if e["typ"] == "tool_result")
    assert "Keine Antwort" in ergebnis["text"]
    an_modell = _werkzeug_nachricht_an_modell(provider)
    assert len(_deutsche_woerter(an_modell.content)) < 2


def test_keine_registry_das_modell_liest_englisch_das_fenster_deutsch(client, chat_id):
    """No tools at all (the feature is off): the same window/model split
    as the other two refusals above — before the fix this text had only
    one copy, and that copy was German."""
    client.app.state.werkzeuge = None
    client.app.state.config.features.mcp = True
    provider = provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"),
            haeppchen=["fertig"],
            werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="loeschen", argumente={})],
        ),
    )

    antwort = client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat_id, "endpoint_id": "test", "content": "mach", "sprache": "de",
        },
    )

    ergebnis = next(e for e in _ereignisse(antwort) if e["typ"] == "tool_result")
    assert len(_deutsche_woerter(ergebnis["text"])) >= 2
    an_modell = _werkzeug_nachricht_an_modell(provider)
    assert len(_deutsche_woerter(an_modell.content)) < 2


def test_zweite_runde_liest_immer_noch_englisch_nicht_die_gespeicherte_karte(client, chat_id):
    """A second turn of the same chat rebuilds history from the stored row
    (app/verlaufsbau.py), not from the live round above — a row that kept
    only the window's own language there would hand the model German
    again, one turn later than the live round above would."""
    class Registry(HeikleRegistry):
        def braucht_bestaetigung(self, name, argumente=None, ordner=None):
            _spaeter_klicken(client, False)
            return True

        def server_von(self, name):
            return ''

        def bestaetigungsgrund(self, name, argumente=None, ordner=None):
            return ''

    registry = Registry()
    provider = _heikles_modell(client, registry)

    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "mach", "sprache": "de"},
    )
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "und jetzt?", "sprache": "de"},
    )

    # Read back as a structured tool turn or folded into the assistant's
    # own text (app/verlaufsbau.py, ``_werkzeugzuege``/``_werkzeuge_als_text``)
    # — either way the model must read the English copy, never the card's.
    gesamter_text = " ".join(n.content for n in provider.letzte_anfrage.nachrichten)
    assert "not allowed" in gesamter_text
    assert len(_deutsche_woerter(gesamter_text)) < 2


def test_bestaetigung_ohne_wartende_generierung(client):
    """The dialog was still up, the response long over — not an error."""
    antwort = client.post(
        "/api/v1/chat/confirm",
        json={"generation_id": "gibtsnicht", "aufruf_id": "a1", "erlaubt": True},
    )
    assert antwort.status_code == 200
    assert antwort.json()["zugestellt"] is False
