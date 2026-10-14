"""An oMLX server entered under the plain ``openai`` dialect is recognised by
its own answer, and only the running service learns it
(app/dialekterkennung.py).

Tested are the rule, the knock and what the discovery does with the
answer — and, just as much, the silences: a cloud answer, a foreign shape,
a timeout and every dialect somebody chose must leave the endpoint exactly
as it was.
"""

from __future__ import annotations

import logging

import httpx

from app import dialekterkennung
from app.config import Capabilities, Config, EndpointConfig
from app.denkschalter import zusatz
from app.discovery import STILLE_BIS_WEG, Discovery
from app.events import EventBus
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

QWEN = "Qwen3.5-9B-original-oQ4e-fp16-mtp"
LLAMA = "Llama-3.3-70B-Instruct-4bit"

# The shape the real server answers with, trimmed to what matters here:
# wrapped in `models`, one row per model, each naming its family.
OMLX_STATUS = {
    "final_ceiling": 54_899_913_318,
    "model_count": 2,
    "models": [
        {"id": QWEN, "config_model_type": "qwen3_5", "max_context_window": 262_144},
        {"id": LLAMA, "config_model_type": "llama", "max_context_window": 131_072},
    ],
}

# Taken once, before any test swaps it: a test that swaps twice must still
# build its client on the real class.
_ECHT = httpx.AsyncClient


def _transport(monkeypatch, handler) -> None:
    """Every request any provider makes goes to ``handler`` instead."""
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _ECHT(transport=transport, **kw))


def _server(status=None, *, fehler=None, gefragt=None):
    """A server with one model and its window in the model list; on the
    status route ``status`` (a 404 when None), or ``fehler`` raised there."""

    def handler(request):
        pfad = request.url.path
        if gefragt is not None:
            gefragt.append(pfad)
        if pfad.endswith("/models/status"):
            if fehler is not None:
                raise fehler
            if status is None:
                return httpx.Response(404)
            return httpx.Response(200, json=status)
        if pfad.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": QWEN, "max_model_len": 262_144}]})
        return httpx.Response(404)

    return handler


def _discovery(tmp_path, dialekt="openai", url="http://127.0.0.1:9/v1"):
    config = Config.model_validate(
        {
            "app": {"data_dir": str(tmp_path / "data"), "log_dir": str(tmp_path / "logs")},
            "endpoints": [
                {
                    "id": "omlx",
                    "provider": "openai_compatible",
                    "base_url": url,
                    "parameter_dialect": dialekt,
                }
            ],
        }
    )
    return Discovery(config, EventBus()), config


# --- The rule ---------------------------------------------------------------


def test_die_form_des_servers_wird_erkannt():
    assert dialekterkennung.ist_mlx_statusblatt(OMLX_STATUS)
    assert dialekterkennung.ist_mlx_statusblatt(OMLX_STATUS["models"])
    assert dialekterkennung.ist_mlx_statusblatt({"data": OMLX_STATUS["models"]})


def test_fremde_antworten_sind_keine_spur():
    """What else a status route, a model list or an error page can carry."""
    for antwort in (
        None,
        "ok",
        42,
        {},
        [],
        {"detail": "Not Found"},
        {"models": []},
        {"status": "ok", "uptime": 12},
        [{"id": "a", "max_model_len": 8192}],
        {"models": [{"id": "a", "max_context_window": 8192}]},
        [{"id": "", "config_model_type": "llama"}],
        [{"id": "a", "config_model_type": ""}],
        [{"id": "a", "config_model_type": None}],
        ["qwen3_5"],
    ):
        assert not dialekterkennung.ist_mlx_statusblatt(antwort), antwort


# --- The knock --------------------------------------------------------------


def _provider():
    return OpenAIKompatiblerProvider(
        EndpointConfig(id="o", base_url="http://127.0.0.1:9/v1", capabilities=Capabilities())
    )


async def test_der_server_antwortet_in_seiner_form(monkeypatch):
    _transport(monkeypatch, _server(OMLX_STATUS))
    assert await _provider().mlx_erkennen() is True


async def test_ein_404_ist_ein_nein(monkeypatch):
    _transport(monkeypatch, _server(None))
    assert await _provider().mlx_erkennen() is False


async def test_eine_fremde_form_ist_ein_nein(monkeypatch):
    _transport(monkeypatch, _server({"status": "ok", "uptime": 12}))
    assert await _provider().mlx_erkennen() is False


async def test_kein_json_ist_ein_nein(monkeypatch):
    _transport(monkeypatch, lambda request: httpx.Response(200, text="<html>hallo</html>"))
    assert await _provider().mlx_erkennen() is False


async def test_keine_antwort_ist_kein_befund(monkeypatch):
    """A timeout says nothing about the server — neither yes nor no."""
    _transport(monkeypatch, _server(fehler=httpx.ConnectTimeout("zu langsam")))
    assert await _provider().mlx_erkennen() is None


# --- What the discovery does with it ------------------------------------------


async def test_ein_omlx_server_wird_fuer_die_sitzung_mlx(tmp_path, monkeypatch, caplog):
    """The switch lands in that server's words, the families are read, and
    the hint that the switch does not work falls silent — because now it
    does. The settings routes hold the same endpoint object, so they see
    it too."""
    caplog.set_level(logging.INFO, logger="app.discovery")
    _transport(monkeypatch, _server(OMLX_STATUS))
    discovery, config = _discovery(tmp_path)

    await discovery.einmal_pruefen()

    zustand = discovery.zustaende["omlx"]
    assert zustand.endpunkt.parameter_dialect == "mlx"
    assert config.endpoints[0] is zustand.endpunkt
    eintrag = zustand.als_dict(QWEN)
    assert eintrag["dialekt"] == "mlx"
    assert eintrag["quelle"] == "MLX"
    assert eintrag["dialekt_verdacht"] is False
    assert zustand.faehigkeiten_erkannt["familien"] == {QWEN: "qwen3_5", LLAMA: "llama"}
    assert zusatz(False, zustand, modell=QWEN) == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert any(
        "omlx" in r.getMessage() and "dialect mlx" in r.getMessage() for r in caplog.records
    )


async def test_ein_nein_bleibt_openai_und_wird_nicht_wieder_gefragt(tmp_path, monkeypatch):
    """A cloud address answers the route with a 404: nothing changes, and
    the next pass does not knock again — once per endpoint, never per
    request."""
    gefragt = []
    _transport(monkeypatch, _server(None, gefragt=gefragt))
    discovery, _ = _discovery(tmp_path, url="https://api.example.com/v1")

    await discovery.einmal_pruefen()
    # The status route is also where a list without an answer limit is
    # looked up (once per model, app/providers/openai_kompatibel.py), so the
    # first pass may knock more than once; the second must not knock at all.
    first_pass = sum(p.endswith("/models/status") for p in gefragt)
    await discovery.einmal_pruefen()

    assert discovery.zustaende["omlx"].endpunkt.parameter_dialect == "openai"
    assert first_pass >= 1
    assert sum(p.endswith("/models/status") for p in gefragt) == first_pass


async def test_eine_fremde_form_bleibt_openai(tmp_path, monkeypatch):
    _transport(monkeypatch, _server({"status": "ok", "uptime": 12}))
    discovery, _ = _discovery(tmp_path)

    await discovery.einmal_pruefen()

    assert discovery.zustaende["omlx"].endpunkt.parameter_dialect == "openai"


async def test_ein_lokaler_server_ohne_familien_behaelt_den_hinweis(tmp_path, monkeypatch):
    """A local server that looks like a serving stack but names no families
    (a model list with windows, a status route of its own shape): the
    program cannot be sure, so it changes nothing and keeps pointing at the
    mismatch."""
    _transport(monkeypatch, _server({"models": [{"id": QWEN, "max_context_window": 262_144}]}))
    discovery, _ = _discovery(tmp_path)

    await discovery.einmal_pruefen()

    zustand = discovery.zustaende["omlx"]
    assert zustand.endpunkt.parameter_dialect == "openai"
    assert zustand.als_dict(QWEN)["dialekt_verdacht"] is True


async def test_ohne_antwort_wird_beim_naechsten_mal_gefragt(tmp_path, monkeypatch):
    """A timeout is no answer: the endpoint stays as it is and is asked again
    on the next pass — and once the real answer lands, the hint raised in
    the meantime goes quiet with it."""
    _transport(monkeypatch, _server(fehler=httpx.ConnectTimeout("zu langsam")))
    discovery, _ = _discovery(tmp_path)
    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["omlx"]
    assert zustand.endpunkt.parameter_dialect == "openai"
    assert zustand.dialekt_geprueft is False

    _transport(monkeypatch, _server(OMLX_STATUS))
    await discovery.einmal_pruefen()

    assert zustand.endpunkt.parameter_dialect == "mlx"
    assert zustand.als_dict(QWEN)["dialekt_verdacht"] is False


async def test_ein_props_das_nicht_antwortet_wird_wieder_gefragt(tmp_path, monkeypatch):
    """A timeout on /props used to be written down as "this server can
    nothing", so a server that was merely slow to start was never believed
    again. No answer is now no answer: it changes nothing that is known, and
    the next pass knocks once more."""

    def handler(request):
        pfad = request.url.path
        if pfad.endswith("/props"):
            if stumm["ja"]:
                raise httpx.ConnectTimeout("zu langsam")
            return httpx.Response(
                200, json={"chat_template_caps": {"supports_tool_calls": True}}
            )
        if pfad.endswith("/models/status"):
            return httpx.Response(404)
        if pfad.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": QWEN}]})
        return httpx.Response(404)

    stumm = {"ja": True}
    _transport(monkeypatch, handler)
    discovery, _ = _discovery(tmp_path)

    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["omlx"]
    assert "tool_calls" not in zustand.faehigkeiten_erkannt

    stumm["ja"] = False
    await discovery.einmal_pruefen()

    assert zustand.faehigkeiten_erkannt["tool_calls"] is True

    # One silent pass after an answer keeps what the answer said.
    stumm["ja"] = True
    await discovery.einmal_pruefen()
    assert zustand.faehigkeiten_erkannt["tool_calls"] is True


def _props_server(mode, asked):
    """A server whose /props answers as ``mode["kind"]`` says: ``"answer"``
    (a chat template with tool calls), ``"silent"`` (a timeout) or ``"missing"``
    (a 404). Every knock is counted in ``asked``."""

    def handler(request):
        path = request.url.path
        if path.endswith("/props"):
            asked.append(path)
            if mode["kind"] == "silent":
                raise httpx.ConnectTimeout("too slow")
            if mode["kind"] == "missing":
                return httpx.Response(404)
            return httpx.Response(
                200, json={"chat_template_caps": {"supports_tool_calls": True}}
            )
        if path.endswith("/models/status"):
            return httpx.Response(404)
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": QWEN}]})
        return httpx.Response(404)

    return handler


async def test_props_is_asked_on_every_pass_and_follows_the_server(tmp_path, monkeypatch):
    """A reachable server that stops answering /props loses what /props said
    once the silence passes the cap, and gets it back when /props returns —
    nothing resets by hand in between."""
    mode = {"kind": "answer"}
    asked: list[str] = []
    _transport(monkeypatch, _props_server(mode, asked))
    discovery, _ = _discovery(tmp_path)

    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["omlx"]
    assert zustand.faehigkeiten_erkannt["tool_calls"] is True

    before = len(asked)
    mode["kind"] = "silent"
    for _ in range(STILLE_BIS_WEG - 1):
        await discovery.einmal_pruefen()
        assert zustand.faehigkeiten_erkannt["tool_calls"] is True
    await discovery.einmal_pruefen()
    assert "tool_calls" not in zustand.faehigkeiten_erkannt

    mode["kind"] = "answer"
    await discovery.einmal_pruefen()
    assert zustand.faehigkeiten_erkannt["tool_calls"] is True
    # One knock per pass, silent or not.
    assert len(asked) - before == STILLE_BIS_WEG + 1


async def test_a_props_route_that_disappears_is_an_answer(tmp_path, monkeypatch):
    """A 404 is the server saying there is no such route: what /props said
    before is gone at once, not after the cap."""
    mode = {"kind": "answer"}
    _transport(monkeypatch, _props_server(mode, []))
    discovery, _ = _discovery(tmp_path)
    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["omlx"]
    assert zustand.faehigkeiten_erkannt["tool_calls"] is True

    mode["kind"] = "missing"
    await discovery.einmal_pruefen()
    assert "tool_calls" not in zustand.faehigkeiten_erkannt

    mode["kind"] = "answer"
    await discovery.einmal_pruefen()
    assert zustand.faehigkeiten_erkannt["tool_calls"] is True


async def test_silence_probe_a_steady_props_gives_the_same_state_on_every_pass(
    tmp_path, monkeypatch
):
    mode = {"kind": "answer"}
    _transport(monkeypatch, _props_server(mode, []))
    discovery, _ = _discovery(tmp_path)
    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["omlx"]
    first = dict(zustand.faehigkeiten_erkannt)

    for _ in range(STILLE_BIS_WEG + 2):
        await discovery.einmal_pruefen()

    assert zustand.faehigkeiten_erkannt == first


async def test_ein_spaet_erkannter_dialekt_holt_die_familien_nach(tmp_path, monkeypatch):
    """The capabilities are asked in the same pass as the dialect, and under
    the plain openai dialect ``denkquellen`` answers nothing at all. Settled
    there, the model families of an mlx server never arrived for the rest of
    the session — the switch then guessed from the file name, which is the
    very defect the families exist to prevent."""
    _transport(monkeypatch, _server(fehler=httpx.ConnectTimeout("zu langsam")))
    discovery, _ = _discovery(tmp_path)
    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["omlx"]
    assert zustand.endpunkt.parameter_dialect == "openai"
    assert not zustand.faehigkeiten_erkannt.get("familien")

    _transport(monkeypatch, _server(OMLX_STATUS))
    await discovery.einmal_pruefen()

    assert zustand.endpunkt.parameter_dialect == "mlx"
    assert zustand.faehigkeiten_erkannt["familien"] == {QWEN: "qwen3_5", LLAMA: "llama"}


async def test_ein_nein_gilt_nur_solange_der_server_erreichbar_ist(tmp_path, monkeypatch):
    """Gone and back is a new stretch: whatever answers at that address now
    may be another server, and is asked again."""
    _transport(monkeypatch, _server(None))
    discovery, _ = _discovery(tmp_path)
    await discovery.einmal_pruefen()
    zustand = discovery.zustaende["omlx"]
    assert zustand.dialekt_geprueft is True

    _transport(monkeypatch, lambda request: httpx.Response(503))
    for _ in range(STILLE_BIS_WEG):
        await discovery.einmal_pruefen()
    assert zustand.erreichbar is False
    assert zustand.dialekt_geprueft is False

    _transport(monkeypatch, _server(OMLX_STATUS))
    await discovery.einmal_pruefen()
    assert zustand.endpunkt.parameter_dialect == "mlx"


async def test_ein_gewaehlter_dialekt_wird_nie_gefragt(tmp_path, monkeypatch):
    """A dialect somebody chose is theirs: not asked about and not
    overruled — not even where the server behind it would answer as oMLX."""
    gefragt = []

    async def mitschreiben(self, timeout=3.0):
        gefragt.append(self.endpunkt.parameter_dialect)
        return True

    monkeypatch.setattr(OpenAIKompatiblerProvider, "mlx_erkennen", mitschreiben)
    _transport(monkeypatch, _server(OMLX_STATUS))
    for dialekt in ("llama_cpp", "anthropic", "mlx"):
        discovery, _ = _discovery(tmp_path / dialekt, dialekt=dialekt)
        await discovery.einmal_pruefen()
        assert discovery.zustaende["omlx"].endpunkt.parameter_dialect == dialekt
    assert gefragt == []
