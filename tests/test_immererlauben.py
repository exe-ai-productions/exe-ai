"""'Immer erlauben' becomes a real rule — the durable bridge
from `fragen` to `ja` in berechtigungen.json, seen and taken back through
its own small route, written from the confirmation box's third button.
"""

from __future__ import annotations

import asyncio
import json

from app import berechtigungen, immererlauben
from app.api.v1.generierung import bestaetigen as confirm_endpunkt
from app.api.v1.schemas import BestaetigungAnfrage
from app.berechtigungsregeln import laden
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Werkzeugaufruf
from tests.conftest import provider_setzen

# --- The module itself ------------------------------------------------------


def test_setzen_schreibt_eine_ja_regel(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    immererlauben.setzen(pfad, "web_search")

    rohdaten = json.loads(pfad.read_text(encoding="utf-8"))
    assert rohdaten["regeln"]["web_search"] == "ja"


def test_setzen_laesst_anderes_unangetastet(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(
        json.dumps({"regeln": {"shell": "nein"}, "niemals": ["rm -rf /"]}),
        encoding="utf-8",
    )
    immererlauben.setzen(pfad, "web_search")

    rohdaten = json.loads(pfad.read_text(encoding="utf-8"))
    assert rohdaten["regeln"] == {"shell": "nein", "web_search": "ja"}
    assert rohdaten["niemals"] == ["rm -rf /"]


def test_entfernen_nimmt_die_regel_wieder_raus(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    immererlauben.setzen(pfad, "web_search")

    assert immererlauben.entfernen(pfad, "web_search") is True
    rohdaten = json.loads(pfad.read_text(encoding="utf-8"))
    assert "web_search" not in rohdaten["regeln"]


def test_entfernen_ohne_regel_meldet_nichts_getan(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    assert immererlauben.entfernen(pfad, "phantom") is False


def test_auflisten_zeigt_alle_regeln(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    immererlauben.setzen(pfad, "web_search")
    immererlauben.setzen(pfad, "read_file")

    assert immererlauben.auflisten(pfad) == {"web_search": "ja", "read_file": "ja"}


def test_auflisten_ohne_datei_ist_leer(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    assert immererlauben.auflisten(pfad) == {}


def test_kaputte_datei_wird_aus_den_vorgaben_neu_angelegt(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text("{kaputt", encoding="utf-8")
    immererlauben.setzen(pfad, "web_search")

    regeln = laden(pfad)
    assert regeln.kaputt is None
    assert regeln.regeln["web_search"] == "ja"


# --- The rule actually holds — chat and agent alike -------------------------


def test_die_regel_greift_im_chat(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    immererlauben.setzen(pfad, "web_search")
    regeln = laden(pfad)

    urteil = berechtigungen.urteil("web_search", {}, [], "chat", regeln=regeln)
    assert urteil.antwort == "ja"


def test_die_regel_greift_auch_im_agentenlauf(tmp_path):
    pfad = tmp_path / "berechtigungen.json"
    immererlauben.setzen(pfad, "web_search")
    regeln = laden(pfad)

    urteil = berechtigungen.urteil("web_search", {}, [], "agent", regeln=regeln)
    assert urteil.antwort == "ja"


def test_ohne_regel_bleibt_es_beim_bisherigen_urteil(tmp_path):
    """The rule's absence must survive too — writing nothing must not
    silently grant anything the file did not already grant."""
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(json.dumps({"standard": "fragen"}), encoding="utf-8")
    regeln = laden(pfad)
    urteil = berechtigungen.urteil("web_search", {}, [], "chat", regeln=regeln)
    assert urteil.antwort == "fragen"


def test_die_regel_dreht_ein_fragen_in_ein_ja(tmp_path):
    """The bridge the auftrag names: 'immer erlauben' turns THIS one
    'fragen' into a standing 'ja', without touching the default for
    everything else."""
    pfad = tmp_path / "berechtigungen.json"
    pfad.write_text(json.dumps({"standard": "fragen"}), encoding="utf-8")
    immererlauben.setzen(pfad, "web_search")
    regeln = laden(pfad)

    assert berechtigungen.urteil("web_search", {}, [], "chat", regeln=regeln).antwort == "ja"
    # A different tool never named is unaffected — still asks.
    assert berechtigungen.urteil("addieren", {}, [], "chat", regeln=regeln).antwort == "fragen"


# --- The route, end to end ---------------------------------------------------


def _spaeter_ueber_die_route_bestaetigen(client, config, *, angefragter_name, dauerhaft):
    """Calls the real confirm route function — the exact code the HTTP
    endpoint runs — once the confirmation prompt is actually up.
    ``angefragter_name`` is what the request itself claims the "always
    allow" is for, letting a test send a name other than the one really
    waiting. Must run from inside a coroutine already under
    way (``braucht_bestaetigung`` below) — the prompt only exists once the
    request that asks for it has started."""
    verwaltung = client.app.state.generierungen

    def versuchen():
        for generierung in verwaltung.laufende():
            for aufruf_id in list(generierung.bestaetigungen):
                confirm_endpunkt(
                    BestaetigungAnfrage(
                        generation_id=generierung.id,
                        aufruf_id=aufruf_id,
                        erlaubt=True,
                        name=angefragter_name,
                        dauerhaft=dauerhaft,
                    ),
                    generierungen=verwaltung,
                    config=config,
                    registry=client.app.state.werkzeuge,
                )
                return True
        return False

    def takt():
        if not versuchen():
            asyncio.get_running_loop().call_later(0.01, takt)

    asyncio.get_running_loop().call_later(0.01, takt)


class _BestaetigungsWerkzeug:
    """A tool that always needs confirmation — stands in for whatever real
    tool the "always allow" button was actually clicked for. Schedules the
    confirm click itself, from ``braucht_bestaetigung`` — the same timing
    ``HeikleRegistry``/``_spaeter_klicken`` use in test_werkzeuge.py, the
    only point during a request where the prompt actually exists yet."""

    def __init__(
        self, name: str, client, config, *, angefragter_name: str, dauerhaft: bool,
        display_names: dict[str, str] | None = None,
    ):
        self.name = name
        self._display_names = display_names or {}
        self.aufgerufen = []
        self._client = client
        self._config = config
        self._angefragter_name = angefragter_name
        self._dauerhaft = dauerhaft

    def als_openai_werkzeuge(self, **_options):
        return [{"type": "function", "function": {"name": self.name, "parameters": {}}}]

    def braucht_bestaetigung(self, name, argumente=None, ordner=None):
        _spaeter_ueber_die_route_bestaetigen(
            self._client, self._config,
            angefragter_name=self._angefragter_name, dauerhaft=self._dauerhaft,
        )
        return True

    def server_von(self, name):
        return ""

    def display_name(self, name):
        return self._display_names.get(name, name)

    def bestaetigungsgrund(self, name, argumente=None, ordner=None):
        return ""

    async def ausfuehren(self, name, argumente, bild_senke=None, ordner=None, chat_id=None):
        self.aufgerufen.append((name, argumente))
        return "erledigt"


def _rueckfrage_beantworten(
    client, config, chat_id, werkzeugname, *, angefragter_name, dauerhaft, display_names=None,
):
    """Runs one chat turn that asks for confirmation on ``werkzeugname``
    and answers it — through the real ``/chat/confirm`` route logic —
    claiming ``angefragter_name`` for the "always allow", with a real
    waiting call behind it rather than a phantom id."""
    client.app.state.config.features.mcp = True
    client.app.state.werkzeuge = _BestaetigungsWerkzeug(
        werkzeugname, client, config,
        angefragter_name=angefragter_name, dauerhaft=dauerhaft, display_names=display_names,
    )
    provider_setzen(
        client,
        MockProvider(
            mock_endpunkt("test"), haeppchen=["fertig"],
            werkzeugaufrufe=[Werkzeugaufruf(id="a1", name=werkzeugname, argumente={})],
        ),
    )
    return client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "los"},
    )


def test_die_regel_kann_nicht_ueber_confirm_ohne_wartenden_aufruf_erlaubt_werden(config, client):
    """'immer erlauben' must not write from a phantom click —
    only a genuine waiting call, matched by name, may turn into a rule."""
    antwort = client.post(
        "/api/v1/chat/confirm",
        json={
            "generation_id": "phantom",
            "aufruf_id": "phantom",
            "erlaubt": True,
            "name": "web_search",
            "dauerhaft": True,
        },
    )
    assert antwort.status_code == 200
    assert antwort.json()["zugestellt"] is False  # nobody was waiting

    regeln = laden(config.pfad(config.app.berechtigungen_datei))
    assert regeln.regeln == {}


def test_die_regel_kann_nicht_ueber_confirm_mit_falschem_namen_erlaubt_werden(config, client, chat_id):
    """A real call is waiting — for 'web_search' — but the request names a
    different tool. That must not write a rule for either name."""
    _rueckfrage_beantworten(
        client, config, chat_id, "web_search", angefragter_name="andermal", dauerhaft=True
    )

    regeln = laden(config.pfad(config.app.berechtigungen_datei))
    assert regeln.regeln == {}


def test_eine_echte_rueckfrage_mit_immer_schreibt_die_regel_weiterhin(config, client, chat_id):
    """The genuine case: a real call is waiting for 'web_search', and the
    request names exactly that — the rule must still land."""
    _rueckfrage_beantworten(
        client, config, chat_id, "web_search", angefragter_name="web_search", dauerhaft=True
    )

    regeln = laden(config.pfad(config.app.berechtigungen_datei))
    assert regeln.regeln["web_search"] == "ja"


def test_a_servers_tool_is_allowed_under_the_name_of_the_model(config, client, chat_id):
    """The window names a server's tool as the server does ('read_file'),
    the gate reads the name the model calls it by: the rule lands under that
    one — never under the plain word, which a built-in tool carries as well."""
    _rueckfrage_beantworten(
        client, config, chat_id, "mcp__fs__read_file", angefragter_name="read_file",
        dauerhaft=True, display_names={"mcp__fs__read_file": "read_file"},
    )

    regeln = laden(config.pfad(config.app.berechtigungen_datei))
    assert regeln.regeln == {"mcp__fs__read_file": "ja"}


def test_another_display_name_writes_no_rule_here_either(config, client, chat_id):
    _rueckfrage_beantworten(
        client, config, chat_id, "mcp__fs__read_file", angefragter_name="write_file",
        dauerhaft=True, display_names={"mcp__fs__read_file": "read_file"},
    )

    regeln = laden(config.pfad(config.app.berechtigungen_datei))
    assert regeln.regeln == {}


def test_ohne_dauerhaft_bleibt_die_datei_unberuehrt(config, client):
    antwort = client.post(
        "/api/v1/chat/confirm",
        json={"generation_id": "phantom", "aufruf_id": "phantom", "erlaubt": True},
    )
    assert antwort.status_code == 200
    regeln = laden(config.pfad(config.app.berechtigungen_datei))
    assert regeln.regeln == {}


def test_abgelehnt_und_dauerhaft_schreibt_keine_regel(config, client):
    """'Immer erlauben' is unreachable from a no — the button only exists
    beside the yes."""
    antwort = client.post(
        "/api/v1/chat/confirm",
        json={
            "generation_id": "phantom",
            "aufruf_id": "phantom",
            "erlaubt": False,
            "name": "web_search",
            "dauerhaft": True,
        },
    )
    assert antwort.status_code == 200
    regeln = laden(config.pfad(config.app.berechtigungen_datei))
    assert regeln.regeln == {}


def test_die_regel_ist_auffindbar_ueber_die_route(config, client, chat_id):
    _rueckfrage_beantworten(
        client, config, chat_id, "web_search", angefragter_name="web_search", dauerhaft=True
    )

    antwort = client.get("/api/v1/permissions/always-allow")
    assert antwort.status_code == 200
    assert antwort.json() == {"web_search": "ja"}


def test_die_regel_laesst_sich_ueber_die_route_entfernen(config, client, chat_id):
    _rueckfrage_beantworten(
        client, config, chat_id, "web_search", angefragter_name="web_search", dauerhaft=True
    )

    antwort = client.delete("/api/v1/permissions/always-allow/web_search")
    assert antwort.status_code == 204

    assert client.get("/api/v1/permissions/always-allow").json() == {}


def test_eine_unbekannte_regel_entfernen_gibt_404(client):
    antwort = client.delete("/api/v1/permissions/always-allow/phantom")
    assert antwort.status_code == 404
