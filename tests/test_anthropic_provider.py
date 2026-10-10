"""Anthropic speaks its own protocol — this pins down the translation.

Everything here is about the two directions: our request into the shape the
Messages API wants, and its typed stream events back into our chunks.
Nothing talks to the network; the stream is fed in as raw lines.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from app.config import EndpointConfig
from app.providers import provider_bauen
from app.providers.anthropic import API_VERSION, AnthropicProvider
from app.providers.base import ChatNachricht, Generierungsanfrage, Werkzeugaufruf


def endpunkt(**felder) -> EndpointConfig:
    return EndpointConfig.model_validate({
        "id": "anthropic",
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "parameter_dialect": "anthropic",
        "api_key_env": "TEST_ANTHROPIC_KEY",
        **felder,
    })


def bauen(**felder) -> AnthropicProvider:
    return AnthropicProvider(endpunkt(**felder))


def ohne_marken(nachrichten: list[dict]) -> list[dict]:
    """The messages as the translation built them, before the cache marks —
    for the tests that pin down the translation and not the marks. A block
    that only turned into a list to carry a mark reads as its string again."""
    raus = []
    for n in nachrichten:
        inhalt = n["content"]
        if isinstance(inhalt, list):
            inhalt = [{k: v for k, v in b.items() if k != "cache_control"} for b in inhalt]
        raus.append({**n, "content": inhalt})
    return raus


MARKE = {"type": "ephemeral"}


# --- Registry -------------------------------------------------------------


def test_anthropic_ist_ein_eigener_anbieter():
    assert isinstance(provider_bauen(endpunkt()), AnthropicProvider)


# --- Headers --------------------------------------------------------------


def test_der_schluessel_reist_als_x_api_key(monkeypatch):
    """Not as a bearer token — the Messages API would reject that."""
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "geheim")
    kopf = bauen()._kopfzeilen
    assert kopf["x-api-key"] == "geheim"
    assert "Authorization" not in kopf


def test_die_version_reist_immer_mit(monkeypatch):
    monkeypatch.delenv("TEST_ANTHROPIC_KEY", raising=False)
    kopf = bauen()._kopfzeilen
    assert kopf["anthropic-version"] == API_VERSION
    # No key set: the header stays away and the API answers 401. A silent
    # workaround would be worse than a clear error.
    assert "x-api-key" not in kopf


# --- Request body ---------------------------------------------------------


def test_der_systemprompt_steht_oben_und_nicht_im_verlauf():
    koerper = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=[
        ChatNachricht(role="system", content="Sei kurz."),
        ChatNachricht(role="user", content="Hallo"),
    ]))
    assert koerper["system"] == [{"type": "text", "text": "Sei kurz.", "cache_control": MARKE}]
    assert [n["role"] for n in koerper["messages"]] == ["user"]


def test_mehrere_systemnachrichten_werden_zu_einer():
    koerper = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=[
        ChatNachricht(role="system", content="Eins"),
        ChatNachricht(role="system", content="Zwei"),
        ChatNachricht(role="user", content="Hallo"),
    ]))
    assert koerper["system"][0]["text"] == "Eins\n\nZwei"
    assert len(koerper["system"]) == 1


def test_die_antwortlaenge_geht_immer_mit():
    """max_tokens is required here — a missing limit is an error. There is no
    shipped number behind it any more: every request has a ceiling resolved
    for it before it is built (app/antwortgrenze.py), and a second answer
    here would only hide the day one is missing."""
    koerper = bauen()._koerper_bauen(Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hallo")],
        max_tokens=128_000,
    ))
    assert koerper["max_tokens"] == 128_000


def test_die_eingestellte_antwortlaenge_gewinnt():
    koerper = bauen()._koerper_bauen(Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hallo")],
        max_tokens=1234,
    ))
    assert koerper["max_tokens"] == 1234


def test_was_der_dialekt_nicht_kennt_faellt_weg():
    """Anthropic knows no seed and no penalties — sending them would be a 400."""
    koerper = bauen()._koerper_bauen(Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hallo")],
        temperature=0.7,
        parameter={"seed": 42, "presence_penalty": 1.0, "top_k": 20},
    ))
    assert koerper["temperature"] == 0.7
    assert koerper["top_k"] == 20
    assert "seed" not in koerper
    assert "presence_penalty" not in koerper


@pytest.mark.parametrize("denken", [
    {"type": "adaptive"},
    {"type": "enabled", "budget_tokens": 8_000},
])
def test_das_denken_wird_als_zusammenfassung_verlangt(denken):
    """The chat shows the thinking live, so the request asks for it as a
    readable summary — whichever of the two thinking kinds is on. What else
    the object carries stays as it was."""
    anfrage = Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hallo")],
        max_tokens=16_000,
        zusatz={"thinking": denken},
    )
    koerper = bauen()._koerper_bauen(anfrage)
    assert koerper["thinking"] == {**denken, "display": "summarized"}
    # The request's own object is not written into: it is read again for the
    # next round of the same run.
    assert "display" not in anfrage.zusatz["thinking"]


def test_eine_genannte_anzeige_bleibt_stehen():
    """A display the request already names is its own choice and is kept."""
    koerper = bauen()._koerper_bauen(Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hallo")],
        zusatz={"thinking": {"type": "adaptive", "display": "omitted"}},
    ))
    assert koerper["thinking"] == {"type": "adaptive", "display": "omitted"}


@pytest.mark.parametrize(("adresse", "fragt"), [
    ("https://compat.example.net/anthropic/v1", False),
    # A name that merely CONTAINS Anthropic's, and a proxy whose PATH does:
    # both are somebody else's machine.
    ("https://api.anthropic.com.example.net/v1", False),
    ("https://proxy.test/api.anthropic.com/v1", False),
    # A real sub-domain is Anthropic's own.
    ("https://eu.api.anthropic.com/v1", True),
])
def test_nur_anthropics_eigener_wirt_bekommt_die_anzeige(adresse, fragt):
    """Only Anthropic's own host is asked for the summary. A server that
    merely speaks the dialect may check the object strictly, and a refusal
    naming `thinking` would be booked against the stage itself."""
    koerper = bauen(base_url=adresse)._koerper_bauen(
        Generierungsanfrage(
            nachrichten=[ChatNachricht(role="user", content="Hallo")],
            zusatz={"thinking": {"type": "adaptive"}},
        )
    )
    assert ("display" in koerper["thinking"]) is fragt


def test_ohne_denken_verlangt_die_anfrage_keine_zusammenfassung():
    """The silence probe: a request that does not think carries no display —
    not without a thinking object, and not with one that switches it off."""
    ohne = bauen()._koerper_bauen(Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hallo")],
    ))
    assert "thinking" not in ohne
    aus = bauen()._koerper_bauen(Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hallo")],
        zusatz={"thinking": {"type": "disabled"}},
    ))
    assert aus["thinking"] == {"type": "disabled"}


def test_werkzeuge_bekommen_input_schema_statt_parameters():
    koerper = bauen()._koerper_bauen(Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hallo")],
        werkzeuge=[{
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Führt aus",
                "parameters": {"type": "object", "properties": {"befehl": {"type": "string"}}},
            },
        }],
    ))
    assert koerper["tools"] == [{
        "name": "run_command",
        "description": "Führt aus",
        "input_schema": {"type": "object", "properties": {"befehl": {"type": "string"}}},
    }]


def test_ein_werkzeugaufruf_wird_zu_einem_block_der_antwort():
    koerper = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=[
        ChatNachricht(role="user", content="Wie spät?"),
        ChatNachricht(
            role="assistant", content="",
            werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="uhr", argumente={"ort": "Berlin"})],
        ),
        ChatNachricht(role="tool", content="12:00", werkzeugaufruf_id="a1"),
    ]))
    assistent = ohne_marken(koerper["messages"])[1]
    assert assistent["content"] == [
        {"type": "tool_use", "id": "a1", "name": "uhr", "input": {"ort": "Berlin"}}
    ]
    # The result is a block inside a user message, not a role of its own.
    assert ohne_marken(koerper["messages"])[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "a1", "content": "12:00"}],
    }


def test_mehrere_ergebnisse_landen_in_einer_nachricht():
    """Two user turns in a row are rejected — they belong together."""
    koerper = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=[
        ChatNachricht(role="user", content="Los"),
        ChatNachricht(
            role="assistant", content="",
            werkzeugaufrufe=[
                Werkzeugaufruf(id="a1", name="x"), Werkzeugaufruf(id="a2", name="y"),
            ],
        ),
        ChatNachricht(role="tool", content="eins", werkzeugaufruf_id="a1"),
        ChatNachricht(role="tool", content="zwei", werkzeugaufruf_id="a2"),
    ]))
    assert len(koerper["messages"]) == 3
    assert len(koerper["messages"][2]["content"]) == 2


def test_ein_plainer_user_zug_nach_werkzeugergebnissen_wird_angehaengt():
    """A folded tool-result message is itself role "user" — a plain user
    message right after it must fold into the SAME turn too, or two user
    turns stand back to back and Anthropic rejects the request."""
    koerper = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=[
        ChatNachricht(role="user", content="Los"),
        ChatNachricht(
            role="assistant", content="", werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="x")],
        ),
        ChatNachricht(role="tool", content="eins", werkzeugaufruf_id="a1"),
        ChatNachricht(role="user", content="Fass zusammen."),
    ]))
    assert len(koerper["messages"]) == 3
    letzter = ohne_marken(koerper["messages"])[2]
    assert letzter["role"] == "user"
    assert letzter["content"] == [
        {"type": "tool_result", "tool_use_id": "a1", "content": "eins"},
        {"type": "text", "text": "Fass zusammen."},
    ]


def test_zwei_plaine_user_zuege_hintereinander_werden_gefaltet():
    """The same fold, without any tool call in between — a fresh
    conversation's very first two turns being "user" is just as invalid."""
    koerper = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=[
        ChatNachricht(role="user", content="Los"),
        ChatNachricht(role="user", content="Fass zusammen."),
    ]))
    assert ohne_marken(koerper["messages"]) == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Los"},
                {"type": "text", "text": "Fass zusammen."},
            ],
        }
    ]


def _marken(koerper) -> list[tuple[str, int]]:
    """Where the marks sit: ("system", block) or (role, message index)."""
    orte = [
        ("system", i)
        for i, b in enumerate(koerper.get("system") or [])
        if "cache_control" in b
    ]
    for i, n in enumerate(koerper["messages"]):
        if isinstance(n["content"], list):
            orte += [(n["role"], i) for b in n["content"] if "cache_control" in b]
    return orte


def test_ein_langer_verlauf_bekommt_vier_marken_am_system_und_den_letzten_drei():
    """Four marks, the most a request may hold: the system prompt, which holds
    still across the conversation, and the three newest messages, each on its
    last block. Five minutes — no ttl field."""
    verlauf = [ChatNachricht(role="system", content="Sei kurz.")]
    for i in range(4):
        verlauf += [
            ChatNachricht(role="user", content=f"Frage {i}"),
            ChatNachricht(role="assistant", content=f"Antwort {i}"),
        ]
    verlauf.append(ChatNachricht(role="user", content="Letzte"))
    koerper = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=verlauf))
    assert _marken(koerper) == [("system", 0), ("user", 6), ("assistant", 7), ("user", 8)]
    assert koerper["messages"][8]["content"] == [
        {"type": "text", "text": "Letzte", "cache_control": MARKE}
    ]
    # Everything older goes out untouched.
    assert koerper["messages"][5] == {"role": "assistant", "content": "Antwort 2"}


def test_eine_einzige_nachricht_bekommt_zwei_marken():
    koerper = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=[
        ChatNachricht(role="system", content="Sei kurz."),
        ChatNachricht(role="user", content="Hallo"),
    ]))
    assert _marken(koerper) == [("system", 0), ("user", 0)]


def test_die_marke_sitzt_am_letzten_block_und_nicht_an_leerem():
    """A tool result is a block that can carry a mark; an empty turn cannot
    — the API refuses a mark on an empty text block — and is passed over."""
    koerper = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=[
        ChatNachricht(role="user", content="Los"),
        ChatNachricht(
            role="assistant", content="", werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="x")],
        ),
        ChatNachricht(role="tool", content="eins", werkzeugaufruf_id="a1"),
    ]))
    assert "system" not in koerper
    assert _marken(koerper) == [("user", 0), ("assistant", 1), ("user", 2)]
    assert koerper["messages"][1]["content"][-1]["cache_control"] == MARKE


def test_die_marken_landen_nicht_in_den_nachrichten_der_anfrage():
    """What goes out is marked; what the caller handed in — and later stores
    or folds — is not touched."""
    nachrichten = [
        ChatNachricht(role="system", content="Sei kurz."),
        ChatNachricht(role="user", content="Hallo"),
    ]
    bauen()._koerper_bauen(Generierungsanfrage(nachrichten=nachrichten))
    assert [n.content for n in nachrichten] == ["Sei kurz.", "Hallo"]


def test_ein_bild_wird_in_rohdaten_und_medientyp_zerlegt():
    """Anthropic wants base64 plus media type, OpenAI takes the whole data URL."""
    koerper = bauen()._koerper_bauen(Generierungsanfrage(nachrichten=[
        ChatNachricht(role="user", content="Was ist das?",
                      bild_url="data:image/png;base64,AAAB"),
    ]))
    assert koerper["messages"][0]["content"][0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AAAB"},
    }


# --- Stream ---------------------------------------------------------------

# A finished stream always names its `stop_reason` in a `message_delta`; one
# that names none is read as a provider that broke off. Tests about what a
# stream CARRIES should not have to spell the ending — it is appended where
# none is named (the same shape as `rohpakete` in the OpenAI tests), and
# `mit_ende=False` keeps a stream without one for the tests about the
# ending itself. The reason follows the round, and it is read at the one
# place the provider reads it: `message_delta.delta.stop_reason`.


def _mit_ende(ereignisse: tuple[dict, ...]) -> tuple[dict, ...]:
    if any(
        e.get("type") == "message_delta" and (e.get("delta") or {}).get("stop_reason")
        for e in ereignisse
    ):
        return ereignisse
    werkzeugrunde = any(
        e.get("type") == "content_block_start"
        and (e.get("content_block") or {}).get("type") == "tool_use"
        for e in ereignisse
    )
    return ereignisse + (
        {"type": "message_delta",
         "delta": {"stop_reason": "tool_use" if werkzeugrunde else "end_turn"}},
    )


def strom(*ereignisse: dict, mit_ende: bool = True) -> httpx.MockTransport:
    if mit_ende:
        ereignisse = _mit_ende(ereignisse)
    zeilen = "".join(f"data: {json.dumps(e)}\n\n" for e in ereignisse)
    return httpx.MockTransport(
        lambda _: httpx.Response(200, text=zeilen, headers={"content-type": "text/event-stream"})
    )


@asynccontextmanager
async def strom_lauf(provider: AnthropicProvider, transport, anfrage=None):
    """The stream itself, behind the patched client, as a context manager —
    for the tests that must look at what had already arrived when the
    stream failed (the tool call that must NOT go out). A context manager
    and not a bare generator: the patch comes off when the `async with` is
    left, whether by its end or by a `break` out of the stream."""
    original = httpx.AsyncClient

    def gefaelscht(**kwargs):
        kwargs["transport"] = transport
        return original(**kwargs)

    httpx.AsyncClient = gefaelscht
    try:
        yield provider.streamen(
            anfrage or Generierungsanfrage(
                nachrichten=[ChatNachricht(role="user", content="Hallo")]
            )
        )
    finally:
        httpx.AsyncClient = original


async def stuecke(provider: AnthropicProvider, transport, anfrage=None):
    async with strom_lauf(provider, transport, anfrage) as quelle:
        return [s async for s in quelle]


@pytest.mark.asyncio
async def test_die_eigene_zeitgrenze_reicht_bis_zu_httpx():
    """This provider builds its own `httpx.AsyncClient` for the streaming
    call, separately from the OpenAI-compatible one — the switch has to
    reach this client too. Fails without the fix (the old code passed a
    flat `self.timeout` that never looked at `timeout_enabled`)."""
    gesehen = {}
    original = httpx.AsyncClient

    def gefaelscht(**kwargs):
        gesehen["timeout"] = kwargs.get("timeout")
        kwargs["transport"] = strom(
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "ok"}},
        )
        return original(**kwargs)

    httpx.AsyncClient = gefaelscht
    try:
        async for _ in bauen(timeout_enabled=False).streamen(
            Generierungsanfrage(nachrichten=[ChatNachricht(role="user", content="Hallo")])
        ):
            pass
    finally:
        httpx.AsyncClient = original

    assert gesehen["timeout"].read is None


@pytest.mark.asyncio
async def test_text_kommt_als_inhalt_an():
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {"input_tokens": 7}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo "}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Welt"}},
        {"type": "message_delta", "usage": {"output_tokens": 2}},
    ))
    assert "".join(s.text for s in ergebnis if s.sorte == "content") == "Hallo Welt"

    stats = [s for s in ergebnis if s.sorte == "stats"][0]
    assert stats.daten["prompt_tokens"] == 7
    assert stats.daten["tokens"] == 2
    # Silent case: the server named no cache, so the stats name none.
    assert "cache_tokens" not in stats.daten


@pytest.mark.asyncio
async def test_das_protokoll_nennt_das_modell_des_servers():
    """Which model answered is said once on this wire — on `message_start`,
    as the resolved id, a dated one where the request named an alias. It
    travels in the stats under the same name the OpenAI-compatible route
    uses, so the one protocol line can read either."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {
            "model": "claude-fable-5-20260101",
            "usage": {"input_tokens": 7},
        }},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo"}},
        {"type": "message_delta", "usage": {"output_tokens": 1}},
    ))
    stats = [s for s in ergebnis if s.sorte == "stats"][0]
    assert stats.daten["modell"] == "claude-fable-5-20260101"


@pytest.mark.asyncio
async def test_ohne_modell_im_ereignis_steht_das_angefragte():
    """Silence probe for the same field: an event that names no model leaves
    the one this request asked for, and never an empty name."""
    anfrage = Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hallo")],
        modell="claude-sonnet-5",
    )
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {"input_tokens": 7}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo"}},
    ), anfrage)
    stats = [s for s in ergebnis if s.sorte == "stats"][0]
    assert stats.daten["modell"] == "claude-sonnet-5"


@pytest.mark.asyncio
async def test_der_prompt_zaehlt_die_cache_teile_mit():
    """With caching, `input_tokens` is only what came after the last mark.
    The prompt the context reading and the fold limit need is all three."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 5000,
        }}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo"}},
        {"type": "message_delta", "usage": {"output_tokens": 1}},
    ))
    stats = [s for s in ergebnis if s.sorte == "stats"][0]
    assert stats.daten["prompt_tokens"] == 5210
    assert stats.daten["gesamt_tokens"] == 5211
    assert stats.daten["cache_tokens"] == 5000
    kontext = [s for s in ergebnis if s.sorte == "kontext"]
    assert kontext and kontext[0].daten["prompt_tokens"] == 5210


@pytest.mark.asyncio
async def test_cache_teile_ohne_input_tokens_ergeben_trotzdem_den_prompt():
    """A compatible server that names the cache parts but no input_tokens
    still reported a prompt — it is not left unknown."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {
            "cache_creation_input_tokens": 200, "cache_read_input_tokens": 5000,
        }}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo"}},
        {"type": "message_delta", "usage": {"output_tokens": 1}},
    ))
    stats = [s for s in ergebnis if s.sorte == "stats"][0]
    assert stats.daten["prompt_tokens"] == 5200


@pytest.mark.asyncio
async def test_der_cache_anteil_steht_schon_waehrend_der_antwort():
    """This wire names all three halves of the prompt in its FIRST event, so
    the share of it the cache already had is known before the first word —
    and stands under the running answer instead of waiting for the end."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 200,
            "cache_read_input_tokens": 5000,
        }}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo"}},
        {"type": "message_delta", "usage": {"output_tokens": 1}},
    ))
    lesungen = [s for s in ergebnis if s.sorte == "denktempo"]
    assert lesungen and lesungen[0].daten["prompt_cache_percent"] == 96
    # Before the text, which is what "live" means here.
    sorten = [s.sorte for s in ergebnis]
    assert sorten.index("denktempo") < sorten.index("content")
    # And the finished answer names the same figure — one reading, one name.
    stats = [s for s in ergebnis if s.sorte == "stats"][0]
    assert stats.daten["prompt_cache_percent"] == 96
    assert stats.daten["cache_tokens"] == 5000


@pytest.mark.asyncio
async def test_ohne_cachefelder_kein_cache_anteil():
    """Silence probe: a server that names no cache sends neither a live
    reading nor a figure in its stats — nothing is claimed."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {"input_tokens": 900}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo"}},
        {"type": "message_delta", "usage": {"output_tokens": 1}},
    ))
    assert not [s for s in ergebnis if s.sorte == "denktempo"]
    stats = [s for s in ergebnis if s.sorte == "stats"][0]
    assert "prompt_cache_percent" not in stats.daten


@pytest.mark.asyncio
async def test_ein_echter_nulltreffer_steht_als_null_prozent():
    """Nothing was read from the cache — that is a reading of zero, not a
    silence, and the two have to stay apart."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 900,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 0,
        }}},
        {"type": "message_delta", "usage": {"output_tokens": 1}},
    ))
    lesungen = [s for s in ergebnis if s.sorte == "denktempo"]
    assert lesungen and lesungen[0].daten["prompt_cache_percent"] == 0
    stats = [s for s in ergebnis if s.sorte == "stats"][0]
    assert stats.daten["prompt_cache_percent"] == 0


@pytest.mark.asyncio
async def test_eine_kaputte_ausgangszahl_toetet_die_runde_nicht():
    """A proxy naming `output_tokens` as text, as a boolean or as a negative
    number must not end the round: it is no count, so the counted figure
    stands — and the stats are still built."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo"}},
        {"type": "message_delta", "usage": {"output_tokens": "1200"}},
    ))
    stats = [s for s in ergebnis if s.sorte == "stats"]
    assert stats, "the round ends without measurements"
    assert stats[0].daten["gesamt_tokens"] == 11


@pytest.mark.asyncio
async def test_negative_zahlen_verderben_den_cache_anteil_nicht():
    """Silence probe for the same rule on this route: a negative half is not
    a count, so the share stays between 0 and 100 instead of going absurd."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {
            "input_tokens": -9999, "cache_read_input_tokens": 5000,
        }}},
        {"type": "message_delta", "usage": {"output_tokens": 1}},
    ))
    lesungen = [s for s in ergebnis if s.sorte == "denktempo"]
    assert lesungen and lesungen[0].daten["prompt_cache_percent"] == 100


@pytest.mark.asyncio
async def test_gedanken_kommen_als_reasoning_an():
    """Declared, not parsed out of the text — no tag has to be hunted for."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "Ich überlege"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Antwort"}},
    ))
    assert [(s.sorte, s.text) for s in ergebnis if s.sorte in ("reasoning", "content")] == [
        ("reasoning", "Ich überlege"),
        ("content", "Antwort"),
    ]


@pytest.mark.asyncio
async def test_ein_werkzeugaufruf_wird_aus_bruchstuecken_zusammengesetzt():
    ergebnis = await stuecke(bauen(), strom(
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "t1", "name": "run_command"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '{"befehl":'}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '"ls"}'}},
        {"type": "content_block_stop", "index": 0},
    ))
    aufrufe = [s for s in ergebnis if s.sorte == "tool_call"][0].werkzeugaufrufe
    assert len(aufrufe) == 1
    assert aufrufe[0].id == "t1"
    assert aufrufe[0].name == "run_command"
    assert aufrufe[0].argumente == {"befehl": "ls"}


@pytest.mark.asyncio
async def test_unlesbare_argumente_werfen_den_aufruf_nicht_weg():
    """Better an empty argument set than a call that vanishes silently."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "t1", "name": "x"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": "{kaputt"}},
        {"type": "content_block_stop", "index": 0},
    ))
    aufrufe = [s for s in ergebnis if s.sorte == "tool_call"][0].werkzeugaufrufe
    assert aufrufe[0].argumente == {}


@pytest.mark.asyncio
async def test_ein_fehler_im_strom_wird_gemeldet():
    from app.providers.base import ProviderFehler

    with pytest.raises(ProviderFehler) as fehler:
        await stuecke(bauen(), strom(
            {"type": "error", "error": {"message": "overloaded"}},
        ))
    assert "overloaded" in str(fehler.value)


@pytest.mark.asyncio
async def test_ohne_gemeldetes_ende_geht_kein_aufruf_hinaus():
    """The provider stopped mid-answer: the call assembled so far was never
    finished and must not run. The failure stands before any finished call
    is handed out — signs of life on the way may already have gone out —
    the same reading the OpenAI-compatible route takes."""
    from app.providers.base import ProviderFehler

    gesehen = []
    async with strom_lauf(bauen(), strom(
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "t1", "name": "run_command"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '{"befehl": "ls"}'}},
        {"type": "content_block_stop", "index": 0},
        mit_ende=False,
    )) as quelle:
        with pytest.raises(ProviderFehler) as fehler:
            async for stueck in quelle:
                gesehen.append(stueck)
    assert fehler.value.key == "fehler.anbieter_ende_fehlt"
    assert gesehen, "the stream must have started before it failed"
    assert [s for s in gesehen if s.sorte == "tool_call"] == []


@pytest.mark.asyncio
async def test_ein_leeres_ende_zaehlt_nicht_als_ende():
    """`message_delta` with a null `stop_reason`: the shape a real server
    may send without having decided anything. It names no ending — the
    stream failed, it did not finish."""
    from app.providers.base import ProviderFehler

    with pytest.raises(ProviderFehler) as fehler:
        await stuecke(bauen(), strom(
            {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Fertig"}},
            {"type": "message_delta", "delta": {"stop_reason": None},
             "usage": {"output_tokens": 3}},
            mit_ende=False,
        ))
    assert fehler.value.key == "fehler.anbieter_ende_fehlt"


@pytest.mark.asyncio
async def test_ein_message_stop_allein_ist_kein_ende():
    """`message_stop` says goodbye, it does not say why: without a
    `message_delta` naming the reason, the stream stopped mid-answer."""
    from app.providers.base import ProviderFehler

    with pytest.raises(ProviderFehler) as fehler:
        await stuecke(bauen(), strom(
            {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Fertig"}},
            {"type": "message_stop"},
            mit_ende=False,
        ))
    assert fehler.value.key == "fehler.anbieter_ende_fehlt"


# --- The context reading, mid-answer --------------------------------------
#
# This is the exact route: `input_tokens` stands complete in the FIRST event
# of the stream, so the reading is right from the moment the answer begins
# instead of only when it ends.


@pytest.mark.asyncio
async def test_der_kontextstand_steht_vor_dem_ersten_wort():
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {"input_tokens": 1500}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo"}},
        {"type": "message_delta", "usage": {"output_tokens": 1}},
    ))
    sorten = [s.sorte for s in ergebnis]
    assert "kontext" in sorten
    # Before any answer text at all — that is the whole point of it.
    assert sorten.index("kontext") < sorten.index("content")

    erster = next(s for s in ergebnis if s.sorte == "kontext")
    assert erster.daten["prompt_tokens"] == 1500
    # The server's own complete count, not a floor: nothing may raise it.
    assert erster.daten["prompt_genau"] is True
    assert erster.daten["erzeugte_tokens"] == 0


@pytest.mark.asyncio
async def test_auch_eine_reine_werkzeugrunde_meldet_ihren_stand():
    """A round that only writes a tool call is the stretch this matters
    most for: minutes of data flowing with nothing to show for it."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {"input_tokens": 900}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "t1", "name": "run_command"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '{"befehl":"ls"}'}},
        {"type": "content_block_stop", "index": 0},
    ))
    staende = [s for s in ergebnis if s.sorte == "kontext"]
    assert staende
    assert staende[0].daten["prompt_tokens"] == 900


@pytest.mark.asyncio
async def test_der_gedankengang_bewegt_die_kontextanzeige(monkeypatch):
    """The window fills with the chain of thought too, so the live reading
    has to grow while the model is still thinking — not only once
    `message_delta` names a real `output_tokens` figure. That figure
    already covers the chain of thought by itself (see `denken_gesehen` in
    `anthropic.py`), so the last reading here must match it exactly rather
    than adding the thinking on top a second time.

    A fake clock is needed to see this: each reading is throttled to at
    most one every half second, and a synthetic stream runs through in a
    few milliseconds of real time.
    """
    uhr = iter(float(n) for n in range(20))
    monkeypatch.setattr("app.providers.anthropic.time.monotonic", lambda: next(uhr, 19.0))
    ergebnis = await stuecke(bauen(), strom(
        {"type": "message_start", "message": {"usage": {"input_tokens": 500}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "Ich überlege"}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Antwort"}},
        {"type": "message_delta", "usage": {"output_tokens": 5}},
    ))
    staende = [s for s in ergebnis if s.sorte == "kontext"]
    werte = [s.daten["erzeugte_tokens"] for s in staende]
    # Grown by the thinking alone, before the answer text and before any
    # real usage figure — the whole point of the counter.
    assert 1 in werte
    stelle = werte.index(1)
    assert werte[stelle - 1] < 1
    # The server's own final figure wins outright, not summed with the
    # counter that only stood in for it.
    assert werte[-1] == 5


@pytest.mark.asyncio
async def test_ohne_prompt_wird_nichts_behauptet():
    """No `message_start`, so no prompt. A zero would be a claim, and there
    is nothing here to claim."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo"}},
    ))
    assert [s for s in ergebnis if s.sorte == "kontext"] == []


@pytest.mark.asyncio
async def test_ohne_prompt_ist_auch_die_summe_keine_behauptung():
    """The stats chunk used to add the output onto a prompt of 0 when no
    `message_start` ever named one, and the service took that sum as the
    whole standing: 12,000 of context became 120. No prompt, no sum."""
    ergebnis = await stuecke(bauen(), strom(
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Hallo"}},
        {"type": "message_delta", "usage": {"output_tokens": 120}},
    ))
    stats = [s for s in ergebnis if s.sorte == "stats"][0]
    assert stats.daten["prompt_tokens"] is None
    assert stats.daten["gesamt_tokens"] is None


# --- Catalogue ------------------------------------------------------------


@pytest.mark.asyncio
async def test_die_modelle_kommen_vom_anbieter():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"data": [
            {"id": "claude-opus-5"}, {"id": "claude-sonnet-5"},
        ]})
    )
    provider = bauen()
    original = httpx.AsyncClient

    def gefaelscht(**kwargs):
        kwargs["transport"] = transport
        return original(**kwargs)

    httpx.AsyncClient = gefaelscht
    try:
        assert await provider.modelle_auflisten() == ["claude-opus-5", "claude-sonnet-5"]
    finally:
        httpx.AsyncClient = original


# --- Context size -----------------------------------------------------------


@pytest.mark.asyncio
async def test_die_bekannte_tabelle_wird_hier_nicht_gefragt():
    """Anthropic has nothing to ask, and this step no longer falls back to
    the known-models table itself — app/fenstergroesse.py is the one place
    that does, after a learned value and before the fallback, so a table
    entry can never outrank a size already learned from a refusal."""
    provider = bauen(modell="claude-sonnet-5")
    assert await provider.kontextgroesse() is None


@pytest.mark.asyncio
async def test_konfigurierter_wert_gewinnt_vor_der_tabelle():
    provider = bauen(modell="claude-sonnet-5", context_tokens=123_456)
    assert await provider.kontextgroesse() == 123_456


@pytest.mark.asyncio
async def test_unbekanntes_modell_wird_nicht_geraten():
    provider = bauen(modell="ein-modell-von-morgen")
    assert await provider.kontextgroesse() is None


@pytest.mark.asyncio
async def test_unangepinnter_endpunkt_ergibt_nichts_statt_eines_katalogaufrufs(monkeypatch):
    """No `modell:` configured — deliberately not resolved via a network
    round trip to the catalogue: discovery calls this every pass until it
    returns something, and a model that never matches the table would
    otherwise mean a fresh catalogue request every discovery tick, forever."""
    provider = bauen()

    async def niemals_aufrufen(timeout=3.0):
        raise AssertionError("kontextgroesse() must not reach the network")

    monkeypatch.setattr(provider, "modelle_auflisten", niemals_aufrufen)
    assert await provider.kontextgroesse() is None


@pytest.mark.asyncio
async def test_null_gilt_als_nicht_konfiguriert():
    """Consistent with the OpenAI-compatible provider's own check
    (``if self.endpunkt.context_tokens:``) — a 0 is not a real size someone
    meant, so this step falls through to the (here empty) model list
    instead of honoring it."""
    provider = bauen(modell="claude-sonnet-5", context_tokens=0)
    assert await provider.kontextgroesse() is None


# --- Speed ----------------------------------------------------------------
#
# The number under an answer has to mean the same thing whoever wrote the
# answer. This route used to answer a different question than the
# OpenAI-compatible one: it divided by the WHOLE duration, prompt
# processing and thinking included, where the other side had long since
# written down that the speed is the speed of the ANSWER. Two columns in
# one table following two definitions is the defect; the arithmetic was
# only how it showed.
#
# So the working out is not done here at all any more — it goes through
# `tempo_ermitteln`, the same function the other route uses. What is
# checked below is that this file hands it the right things and passes on
# what comes back.


def strom_mit_pausen(*ereignisse: dict, pause_vor: dict[int, float] | None = None):
    """The same stream as `strom`, but handed over across real time.

    A speed is measured between two moments, so a transport that delivers
    the whole answer in one piece measures nothing at all. The pauses stand
    in for what a model spends: before the first text block for the prompt
    or a chain of thought, between the blocks for the writing.
    """
    ereignisse = _mit_ende(ereignisse)
    pausen = pause_vor or {}

    async def zeilen():
        for i, ereignis in enumerate(ereignisse):
            if i in pausen:
                await asyncio.sleep(pausen[i])
            yield f"data: {json.dumps(ereignis)}\n\n".encode()

    return httpx.MockTransport(
        lambda _: httpx.Response(
            200, content=zeilen(), headers={"content-type": "text/event-stream"}
        )
    )


def _text(inhalt: str) -> dict:
    return {"type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": inhalt}}


async def _messwerte(*ereignisse: dict, pause_vor=None) -> dict:
    ergebnis = await stuecke(bauen(), strom_mit_pausen(*ereignisse, pause_vor=pause_vor))
    return [s for s in ergebnis if s.sorte == "stats"][0].daten


# Six words written across 0.18 s, after 0.6 s in which nothing came back.
# The old formula divided by all 0.78 s of it.
_LANGER_PROMPT = {"type": "message_start", "message": {"usage": {"input_tokens": 90_000}}}
_SECHS_WORTE = [_text(f"Wort{i} ") for i in range(6)]
_NUTZUNG_SECHS = {"type": "message_delta", "usage": {"output_tokens": 6}}
_PAUSEN = {1: 0.6, 2: 0.03, 3: 0.03, 4: 0.03, 5: 0.03, 6: 0.03, 7: 0.03}


@pytest.mark.asyncio
async def test_das_tempo_meint_die_antwort_nicht_die_promptverarbeitung():
    """A long prompt must not press the number down.

    Measured with the old formula: the same one-token answer read as 0.86
    tok/s where the writing itself ran at a thousand, and a 120-token
    answer behind ten seconds of prompt read as 9.23 where the answer was
    written at 40. The number was not absurd, it was simply about something
    else — the whole request instead of the answer.
    """
    werte = await _messwerte(
        _LANGER_PROMPT, *_SECHS_WORTE, _NUTZUNG_SECHS, pause_vor=_PAUSEN
    )

    assert werte["erstes_token_nach_sekunden"] >= 0.6
    # Everything after the first token of the answer, and nothing before it.
    assert werte["erzeugungs_sekunden"] < werte["dauer_sekunden"] / 2
    assert werte["tokens_pro_sekunde"] == round(
        werte["erzeugte_tokens"] / werte["erzeugungs_sekunden"], 2
    )
    # What the old formula would have said, and how far off it was.
    assert werte["tokens_pro_sekunde"] > 3 * (6 / werte["dauer_sekunden"])


@pytest.mark.asyncio
async def test_die_runden_finden_ihre_zahlen_beim_zusammenzaehlen_wieder():
    """The defect: an answer over more than one round lost its speed whole.

    This route sent `tokens` and `tokens_pro_sekunde` and neither
    `erzeugte_tokens` nor `erzeugungs_sekunden` — which are the two fields
    the merge over tool rounds reads. Measured: two rounds worth 42.5 and
    40.0 tok/s on their own came out of the merge as nothing at all.
    """
    from app.api.v1.generierung import _messwerte_mergen

    erste = await _messwerte(
        _LANGER_PROMPT, *_SECHS_WORTE, _NUTZUNG_SECHS, pause_vor=_PAUSEN
    )
    zweite = await _messwerte(
        _LANGER_PROMPT, *_SECHS_WORTE, _NUTZUNG_SECHS, pause_vor=_PAUSEN
    )
    assert erste["erzeugte_tokens"] == 6
    assert erste["erzeugungs_sekunden"] > 0

    zusammen = _messwerte_mergen(erste, zweite)
    assert zusammen["erzeugte_tokens"] == 12
    assert zusammen["tokens_pro_sekunde"] == round(
        12 / (erste["erzeugungs_sekunden"] + zweite["erzeugungs_sekunden"]), 2
    )


@pytest.mark.asyncio
async def test_gedachte_tokens_ohne_aufteilung_lassen_die_stufe_fallen():
    """`output_tokens` counts the thinking in, and this API names no split.

    So the count and the divisor beside it describe two different stretches
    of time, and there is no arithmetic that joins them after the fact. The
    tier steps down to the counted chunks instead — they are answer chunks
    and only those, which is the divisor's own definition. Exactly what the
    OpenAI-compatible route does with a server that thinks and says nothing.
    """
    werte = await _messwerte(
        {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "thinking_delta", "thinking": "Ich überlege"}},
        *_SECHS_WORTE,
        {"type": "message_delta", "usage": {"output_tokens": 900}},
        pause_vor={2: 0.5, 3: 0.03, 4: 0.03, 5: 0.03, 6: 0.03, 7: 0.03},
    )
    assert werte["tempo_quelle"] == "geschaetzt"
    assert werte["erzeugte_tokens"] == 6      # the six words, not the 900
    assert werte["erstes_token_nach_sekunden"] >= 0.5  # the thinking is outside


@pytest.mark.asyncio
async def test_die_quelle_nennt_die_stufe_und_nicht_den_hersteller():
    """`tempo_quelle` ranks how a number was arrived at.

    "anthropic" said nothing about that and stood in no ranking, so the
    merge sorted it below every real tier via its fallback and let it name
    the source of any run it appeared in.
    """
    from app.api.v1.generierung import _QUELLEN_RANG

    werte = await _messwerte(
        _LANGER_PROMPT, *_SECHS_WORTE, _NUTZUNG_SECHS, pause_vor=_PAUSEN
    )
    assert werte["tempo_quelle"] == "gemessen"
    assert werte["tempo_quelle"] in _QUELLEN_RANG


@pytest.mark.asyncio
async def test_zu_kurz_gemessen_meldet_auch_hier_kein_tempo():
    """The floors apply to this route too, now that it divides like the other.

    Every event of this stream is already in the buffer, so the six words
    are read out in microseconds — nothing was generated in that span, and
    a reading in the thousands would only be saying how fast this process
    parses JSON.
    """
    werte = await _messwerte(_LANGER_PROMPT, *_SECHS_WORTE, _NUTZUNG_SECHS)

    assert werte["erzeugte_tokens"] == 6   # the count is real and stays
    assert werte["tokens_pro_sekunde"] is None


def test_zwei_assistentenzuege_in_folge_werden_gefaltet():
    """A background command's report is an assistant row right after the
    answer row; two assistant turns in a row are rejected by the API, so
    the builder folds them into one, blocks concatenated in order."""
    _, nachrichten = bauen()._nachrichten_bauen([
        ChatNachricht(role="user", content="Frage"),
        ChatNachricht(role="assistant", content="Antwort"),
        ChatNachricht(role="assistant", content="[Befehlsbericht]"),
        ChatNachricht(role="user", content="weiter"),
    ])
    assert [n["role"] for n in nachrichten] == ["user", "assistant", "user"]
    bloecke = nachrichten[1]["content"]
    assert [b["text"] for b in bloecke] == ["Antwort", "[Befehlsbericht]"]


def test_ein_auszug_der_auf_assistant_beginnt_bekommt_einen_user_anfang():
    """Chat compaction slices the middle of a history, which can open on
    the assistant — the API requires the first turn to be the user's, so
    an excerpt marker is prepended rather than the fold failing with 400
    on every attempt."""
    _, nachrichten = bauen()._nachrichten_bauen([
        ChatNachricht(role="assistant", content="Mitte einer Antwort"),
        ChatNachricht(role="user", content="Fasse zusammen"),
    ])
    assert nachrichten[0]["role"] == "user"
    assert nachrichten[1]["role"] == "assistant"
    assert nachrichten[2]["role"] == "user"


def _anthropic_list(*entries: dict):
    """A provider whose model list carries the given entries; every request
    is counted."""
    asked: list[str] = []

    def handler(request):
        asked.append(request.url.path)
        return httpx.Response(200, json={"data": list(entries)})

    return httpx.MockTransport(handler), asked


@pytest.mark.asyncio
async def test_every_model_of_the_list_carries_its_own_window(monkeypatch):
    """No model pinned: each model of the catalogue gets the
    `max_input_tokens` its own row names, not the table's one number."""
    transport, _ = _anthropic_list(
        {"id": "claude-opus-5", "max_input_tokens": 1_000_000},
        {"id": "claude-haiku-5", "max_input_tokens": 200_000},
    )
    echt = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: echt(transport=transport, **kw))
    provider = AnthropicProvider(EndpointConfig(
        id="anthropic", base_url="https://api.example.invalid/v1", provider="anthropic",
    ))
    assert await provider.context_per_model(1.0) == {
        "claude-opus-5": 1_000_000,
        "claude-haiku-5": 200_000,
    }


@pytest.mark.asyncio
async def test_a_list_without_the_field_names_no_window(monkeypatch):
    """Silence probe: rows without `max_input_tokens` give no number, and the
    table (app/fenstergroesse.py) stands as before."""
    transport, _ = _anthropic_list({"id": "claude-opus-5"}, {"id": "claude-haiku-5"})
    echt = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: echt(transport=transport, **kw))
    provider = AnthropicProvider(EndpointConfig(
        id="anthropic", base_url="https://api.example.invalid/v1", provider="anthropic",
    ))
    assert await provider.context_per_model(1.0) == {}


# --- Where the cache marks go -------------------------------------------


def _marked(base_url: str, modell: str) -> bool:
    """Does a request with a system prompt carry any cache mark here?"""
    koerper = bauen(base_url=base_url)._koerper_bauen(Generierungsanfrage(
        modell=modell,
        nachrichten=[ChatNachricht(role="system", content="Sei kurz."),
                     ChatNachricht(role="user", content="Hallo")],
    ))
    return "cache_control" in json.dumps(koerper)


def test_a_foreign_anthropic_shaped_server_gets_no_cache_marks():
    """A server that speaks the dialect but does not know the field answers
    the whole request with a 400; only where the field is known to be
    accepted do they go."""
    assert not _marked("https://llm.example.net/v1", "glm-5")
    # MiniMax caches M3 by itself: no marks even on its own host.
    assert not _marked("https://api.minimax.io/anthropic", "MiniMax-M3")


def test_the_cache_marks_stay_where_they_were_granted():
    """Silence probe: Anthropic's own host, a Claude model behind a foreign
    gateway and MiniMax's own models keep their marks as before."""
    assert _marked("https://api.anthropic.com/v1", "claude-fable-5-1")
    assert _marked("https://api.anthropic.com/v1", "")
    assert _marked("https://gateway.example.net/v1", "claude-sonnet-5")
    assert _marked("https://api.minimaxi.com/anthropic", "MiniMax-M2.7")
