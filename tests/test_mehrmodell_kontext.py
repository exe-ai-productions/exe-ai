"""A server holding many models, and the window size of the one it runs.

The endpoint that started this: thirty entries in its model list and no
model pinned in the configuration, because the choice is made from the list
in the chat. Both readings the search had missed it — a pinned name there
was none, and "exactly one entry" was thirty entries away — so the context
bar stayed empty while the number sat in the list all along.

The third reading is the name the server reports for itself. What is tested
here is that order and, just as much, what it must NOT do: override a pinned
name, invent a number where none is offered, or keep an answer past the
model it belongs to.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Capabilities, EndpointConfig
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

pytestmark = pytest.mark.anyio


def _endpunkt(modell=None, url="http://127.0.0.1:9/v1"):
    return EndpointConfig(
        id="x",
        base_url=url,
        modell=modell,
        parameter_dialect="openai",
        capabilities=Capabilities(),
    )


def _provider(monkeypatch, handler, modell=None):
    provider = OpenAIKompatiblerProvider(_endpunkt(modell=modell))
    transport = httpx.MockTransport(handler)
    echter = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: echter(transport=transport, **kw)
    )
    return provider


def _viele_modelle(*, laeuft="gross-modell", fenster=262144, zahl=30):
    """A model list of `zahl` entries, only one of which carries a window."""
    eintraege = [{"id": f"anderes-{i}"} for i in range(zahl - 1)]
    eintraege.insert(7, {"id": laeuft, "max_model_len": fenster})

    def handler(request):
        if request.url.path.endswith("/props"):
            return httpx.Response(404)
        if request.url.path.endswith("/models/status"):
            return httpx.Response(404)
        return httpx.Response(200, json={"data": eintraege})

    return handler


# --- The finding itself ----------------------------------------------------


async def test_ohne_gemeldeten_namen_bleibt_die_liste_stumm(monkeypatch):
    """The state before: no pinned name, thirty entries, no answer."""
    provider = _provider(monkeypatch, _viele_modelle())
    assert await provider.kontextgroesse(1.0) is None


async def test_der_gemeldete_name_findet_die_zeile(monkeypatch):
    """The same list, with the name the server reports for itself."""
    provider = _provider(monkeypatch, _viele_modelle())
    assert await provider.kontextgroesse(1.0, "gross-modell") == 262144


async def test_auch_das_statusblatt_liest_den_gemeldeten_namen(monkeypatch):
    """The other route carries the number for some servers, and the two have
    to agree — otherwise the answer would depend on which route happened to
    hold it."""

    def handler(request):
        if request.url.path.endswith("/models/status"):
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"id": "anderes", "max_context_window": 4096},
                        {"id": "gross-modell", "max_context_window": 262144},
                    ]
                },
            )
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(
                200, json={"data": [{"id": "anderes"}, {"id": "gross-modell"}]}
            )
        return httpx.Response(404)

    provider = _provider(monkeypatch, handler)
    assert await provider.kontextgroesse(1.0, "gross-modell") == 262144


# --- What it must not do ---------------------------------------------------


async def test_ein_eingetragener_name_gewinnt(monkeypatch):
    """A name in the configuration is somebody's statement, and it outranks
    what the server reports. Where it misses, the search ends rather than
    falling through to another model's number."""
    provider = _provider(monkeypatch, _viele_modelle(), modell="anderes-3")
    assert await provider.kontextgroesse(1.0, "gross-modell") is None


async def test_ein_einzelserver_traegt_weiter(monkeypatch):
    """The single-entry shortcut is what a local server with one model lives
    on, and it stays untouched."""

    def handler(request):
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(
                200, json={"data": [{"id": "das-eine", "max_model_len": 32768}]}
            )
        return httpx.Response(404)

    provider = _provider(monkeypatch, handler)
    assert await provider.kontextgroesse(1.0) == 32768


async def test_ohne_zahl_bleibt_es_bei_nichts(monkeypatch):
    """The quiet case, and the more important half of the test: a server
    that offers no number anywhere is not talked into one."""

    def handler(request):
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, json={"data": [{"id": "gross-modell"}]})
        return httpx.Response(404)

    provider = _provider(monkeypatch, handler)
    assert await provider.kontextgroesse(1.0, "gross-modell") is None


# --- The remembered answer -------------------------------------------------


async def test_dieselbe_frage_wird_nur_einmal_gestellt(monkeypatch):
    """Asked again on every pass for as long as the answer is unknown, so a
    server carrying no number would pay three requests per pass for ever."""
    gefragt: list[str] = []
    innen = _viele_modelle()

    def handler(request):
        gefragt.append(request.url.path)
        return innen(request)

    provider = _provider(monkeypatch, handler)
    assert await provider.kontextgroesse(1.0, "gross-modell") == 262144
    bisher = len(gefragt)
    assert await provider.kontextgroesse(1.0, "gross-modell") == 262144
    assert len(gefragt) == bisher


async def test_ein_anderes_modell_wird_neu_gefragt(monkeypatch):
    """The point of the whole cache being keyed by name. Swapping the model
    on the server changes the window, and an answer kept past that swap would
    be a number belonging to somebody else."""
    laeuft = {"handler": _viele_modelle(laeuft="gross-modell")}
    provider = _provider(monkeypatch, lambda anfrage: laeuft["handler"](anfrage))
    assert await provider.kontextgroesse(1.0, "gross-modell") == 262144

    # The server is switched over to another model behind the provider's back.
    laeuft["handler"] = _viele_modelle(laeuft="klein-modell", fenster=8192)
    assert await provider.kontextgroesse(1.0, "klein-modell") == 8192


async def test_auch_das_leere_ergebnis_wird_gemerkt(monkeypatch):
    """The expensive case is the one with no answer, so that is the one the
    memory has to cover."""
    gefragt: list[str] = []

    def handler(request):
        gefragt.append(request.url.path)
        return httpx.Response(404)

    provider = _provider(monkeypatch, handler)
    assert await provider.kontextgroesse(1.0, "gross-modell") is None
    bisher = len(gefragt)
    assert await provider.kontextgroesse(1.0, "gross-modell") is None
    assert len(gefragt) == bisher
