"""The context window of a cloud provider: asked, not guessed.

Two halves. The provider asks its model list for ``max_input_tokens``
instead of taking a substring table's word for it — the table itself moved
out to ``app/fenstergroesse.py``, the one place that falls through to it
for every provider alike (see ``tests/test_fenstergroesse.py``). And the
number can be said by hand for every provider whose list names none, which
is the whole of OpenAI's.
"""

from __future__ import annotations

import httpx
import pytest
import yaml

from app import fenstergroesse, paketierung
from app.config import EndpointConfig
from app.providers.anthropic import AnthropicProvider


def _endpunkt(**felder) -> EndpointConfig:
    return EndpointConfig.model_validate({
        "id": "a", "name": "A", "base_url": "http://x/v1",
        "provider": "anthropic", "parameter_dialect": "anthropic",
        "api_key_env": "TEST_SCHLUESSEL", **felder,
    })


def _liste(*modelle: dict) -> tuple[httpx.MockTransport, list[str]]:
    """A model list, plus the record of how often it was asked for."""
    gefragt: list[str] = []

    def griff(anfrage: httpx.Request) -> httpx.Response:
        gefragt.append(str(anfrage.url))
        return httpx.Response(200, json={"data": list(modelle)})

    return httpx.MockTransport(griff), gefragt


def _verdrahten(transport, monkeypatch) -> None:
    """Routes every client of this test through the mock transport.

    Set up once per test: patching a second time would wrap the already
    patched class and hand it two transports.
    """
    echt = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: echt(transport=transport, **kw))


async def _fragen(provider, transport, monkeypatch) -> int | None:
    if not isinstance(httpx.AsyncClient, type):
        return await provider.kontextgroesse(1.0)
    _verdrahten(transport, monkeypatch)
    return await provider.kontextgroesse(1.0)


# --- Out of the model list ------------------------------------------------


@pytest.mark.asyncio
async def test_das_fenster_kommt_aus_der_modellliste(monkeypatch):
    """The number sat in the answer all along — it was never taken out."""
    transport, _ = _liste({"id": "claude-opus-5", "max_input_tokens": 1_000_000})
    provider = AnthropicProvider(_endpunkt(modell="claude-opus-5"))
    assert await _fragen(provider, transport, monkeypatch) == 1_000_000


@pytest.mark.asyncio
async def test_die_tabelle_wird_hier_nicht_mehr_gefragt(monkeypatch):
    """A pinned snapshot the provider no longer lists gets no number here —
    app/fenstergroesse.py is where it falls through to the table instead,
    so a table entry can never outrank a size the provider had already
    learned from a refusal (see app/fenstergroesse.py, ``aufloesen``)."""
    transport, _ = _liste({"id": "claude-opus-5", "max_input_tokens": 1_000_000})
    provider = AnthropicProvider(_endpunkt(modell="claude-2.1-20231106"))
    assert await _fragen(provider, transport, monkeypatch) is None


@pytest.mark.asyncio
async def test_das_eingetragene_schlaegt_alles(monkeypatch):
    transport, gefragt = _liste({"id": "claude-opus-5", "max_input_tokens": 1_000_000})
    provider = AnthropicProvider(_endpunkt(modell="claude-opus-5", context_tokens=64_000))
    assert await _fragen(provider, transport, monkeypatch) == 64_000
    assert gefragt == [], "What is entered needs no request"


@pytest.mark.asyncio
async def test_ohne_festgelegtes_modell_wird_nichts_behauptet(monkeypatch):
    """A provider left to pick from its catalogue has no one window to
    report — and must not knock on the network to find that out."""
    transport, gefragt = _liste({"id": "claude-opus-5", "max_input_tokens": 1_000_000})
    provider = AnthropicProvider(_endpunkt())
    assert await _fragen(provider, transport, monkeypatch) is None
    assert gefragt == []


@pytest.mark.asyncio
async def test_die_liste_wird_nur_einmal_geholt(monkeypatch):
    """Discovery asks again every pass until it gets an answer. A model that
    never turns up must not cost a round trip each time."""
    transport, gefragt = _liste({"id": "claude-opus-5", "max_input_tokens": 1_000_000})
    provider = AnthropicProvider(_endpunkt(modell="gibt-es-nicht"))
    for _ in range(3):
        assert await _fragen(provider, transport, monkeypatch) is None
    assert len(gefragt) == 1


@pytest.mark.asyncio
async def test_eine_abgewiesene_liste_zaehlt_nicht_als_antwort(monkeypatch):
    """A rejected key is not the same as "the list has nothing" — the next
    pass, with a working key, has to be allowed to try again."""
    versuche: list[str] = []

    def griff(anfrage: httpx.Request) -> httpx.Response:
        versuche.append(str(anfrage.url))
        if len(versuche) == 1:
            return httpx.Response(401, json={"error": "kein Schlüssel"})
        return httpx.Response(
            200, json={"data": [{"id": "claude-opus-5", "max_input_tokens": 1_000_000}]}
        )

    transport = httpx.MockTransport(griff)
    provider = AnthropicProvider(_endpunkt(modell="claude-opus-5"))
    assert await _fragen(provider, transport, monkeypatch) is None  # rejected, not answered
    assert await _fragen(provider, transport, monkeypatch) == 1_000_000
    assert len(versuche) == 2


# --- Said by hand ---------------------------------------------------------


@pytest.fixture
def eigener_ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path)
    (tmp_path / "config.yaml").write_text("endpoints: []\n", encoding="utf-8")
    monkeypatch.setenv("EIGENE_API_KEY", "vorher")
    return tmp_path


def _anlegen(client):
    client.post(
        "/api/v1/providers",
        json={
            "art": "eigen", "kennung": "eigene",
            "url": "http://127.0.0.1:9/v1", "schluessel": "sk-test-1234",
        },
    )


def test_die_zahl_laesst_sich_von_hand_setzen(client, eigener_ordner):
    """OpenAI's model list carries no size at all, so its context bar stayed
    empty with no way to fill it in short of editing the file."""
    _anlegen(client)
    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.context_tokens is None

    antwort = client.put("/api/v1/providers/eigene/context", json={"context_tokens": 400_000})
    assert antwort.status_code == 200
    assert antwort.json() == {"id": "eigene", "context_tokens": 400_000}
    # The running service knows it at once …
    assert zustand.context_tokens == 400_000
    assert zustand.endpunkt.context_tokens == 400_000
    # … and the file carries it to the next start.
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert eintrag["context_tokens"] == 400_000


def test_geleert_wird_wieder_gefragt(client, eigener_ordner):
    """An emptied field means "work it out yourself" (app/fenstergroesse.py),
    resolved right away — never a blank ``None`` until the next poll. This
    endpoint answers nothing (port 9 is not listening), so the chain falls
    all the way through to the fallback."""
    _anlegen(client)
    client.put("/api/v1/providers/eigene/context", json={"context_tokens": 400_000})
    antwort = client.put("/api/v1/providers/eigene/context", json={"context_tokens": 0})
    assert antwort.status_code == 200
    assert antwort.json()["context_tokens"] is None
    zustand = client.app.state.discovery.zustaende["eigene"]
    assert zustand.context_tokens == fenstergroesse.ERSATZ
    assert zustand.kontext_quelle == fenstergroesse.QUELLE_ERSATZ
    gespeichert = yaml.safe_load((eigener_ordner / "config.yaml").read_text())
    eintrag = next(e for e in gespeichert["endpoints"] if e["id"] == "eigene")
    assert "context_tokens" not in eintrag


def test_unsinn_kommt_nicht_durch(client, eigener_ordner):
    _anlegen(client)
    assert client.put(
        "/api/v1/providers/eigene/context", json={"context_tokens": -5}
    ).status_code == 422
    assert client.put(
        "/api/v1/providers/gibtsnicht/context", json={"context_tokens": 1000}
    ).status_code == 404
