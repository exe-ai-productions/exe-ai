"""When Anthropic refuses the check of a provider, the reason it gives is not lost.

A key that belongs to no workspace gets HTTP 400 with a sentence; a wrong key
gets 401 with another. The sentence goes to the log as a warning with status
and type, stays with the endpoint's state, and the window that just saved the
provider shows it instead of "Saved, but not reachable". Without a reason (no
answer, no JSON) everything stays as it was, and the key is never part of any
of it.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from app.config import EndpointConfig
from app.i18n import t
from app.providers.anthropic import AnthropicProvider

WORKSPACE = (
    "This API key is not scoped to a workspace, so this request must include the "
    "anthropic-workspace-id header."
)
KEY = "sk-ant-api03-test-key-0123456789"
# The real client, kept before any test stands a transport in for it.
_REAL_CLIENT = httpx.AsyncClient


def _error(kind: str, message: str) -> dict:
    return {"type": "error", "error": {"type": kind, "message": message}}


def _provider(monkeypatch, handler, key: str = KEY) -> AnthropicProvider:
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", key)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=transport, **kw))
    return AnthropicProvider(EndpointConfig(
        id="anthropic", base_url="https://api.example.invalid/v1", provider="anthropic",
        api_key_env="TEST_ANTHROPIC_KEY",
    ))


# --- The provider ---


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "kind", "message"), [
    (400, "invalid_request_error", WORKSPACE),
    (401, "authentication_error", "invalid x-api-key"),
])
async def test_the_sentence_of_a_refusal_is_kept_and_logged(monkeypatch, caplog, status, kind, message):
    provider = _provider(monkeypatch, lambda request: httpx.Response(status, json=_error(kind, message)))
    with caplog.at_level(logging.INFO, logger="app.providers.anthropic"):
        assert await provider.erreichbar(1.0) is False
    assert provider.letzter_grund == message
    warning = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning) == 1
    line = warning[0].getMessage()
    assert str(status) in line and kind in line and message in line
    assert KEY not in caplog.text


@pytest.mark.asyncio
async def test_the_key_is_not_part_of_the_reason_even_when_the_sentence_names_it(monkeypatch, caplog):
    provider = _provider(
        monkeypatch,
        lambda request: httpx.Response(401, json=_error("authentication_error", f"invalid x-api-key {KEY}")),
    )
    with caplog.at_level(logging.INFO, logger="app.providers.anthropic"):
        await provider.erreichbar(1.0)
    assert provider.letzter_grund == "invalid x-api-key …"
    assert KEY not in caplog.text


@pytest.mark.asyncio
async def test_a_reason_goes_with_the_next_answer(monkeypatch):
    state = {"status": 400}

    def handler(request):
        if state["status"] == 400:
            return httpx.Response(400, json=_error("invalid_request_error", WORKSPACE))
        return httpx.Response(200, json={"data": []})

    provider = _provider(monkeypatch, handler)
    assert await provider.erreichbar(1.0) is False and provider.letzter_grund == WORKSPACE
    state["status"] = 200
    assert await provider.erreichbar(1.0) is True and provider.letzter_grund is None


@pytest.mark.asyncio
async def test_silence_without_a_reason_everything_stays_as_it_was(monkeypatch, caplog):
    answers = {
        "ok": lambda request: httpx.Response(200, json={"data": []}),
        "401 without json": lambda request: httpx.Response(401, text="Unauthorized"),
        "500 without json": lambda request: httpx.Response(500, text="<html>oops</html>"),
        "400 without a sentence": lambda request: httpx.Response(400, json={"error": {"type": "x"}}),
        "400 with a list": lambda request: httpx.Response(400, json=["no", "object"]),
    }
    for name, handler in answers.items():
        provider = _provider(monkeypatch, handler)
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="app.providers.anthropic"):
            reachable = await provider.erreichbar(1.0)
        assert reachable is (name == "ok"), name
        assert provider.letzter_grund is None, name
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING], name
    # The old line for a rejected key without a reason stays.
    provider = _provider(monkeypatch, answers["401 without json"])
    with caplog.at_level(logging.INFO, logger="app.providers.anthropic"):
        await provider.erreichbar(1.0)
    assert "Anthropic answers, but the key is rejected" in caplog.text


@pytest.mark.asyncio
async def test_a_timeout_has_no_reason(monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("no answer", request=request)

    provider = _provider(monkeypatch, handler)
    assert await provider.erreichbar(1.0) is False
    assert provider.letzter_grund is None


# --- The route that saves a provider ---


def _add_anthropic(client, monkeypatch, tmp_path, handler):
    from app import paketierung

    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path)
    (tmp_path / "config.yaml").write_text("endpoints: []\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "vorher")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=transport, **kw))
    return client.post("/api/v1/providers", json={"art": "anthropic", "schluessel": KEY})


def _sentences(message: str) -> set[str]:
    return {
        t("fehler.anbieter_nicht_erreichbar", lang, name="anthropic", detail=message)
        for lang in ("de", "en")
    }


@pytest.mark.parametrize(("status", "kind", "message"), [
    (400, "invalid_request_error", WORKSPACE),
    (401, "authentication_error", "invalid x-api-key"),
])
def test_the_answer_of_saving_carries_the_sentence_and_the_state_the_reason(
    client, monkeypatch, tmp_path, status, kind, message,
):
    answer = _add_anthropic(
        client, monkeypatch, tmp_path,
        lambda request: httpx.Response(status, json=_error(kind, message)),
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["erreichbar"] is False
    assert body["hinweis"] in _sentences(message)
    assert KEY not in answer.text
    zustand = client.app.state.discovery.zustaende["anthropic"]
    assert zustand.grund == message
    assert zustand.als_dict()["grund"] == message


def test_silence_saving_a_working_provider_or_a_dead_one_says_what_it_said_before(
    client, monkeypatch, tmp_path,
):
    ok = _add_anthropic(
        client, monkeypatch, tmp_path, lambda request: httpx.Response(200, json={"data": []}),
    )
    assert ok.status_code == 200
    assert ok.json() == {
        "id": "anthropic", "api_key_env": "ANTHROPIC_API_KEY", "erreichbar": True, "hinweis": None,
    }
    assert client.app.state.discovery.zustaende["anthropic"].grund is None


def test_silence_a_provider_that_does_not_answer_has_no_sentence(client, monkeypatch, tmp_path):
    def handler(request):
        raise httpx.ConnectTimeout("no answer", request=request)

    answer = _add_anthropic(client, monkeypatch, tmp_path, handler)
    assert answer.status_code == 200
    assert answer.json()["erreichbar"] is False and answer.json()["hinweis"] is None
    assert client.app.state.discovery.zustaende["anthropic"].grund is None
