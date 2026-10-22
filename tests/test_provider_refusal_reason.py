"""When an OpenAI-compatible provider refuses the check, the reason it gives is not lost.

A wrong key gets 401 with a sentence (OpenAI, Mistral), some hosts answer 400
(Google). The sentence goes to the log as a warning with status and kind,
stays with the endpoint's state, and the window that just saved the provider
shows it instead of "Saved, but not reachable". Without a sentence (no answer,
no JSON) the provider is still not reachable on 400, 401 and 403, but says
nothing more; a missing page (404) and every answer below 500 otherwise stay
as they were. The key is never part of any of it. The words of every
provider are read by the one helper in ``app/providers/base.py``.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from app.config import EndpointConfig
from app.i18n import t
from app.providers.base import refusal_of
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

KEY = "sk-test-key-0123456789abcdef"
OPENAI_SENTENCE = "Incorrect API key provided: sk-inval***. You can find your API key at the provider."
GOOGLE_SENTENCE = "Please pass a valid API key."
# The real client, kept before any test stands a transport in for it.
_REAL_CLIENT = httpx.AsyncClient

OPENAI_BODY = {"error": {"message": OPENAI_SENTENCE, "type": "invalid_request_error", "code": "invalid_api_key"}}
# Google answers in a list of one object, with a `status` word in place of `type`.
GOOGLE_BODY = [{"error": {"code": 400, "message": GOOGLE_SENTENCE, "status": "INVALID_ARGUMENT"}}]
MISTRAL_BODY = {"detail": "Invalid API Key"}


def _provider(monkeypatch, handler, key: str = KEY) -> OpenAIKompatiblerProvider:
    monkeypatch.setenv("TEST_OPENAI_KEY", key)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=transport, **kw))
    return OpenAIKompatiblerProvider(EndpointConfig(
        id="cloudhouse", base_url="https://api.example.invalid/v1", provider="openai_compatible",
        api_key_env="TEST_OPENAI_KEY",
    ))


# --- The helper every provider reads a refusal with ---


@pytest.mark.parametrize(("body", "expected"), [
    (OPENAI_BODY, ("invalid_request_error", OPENAI_SENTENCE)),
    (GOOGLE_BODY, ("INVALID_ARGUMENT", GOOGLE_SENTENCE)),
    (MISTRAL_BODY, ("", "Invalid API Key")),
    ({"error": "Bad key"}, ("", "Bad key")),
    ({"message": "Unauthorized"}, ("", "Unauthorized")),
    ({"error": {"code": "invalid_api_key", "message": "No"}}, ("invalid_api_key", "No")),
])
def test_the_sentence_is_found_where_the_providers_put_it(body, expected):
    assert refusal_of(httpx.Response(401, json=body)) == expected


@pytest.mark.parametrize("response", [
    httpx.Response(401, text="Unauthorized"),
    httpx.Response(401, text="<html>no</html>"),
    httpx.Response(400, json={"error": {"type": "x"}}),
    httpx.Response(400, json=["no", "object"]),
    httpx.Response(400, json={"detail": [{"loc": ["body"], "msg": "x"}]}),
    httpx.Response(400, json={"error": {"message": "  "}}),
])
def test_silence_a_body_without_a_sentence_gives_none(response):
    assert refusal_of(response) is None


def test_the_key_is_replaced_and_the_sentence_is_cut():
    answer = httpx.Response(401, json={"error": {"message": f"invalid {KEY} here " + "x" * 600}})
    kind, sentence = refusal_of(answer, KEY)
    assert sentence.startswith("invalid … here ") and KEY not in sentence and len(sentence) == 400


# --- The provider ---


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "body", "kind", "sentence"), [
    (401, OPENAI_BODY, "invalid_request_error", OPENAI_SENTENCE),
    (400, GOOGLE_BODY, "INVALID_ARGUMENT", GOOGLE_SENTENCE),
    (401, MISTRAL_BODY, "", "Invalid API Key"),
    (403, {"error": {"message": "No access", "type": "permission_error"}}, "permission_error", "No access"),
])
async def test_the_sentence_of_a_refusal_is_kept_and_logged(monkeypatch, caplog, status, body, kind, sentence):
    provider = _provider(monkeypatch, lambda request: httpx.Response(status, json=body))
    with caplog.at_level(logging.INFO, logger="app.providers.openai_kompatibel"):
        assert await provider.erreichbar(1.0) is False
    assert provider.letzter_grund == sentence
    warning = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning) == 1
    line = warning[0].getMessage()
    assert str(status) in line and kind in line and sentence in line
    assert KEY not in caplog.text


@pytest.mark.asyncio
async def test_the_key_is_not_part_of_the_reason_even_when_the_sentence_names_it(monkeypatch, caplog):
    provider = _provider(
        monkeypatch,
        lambda request: httpx.Response(401, json={"error": {"message": f"bad key {KEY}", "type": "x"}}),
    )
    with caplog.at_level(logging.INFO, logger="app.providers.openai_kompatibel"):
        await provider.erreichbar(1.0)
    assert provider.letzter_grund == "bad key …"
    assert KEY not in caplog.text


@pytest.mark.asyncio
async def test_a_reason_goes_with_the_next_answer(monkeypatch):
    state = {"status": 401}

    def handler(request):
        if state["status"] == 401:
            return httpx.Response(401, json=OPENAI_BODY)
        return httpx.Response(200, json={"data": []})

    provider = _provider(monkeypatch, handler)
    assert await provider.erreichbar(1.0) is False and provider.letzter_grund == OPENAI_SENTENCE
    state["status"] = 200
    assert await provider.erreichbar(1.0) is True and provider.letzter_grund is None


@pytest.mark.asyncio
async def test_a_refusal_without_a_sentence_is_still_a_refusal_and_is_logged(monkeypatch, caplog):
    provider = _provider(monkeypatch, lambda request: httpx.Response(401, text="Unauthorized"))
    with caplog.at_level(logging.INFO, logger="app.providers.openai_kompatibel"):
        assert await provider.erreichbar(1.0) is False
    assert provider.letzter_grund is None
    warning = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning) == 1 and "401" in warning[0] and "no reason" in warning[0]


@pytest.mark.asyncio
async def test_the_same_refusal_is_told_once_a_changed_one_and_a_later_one_again(monkeypatch, caplog):
    state = {"body": OPENAI_BODY, "status": 401}

    def handler(request):
        if state["status"] == 200:
            return httpx.Response(200, json={"data": []})
        return httpx.Response(state["status"], json=state["body"])

    provider = _provider(monkeypatch, handler)

    async def lines() -> int:
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="app.providers.openai_kompatibel"):
            await provider.erreichbar(1.0)
        return len([r for r in caplog.records if r.levelno == logging.WARNING])

    assert [await lines(), await lines(), await lines()] == [1, 0, 0]
    # The reason itself stays with every answer, told or not.
    assert provider.letzter_grund == OPENAI_SENTENCE
    state["body"] = MISTRAL_BODY
    assert await lines() == 1
    state["status"] = 200
    assert await lines() == 0
    state["status"], state["body"] = 401, MISTRAL_BODY
    assert await lines() == 1


@pytest.mark.asyncio
async def test_silence_every_other_answer_stays_as_it_was(monkeypatch, caplog):
    answers = {
        "200": (lambda request: httpx.Response(200, json={"data": []}), True),
        "404": (lambda request: httpx.Response(404, json={"error": {"message": "no such page"}}), True),
        "429": (lambda request: httpx.Response(429, json={"error": {"message": "slow down"}}), True),
        "500": (lambda request: httpx.Response(500, json={"error": {"message": "broken"}}), False),
        "503": (lambda request: httpx.Response(503, text="<html>oops</html>"), False),
    }
    for name, (handler, reachable) in answers.items():
        provider = _provider(monkeypatch, handler)
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="app.providers.openai_kompatibel"):
            assert await provider.erreichbar(1.0) is reachable, name
        assert provider.letzter_grund is None, name
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING], name


@pytest.mark.asyncio
async def test_a_timeout_has_no_reason(monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("no answer", request=request)

    provider = _provider(monkeypatch, handler)
    assert await provider.erreichbar(1.0) is False
    assert provider.letzter_grund is None


# --- The route that saves a provider ---


def _add(client, monkeypatch, tmp_path, handler, body):
    from app import paketierung

    monkeypatch.setattr(paketierung, "daten", lambda: tmp_path)
    (tmp_path / "config.yaml").write_text("endpoints: []\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "vorher")
    monkeypatch.setenv("HAUS_API_KEY", "vorher")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=transport, **kw))
    return client.post("/api/v1/providers", json=body)


def _sentences(name: str, message: str) -> set[str]:
    return {
        t("fehler.anbieter_nicht_erreichbar", lang, name=name, detail=message)
        for lang in ("de", "en")
    }


def test_the_answer_of_saving_carries_the_sentence_and_the_state_the_reason(client, monkeypatch, tmp_path):
    answer = _add(
        client, monkeypatch, tmp_path, lambda request: httpx.Response(401, json=OPENAI_BODY),
        {"art": "openai", "schluessel": KEY},
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["erreichbar"] is False
    assert body["hinweis"] in _sentences("openai", OPENAI_SENTENCE)
    assert KEY not in answer.text
    zustand = client.app.state.discovery.zustaende["openai"]
    assert zustand.grund == OPENAI_SENTENCE
    assert zustand.als_dict()["grund"] == OPENAI_SENTENCE


def test_an_own_provider_that_answers_a_wrong_key_with_400_is_not_reachable_and_says_why(
    client, monkeypatch, tmp_path,
):
    answer = _add(
        client, monkeypatch, tmp_path, lambda request: httpx.Response(400, json=GOOGLE_BODY),
        {"art": "eigen", "kennung": "haus", "schluessel": KEY,
         "url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["erreichbar"] is False
    assert body["hinweis"] in _sentences("haus", GOOGLE_SENTENCE)
    assert client.app.state.discovery.zustaende["haus"].grund == GOOGLE_SENTENCE


def test_silence_saving_a_working_provider_or_a_dead_one_says_what_it_said_before(client, monkeypatch, tmp_path):
    ok = _add(
        client, monkeypatch, tmp_path, lambda request: httpx.Response(200, json={"data": []}),
        {"art": "openai", "schluessel": KEY},
    )
    assert ok.status_code == 200
    assert ok.json() == {"id": "openai", "api_key_env": "OPENAI_API_KEY", "erreichbar": True, "hinweis": None}
    assert client.app.state.discovery.zustaende["openai"].grund is None


def test_silence_a_provider_that_does_not_answer_has_no_sentence(client, monkeypatch, tmp_path):
    def handler(request):
        raise httpx.ConnectTimeout("no answer", request=request)

    answer = _add(client, monkeypatch, tmp_path, handler, {"art": "openai", "schluessel": KEY})
    assert answer.status_code == 200
    assert answer.json()["erreichbar"] is False and answer.json()["hinweis"] is None
    assert client.app.state.discovery.zustaende["openai"].grund is None


def test_the_model_list_carries_the_sentence_for_the_windows(client, monkeypatch, tmp_path):
    """The windows read the sentence from the list of models (``/models?alle=true``)
    — an unreachable provider is in it."""
    answer = _add(
        client, monkeypatch, tmp_path, lambda request: httpx.Response(401, json=OPENAI_BODY),
        {"art": "openai", "schluessel": KEY},
    )
    assert answer.status_code == 200, answer.text
    listed = client.get("/api/v1/models", params={"alle": "true"}).json()
    house = [m for m in listed if m["anbieter"] == "openai"]
    assert house and all(m["erreichbar"] is False and m["grund"] == OPENAI_SENTENCE for m in house), house
    assert KEY not in str(listed)
