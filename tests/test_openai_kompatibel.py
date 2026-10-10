"""A server that fails in the middle of a stream says why, and the round
ends with its words.

The 200 is long sent by then, so the failure comes as one last packet with
an ``error`` object, and the stream closes without naming an end. Read as an
ordinary packet it held no choice and passed unnoticed; all that was left to
say was that the stream reported no ending.

Driven through the real stream reader against the stub server of
tests/test_openai_provider.py.
"""

from __future__ import annotations

import json

import pytest

from app.providers.base import ProviderFehler
from tests import test_openai_provider
from tests.test_openai_provider import _einsammeln, _provider, _text

# The stub OpenAI-compatible server, borrowed as a fixture.
modellserver = test_openai_provider.modellserver

TEXT = 'data: {"choices": [{"delta": {"content": "Half"}, "index": 0}]}\n\n'
END = 'data: {"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}]}\n\n'
KV_CACHE = {
    "code": 400,
    "message": "failed to find 7909 available cells in kv cache",
    "type": "exceed_context_size_error",
}


def _error_packet(error) -> str:
    return f"data: {json.dumps({'error': error})}\n\n"


async def _read(provider):
    """The pieces a stream handed out, and the error that ended it."""
    from app.providers.base import ChatNachricht, Generierungsanfrage

    pieces = []
    try:
        async for piece in provider.streamen(
            Generierungsanfrage(nachrichten=[ChatNachricht(role="user", content="Hello")])
        ):
            pieces.append(piece)
    except ProviderFehler as error:
        return pieces, error
    return pieces, None


@pytest.mark.asyncio
async def test_an_error_packet_ends_the_stream_with_the_servers_words(modellserver):
    modellserver.rohzeilen = [TEXT, _error_packet(KV_CACHE)]

    _, error = await _read(_provider(modellserver.basis))

    assert error is not None, "the error packet passed unnoticed"
    assert error.key == "fehler.anbieter_antwortet_mit"
    assert str(error) == (
        "Prüflabor answered with 400: failed to find 7909 available cells in kv cache"
    )
    assert error.text("de") == (
        "Prüflabor hat mit 400 geantwortet: failed to find 7909 available cells in kv cache"
    )
    assert error.status == 400


@pytest.mark.asyncio
async def test_what_came_before_the_error_packet_was_still_handed_out(modellserver):
    modellserver.rohzeilen = [TEXT, _error_packet(KV_CACHE)]

    pieces, error = await _read(_provider(modellserver.basis))

    assert _text(pieces, "content") == "Half"
    assert error is not None and error.key == "fehler.anbieter_antwortet_mit"


@pytest.mark.asyncio
async def test_an_error_packet_as_the_first_packet_ends_the_stream_too(modellserver):
    modellserver.rohzeilen = [_error_packet(KV_CACHE), TEXT, END]

    pieces, error = await _read(_provider(modellserver.basis))

    assert _text(pieces, "content") == ""
    assert error is not None and error.key == "fehler.anbieter_antwortet_mit"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "sentence"),
    [
        # A code in words stands where the status would, and is no status.
        ({"message": "Rate limit reached", "type": "requests", "code": "rate_limit_exceeded"},
         "Prüflabor answered with rate_limit_exceeded: Rate limit reached"),
        # No code at all: the kind of error the server named.
        ({"message": "The server had an error", "type": "server_error", "code": None},
         "Prüflabor answered with server_error: The server had an error"),
        # No message: the kind is all there is to say.
        ({"type": "server_error"}, "Prüflabor answered with server_error: server_error"),
        # Some servers write the error as one plain sentence.
        ("the model crashed", "Prüflabor answered with error: the model crashed"),
    ],
)
async def test_an_error_without_a_number_is_named_by_what_the_server_gave(
    modellserver, error, sentence
):
    modellserver.rohzeilen = [TEXT, _error_packet(error)]

    _, failure = await _read(_provider(modellserver.basis))

    assert failure is not None and str(failure) == sentence
    assert failure.status is None


# --- the silence probes ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stream_that_names_its_end_ends_as_before(modellserver):
    modellserver.rohzeilen = [TEXT, END]

    pieces = await _einsammeln(_provider(modellserver.basis))

    assert _text(pieces, "content") == "Half"


@pytest.mark.asyncio
async def test_a_stream_that_breaks_off_without_either_still_reports_no_ending(modellserver):
    modellserver.rohzeilen = [TEXT]

    _, error = await _read(_provider(modellserver.basis))

    assert error is not None and error.key == "fehler.anbieter_ende_fehlt"
    assert str(error) == "The answer from Prüflabor reported no ending"


@pytest.mark.asyncio
async def test_an_empty_error_field_in_an_ordinary_packet_is_no_error(modellserver):
    packet = {"choices": [{"delta": {"content": "Half"}, "index": 0}], "error": None}
    modellserver.rohzeilen = [f"data: {json.dumps(packet)}\n\n", END]

    pieces, error = await _read(_provider(modellserver.basis))

    assert error is None
    assert _text(pieces, "content") == "Half"
