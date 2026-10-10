"""The answer ran into its length limit — and the program finally says so.

Two silence probes stand in here, because "reports a cut-off answer" and
"stays quiet about a complete one" are two different claims and only the
pair of them is worth anything: a note that always appears is exactly as
useless as one that never does.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import antwortende
from app.config import EndpointConfig
from app.providers.anthropic import AnthropicProvider
from app.providers.base import ChatNachricht, Generierungsanfrage, ProviderFehler
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider


# --- The vocabulary -------------------------------------------------------


def test_jedes_backend_hat_sein_eigenes_wort_dafuer():
    assert antwortende.abgeschnitten("length")
    assert antwortende.abgeschnitten("max_tokens")
    assert antwortende.abgeschnitten("MAX_TOKENS")


def test_ein_normales_ende_ist_kein_abschnitt():
    assert not antwortende.abgeschnitten("stop")
    assert not antwortende.abgeschnitten("end_turn")
    assert not antwortende.abgeschnitten("tool_calls")


def test_ohne_wort_wird_nichts_behauptet():
    """A wrong silence costs a note. A wrong claim calls a whole answer a
    fragment."""
    assert not antwortende.abgeschnitten(None)
    assert not antwortende.abgeschnitten("")
    assert not antwortende.abgeschnitten("etwas_neues")


def test_volles_kontextfenster_zaehlt_auch_als_abgeschnitten():
    assert antwortende.abgeschnitten("model_context_window_exceeded")
    assert antwortende.kontextfenster_voll("model_context_window_exceeded")


def test_kontextfenster_voll_ist_die_engere_frage():
    """The answer's own length cap sets `abgeschnitten` too, but it is not
    the context-window case — the silence probe the hint under the answer
    relies on to pick the right wording."""
    assert not antwortende.kontextfenster_voll("length")
    assert not antwortende.kontextfenster_voll("max_tokens")
    assert not antwortende.kontextfenster_voll(None)
    assert not antwortende.kontextfenster_voll("end_turn")


# --- The window behind the word -------------------------------------------


def test_llama_cpp_meldet_das_volle_fenster_als_laengenende():
    """The numbers measured on a llama-server with a 256-token window: the
    prompt and the answer together fill it exactly, and the only word that
    came back was `length`."""
    assert antwortende.fenster_voll(
        "length", gesamt_tokens=150 + 106, fenster=256, eigene_grenze=True
    )


def test_mit_luft_im_fenster_bleibt_es_das_laengenende():
    """The same word, the same self-set ceiling — and a window with room to
    spare. Then the length really was the reason and the hint has to say so."""
    assert not antwortende.fenster_voll(
        "length", gesamt_tokens=150 + 106, fenster=8_192, eigene_grenze=True
    )


def test_ohne_bekanntes_fenster_zaehlt_nur_der_grund():
    """Nothing is claimed from a size nobody resolved."""
    assert not antwortende.fenster_voll(
        "length", gesamt_tokens=5_000, fenster=None, eigene_grenze=True
    )


def test_eine_grenze_die_niemand_gesetzt_hat_ist_das_fenster():
    """Under Auto the ceiling IS what is left of the window — where the
    numbers say the window really ran out. A window nobody confirmed keeps
    that reading, because then the end reason is all there is."""
    assert antwortende.fenster_voll("length", gesamt_tokens=8_192, fenster=8_192)
    assert antwortende.fenster_voll("length", gesamt_tokens=None, fenster=None)


def test_eine_grenze_die_niemand_gesetzt_hat_mit_luft_ist_der_anbieter():
    """The same ending with room left in the window: then it was a limit of
    the PROVIDER's — a maker's number, a learned cap, or a server deciding
    the length itself. Saying "context window full" there would
    be wrong, and the answer-length setting was never touched."""
    assert not antwortende.fenster_voll("length", gesamt_tokens=8_128, fenster=8_192)
    assert antwortende.anbietergrenze("length", gesamt_tokens=8_128, fenster=8_192)
    # A ceiling the user DID set is the user's own length, not the provider's.
    assert not antwortende.anbietergrenze(
        "length", gesamt_tokens=8_128, fenster=8_192, eigene_grenze=True
    )
    # Anthropic's own word for a full window stays a full window.
    assert not antwortende.anbietergrenze(
        "model_context_window_exceeded", gesamt_tokens=10, fenster=8_192
    )
    # An unknown window: no claim either way.
    assert not antwortende.anbietergrenze("length", gesamt_tokens=10, fenster=None)
    # A finished answer says nothing at all.
    assert not antwortende.anbietergrenze("stop", gesamt_tokens=10, fenster=8_192)


def test_anthropics_eigenes_wort_zaehlt_ohne_jede_zahl():
    assert antwortende.fenster_voll(
        "model_context_window_exceeded", eigene_grenze=True, fenster=1_000_000
    )


def test_denken_das_die_laenge_aufbraucht_wird_erkannt():
    """A length stop, thinking the server labelled as thinking, and nothing
    visible after it: the model spent its whole output budget reasoning."""
    assert antwortende.denken_aufgebraucht(
        "length", denktext="Let me think...", sichtbarer_text=""
    )
    # Visible text after the thinking: the answer was cut off, but something
    # was said — that is the ordinary "cut off" note.
    assert not antwortende.denken_aufgebraucht(
        "length", denktext="Let me think...", sichtbarer_text="Here is the"
    )
    # Whitespace is not visible text.
    assert antwortende.denken_aufgebraucht(
        "length", denktext="hm", sichtbarer_text="   \n"
    )
    # No thinking at all: an empty answer cut off at its length, nothing more.
    assert not antwortende.denken_aufgebraucht("length", denktext="", sichtbarer_text="")
    assert not antwortende.denken_aufgebraucht("length", denktext=None, sichtbarer_text="")
    # A finished answer says nothing.
    assert not antwortende.denken_aufgebraucht("stop", denktext="hm", sichtbarer_text="")
    # A full window is its own reason and wins.
    assert not antwortende.denken_aufgebraucht(
        "model_context_window_exceeded", denktext="hm", sichtbarer_text=""
    )


def test_das_natuerliche_ende_kennt_beide_worte():
    """The words that mean the model ended it by itself.

    Two backends, two spellings (``stop``/``end_turn``), and a server that
    hands the word over in capitals or with space around it — all of those
    are the model's own ending. Everything else is somebody else's: a length
    stop, a full window, a tool call, a refusal. And an unknown word never
    passes for a finished answer, which is why nothing else counts.
    """
    for wort in ("stop", "end_turn", "STOP", " end_turn "):
        assert antwortende.natuerliches_ende(wort)
    for wort in (
        "length",
        "max_tokens",
        "model_context_window_exceeded",
        "tool_calls",
        "tool_use",
        "content_filter",
        "",
        None,
        7,
    ):
        assert not antwortende.natuerliches_ende(wort)


def test_ein_normales_ende_bleibt_still_wie_voll_das_fenster_auch_ist():
    """The silence probe: a finished answer stays a finished answer even
    where its round happened to fill the window to the last token."""
    for grund in ("stop", "end_turn", "tool_calls", None, ""):
        assert not antwortende.fenster_voll(grund, gesamt_tokens=256, fenster=256)


# --- Through the stream ---------------------------------------------------


def _transport(*pakete: dict) -> httpx.MockTransport:
    zeilen = "".join(f"data: {json.dumps(p)}\n\n" for p in pakete) + "data: [DONE]\n\n"
    return httpx.MockTransport(
        lambda _: httpx.Response(
            200, text=zeilen, headers={"content-type": "text/event-stream"}
        )
    )


async def _messwerte(provider, transport) -> dict:
    echt = httpx.AsyncClient
    try:
        httpx.AsyncClient = lambda **kw: echt(transport=transport, **kw)
        stuecke = [
            s
            async for s in provider.streamen(
                Generierungsanfrage(
                    nachrichten=[ChatNachricht(role="user", content="Hallo")]
                )
            )
        ]
    finally:
        httpx.AsyncClient = echt
    return next(s.daten for s in stuecke if s.sorte == "stats")


def _openai(dialekt: str = "llama_cpp") -> OpenAIKompatiblerProvider:
    return OpenAIKompatiblerProvider(
        EndpointConfig.model_validate({
            "id": "p", "name": "P", "base_url": "http://x/v1",
            "parameter_dialect": dialekt,
        })
    )


def _anthropic() -> AnthropicProvider:
    return AnthropicProvider(
        EndpointConfig.model_validate({
            "id": "a", "name": "A", "base_url": "http://x/v1",
            "provider": "anthropic", "parameter_dialect": "anthropic",
            "api_key_env": "TEST_SCHLUESSEL",
        })
    )


@pytest.mark.asyncio
async def test_die_abgeschnittene_antwort_meldet_sich():
    messwerte = await _messwerte(_openai(), _transport(
        {"choices": [{"index": 0, "delta": {"content": "Ich denke nach"}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]},
    ))
    assert messwerte["ende_grund"] == "length"
    assert messwerte["abgeschnitten"] is True
    assert messwerte["kontextfenster_voll"] is False


@pytest.mark.asyncio
async def test_die_vollstaendige_antwort_schweigt():
    messwerte = await _messwerte(_openai(), _transport(
        {"choices": [{"index": 0, "delta": {"content": "Fertig"}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ))
    assert messwerte["abgeschnitten"] is False


@pytest.mark.asyncio
async def test_ohne_jede_angabe_ist_der_anbieter_ausgefallen():
    """A stream that names no reason at all never reaches the metrics.

    It is not an answer with an unknown ending: it is a provider that
    stopped mid-answer (as measured on an mlx server whose model was
    unloaded while writing). The reading of an unknown reason itself is
    unchanged — nothing is claimed about it — but there is no metrics block
    to read it from any more.
    """
    with pytest.raises(ProviderFehler):
        await _messwerte(_openai(), _transport(
            {"choices": [{"index": 0, "delta": {"content": "Fertig"}}]},
        ))
    assert antwortende.abgeschnitten(None) is False


@pytest.mark.asyncio
async def test_anthropic_ohne_ende_ist_ein_ausfall(monkeypatch):
    """The same reading for the Anthropic protocol: a stream that closes
    without a `message_delta` naming its `stop_reason` is a provider that
    stopped mid-answer — and there is NO metrics block: the half answer
    must not be stored as a whole one."""
    monkeypatch.setenv("TEST_SCHLUESSEL", "geheim")
    echt = httpx.AsyncClient
    httpx.AsyncClient = lambda **kw: echt(
        transport=_transport(
            {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Fertig"}},
        ),
        **kw,
    )
    gesehen = []
    try:
        with pytest.raises(ProviderFehler) as fehler:
            async for stueck in _anthropic().streamen(
                Generierungsanfrage(
                    nachrichten=[ChatNachricht(role="user", content="Hallo")]
                )
            ):
                gesehen.append(stueck)
    finally:
        httpx.AsyncClient = echt
    assert fehler.value.key == "fehler.anbieter_ende_fehlt"
    assert [s for s in gesehen if s.sorte == "stats"] == []


@pytest.mark.asyncio
async def test_anthropic_meldet_es_mit_seinem_eigenen_wort(monkeypatch):
    monkeypatch.setenv("TEST_SCHLUESSEL", "geheim")
    messwerte = await _messwerte(_anthropic(), _transport(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Ich denke"}},
        {"type": "message_delta", "delta": {"stop_reason": "max_tokens"},
         "usage": {"output_tokens": 12}},
    ))
    assert messwerte["abgeschnitten"] is True
    assert messwerte["kontextfenster_voll"] is False


@pytest.mark.asyncio
async def test_anthropic_meldet_das_volle_kontextfenster(monkeypatch):
    """The window ran out, not the answer's own length setting — both stop
    the run the same way, but the hint under the answer needs to tell them
    apart."""
    monkeypatch.setenv("TEST_SCHLUESSEL", "geheim")
    messwerte = await _messwerte(_anthropic(), _transport(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Ich denke"}},
        {"type": "message_delta",
         "delta": {"stop_reason": "model_context_window_exceeded"},
         "usage": {"output_tokens": 12}},
    ))
    assert messwerte["abgeschnitten"] is True
    assert messwerte["kontextfenster_voll"] is True


@pytest.mark.asyncio
async def test_anthropic_schweigt_beim_normalen_ende(monkeypatch):
    monkeypatch.setenv("TEST_SCHLUESSEL", "geheim")
    messwerte = await _messwerte(_anthropic(), _transport(
        {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Fertig"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 3}},
    ))
    assert messwerte["abgeschnitten"] is False
