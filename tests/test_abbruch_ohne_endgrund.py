"""A stream that ends without ever saying why is a provider that broke off.

Measured on an mlx server whose model was unloaded while it was
writing: the abort arrived as ordinary ``delta.content`` — a sentence
beginning "[Error: Request aborted …" — with no ``finish_reason``, no
``usage`` and no HTTP error. Read as an answer, the half of it that arrived
was stored and shown as a whole one, and a fold put that sentence in place
of the conversation it replaced.

The reading here is the PROTOCOL, never the text: a finished answer always
names its end (stop, length, tool_calls — measured on mlx, llama.cpp and
vLLM), so a stream that names none is a break-off, whatever it carried. A
text pattern on the content would be a second, weaker answer to the same
question, and every provider writes a different sentence.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import EndpointConfig
from app.providers.base import ChatNachricht, Generierungsanfrage, ProviderFehler
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

# The end of a stream measured on the check service, word for word.
ABBRUCHTEXT = (
    "\n\n[Error: Request aborted: process memory limit exceeded (usage 54.9 GB, "
    "abort threshold (hard watermark) 53.8 GB, dynamic ceiling 56.6 GB).]"
)


def _transport(*pakete: dict, done: bool = True) -> httpx.MockTransport:
    zeilen = "".join(f"data: {json.dumps(p)}\n\n" for p in pakete)
    if done:
        zeilen += "data: [DONE]\n\n"
    return httpx.MockTransport(
        lambda _: httpx.Response(
            200, text=zeilen, headers={"content-type": "text/event-stream"}
        )
    )


def _provider() -> OpenAIKompatiblerProvider:
    return OpenAIKompatiblerProvider(
        EndpointConfig.model_validate({
            "id": "p", "name": "P", "base_url": "http://x/v1",
            "parameter_dialect": "openai",
        })
    )


async def _stuecke(transport) -> list:
    echt = httpx.AsyncClient
    try:
        httpx.AsyncClient = lambda **kw: echt(transport=transport, **kw)
        return [
            s
            async for s in _provider().streamen(
                Generierungsanfrage(
                    nachrichten=[ChatNachricht(role="user", content="Hallo")]
                )
            )
        ]
    finally:
        httpx.AsyncClient = echt


@pytest.mark.asyncio
async def test_der_abbruchtext_endet_die_runde_als_ausfall():
    """Content, then the abort as content, then ``[DONE]`` — and no reason."""
    with pytest.raises(ProviderFehler):
        await _stuecke(_transport(
            {"choices": [{"index": 0, "delta": {"content": "Here is the list:"}}]},
            {"choices": [{"index": 0, "delta": {"content": ABBRUCHTEXT}}]},
        ))


@pytest.mark.asyncio
async def test_ein_strom_ohne_done_endet_ebenso():
    """The other shape of the same break-off: the connection simply closes."""
    with pytest.raises(ProviderFehler):
        await _stuecke(_transport(
            {"choices": [{"index": 0, "delta": {"content": "Here is the list:"}}]},
            done=False,
        ))


@pytest.mark.asyncio
async def test_ein_halber_werkzeugaufruf_wird_nicht_ausgefuehrt():
    """The arguments of a call are only complete once the stream says so.

    Handing out a call whose arguments broke off mid-sentence would run a
    command nobody wrote.
    """
    with pytest.raises(ProviderFehler):
        await _stuecke(_transport(
            {"choices": [{"index": 0, "delta": {"tool_calls": [{
                "index": 0, "id": "w1", "type": "function",
                "function": {"name": "run_command", "arguments": '{"command": "rm -'},
            }]}}]},
        ))


@pytest.mark.asyncio
@pytest.mark.parametrize("grund", ["stop", "length", "tool_calls"])
async def test_schweigeprobe_jeder_genannte_grund_bleibt_wie_er_ist(grund):
    """Every stream that names its end is read exactly as before."""
    stuecke = await _stuecke(_transport(
        {"choices": [{"index": 0, "delta": {"content": "Fertig"}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": grund}]},
    ))
    messwerte = next(s.daten for s in stuecke if s.sorte == "stats")
    assert messwerte["ende_grund"] == grund


@pytest.mark.asyncio
async def test_der_inhalt_vor_dem_abbruch_reist_wie_immer():
    """Nothing is searched for and nothing removed: what arrived, arrived.

    The pieces before the break-off are handed out as they were; only the
    round's end changes.
    """
    gesehen: list[str] = []
    with pytest.raises(ProviderFehler):
        echt = httpx.AsyncClient
        transport = _transport(
            {"choices": [{"index": 0, "delta": {"content": "Here is the list:"}}]},
            {"choices": [{"index": 0, "delta": {"content": ABBRUCHTEXT}}]},
        )
        try:
            httpx.AsyncClient = lambda **kw: echt(transport=transport, **kw)
            async for stueck in _provider().streamen(
                Generierungsanfrage(
                    nachrichten=[ChatNachricht(role="user", content="Hallo")]
                )
            ):
                if stueck.sorte == "content":
                    gesehen.append(stueck.text)
        finally:
            httpx.AsyncClient = echt
    assert "".join(gesehen) == "Here is the list:" + ABBRUCHTEXT
