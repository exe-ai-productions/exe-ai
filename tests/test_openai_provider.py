"""The OpenAI-compatible provider against a rebuilt model server.

This module talks to every model server — mlx_lm, mlx_vlm, llama.cpp,
Ollama, vLLM and the cloud providers. Trying it by hand against Mana is
not enough: the quirks of the other servers (their own reasoning field,
Harmony markers, 404 on the `model` field) never show up there.

Hence a small, real HTTP server here that behaves like the various model
servers — including Server-Sent Events over real network connections.
"""

from __future__ import annotations

import asyncio
import json
import socket
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import denkschalter
from app.config import EndpointConfig
from app.providers import ChatNachricht, Generierungsanfrage, ProviderFehler
from app.providers.base import Werkzeugaufruf, zeitlimit
from app.providers.openai_kompatibel import (
    OpenAIKompatiblerProvider,
    _AnteilDrossel,
    _cache_share,
    _DenktempoDrossel,
    einlesen_ermitteln,
    tempo_ermitteln,
)
from app.providers.openai_responses import _nutzung, koerper_umbauen


class ModellServerAttrappe:
    """Behaves like an OpenAI-compatible server, configurable per test."""

    def __init__(self) -> None:
        self.pakete: list[dict] = []
        # Raw SSE lines, in case a test wants to send something that is not
        # valid JSON. Takes precedence over self.pakete.
        self.rohzeilen: list[str] | None = None
        self.status = 200
        self.fehlertext = "kaputt"
        self.empfangene_koerper: list[dict] = []
        # Which of the two routes each request really took. The path is the
        # finding in the tests that read it, not a nice-to-have: the body alone
        # does not say whether it went to the wire it was meant for.
        self.pfade: list[str] = []
        # What the Responses route streams. Empty means the closing event of a
        # plain answer, built by `antworten_senden`.
        self.antwort_ereignisse: list[dict] = []
        # Errors the Responses route answers first, one per request, before
        # it streams again: (status, error text).
        self.refusals: list[tuple[int, str]] = []
        self.app = FastAPI()

        # Configurable, because the servers answer very differently here:
        # mlx_lm in the OpenAI layout, llama-server with its own list.
        self.modell_antwort: dict = {"object": "list", "data": [{"id": "testmodell"}]}

        @self.app.get("/v1/models")
        async def modelle():
            return self.modell_antwort

        @self.app.post("/v1/chat/completions")
        async def completions(request: Request):
            koerper = await request.json()
            self.empfangene_koerper.append(koerper)
            self.pfade.append("/v1/chat/completions")

            if self.status >= 400:
                return JSONResponse({"error": self.fehlertext}, status_code=self.status)

            async def strom():
                if self.rohzeilen is not None:
                    for zeile in self.rohzeilen:
                        yield zeile
                        await asyncio.sleep(0)
                else:
                    for paket in self.pakete:
                        yield f"data: {json.dumps(paket)}\n\n"
                        await asyncio.sleep(0)
                yield "data: [DONE]\n\n"

            return StreamingResponse(strom(), media_type="text/event-stream")

        @self.app.post("/v1/responses")
        async def responses(request: Request):
            koerper = await request.json()
            self.empfangene_koerper.append(koerper)
            self.pfade.append("/v1/responses")

            if self.refusals:
                status, text = self.refusals.pop(0)
                return JSONResponse({"error": {"message": text}}, status_code=status)
            if self.status >= 400:
                return JSONResponse({"error": self.fehlertext}, status_code=self.status)

            async def strom():
                for ereignis in self.antwort_ereignisse:
                    yield f"data: {json.dumps(ereignis)}\n\n"
                    await asyncio.sleep(0)
                yield "data: [DONE]\n\n"

            return StreamingResponse(strom(), media_type="text/event-stream")

    def antworten_senden(self, *texte: str) -> None:
        """A whole answer on the Responses route: text pieces, then the
        closing event every real server sends.

        The closing event is not decoration here — it is what carries the
        `finish_reason` and the usage, and a stream without it is read as a
        provider that stopped mid-answer (app/providers/openai_responses.py,
        `_schlusspaket`).
        """
        self.antwort_ereignisse = [
            {"type": "response.created", "response": {"id": "resp_1", "status": "in_progress"}}
        ] + [
            {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 0, "delta": text}
            for text in texte
        ] + [
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "status": "completed",
                    "output": [{"type": "message", "id": "msg_1", "content": []}],
                    "usage": {
                        "input_tokens": 40,
                        "output_tokens": 3,
                        "total_tokens": 43,
                        "output_tokens_details": {"reasoning_tokens": 2},
                    },
                },
            }
        ]

    def inhalt_senden(self, *texte: str) -> None:
        """Prepares normal text packets — and the closing word every real
        server says.

        A finished answer always names its end (measured on mlx, llama.cpp
        and vLLM: `stop`, `length`, `tool_calls`), and a stream that names
        none is read as a provider that stopped mid-answer
        (app/providers/openai_kompatibel.py). A stub that left the word out
        was not sending what it claims to stand for.
        """
        self.pakete = [
            {"choices": [{"delta": {"content": text}, "index": 0}]} for text in texte
        ] + [{"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]}]

    def rohpakete(self, pakete: list[dict]) -> None:
        """Exactly these packets — plus the closing word, where they name none.

        The same reason as in `inhalt_senden`: a real server always says why
        it stopped, and a stream that says nothing is read as a provider that
        broke off. Tests about what a stream CARRIES should not have to
        spell the ending; a test about the ending itself spells it and keeps
        what it wrote.
        """
        nennt_ende = any(
            (wahl or {}).get("finish_reason")
            for paket in pakete
            for wahl in (paket.get("choices") or [])
        )
        self.pakete = pakete if nennt_ende else pakete + [
            {"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]}
        ]


@pytest.fixture
async def modellserver():
    attrappe = ModellServerAttrappe()

    lauscher = socket.socket()
    lauscher.bind(("127.0.0.1", 0))
    port = lauscher.getsockname()[1]
    lauscher.close()

    server = uvicorn.Server(
        uvicorn.Config(attrappe.app, host="127.0.0.1", port=port, log_level="error")
    )
    aufgabe = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)

    attrappe.basis = f"http://127.0.0.1:{port}/v1"
    # The same server as a proxy address. A request to OpenAI's own host is
    # only reachable in a test as a proxy request: the address keeps the host
    # the code reads its rules from, while the connection goes to this stub
    # (see `_ueber_proxy` below).
    attrappe.proxy = f"http://127.0.0.1:{port}"
    try:
        yield attrappe
    finally:
        server.should_exit = True
        await aufgabe


def _provider(basis: str, **felder) -> OpenAIKompatiblerProvider:
    endpunkt = EndpointConfig.model_validate(
        {"id": "prueflabor", "name": "Prüflabor", "base_url": basis, **felder}
    )
    return OpenAIKompatiblerProvider(endpunkt)


def _ueber_proxy(monkeypatch, attrappe) -> None:
    """Let a request to OpenAI's own host end at the stub.

    Which wire a request takes is decided by its HOST, so the address it is
    built for has to be the real one — while the connection has to end
    somewhere local. A proxy does both: httpx hands the request to the stub
    and keeps the address it was built for, so the stub answers for a host
    that never sees this traffic.
    """
    monkeypatch.setenv("HTTP_PROXY", attrappe.proxy)
    monkeypatch.delenv("NO_PROXY", raising=False)


async def _einsammeln(provider, anfrage=None):
    anfrage = anfrage or Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hallo")]
    )
    stuecke = []
    async for stueck in provider.streamen(anfrage):
        stuecke.append(stueck)
    return stuecke


def _text(stuecke, sorte: str) -> str:
    return "".join(s.text for s in stuecke if s.sorte == sorte)


# --- Reachability ---------------------------------------------------------


@pytest.mark.asyncio
async def test_erreichbar_wenn_der_server_antwortet(modellserver):
    assert await _provider(modellserver.basis).erreichbar() is True


@pytest.mark.asyncio
async def test_nicht_erreichbar_ohne_server():
    # Port 9 is the discard service and accepts no HTTP connection.
    assert await _provider("http://127.0.0.1:9/v1").erreichbar(timeout=1) is False


@pytest.mark.asyncio
async def test_erreichbarkeit_wirft_keine_ausnahme_bei_kaputtem_namen():
    provider = _provider("http://gibt-es-nicht.invalid/v1")
    assert await provider.erreichbar(timeout=2) is False


# --- Streaming -----------------------------------------------------------


@pytest.mark.asyncio
async def test_inhalt_kommt_haeppchenweise_an(modellserver):
    modellserver.inhalt_senden("Guten ", "Tag", "!")
    stuecke = await _einsammeln(_provider(modellserver.basis))
    assert _text(stuecke, "content") == "Guten Tag!"


@pytest.mark.asyncio
async def test_messwerte_werden_erhoben(modellserver):
    modellserver.inhalt_senden("a", "b", "c")
    stuecke = await _einsammeln(_provider(modellserver.basis))
    messwerte = next(s for s in stuecke if s.sorte == "stats").daten
    assert messwerte["haeppchen"] == 3
    assert messwerte["dauer_sekunden"] >= 0
    assert messwerte["erstes_token_nach_sekunden"] is not None
    assert messwerte["endpunkt"] == "prueflabor"


# --- What came out of the cache, and the reading-in -----------------------


@pytest.mark.asyncio
async def test_llama_server_nennt_cache_und_einlesen_in_der_statistik(modellserver):
    """The numbers measured on a llama.cpp server: 982 prompt tokens, 978 from the
    cache, 4 read in fresh in 93 ms. All three reach the round's stats."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}]},
        {"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 982, "completion_tokens": 1,
                   "prompt_tokens_details": {"cached_tokens": 978}},
         "timings": {"prompt_n": 4, "prompt_ms": 93.2, "cache_n": 978,
                     "predicted_n": 1, "predicted_ms": 20.0}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    stats = [s for s in stuecke if s.sorte == "stats"][-1].daten
    assert stats["cache_tokens"] == 978
    assert stats["eingelesen_tokens"] == 4
    assert stats["einlese_sekunden"] == 0.093


@pytest.mark.asyncio
async def test_ein_anbieter_ohne_cachefelder_schreibt_nichts_hinein(modellserver):
    """Silent case: no cache field, no timings — the stats name nothing,
    rather than a zero that would claim the cache missed."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}],
         "usage": {"prompt_tokens": 10, "completion_tokens": 1}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    stats = [s for s in stuecke if s.sorte == "stats"][-1].daten
    for feld in ("cache_tokens", "eingelesen_tokens", "einlese_sekunden"):
        assert feld not in stats


def test_die_openai_form_allein_nennt_nur_die_menge():
    """A cloud provider reports a quantity and no timing — only the
    quantity is shown."""
    assert einlesen_ermitteln(
        None, {"prompt_tokens_details": {"cached_tokens": 1024}}
    ) == {"cache_tokens": 1024}


def test_cache_n_steht_ein_wo_die_openai_form_fehlt():
    assert einlesen_ermitteln({"cache_n": 50, "prompt_n": 3}, {})["cache_tokens"] == 50


def test_eine_unendliche_einlesedauer_wird_verworfen():
    """Infinity would reach the window as a JSON word it cannot parse."""
    assert "einlese_sekunden" not in einlesen_ermitteln({"prompt_ms": float("inf")}, {})


def test_ein_gemeldeter_nullwert_ist_eine_antwort():
    """Zero named by the server is a miss it reported — kept, unlike a
    missing field."""
    assert einlesen_ermitteln(None, {"prompt_tokens_details": {"cached_tokens": 0}}) == {
        "cache_tokens": 0
    }


def test_timings_cache_beats_a_reported_zero_beside_it():
    """A server that counted its cached tokens itself is not overruled by a
    0 in the OpenAI form beside it — measured: one server reports that field
    as 0 on every single request. The server's own count is the one that was
    really counted."""
    assert einlesen_ermitteln(
        {"prompt_n": 524, "cache_n": 977},
        {"prompt_tokens": 1501, "prompt_tokens_details": {"cached_tokens": 0}},
    )["cache_tokens"] == 977
    assert _cache_share(
        {"prompt_n": 524, "cache_n": 977},
        {"prompt_tokens": 1501, "prompt_tokens_details": {"cached_tokens": 0}},
    ) == {"prompt_cache_percent": 65}


# --- The context reading, mid-answer --------------------------------------
#
# Three shapes reach here, and the difference between them is carried out to
# the caller instead of being flattened into one number: a complete count, a
# floor, and nothing at all.


@pytest.mark.asyncio
async def test_llama_cpp_meldet_seinen_prompt_als_untergrenze(modellserver):
    """`timings.prompt_n` counts only what really had to be PROCESSED — in
    an ongoing chat the cached part is missing (measured: 524 instead of
    1501 with 977 cached). So it travels as a floor, never as a prompt
    size, and the caller raises it with what it knows."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Guten "}, "index": 0}],
         "timings": {"prompt_n": 512}},
        {"choices": [{"delta": {"content": "Tag"}, "index": 0}],
         "timings": {"prompt_n": 512}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    staende = [s for s in stuecke if s.sorte == "kontext"]
    assert staende
    assert staende[0].daten["prompt_tokens"] == 512
    assert staende[0].daten["prompt_genau"] is False


@pytest.mark.asyncio
async def test_ein_usage_block_ist_die_genaue_zahl(modellserver):
    """What the server counted itself. Cloud servers only send it in the
    very last packet, so this is what the LAST reading of a round is made
    of, not the first."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}]},
        {"choices": [{"delta": {"content": " Welt"}, "index": 0}],
         "usage": {"prompt_tokens": 1501, "completion_tokens": 2}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    letzter = [s for s in stuecke if s.sorte == "kontext"][-1]
    assert letzter.daten["prompt_tokens"] == 1501
    assert letzter.daten["prompt_genau"] is True


@pytest.mark.asyncio
async def test_ohne_jede_zahl_bleibt_der_prompt_unbekannt(modellserver):
    """The cloud mid-stream: no timings, no usage yet. `None` rather than a
    guess — the caller can tell the two apart and estimates for itself."""
    modellserver.inhalt_senden("Hallo")
    stuecke = await _einsammeln(_provider(modellserver.basis))
    staende = [s for s in stuecke if s.sorte == "kontext"]
    assert staende
    assert staende[0].daten["prompt_tokens"] is None
    assert staende[0].daten["prompt_genau"] is False
    # The half it CAN count is counted.
    assert staende[0].daten["erzeugte_tokens"] == 1


@pytest.mark.asyncio
async def test_ein_nan_im_usage_block_beendet_den_strom_nicht(modellserver):
    """``json.loads`` accepts ``NaN`` and ``Infinity``, and a hand-written
    count guard let both through: ``nan < 0`` is False, ``int(nan)`` raises,
    and the answer died mid-stream on a number the server never meant. The
    reading costs that one field, never the round."""
    modellserver.rohzeilen = [
        'data: {"choices": [{"delta": {"content": "Hallo"}, "index": 0}]}\n\n',
        'data: {"choices": [{"delta": {"content": " Welt"}, "index": 0}], '
        '"usage": {"prompt_tokens": NaN, "completion_tokens": Infinity}}\n\n',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]}\n\n',
    ]
    stuecke = await _einsammeln(_provider(modellserver.basis))
    assert _text(stuecke, "content") == "Hallo Welt"
    letzter = [s for s in stuecke if s.sorte == "kontext"][-1]
    assert letzter.daten["prompt_tokens"] is None


@pytest.mark.asyncio
async def test_der_prompt_wird_nicht_mit_predicted_verkoppelt(modellserver):
    """mlx sends `timings` on every chunk, but `predicted_*` only becomes
    usable later. The prompt half must not have to wait for the speed half
    — reading it out of the same condition would delay it by the whole
    answer on llama.cpp, which sends the complete block only at the end."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "a"}, "index": 0}],
         "timings": {"prompt_n": 21, "predicted_n": 0, "predicted_ms": 0}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    assert [s for s in stuecke if s.sorte == "kontext"][0].daten["prompt_tokens"] == 21


@pytest.mark.asyncio
async def test_ein_unsinniger_prompt_kostet_nur_sich_selbst(modellserver):
    """Comes straight off a model server, a boundary this module does not
    control: a broken field costs this one reading, not the round."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "a"}, "index": 0}],
         "timings": {"prompt_n": "viele"}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    assert _text(stuecke, "content") == "a"
    assert [s for s in stuecke if s.sorte == "kontext"][0].daten["prompt_tokens"] is None


# --- Speed ----------------------------------------------------------------
#
# Calculated the same way the model servers do it themselves: generated
# tokens divided by pure generation time. Prompt processing stays out of it.


def test_tempo_kommt_am_liebsten_vom_server():
    """The `timings` block beats everything else — it measures at the source."""
    werte = tempo_ermitteln(
        zeitmessung={"predicted_n": 60, "predicted_ms": 2580.0, "prompt_n": 21},
        nutzung={"completion_tokens": 60},
        haeppchen=55,
        dauer=99.0,  # deliberately absurd: must play no role
        erstes_token_nach=0.5,
    )
    assert werte["tokens_pro_sekunde"] == 23.26
    assert werte["erzeugte_tokens"] == 60
    assert werte["tempo_quelle"] == "server"


def test_promptgroesse_kommt_aus_usage_nicht_aus_timings():
    """`timings.prompt_n` counts only what was newly processed, not the cache.

    Measured against llama.cpp: 1501 prompt tokens, 977 of them from the
    cache — `prompt_n` read 524. For "how big was the prompt" that is the
    wrong number.
    """
    werte = tempo_ermitteln(
        zeitmessung={"predicted_n": 10, "predicted_ms": 500.0, "prompt_n": 524},
        nutzung={"prompt_tokens": 1501},
        haeppchen=10, dauer=3.0, erstes_token_nach=1.0,
    )
    assert werte["prompt_tokens"] == 1501


def test_ohne_timings_zaehlt_usage_auf_eigener_zeit():
    werte = tempo_ermitteln(
        zeitmessung={},
        nutzung={"completion_tokens": 40, "prompt_tokens": 900},
        haeppchen=37,
        dauer=6.0,
        erstes_token_nach=2.0,
    )
    # 40 tokens in the 4 s AFTER the first token — not in 6 s.
    assert werte["tokens_pro_sekunde"] == 10.0
    assert werte["erzeugungs_sekunden"] == 4.0
    assert werte["tempo_quelle"] == "gemessen"


def test_ohne_alles_bleiben_die_haeppchen_aber_ohne_tempo():
    """The chunk tier still carries the count and the span — they are true
    whatever a chunk holds — and it reports NO speed, because a chunk is not
    a token. Its name stays `geschaetzt`, so a reader can see
    which tier answered."""
    werte = tempo_ermitteln(
        zeitmessung={}, nutzung={}, haeppchen=20, dauer=5.0, erstes_token_nach=1.0
    )
    assert werte["tokens_pro_sekunde"] is None  # 5.0 before, out of chunks
    assert werte["erzeugte_tokens"] == 20
    assert werte["erzeugungs_sekunden"] == 4.0
    assert werte["tempo_quelle"] == "geschaetzt"


def test_die_promptverarbeitung_zieht_das_tempo_nicht_mehr_herunter():
    """The old bug: long prompt = absurdly low number.

    Measured against mlx_vlm with a cold model: 8 tokens generated in 0.79 s,
    preceded by 37.4 s of prompt processing. The old math reported 0.2 tok/s.
    """
    werte = tempo_ermitteln(
        zeitmessung={}, nutzung={"completion_tokens": 8}, haeppchen=8,
        dauer=38.2, erstes_token_nach=37.4,
    )
    assert werte["tokens_pro_sekunde"] == 10.0
    assert round(8 / 38.2, 2) == 0.21  # what would have been shown before


def test_ohne_ein_einziges_token_gibt_es_kein_tempo():
    werte = tempo_ermitteln(
        zeitmessung={}, nutzung={}, haeppchen=0, dauer=3.0, erstes_token_nach=None
    )
    assert werte["tokens_pro_sekunde"] is None
    assert werte["tempo_quelle"] is None


@pytest.mark.asyncio
async def test_zwischenwerte_von_mlx_werden_verworfen(modellserver):
    """mlx sends `timings` on every chunk — with garbage values along the way.

    Measured against a live mlx server: the same response reports `null`
    along the way, then 6.6, then 14625 tok/s. Only the complete block
    at the end carries `predicted_n` and `predicted_ms` and may count.
    """
    modellserver.rohpakete(
        [
            {
                "choices": [{"delta": {"content": "a"}, "index": 0}],
                "timings": {"predicted_per_second": None},
            },
            {
                "choices": [{"delta": {"content": "b"}, "index": 0}],
                "timings": {"predicted_per_second": 14625.2},
            },
            {
                "choices": [],
                "usage": {"completion_tokens": 2},
                "timings": {"predicted_n": 2, "predicted_ms": 100.0},
            },
        ]
    )
    stuecke = await _einsammeln(_provider(modellserver.basis))
    messwerte = next(s for s in stuecke if s.sorte == "stats").daten
    assert messwerte["tokens_pro_sekunde"] == 20.0
    assert messwerte["tempo_quelle"] == "server"


@pytest.mark.asyncio
async def test_nutzungsangaben_werden_uebernommen(modellserver):
    modellserver.rohpakete(
        [
            {"choices": [{"delta": {"content": "x"}, "index": 0}]},
            {"choices": [{"delta": {}, "index": 0}], "usage": {"total_tokens": 42}},
        ]
    )
    stuecke = await _einsammeln(_provider(modellserver.basis))
    messwerte = next(s for s in stuecke if s.sorte == "stats").daten
    assert messwerte["nutzung"]["total_tokens"] == 42


@pytest.mark.asyncio
async def test_unlesbares_paket_wird_uebersprungen(modellserver):
    """A broken packet must not shoot down the whole stream."""
    modellserver.rohzeilen = [
        'data: {"choices": [{"delta": {"content": "vorher"}}]}\n\n',
        "data: das ist kein json\n\n",
        ": ein Kommentar, den Server zum Offenhalten schicken\n\n",
        "\n",
        'data: {"choices": [{"delta": {"content": "nachher"}}]}\n\n',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop", "index": 0}]}\n\n',
    ]
    stuecke = await _einsammeln(_provider(modellserver.basis))
    assert _text(stuecke, "content") == "vorhernachher"


# --- Reasoning in all three formats ---------------------------------------


@pytest.mark.asyncio
async def test_natives_reasoning_feld(modellserver):
    """Gemma 4 delivers the reasoning in delta.reasoning."""
    modellserver.rohpakete(
        [
            {"choices": [{"delta": {"reasoning": "Ich überlege"}, "index": 0}]},
            {"choices": [{"delta": {"content": "Die Antwort"}, "index": 0}]},
        ]
    )
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    assert _text(stuecke, "reasoning") == "Ich überlege"
    assert _text(stuecke, "content") == "Die Antwort"


@pytest.mark.asyncio
async def test_gedankengang_zaehlt_beim_tempo_nicht_mit(modellserver):
    """Speed is the speed of the ANSWER, and a long think must not push it.

    This test used to assert the opposite, on the reasoning that leaving the
    thinking out made a deep model look absurdly slow. That reading is
    retired: the thinking time no longer sits in the denominator either, so
    it is not that the number is unfairly low — it is that the number stops
    being about the thinking at all. The two providers now answer the same
    way, which they did not before.
    """
    modellserver.rohpakete(
        [{"choices": [{"delta": {"reasoning": f"Schritt {i} "}, "index": 0}]} for i in range(9)]
        + [{"choices": [{"delta": {"content": "Antwort"}, "index": 0}]}]
    )
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    messwerte = next(s for s in stuecke if s.sorte == "stats").daten
    assert messwerte["haeppchen"] == 1


@pytest.mark.asyncio
async def test_gedankengang_bewegt_die_kontextanzeige(modellserver):
    """The window fills up with the chain of thought too, not only the
    answer — so the live reading has to move already while the model is
    still thinking, before a single word of the answer has arrived. Before
    this counter existed, a thinking-only stretch produced no reading at
    all: neither the prompt nor `token_gezaehlt` was known yet, so the
    condition guarding the event never became true.
    """
    modellserver.rohpakete(
        [{"choices": [{"delta": {"reasoning": f"Schritt {i} "}, "index": 0}]} for i in range(3)]
    )
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    staende = [s for s in stuecke if s.sorte == "kontext"]
    assert staende
    assert staende[-1].daten["erzeugte_tokens"] >= 1
    # Untouched by the same stream: the speed still counts only the answer.
    messwerte = next(s for s in stuecke if s.sorte == "stats").daten
    assert messwerte["haeppchen"] == 0


@pytest.mark.asyncio
async def test_denk_marker_bewegt_die_kontextanzeige(modellserver):
    """The same growth for the marker-split route (`<think>…</think>`),
    which counts reasoning in a different branch than the dedicated field
    above and needs its own proof."""
    modellserver.inhalt_senden("<think>Gedanke</think>")
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="think"))
    staende = [s for s in stuecke if s.sorte == "kontext"]
    assert staende
    assert staende[-1].daten["erzeugte_tokens"] >= 1
    messwerte = next(s for s in stuecke if s.sorte == "stats").daten
    assert messwerte["haeppchen"] == 0


@pytest.mark.asyncio
async def test_reasoning_content_wird_auch_erkannt(modellserver):
    """Some servers call the field reasoning_content."""
    modellserver.rohpakete(
        [{"choices": [{"delta": {"reasoning_content": "Gedanke"}, "index": 0}]}]
    )
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    assert _text(stuecke, "reasoning") == "Gedanke"


@pytest.mark.asyncio
async def test_think_tags_ueber_paketgrenzen(modellserver):
    modellserver.inhalt_senden("<thi", "nk>Gedanke</thi", "nk>Antwort")
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="think"))
    assert _text(stuecke, "reasoning") == "Gedanke"
    assert _text(stuecke, "content") == "Antwort"


@pytest.mark.asyncio
async def test_harmony_marker(modellserver):
    modellserver.inhalt_senden(
        "<|channel|>analysis<|message|>Denken<|end|>",
        "<|channel|>final<|message|>Antwort<|return|>",
    )
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="harmony"))
    assert _text(stuecke, "reasoning") == "Denken"
    assert _text(stuecke, "content") == "Antwort"


@pytest.mark.asyncio
async def test_bei_native_wird_der_text_nicht_zerlegt(modellserver):
    """Otherwise a <think> in normal text would be wrongly swallowed."""
    modellserver.inhalt_senden("<think>kein Marker</think>")
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    assert _text(stuecke, "content") == "<think>kein Marker</think>"


# --- A live speed while the model is still thinking ------------------------


@pytest.mark.asyncio
async def test_denktempo_geht_waehrend_des_denkens_hinaus(modellserver):
    """A packet carrying `timings` while the model is still thinking sends
    the server's own outright speed straight out — not the answer's speed,
    which does not exist yet, but the reading for THIS instant."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"reasoning": "Ich "}, "index": 0}],
         "timings": {"predicted_n": 3, "predicted_ms": 60, "predicted_per_second": 50.0}},
        {"choices": [{"delta": {"reasoning": "denke"}, "index": 0}],
         "timings": {"predicted_n": 6, "predicted_ms": 120, "predicted_per_second": 44.3}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    denktempi = [s for s in stuecke if s.sorte == "denktempo"]
    assert denktempi
    assert denktempi[0].daten["tokens_pro_sekunde"] == 50.0
    assert denktempi[0].daten["tempo_quelle"] == "server"


@pytest.mark.asyncio
async def test_der_cache_anteil_faehrt_waehrend_der_antwort_mit(modellserver):
    """The prompt is counted in two — what stood in the cache and what had
    to be read in — and their sum is the prompt. The running answer says how
    much of it the server already had, so the share is visible while the
    answer is still being written."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"reasoning": "Ich "}, "index": 0}],
         "timings": {"predicted_n": 3, "predicted_ms": 60, "predicted_per_second": 50.0,
                     "prompt_n": 20, "cache_n": 980}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    denktempi = [s for s in stuecke if s.sorte == "denktempo"]
    assert denktempi
    # The two readings that were there before travel on unchanged — the
    # share is joined onto them, not put in their place.
    assert denktempi[0].daten["tokens_pro_sekunde"] == 50.0
    assert denktempi[0].daten["tempo_quelle"] == "server"
    assert denktempi[0].daten["prompt_cache_percent"] == 98


@pytest.mark.asyncio
async def test_eine_haelfte_des_prompts_ist_kein_anteil(modellserver):
    """The silent case: a server naming only one of the two halves leaves
    the share out entirely. Half a prompt has no share, and a number made up
    from it would claim a cache reading the server never gave."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"reasoning": "Ich "}, "index": 0}],
         "timings": {"predicted_n": 3, "predicted_ms": 60, "predicted_per_second": 50.0,
                     "prompt_n": 20}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    denktempi = [s for s in stuecke if s.sorte == "denktempo"]
    assert denktempi
    assert "prompt_cache_percent" not in denktempi[0].daten


@pytest.mark.asyncio
async def test_ein_echter_nulltreffer_steht_als_null_prozent(modellserver):
    """A server that really had nothing cached gets a real "0 %" — the
    difference between "the cache missed" and "nobody counted" has to stay
    visible, which is why neither the view nor the provider turns a zero
    into silence."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"reasoning": "Ich "}, "index": 0}],
         "timings": {"predicted_n": 3, "predicted_ms": 60, "predicted_per_second": 50.0,
                     "prompt_n": 500, "cache_n": 0}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    denktempi = [s for s in stuecke if s.sorte == "denktempo"]
    assert denktempi
    assert denktempi[0].daten["prompt_cache_percent"] == 0


@pytest.mark.asyncio
async def test_der_anteil_geht_auch_ohne_tempo_hinaus(modellserver):
    """A server that names the two prompt halves but no usable speed still
    has something to say about the cache. The share keeps its own condition
    — waiting for a speed would keep it off the screen for the whole answer
    on exactly the servers that never name one."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 980}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    denktempi = [s for s in stuecke if s.sorte == "denktempo"]
    assert denktempi
    assert denktempi[0].daten["prompt_cache_percent"] == 98
    # And nothing is invented beside it: no speed was named, so none is sent.
    assert "tokens_pro_sekunde" not in denktempi[0].daten
    assert "tempo_quelle" not in denktempi[0].daten


@pytest.mark.asyncio
async def test_ein_zu_kleiner_zeitblock_haelt_den_anteil_nicht_zurueck(modellserver):
    """`predicted_n: 1` alone is below the speed's floor — a reading for a
    single token is noise. The share comes from the same block and is not
    noise, so it goes out anyway; that is the whole point of the two
    conditions living apart."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 980, "predicted_n": 1}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    lesungen = [s for s in stuecke if s.sorte == "denktempo"]
    assert lesungen
    assert lesungen[0].daten["prompt_cache_percent"] == 98
    assert "tokens_pro_sekunde" not in lesungen[0].daten
    sorten = [s.sorte for s in stuecke]
    assert sorten.index("denktempo") < sorten.index("stats")


@pytest.mark.asyncio
async def test_the_finished_share_stands_without_the_predicted_pair(modellserver):
    """A server that names the two prompt halves but never `predicted_n`
    with `predicted_ms` in one piece: the share stood under the running
    answer, and it must stand in the round's stats too — it is a property
    of the prompt, not of the speed block."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 980}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    stats = [s for s in stuecke if s.sorte == "stats"][-1].daten
    assert stats["prompt_cache_percent"] == 98


@pytest.mark.asyncio
async def test_a_named_zero_cache_reaches_the_finished_stats(modellserver):
    """A real miss (cache_n 0 beside prompt_n 500) reads as 0 — a number,
    not silence — under the running answer and in the stats (the silence
    check beside the test above)."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}],
         "timings": {"prompt_n": 500, "cache_n": 0}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    stats = [s for s in stuecke if s.sorte == "stats"][-1].daten
    assert stats["prompt_cache_percent"] == 0


@pytest.mark.asyncio
async def test_one_cache_share_from_the_first_packet_to_the_stats(modellserver):
    """The closing packet names only `usage` and no `timings`: the standing
    share must not be pulled down by it (it read 98, 90, 98 before), the
    throttle must send it once, and the stats must carry that same one
    number."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 980,
                     "predicted_n": 3, "predicted_ms": 60}},
        {"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 1000, "completion_tokens": 1,
                   "prompt_tokens_details": {"cached_tokens": 900}}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    lesungen = [
        s for s in stuecke if s.sorte == "denktempo" and "prompt_cache_percent" in s.daten
    ]
    assert [s.daten["prompt_cache_percent"] for s in lesungen] == [98]
    stats = [s for s in stuecke if s.sorte == "stats"][-1].daten
    assert stats["prompt_cache_percent"] == 98


@pytest.mark.asyncio
async def test_the_last_live_reading_is_the_one_in_the_stats(modellserver):
    """One stand, two readings: whatever the running answer last said about
    the cache is exactly what the round's stats say."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 980,
                     "predicted_n": 3, "predicted_ms": 60}},
        {"choices": [{"delta": {"content": "da"}, "index": 0}]},
        {"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 1000, "completion_tokens": 2,
                   "prompt_tokens_details": {"cached_tokens": 900}}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    lesungen = [
        s for s in stuecke if s.sorte == "denktempo" and "prompt_cache_percent" in s.daten
    ]
    assert lesungen
    stats = [s for s in stuecke if s.sorte == "stats"][-1].daten
    assert lesungen[-1].daten["prompt_cache_percent"] == stats["prompt_cache_percent"]


@pytest.mark.asyncio
async def test_the_stats_carry_one_cache_number_from_one_stand(modellserver):
    """`timings` names the cache (980); the usage beside it repeats the
    OpenAI form with a 0. The round's stats must not carry that 0 under the
    same name the running answer showed 98 under — one stand, one number."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 980},
         "usage": {"prompt_tokens": 1000,
                   "prompt_tokens_details": {"cached_tokens": 0}}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    stats = [s for s in stuecke if s.sorte == "stats"][-1].daten
    assert stats["prompt_cache_percent"] == 98
    assert stats["cache_tokens"] == 980
    assert stats["eingelesen_tokens"] == 20


@pytest.mark.asyncio
async def test_a_contradictory_late_zero_does_not_wipe_the_share(modellserver):
    """The halves of a prompt are constants of its request: a later zero
    beside a standing value is a hole in the wire, not news. Taken, it
    would wipe the reading and the number would vanish exactly when the
    answer ends — which the cache share is there to avoid."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 980}},
        {"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
         "timings": {"prompt_n": 0, "cache_n": 0}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    stats = [s for s in stuecke if s.sorte == "stats"][-1].daten
    assert stats["prompt_cache_percent"] == 98
    assert stats["cache_tokens"] == 980


@pytest.mark.asyncio
async def test_the_live_share_ignores_a_reported_zero_beside_cache_n(modellserver):
    """The same case as the unit test above, as a stream: a 0 in the OpenAI
    form beside a `cache_n` of 977 leaves the reading at 65, live."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"reasoning": "Ich "}, "index": 0}],
         "timings": {"prompt_n": 524, "cache_n": 977,
                     "predicted_n": 3, "predicted_ms": 60,
                     "predicted_per_second": 50.0},
         "usage": {"prompt_tokens": 1501,
                   "prompt_tokens_details": {"cached_tokens": 0}}},
    ])
    stuecke = await _einsammeln(
        _provider(modellserver.basis, reasoning_format="native")
    )
    denktempi = [s for s in stuecke if s.sorte == "denktempo"]
    assert denktempi
    assert denktempi[0].daten["prompt_cache_percent"] == 65


@pytest.mark.asyncio
async def test_ein_paket_ohne_worte_nennt_den_anteil_aber_kein_tempo(modellserver):
    """A packet of tool-argument deltas carries no words of its own: the
    share belongs to the prompt and goes out, the speed is a reading of
    words being written and stays in — the reading it had before the share
    joined it."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "a", "function": {"name": "lies", "arguments": "{"}}
        ]}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 980,
                     "predicted_n": 40, "predicted_ms": 500,
                     "predicted_per_second": 80.0}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    lesungen = [s for s in stuecke if s.sorte == "denktempo"]
    assert lesungen
    assert lesungen[0].daten["prompt_cache_percent"] == 98
    assert "tokens_pro_sekunde" not in lesungen[0].daten


@pytest.mark.asyncio
async def test_der_anteil_kommt_waehrend_der_antwort_aus_usage(modellserver):
    """The OpenAI form names the cached half in its `usage`, not in a
    `timings` block. Read while the answer runs — a server of that shape
    would otherwise only show its share once the round is over."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo"}, "index": 0}],
         "usage": {"prompt_tokens": 1000,
                   "prompt_tokens_details": {"cached_tokens": 900}}},
        {"choices": [{"delta": {"content": " Welt"}, "index": 0}]},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    lesungen = [s for s in stuecke if s.sorte == "denktempo"]
    assert lesungen
    assert lesungen[0].daten["prompt_cache_percent"] == 90
    # Before the round's own figures, which is what "live" means here.
    sorten = [s.sorte for s in stuecke]
    assert sorten.index("denktempo") < sorten.index("stats")


@pytest.mark.asyncio
async def test_der_anteil_geht_nur_bei_aenderung_noch_einmal_hinaus(modellserver):
    """The share is a property of the prompt, not of the moment: a second
    reading of the same number carries nothing and stays in — and one that
    says something else is news, however fast it arrives."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "a"}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 980}},
        {"choices": [{"delta": {"content": "b"}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 980}},
        {"choices": [{"delta": {"content": "c"}, "index": 0}],
         "timings": {"prompt_n": 20, "cache_n": 500}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    anteile = [
        s.daten["prompt_cache_percent"]
        for s in stuecke
        if s.sorte == "denktempo" and "prompt_cache_percent" in s.daten
    ]
    # 980 of 1000 and then 500 of 520 — the reading in between repeats the
    # first and is not sent again. (The stats carry the standing share too;
    # this counts the readings that went OUT along the way.)
    assert anteile == [98, 96]


def test_anteildrossel_haelt_eine_unveraenderte_lesung_zurueck():
    """No minimum gap: the same number again says nothing, and a different
    one is news straight away — a share is a property of the prompt, not of
    the moment, so it needs no waiting time, only a reason to speak."""
    drossel = _AnteilDrossel()
    assert drossel.faellig(98) is True
    assert drossel.faellig(98) is False
    assert drossel.faellig(90) is True
    assert drossel.faellig(90) is False


def test_umbenannte_zahlen_werden_geprueft():
    """A string, a negative number or a boolean under one of these names is
    not a count. Left out while it is renamed — carried on it would stand
    under the finished answer and in the context reading as a token figure."""
    assert _nutzung({
        "input_tokens": "1200",
        "output_tokens": -5,
        "total_tokens": True,
        "input_tokens_details": {"cached_tokens": "980"},
        "output_tokens_details": {"reasoning_tokens": -1},
    }) == {}


def test_umbenannte_zahlen_nehmen_die_brauchbaren_nicht_mit():
    """Silence probe for the same rule: what IS a count stays, a real zero
    included — a zero claims a cache miss, and that is a reading, not a
    silence."""
    assert _nutzung({
        "input_tokens": 1000,
        "output_tokens": -5,
        "total_tokens": 1020,
        "input_tokens_details": {"cached_tokens": 0},
    }) == {
        "prompt_tokens": 1000,
        "total_tokens": 1020,
        "prompt_tokens_details": {"cached_tokens": 0},
    }


def test_denktempodrossel_laesst_die_erste_lesung_immer_durch():
    """Unconditional, the same rule `KontextDrossel` follows: the run is
    silent up to now, so there is no earlier reading to wait its turn
    beside."""
    drossel = _DenktempoDrossel()
    assert drossel.faellig(50.0, 0.0) is True


def test_denktempodrossel_haelt_eine_unveraenderte_lesung_zurueck():
    drossel = _DenktempoDrossel()
    assert drossel.faellig(50.0, 0.0) is True
    assert drossel.faellig(50.0, 0.5) is False


def test_denktempodrossel_wartet_ihre_mindestabstand_ab():
    """A different value, but too soon after the last one that went out."""
    drossel = _DenktempoDrossel(mindestabstand=0.5)
    assert drossel.faellig(50.0, 0.0) is True
    assert drossel.faellig(44.3, 0.2) is False
    assert drossel.faellig(44.3, 0.6) is True


@pytest.mark.asyncio
async def test_ohne_timings_waehrend_des_denkens_kein_denktempo(modellserver):
    """The same reasoning chunks, but the server sent no `timings` at all —
    nothing is estimated to fill that hole."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"reasoning": "Ich denke"}, "index": 0}]},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    assert [s for s in stuecke if s.sorte == "denktempo"] == []


@pytest.mark.asyncio
async def test_ein_zu_kleiner_ausschnitt_bleibt_ohne_denktempo(modellserver):
    """`predicted_n`/`predicted_ms` present is not enough by itself — mlx's
    own early readings jump from zero via 6 up to 14625 tok/s before they
    settle, both fields present and non-zero the whole time. The same
    floors that guard the finished answer's own speed apply here too."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"reasoning": "Ich"}, "index": 0}],
         "timings": {"predicted_n": 1, "predicted_ms": 1, "predicted_per_second": 14625.0}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis, reasoning_format="native"))
    assert [s for s in stuecke if s.sorte == "denktempo"] == []


@pytest.mark.asyncio
async def test_live_speed_goes_out_while_the_answer_is_written(modellserver):
    """The same reading keeps going out once the answer text flows, so the
    figure under a running answer moves with it instead of standing still
    until the round ends."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo "}, "index": 0}],
         "timings": {"predicted_n": 4, "predicted_ms": 80, "predicted_per_second": 61.0}},
        {"choices": [{"delta": {"content": "Welt"}, "index": 0}],
         "timings": {"predicted_n": 8, "predicted_ms": 160, "predicted_per_second": 57.5}},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    readings = [s for s in stuecke if s.sorte == "denktempo"]
    assert readings
    assert readings[0].daten["tokens_pro_sekunde"] == 61.0
    assert readings[0].daten["tempo_quelle"] == "server"


@pytest.mark.asyncio
async def test_no_live_speed_for_the_answer_without_timings(modellserver):
    """The silence probe: answer text from a server that sends no `timings`
    — a cloud route — carries no live reading; nothing is estimated."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Hallo Welt"}, "index": 0}]},
    ])
    stuecke = await _einsammeln(_provider(modellserver.basis))
    assert [s for s in stuecke if s.sorte == "denktempo"] == []


# --- Request body ---------------------------------------------------------


@pytest.mark.asyncio
async def test_llama_cpp_wird_um_timings_je_token_gebeten(modellserver):
    """Without this flag llama.cpp keeps `timings` off every chunk but the
    last — measured on a llama.cpp server. Only llama.cpp needs to be asked: mlx
    already sends the block on every chunk by itself, and a cloud server
    would not know the field."""
    modellserver.inhalt_senden("x")
    await _einsammeln(_provider(modellserver.basis, parameter_dialect="llama_cpp"))
    assert modellserver.empfangene_koerper[0]["timings_per_token"] is True


@pytest.mark.asyncio
async def test_andere_dialekte_werden_nicht_um_timings_je_token_gebeten(modellserver):
    modellserver.inhalt_senden("x")
    await _einsammeln(_provider(modellserver.basis, parameter_dialect="openai"))
    assert "timings_per_token" not in modellserver.empfangene_koerper[0]


@pytest.mark.asyncio
async def test_modellfeld_faellt_ohne_kennung_weg(modellserver):
    """Without a reported id, the field is not sent at all.

    mlx_lm.server interprets "model" as a HuggingFace id and answers
    anything else with 404. Sending nothing is better than guessing.
    """
    modellserver.inhalt_senden("x")
    anfrage = Generierungsanfrage(nachrichten=[ChatNachricht(role="user", content="Hi")])
    await _einsammeln(_provider(modellserver.basis), anfrage)
    assert "model" not in modellserver.empfangene_koerper[0]


@pytest.mark.asyncio
async def test_gemeldete_kennung_geht_unveraendert_mit(modellserver):
    """Whatever the server reports under /v1/models goes back exactly as is."""
    modellserver.inhalt_senden("x")
    anfrage = Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hi")],
        modell="zecanard/gemma-4-26B-A4B-it",
    )
    await _einsammeln(_provider(modellserver.basis), anfrage)
    assert modellserver.empfangene_koerper[0]["model"] == "zecanard/gemma-4-26B-A4B-it"


@pytest.mark.asyncio
async def test_nicht_gesetzte_parameter_werden_nicht_mitgeschickt(modellserver):
    """Otherwise null values would override the server's defaults."""
    modellserver.inhalt_senden("x")
    await _einsammeln(_provider(modellserver.basis))
    koerper = modellserver.empfangene_koerper[0]
    assert "temperature" not in koerper
    assert "top_p" not in koerper
    assert "max_tokens" not in koerper


@pytest.mark.asyncio
async def test_gesetzte_parameter_kommen_an(modellserver):
    modellserver.inhalt_senden("x")
    anfrage = Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hi")],
        temperature=0.4,
        top_p=0.9,
        max_tokens=256,
    )
    await _einsammeln(_provider(modellserver.basis), anfrage)
    koerper = modellserver.empfangene_koerper[0]
    assert (koerper["temperature"], koerper["top_p"], koerper["max_tokens"]) == (0.4, 0.9, 256)


@pytest.mark.asyncio
async def test_werkzeuge_werden_mitgeschickt(modellserver):
    modellserver.inhalt_senden("x")
    werkzeug = {"type": "function", "function": {"name": "suchen", "parameters": {}}}
    anfrage = Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Hi")], werkzeuge=[werkzeug]
    )
    await _einsammeln(_provider(modellserver.basis), anfrage)
    koerper = modellserver.empfangene_koerper[0]
    assert koerper["tools"] == [werkzeug]
    assert koerper["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_werkzeugverlauf_wird_richtig_uebersetzt(modellserver):
    """Call and result must arrive in the format the servers expect."""
    from app.providers.base import Werkzeugaufruf

    modellserver.inhalt_senden("fertig")
    anfrage = Generierungsanfrage(
        nachrichten=[
            ChatNachricht(role="user", content="rechne"),
            ChatNachricht(
                role="assistant",
                content="",
                werkzeugaufrufe=[Werkzeugaufruf(id="a1", name="addieren", argumente={"a": 1})],
            ),
            ChatNachricht(role="tool", content="42", werkzeugaufruf_id="a1"),
        ]
    )
    await _einsammeln(_provider(modellserver.basis), anfrage)

    nachrichten = modellserver.empfangene_koerper[0]["messages"]
    assert nachrichten[1]["tool_calls"][0]["id"] == "a1"
    assert json.loads(nachrichten[1]["tool_calls"][0]["function"]["arguments"]) == {"a": 1}
    assert nachrichten[2]["tool_call_id"] == "a1"


# --- Tool calls from the stream -------------------------------------------


@pytest.mark.asyncio
async def test_zerstueckelter_werkzeugaufruf_wird_zusammengesetzt(modellserver):
    """Exactly the packet sequence llama.cpp sent for Mana."""
    modellserver.rohpakete(
        [
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "W1", "type": "function",
                 "function": {"name": "wetter", "arguments": "{"}}]}, "index": 0}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": '"ort":"'}}]}, "index": 0}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "Berlin"}}]}, "index": 0}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": '"}'}}]}, "index": 0}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls", "index": 0}]},
        ]
    )
    stuecke = await _einsammeln(_provider(modellserver.basis))
    aufrufe = next(s for s in stuecke if s.sorte == "tool_call").werkzeugaufrufe
    assert len(aufrufe) == 1
    assert aufrufe[0].id == "W1"
    assert aufrufe[0].name == "wetter"
    assert aufrufe[0].argumente == {"ort": "Berlin"}


@pytest.mark.asyncio
async def test_ohne_werkzeugaufruf_kein_tool_call_stueck(modellserver):
    modellserver.inhalt_senden("nur Text")
    stuecke = await _einsammeln(_provider(modellserver.basis))
    assert not [s for s in stuecke if s.sorte == "tool_call"]


# --- Errors ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_fehler_wird_zu_providerfehler(modellserver):
    modellserver.status = 404
    modellserver.fehlertext = "Model not found"
    with pytest.raises(ProviderFehler) as fehler:
        await _einsammeln(_provider(modellserver.basis))
    assert "404" in str(fehler.value)
    assert "Model not found" in str(fehler.value)


@pytest.mark.asyncio
async def test_serverfehler_wird_zu_providerfehler(modellserver):
    modellserver.status = 500
    with pytest.raises(ProviderFehler):
        await _einsammeln(_provider(modellserver.basis))


@pytest.mark.asyncio
async def test_nicht_erreichbarer_server_wird_zu_providerfehler():
    with pytest.raises(ProviderFehler) as fehler:
        await _einsammeln(_provider("http://127.0.0.1:9/v1"))
    assert "is not reachable" in str(fehler.value)


# --- Model name from the server -------------------------------------------
#
# The name in the UI comes from the server, not from the configuration:
# nobody should have to maintain model names, least of all for third-party
# models they have never seen.


@pytest.mark.asyncio
async def test_modellname_aus_dem_openai_aufbau(modellserver):
    """mlx_lm.server and the cloud providers answer like this."""
    modellserver.modell_antwort = {"object": "list", "data": [{"id": "testmodell"}]}
    assert await _provider(modellserver.basis).modellname() == "testmodell"


@pytest.mark.asyncio
async def test_modellname_aus_der_llama_liste(modellserver):
    """llama-server answers with its own list under 'models'."""
    modellserver.modell_antwort = {
        "models": [{"name": "qwen3.6-35b-a3b", "model": "qwen3.6-35b-a3b"}]
    }
    assert await _provider(modellserver.basis).modellname() == "qwen3.6-35b-a3b"


@pytest.mark.asyncio
async def test_modellname_ueberspringt_dateipfade(modellserver):
    """mlx_lm.server reports the same model twice.

    Once under its id and once under its path in the HuggingFace cache.
    Even if the path comes first, it must not pass as the name — it says
    nothing about what is loaded.
    """
    modellserver.modell_antwort = {
        "object": "list",
        "data": [
            {"id": "/Users/wer/.cache/huggingface/hub/models--x--y/snapshots/abc123"},
            {"id": "zecanard/gemma-4-26B-A4B-it-MLX-6bit"},
        ],
    }
    name = await _provider(modellserver.basis).modellname()
    assert name == "zecanard/gemma-4-26B-A4B-it-MLX-6bit"


@pytest.mark.asyncio
async def test_modellname_schraegstrich_allein_ist_kein_pfad(modellserver):
    """'zecanard/gemma-4' is a perfectly normal model name, not a path."""
    modellserver.modell_antwort = {"object": "list", "data": [{"id": "org/modell-7b"}]}
    assert await _provider(modellserver.basis).modellname() == "org/modell-7b"


@pytest.mark.asyncio
async def test_modellname_leer_wenn_nichts_brauchbares_kommt(modellserver):
    """Then the fallback to the configuration entry kicks in."""
    modellserver.modell_antwort = {"object": "list", "data": []}
    assert await _provider(modellserver.basis).modellname() is None


@pytest.mark.asyncio
async def test_modellname_leer_bei_unbrauchbarer_antwort(modellserver):
    """A server that sends something completely different must break nothing."""
    modellserver.modell_antwort = {"irgendwas": "anderes"}
    assert await _provider(modellserver.basis).modellname() is None


# --- The second wire to OpenAI's own host ---------------------------------
#
# A request to api.openai.com that carries tools AND a thinking stage cannot
# travel on the chat route: the server refuses that combination with a 400 and
# names its Responses API as the way out. Which of the two routes a request
# takes is the finding of every test below, so each one reads the PATH the
# stub saw, not only the body.

WERKZEUG = {
    "type": "function",
    "function": {
        "name": "wetter",
        "description": "Sagt das Wetter",
        "parameters": {"type": "object", "properties": {"ort": {"type": "string"}}},
    },
}


def _anfrage(
    werkzeuge: bool = True, stufe: str | None = "high", zusatz: dict | None = None
) -> Generierungsanfrage:
    return Generierungsanfrage(
        nachrichten=[ChatNachricht(role="user", content="Wie ist das Wetter?")],
        modell="gpt-5.6-luna",
        werkzeuge=[WERKZEUG] if werkzeuge else [],
        zusatz=zusatz if zusatz is not None else ({"reasoning_effort": stufe} if stufe else {}),
    )


@pytest.mark.asyncio
async def test_werkzeuge_und_stufe_gehen_ueber_die_responses_route(modellserver, monkeypatch):
    """The case from the finding: tools plus a stage arrive on the other wire,
    in the shape it reads — and the answer still comes back whole."""
    modellserver.antworten_senden("Es", " ist sonnig.")
    _ueber_proxy(monkeypatch, modellserver)

    stuecke = await _einsammeln(_provider("http://api.openai.com/v1", parameter_dialect="openai"),
                                _anfrage())

    assert modellserver.pfade == ["/v1/responses"]
    koerper = modellserver.empfangene_koerper[0]
    # The stage as its `effort`, and the summary asked for beside it: without
    # one this wire keeps the chain of thought to itself.
    assert koerper["reasoning"] == {"effort": "high", "summary": "auto"}
    assert "reasoning_effort" not in koerper
    assert "messages" not in koerper
    assert koerper["stream"] is True
    # The chat wire's usage switch has no meaning here: the closing event
    # reports the counts anyway.
    assert "stream_options" not in koerper
    assert koerper["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "Wie ist das Wetter?"}]}
    ]
    # The function IS the tool on this wire; there is no `function` inside it.
    assert koerper["tools"] == [
        {
            "type": "function",
            "name": "wetter",
            "description": "Sagt das Wetter",
            "parameters": {"type": "object", "properties": {"ort": {"type": "string"}}},
        }
    ]
    assert _text(stuecke, "content") == "Es ist sonnig."


@pytest.mark.asyncio
async def test_a_stage_without_tools_takes_the_responses_route(modellserver, monkeypatch):
    """Only the Responses wire returns a summary of the thinking, so a stage
    goes there with or without tools — asking for the summary, for the sealed
    thinking, and for nothing to be stored."""
    modellserver.antworten_senden("ok")
    _ueber_proxy(monkeypatch, modellserver)

    await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"),
        _anfrage(werkzeuge=False),
    )

    assert modellserver.pfade == ["/v1/responses"]
    koerper = modellserver.empfangene_koerper[0]
    assert koerper["reasoning"] == {"effort": "high", "summary": "auto"}
    assert koerper["store"] is False
    assert koerper["include"] == ["reasoning.encrypted_content"]
    assert "tools" not in koerper
    assert "tool_choice" not in koerper


@pytest.mark.asyncio
async def test_tools_without_a_stage_take_the_responses_route(modellserver, monkeypatch):
    """Tools go the same way without a stage, so one turn never changes wires
    between its rounds — and without a stage there is no thinking to ask
    back."""
    modellserver.antworten_senden("ok")
    _ueber_proxy(monkeypatch, modellserver)

    await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"),
        _anfrage(stufe=None),
    )

    assert modellserver.pfade == ["/v1/responses"]
    koerper = modellserver.empfangene_koerper[0]
    assert [w["name"] for w in koerper["tools"]] == ["wetter"]
    assert koerper["store"] is False
    assert "reasoning" not in koerper
    assert "include" not in koerper


@pytest.mark.asyncio
async def test_silence_probe_neither_stage_nor_tools_stays_on_the_chat_route(
    modellserver, monkeypatch
):
    """A plain chat keeps the compatibility route, untouched."""
    modellserver.inhalt_senden("ok")
    _ueber_proxy(monkeypatch, modellserver)

    await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"),
        _anfrage(werkzeuge=False, stufe=None),
    )

    assert modellserver.pfade == ["/v1/chat/completions"]
    koerper = modellserver.empfangene_koerper[0]
    assert "store" not in koerper
    assert "include" not in koerper


@pytest.mark.asyncio
async def test_silence_probe_stage_none_asks_for_no_summary(modellserver, monkeypatch):
    """A stage that switches thinking off has nothing to summarise and nothing
    sealed to hand back."""
    modellserver.antworten_senden("ok")
    _ueber_proxy(monkeypatch, modellserver)

    await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"),
        _anfrage(werkzeuge=False, stufe="none"),
    )

    assert modellserver.pfade == ["/v1/responses"]
    koerper = modellserver.empfangene_koerper[0]
    assert koerper["reasoning"] == {"effort": "none"}
    assert "include" not in koerper


@pytest.mark.asyncio
async def test_ein_anderer_wirt_bleibt_auf_der_chat_route(modellserver):
    """Every other server keeps the route it had — tools and stage or not.

    No proxy here on purpose: this address IS the stub, which stands for any
    OpenAI-compatible server that is not OpenAI's own.
    """
    modellserver.inhalt_senden("ok")

    await _einsammeln(_provider(modellserver.basis), _anfrage())

    assert modellserver.pfade == ["/v1/chat/completions"]
    assert modellserver.empfangene_koerper[0]["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_die_abgeschaltete_stufe_geht_als_none_hinaus(modellserver, monkeypatch):
    """Switched off, the request says `none` on this wire too — never the
    internal word, which a server would read as a stage nobody asked for.

    The stage comes through the real path here (`app/denkschalter.py`, which
    is the only place that decides the word), so the test covers the whole
    chain and not just the renaming.
    """
    modellserver.antworten_senden("ok")
    _ueber_proxy(monkeypatch, modellserver)
    endpunkt = EndpointConfig(
        id="prueflabor",
        base_url="http://api.openai.com/v1",
        parameter_dialect="openai",
    )
    stufe = denkschalter.zusatz(
        "off",
        SimpleNamespace(endpunkt=endpunkt, gemeldeter_name="gpt-5.6-luna", faehigkeiten_erkannt={}),
    )
    assert stufe == {"reasoning_effort": "none"}

    await _einsammeln(
        _provider(endpunkt.base_url, parameter_dialect="openai"),
        _anfrage(stufe=None, zusatz=stufe),
    )

    assert modellserver.pfade == ["/v1/responses"]
    koerper = modellserver.empfangene_koerper[0]
    # The silence probe: switched off, nothing is asked to be summarised.
    assert koerper["reasoning"] == {"effort": "none"}
    assert "off" not in json.dumps(koerper)


def test_eine_genannte_zusammenfassung_bleibt_stehen():
    """A summary the request already names is its own choice and is kept."""
    umgebaut = koerper_umbauen({
        "model": "gpt-5.6-luna",
        "messages": [{"role": "user", "content": "Hallo"}],
        "reasoning_effort": "high",
        "reasoning": {"summary": "detailed"},
    })
    assert umgebaut["reasoning"] == {"summary": "detailed", "effort": "high"}


def test_ohne_stufe_verlangt_der_umbau_keine_zusammenfassung():
    """The silence probe on the shape itself: a body without a stage gets no
    `reasoning` object at all, so no summary is asked of it either."""
    umgebaut = koerper_umbauen(
        {"model": "gpt-5.6-luna", "messages": [{"role": "user", "content": "Hallo"}]}
    )
    assert "reasoning" not in umgebaut


@pytest.mark.asyncio
async def test_ein_werkzeugaufruf_kommt_auch_ueber_die_responses_route_an(
    modellserver, monkeypatch
):
    """A call is reported item by item there: it opens with name and id, the
    arguments follow in pieces. What the assembler needs is all of it."""

    modellserver.antwort_ereignisse = [
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "wetter",
                "arguments": "",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "item_id": "fc_1",
            "delta": '{"ort":',
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "item_id": "fc_1",
            "delta": '"Berlin"}',
        },
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [{"type": "function_call", "id": "fc_1", "call_id": "call_1"}],
                "usage": {"input_tokens": 12, "output_tokens": 5, "total_tokens": 17},
            },
        },
    ]
    _ueber_proxy(monkeypatch, modellserver)

    stuecke = await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
    )

    aufrufe = [a for s in stuecke if s.sorte == "tool_call" for a in s.werkzeugaufrufe]
    assert [(a.id, a.name, a.argumente) for a in aufrufe] == [
        ("call_1", "wetter", {"ort": "Berlin"})
    ]
    # And the round named its end, so nothing here is read as a broken stream.
    stats = [s.daten for s in stuecke if s.sorte == "stats"][0]
    assert stats["ende_grund"] == "tool_calls"
    assert stats["abgeschnitten"] is False
    assert stats["nutzung"]["completion_tokens"] == 5


@pytest.mark.asyncio
async def test_das_modell_kommt_auch_ueber_die_responses_route_an(modellserver, monkeypatch):
    """This wire says which model answered in ``response.model`` — a
    top-level field of its own, as the chat wire has one. Translated out of
    the closing event it reaches the same stats key, so the protocol line
    names the model on either route instead of falling back to the requested
    one."""
    modellserver.antwort_ereignisse = [
        {"type": "response.output_text.delta", "item_id": "msg_1", "delta": "Hallo"},
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "model": "gpt-5.6-luna-2026-09-01",
                "output": [],
                "usage": {"input_tokens": 12, "output_tokens": 2, "total_tokens": 14},
            },
        },
    ]
    _ueber_proxy(monkeypatch, modellserver)

    stuecke = await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
    )

    stats = [s.daten for s in stuecke if s.sorte == "stats"][0]
    # The server's own id, not the `gpt-5.6-luna` this request named.
    assert stats["modell"] == "gpt-5.6-luna-2026-09-01"


@pytest.mark.asyncio
async def test_denken_kommt_auch_ueber_die_responses_route_an(modellserver, monkeypatch):
    """A chain of thought is reported there under its own event, and it stays
    what it is here: thinking, not answer text."""
    modellserver.antwort_ereignisse = [
        {"type": "response.reasoning_summary_text.delta", "item_id": "rs_1", "delta": "Erst "},
        {"type": "response.reasoning_summary_text.delta", "item_id": "rs_1", "delta": "zählen."},
        {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 1, "delta": "21"},
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [{"type": "message", "id": "msg_1", "content": []}],
                "usage": {
                    "input_tokens": 9,
                    "output_tokens": 4,
                    "total_tokens": 13,
                    "output_tokens_details": {"reasoning_tokens": 2},
                },
            },
        },
    ]
    _ueber_proxy(monkeypatch, modellserver)

    stuecke = await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
    )

    assert _text(stuecke, "reasoning") == "Erst zählen."
    assert _text(stuecke, "content") == "21"


@pytest.mark.asyncio
async def test_die_teile_einer_zusammenfassung_stehen_getrennt(modellserver, monkeypatch):
    """A summary arrives in parts, and the text events carry no break between
    them: from the second part on a blank line goes first, so one part's last
    sentence does not run into the next one's heading. The first part gets
    none — the thinking does not start on an empty line."""
    modellserver.antwort_ereignisse = [
        # A first part that carries no text owes nothing to the next one.
        {"type": "response.reasoning_summary_part.added", "item_id": "rs_0", "summary_index": 0},
        {"type": "response.reasoning_summary_part.added", "item_id": "rs_1", "summary_index": 0},
        {"type": "response.reasoning_summary_text.delta", "item_id": "rs_1", "delta": "**Plan** Erst."},
        {"type": "response.reasoning_summary_part.added", "item_id": "rs_1", "summary_index": 1},
        {"type": "response.reasoning_summary_text.delta", "item_id": "rs_1", "delta": "**Prüfen** Dann."},
        # A second reasoning item numbers its parts from 0 again.
        {"type": "response.reasoning_summary_part.added", "item_id": "rs_2", "summary_index": 0},
        {"type": "response.reasoning_summary_text.delta", "item_id": "rs_2", "delta": "**Ende** Fertig."},
        {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 1, "delta": "ok"},
        {
            "type": "response.completed",
            "response": {"status": "completed", "output": [], "usage": {"input_tokens": 3, "output_tokens": 2}},
        },
    ]
    _ueber_proxy(monkeypatch, modellserver)

    stuecke = await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
    )

    assert _text(stuecke, "reasoning") == "**Plan** Erst.\n\n**Prüfen** Dann.\n\n**Ende** Fertig."


@pytest.mark.asyncio
async def test_ein_abgeschnittener_strom_gilt_auch_hier_als_abgebrochen(
    modellserver, monkeypatch
):
    """The guard that a stream must name its end is not a property of one wire:
    a Responses stream that stops after its text is read as a broken provider
    too, not as a finished answer."""
    modellserver.antwort_ereignisse = [
        {"type": "response.output_text.delta", "item_id": "msg_1", "delta": "halb"}
    ]
    _ueber_proxy(monkeypatch, modellserver)

    with pytest.raises(ProviderFehler):
        await _einsammeln(
            _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
        )
    # And it was really this wire that ended without a word: the same test
    # used to pass over a chat route the request never should have taken.
    assert modellserver.pfade == ["/v1/responses"]


@pytest.mark.asyncio
async def test_zwei_werkzeugaufrufe_in_einer_runde_bleiben_getrennt(
    modellserver, monkeypatch
):
    """One call opens with name and position, the pieces after it carry only
    the item id. Tied by two different keys, the name of one call lands under
    a number the arguments never reach — the call arrives nameless, the
    assembler drops it, and the tool would run with no arguments at all.

    Two calls, because that is what tells the two keys apart; with one call
    both readings happen to land on zero.
    """
    modellserver.antwort_ereignisse = [
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {"type": "function_call", "id": "fc_1", "call_id": "call_1",
                     "name": "wetter", "arguments": ""},
        },
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {"type": "function_call", "id": "fc_2", "call_id": "call_2",
                     "name": "uhrzeit", "arguments": ""},
        },
        {"type": "response.function_call_arguments.delta", "item_id": "fc_1",
         "delta": '{"ort": "Berlin"}'},
        {"type": "response.function_call_arguments.delta", "item_id": "fc_2",
         "delta": '{"stadt": "Berlin"}'},
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [
                    {"type": "function_call", "id": "fc_1", "call_id": "call_1"},
                    {"type": "function_call", "id": "fc_2", "call_id": "call_2"},
                ],
            },
        },
    ]
    _ueber_proxy(monkeypatch, modellserver)

    stuecke = await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
    )

    aufrufe = [a for s in stuecke if s.sorte == "tool_call" for a in s.werkzeugaufrufe]
    assert [(a.id, a.name, a.argumente) for a in aufrufe] == [
        ("call_1", "wetter", {"ort": "Berlin"}),
        ("call_2", "uhrzeit", {"stadt": "Berlin"}),
    ]


@pytest.mark.asyncio
async def test_eine_verweigerung_kommt_als_antwort_an(modellserver, monkeypatch):
    """A refusal is what the model answered, not a missing answer: the chat
    route sends the same sentence as ordinary content, and left out it arrives
    as an empty answer with a clean "stop" under it."""
    modellserver.antwort_ereignisse = [
        {"type": "response.refusal.delta", "item_id": "msg_1", "delta": "Das darf ich nicht."},
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [{"type": "message", "id": "msg_1", "content": []}],
            },
        },
    ]
    _ueber_proxy(monkeypatch, modellserver)

    stuecke = await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
    )

    assert _text(stuecke, "content") == "Das darf ich nicht."


@pytest.mark.asyncio
async def test_ein_unvollstaendiger_strom_ohne_grund_behauptet_keinen_deckel(
    modellserver, monkeypatch
):
    """`response.incomplete` without a reason says the answer is not finished,
    nothing about why. Claiming a length end there would put a cut-off notice
    under an answer whose reason the server never named."""
    modellserver.antwort_ereignisse = [
        {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 0,
         "delta": "halb"},
        {"type": "response.incomplete", "response": {"status": "incomplete"}},
    ]
    _ueber_proxy(monkeypatch, modellserver)

    stuecke = await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
    )

    stats = [s.daten for s in stuecke if s.sorte == "stats"][0]
    assert stats["ende_grund"] == "incomplete"
    assert stats["abgeschnitten"] is False


@pytest.mark.asyncio
async def test_der_laufende_deckel_gilt_weiter_als_laengenende(modellserver, monkeypatch):
    """The one reason this wire does name — `max_output_tokens` — is passed on
    as it is, and `app/antwortende.py` knows that word."""
    modellserver.antwort_ereignisse = [
        {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 0,
         "delta": "halb"},
        {
            "type": "response.incomplete",
            "response": {"status": "incomplete",
                         "incomplete_details": {"reason": "max_output_tokens"}},
        },
    ]
    _ueber_proxy(monkeypatch, modellserver)

    stuecke = await _einsammeln(
        _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
    )

    stats = [s.daten for s in stuecke if s.sorte == "stats"][0]
    assert stats["abgeschnitten"] is True


@pytest.mark.asyncio
async def test_a_nameless_tool_leaves_tools_and_tool_choice_out(modellserver, monkeypatch):
    """The stage takes the request to the Responses wire; the one tool there
    cannot be sent, and an empty list or a choice with nothing to choose from
    stays out of the body."""
    modellserver.antworten_senden("ok")
    _ueber_proxy(monkeypatch, modellserver)
    anfrage = _anfrage()
    anfrage.werkzeuge = [{"type": "function", "function": {"parameters": {}}}]

    await _einsammeln(_provider("http://api.openai.com/v1", parameter_dialect="openai"), anfrage)

    assert modellserver.pfade == ["/v1/responses"]
    koerper = modellserver.empfangene_koerper[0]
    assert "tools" not in koerper
    assert "tool_choice" not in koerper


@pytest.mark.asyncio
async def test_silence_probe_only_nameless_tools_and_no_stage_stay_on_the_chat_route(
    modellserver, monkeypatch
):
    """Without a stage, a tool the other wire cannot send is no reason to
    change the route."""
    modellserver.inhalt_senden("ok")
    _ueber_proxy(monkeypatch, modellserver)
    anfrage = _anfrage(stufe=None)
    anfrage.werkzeuge = [{"type": "function", "function": {"parameters": {}}}]

    await _einsammeln(_provider("http://api.openai.com/v1", parameter_dialect="openai"), anfrage)

    assert modellserver.pfade == ["/v1/chat/completions"]


SUMMARY_REFUSAL = (
    400,
    "Your organization must be verified to generate reasoning summaries. "
    "param: reasoning.summary",
)


@pytest.mark.asyncio
async def test_a_refused_summary_is_asked_once_more_without_it(modellserver, monkeypatch):
    """The 400 names the summary: the same request goes out once more without
    it, the answer arrives, and the next request of this endpoint goes without
    it straight away. No error reaches the caller, so nothing is learned as a
    refused stage either."""
    modellserver.antworten_senden("Es ist sonnig.")
    modellserver.refusals = [SUMMARY_REFUSAL]
    _ueber_proxy(monkeypatch, modellserver)
    provider = _provider("http://api.openai.com/v1", parameter_dialect="openai")

    stuecke = await _einsammeln(provider, _anfrage())

    assert modellserver.pfade == ["/v1/responses", "/v1/responses"]
    erster, zweiter = modellserver.empfangene_koerper
    assert erster["reasoning"] == {"effort": "high", "summary": "auto"}
    assert zweiter["reasoning"] == {"effort": "high"}
    assert {k: v for k, v in erster.items() if k != "reasoning"} == {
        k: v for k, v in zweiter.items() if k != "reasoning"
    }
    assert _text(stuecke, "content") == "Es ist sonnig."
    assert not [s for s in stuecke if s.sorte == "error"]

    await _einsammeln(provider, _anfrage())

    assert len(modellserver.pfade) == 3
    assert modellserver.empfangene_koerper[2]["reasoning"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_silence_probe_a_failed_retry_keeps_the_summary(modellserver, monkeypatch):
    """When the request without the summary is refused as well, the summary
    was not the reason: the error reaches the caller, and the next request
    asks for the summary again."""
    modellserver.antworten_senden("ok")
    modellserver.refusals = [SUMMARY_REFUSAL, SUMMARY_REFUSAL]
    _ueber_proxy(monkeypatch, modellserver)
    provider = _provider("http://api.openai.com/v1", parameter_dialect="openai")

    with pytest.raises(ProviderFehler):
        await _einsammeln(provider, _anfrage())
    assert modellserver.pfade == ["/v1/responses", "/v1/responses"]

    await _einsammeln(provider, _anfrage())
    assert modellserver.empfangene_koerper[-1]["reasoning"] == {"effort": "high", "summary": "auto"}


@pytest.mark.asyncio
async def test_silence_probe_another_endpoint_keeps_the_summary(modellserver, monkeypatch):
    """What one endpoint learned stays with it."""
    modellserver.antworten_senden("ok")
    modellserver.refusals = [SUMMARY_REFUSAL]
    _ueber_proxy(monkeypatch, modellserver)
    await _einsammeln(_provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage())

    await _einsammeln(_provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage())

    assert modellserver.empfangene_koerper[-1]["reasoning"] == {"effort": "high", "summary": "auto"}


@pytest.mark.asyncio
async def test_silence_probe_a_400_about_another_field_is_no_reason_to_drop_it(
    modellserver, monkeypatch
):
    """Only a refusal naming the summary is answered by sending again; any
    other 400 ends the request as before, and the summary stays."""
    modellserver.antworten_senden("ok")
    modellserver.refusals = [(400, "Unsupported parameter: 'temperature'")]
    _ueber_proxy(monkeypatch, modellserver)
    provider = _provider("http://api.openai.com/v1", parameter_dialect="openai")

    with pytest.raises(ProviderFehler) as fehler:
        await _einsammeln(provider, _anfrage())
    assert fehler.value.status == 400
    assert modellserver.pfade == ["/v1/responses"]

    await _einsammeln(provider, _anfrage())
    assert modellserver.empfangene_koerper[-1]["reasoning"] == {"effort": "high", "summary": "auto"}


def _runde_mit_denken() -> list[dict]:
    """A round that thinks, comments and calls a tool — the items in the order
    a real stream sends them."""
    denken = {
        "type": "reasoning",
        "id": "rs_1",
        "status": "completed",
        "summary": [{"type": "summary_text", "text": "Nachsehen."}],
        "encrypted_content": "versiegelt",
    }
    kommentar = {
        "type": "message",
        "id": "msg_1",
        "status": "completed",
        "role": "assistant",
        "phase": "commentary",
        "content": [{"type": "output_text", "text": "Ich sehe nach. ", "annotations": []}],
    }
    aufruf = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "wetter",
        "arguments": "",
    }
    return [
        {"type": "response.output_item.done", "output_index": 0, "item": denken},
        {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 1,
         "delta": "Ich sehe nach. "},
        {"type": "response.output_item.done", "output_index": 1, "item": kommentar},
        {"type": "response.output_item.added", "output_index": 2, "item": aufruf},
        {"type": "response.function_call_arguments.delta", "item_id": "fc_1",
         "output_index": 2, "delta": '{"ort": "Berlin"}'},
        {"type": "response.output_item.done", "output_index": 2,
         "item": {**aufruf, "arguments": '{"ort": "Berlin"}'}},
        {"type": "response.completed", "response": {
            "status": "completed", "output": [denken, kommentar, aufruf]}},
    ]


@pytest.mark.asyncio
async def test_the_next_round_hands_back_the_sealed_thinking_and_the_phase(
    modellserver, monkeypatch
):
    """With `store: false` the server keeps nothing: the second round carries
    the first round's thinking item without `id` and `status`, then its text
    item with its `phase`, then the call and its result."""
    modellserver.antwort_ereignisse = _runde_mit_denken()
    _ueber_proxy(monkeypatch, modellserver)
    provider = _provider("http://api.openai.com/v1", parameter_dialect="openai")
    anfrage = _anfrage()

    stuecke = await _einsammeln(provider, anfrage)

    teile = [s.daten["eintrag"] for s in stuecke if s.sorte == "response_item"]
    assert [t["type"] for t in teile] == ["reasoning", "message"]
    aufrufe = next(s for s in stuecke if s.sorte == "tool_call").werkzeugaufrufe
    anfrage.nachrichten += [
        ChatNachricht(
            role="assistant",
            content="Ich sehe nach. ",
            werkzeugaufrufe=aufrufe,
            reasoning_items=[t for t in teile if t["type"] == "reasoning"],
            message_items=[t for t in teile if t["type"] == "message"],
        ),
        ChatNachricht(role="tool", content="Sonne", werkzeugaufruf_id="call_1"),
    ]
    modellserver.antworten_senden("Es ist sonnig.")

    await _einsammeln(provider, anfrage)

    eingabe = modellserver.empfangene_koerper[1]["input"]
    assert eingabe[1:] == [
        {
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "Nachsehen."}],
            "encrypted_content": "versiegelt",
        },
        {
            "type": "message",
            "role": "assistant",
            "phase": "commentary",
            "content": [{"type": "output_text", "text": "Ich sehe nach. "}],
        },
        {"type": "function_call", "call_id": "call_1", "name": "wetter",
         "arguments": '{"ort": "Berlin"}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "Sonne"},
    ]


@pytest.mark.asyncio
async def test_silence_probe_the_chat_route_never_sends_the_items(modellserver):
    """Items that reached a message are the other wire's business; a chat
    server never sees them."""
    modellserver.inhalt_senden("ok")
    anfrage = Generierungsanfrage(
        nachrichten=[
            ChatNachricht(role="user", content="Hallo"),
            ChatNachricht(
                role="assistant",
                content="",
                werkzeugaufrufe=[Werkzeugaufruf(id="c1", name="wetter", argumente={})],
                reasoning_items=[{"type": "reasoning", "encrypted_content": "x"}],
                message_items=[{"type": "message", "role": "assistant", "content": []}],
            ),
            ChatNachricht(role="tool", content="Sonne", werkzeugaufruf_id="c1"),
        ]
    )

    await _einsammeln(_provider(modellserver.basis), anfrage)

    assert modellserver.pfade == ["/v1/chat/completions"]
    for nachricht in modellserver.empfangene_koerper[0]["messages"]:
        assert "reasoning_items" not in nachricht
        assert "message_items" not in nachricht


@pytest.mark.asyncio
async def test_ein_flacher_fehler_traegt_seinen_text(modellserver, monkeypatch):
    """A failed stream says why in three shapes; the flat one carries the
    message and the code on top, and reading only the nested ones would pass
    an empty reason on to the window and the refusal readers."""
    modellserver.antwort_ereignisse = [
        {"type": "error", "code": "server_error", "message": "upstream ist weg"}
    ]
    _ueber_proxy(monkeypatch, modellserver)

    with pytest.raises(ProviderFehler) as fehler:
        await _einsammeln(
            _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
        )
    assert "upstream ist weg" in str(fehler.value)
    assert "server_error" in str(fehler.value)


@pytest.mark.asyncio
async def test_ein_gescheiterte_antwort_wird_zum_anbieterfehler(modellserver, monkeypatch):
    """A failed response carries the reason; it is passed on instead of being
    read as an empty answer."""
    modellserver.antwort_ereignisse = [
        {
            "type": "response.failed",
            "response": {"status": "failed", "error": {"message": "rate limit reached"}},
        }
    ]
    _ueber_proxy(monkeypatch, modellserver)

    with pytest.raises(ProviderFehler) as fehler:
        await _einsammeln(
            _provider("http://api.openai.com/v1", parameter_dialect="openai"), _anfrage()
        )
    assert "rate limit reached" in str(fehler.value)


@pytest.mark.asyncio
async def test_die_antwortgrenze_reist_unter_ihrem_neuen_namen(modellserver, monkeypatch):
    """A ceiling someone set travels as `max_output_tokens` there — and only
    when it was set at all: a number nobody chose is not invented for this
    wire either."""
    modellserver.antworten_senden("ok")
    _ueber_proxy(monkeypatch, modellserver)
    provider = _provider("http://api.openai.com/v1", parameter_dialect="openai")

    ohne = _anfrage()
    ohne.werkzeuge = [WERKZEUG]
    await _einsammeln(provider, ohne)
    assert "max_output_tokens" not in modellserver.empfangene_koerper[0]

    mit = _anfrage()
    mit.max_tokens = 512
    await _einsammeln(provider, mit)
    koerper = modellserver.empfangene_koerper[1]
    assert koerper["max_output_tokens"] == 512
    assert "max_tokens" not in koerper
    assert "max_completion_tokens" not in koerper


@pytest.mark.asyncio
async def test_der_werkzeugverlauf_wird_fuer_diese_route_umgebaut(modellserver, monkeypatch):
    """An assistant row carrying a call becomes a call item, the tool row its
    output item — beside the messages, not inside them."""
    from app.providers.base import Werkzeugaufruf

    modellserver.antworten_senden("ok")
    _ueber_proxy(monkeypatch, modellserver)
    anfrage = Generierungsanfrage(
        nachrichten=[
            ChatNachricht(role="user", content="rechne"),
            ChatNachricht(
                role="assistant",
                content="Ich rechne.",
                werkzeugaufrufe=[Werkzeugaufruf(id="call_1", name="addieren", argumente={"a": 1})],
            ),
            ChatNachricht(role="tool", content="42", werkzeugaufruf_id="call_1"),
        ],
        modell="gpt-5.6-luna",
        werkzeuge=[WERKZEUG],
        zusatz={"reasoning_effort": "low"},
    )
    await _einsammeln(_provider("http://api.openai.com/v1", parameter_dialect="openai"), anfrage)

    assert modellserver.pfade == ["/v1/responses"]
    assert modellserver.empfangene_koerper[0]["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "rechne"}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "Ich rechne."}]},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "addieren",
            "arguments": json.dumps({"a": 1}),
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "42"},
    ]


# --- The "Zeitgrenze" switch ----------------------------------------------


def test_eine_ausgeschaltete_zeitgrenze_nimmt_die_lesefrist_weg():
    """The whole point of the switch: the read timeout goes away — fails
    without the fix (the flat float the old code passed had no `read`)."""
    ergebnis = zeitlimit(600.0, timeout_enabled=False)
    assert ergebnis.read is None
    assert ergebnis.connect == 600.0


def test_schweigeprobe_eine_eingeschaltete_zeitgrenze_bleibt_bei_600s():
    """The switch left on must still behave exactly as it always did."""
    ergebnis = zeitlimit(600.0, timeout_enabled=True)
    assert ergebnis.read == 600.0
    assert ergebnis.connect == 600.0


def test_ein_neuer_endpunkt_startet_mit_eingeschalteter_zeitgrenze():
    """The default a bare entry gets, in `config.yaml` or in code — off
    must be a choice someone made, never the silent result of a missing
    field."""
    endpunkt = EndpointConfig(id="x", base_url="http://x")
    assert endpunkt.timeout_enabled is True


@pytest.mark.asyncio
async def test_der_provider_reicht_die_eigene_zeitgrenze_an_httpx_durch(modellserver):
    """The value travels from the endpoint to the request, not only to a
    field nobody reads: the provider is built with the switch off, and the
    real streaming call still completes — proof it used the endpoint's own
    setting rather than the constructor default."""
    modellserver.inhalt_senden("ok")
    provider = _provider(modellserver.basis, timeout_enabled=False)
    stuecke = await _einsammeln(provider)
    assert _text(stuecke, "content") == "ok"


# --- The Responses wire names the same numbers differently -----------------


def test_die_responses_nutzung_nennt_den_cache_anteil():
    """`usage.input_tokens_details.cached_tokens` is this wire's name for
    what the chat wire calls `prompt_tokens_details.cached_tokens` — and
    that is where an answer's `cache_tokens` comes from
    (`einlesen_ermitteln`). Left unnamed, the cache share under an answer
    was simply missing on this route."""
    nutzung = _nutzung({
        "input_tokens": 1200,
        "output_tokens": 40,
        "input_tokens_details": {"cached_tokens": 980},
    })
    assert nutzung["prompt_tokens"] == 1200
    assert nutzung["prompt_tokens_details"] == {"cached_tokens": 980}
    assert einlesen_ermitteln(None, nutzung)["cache_tokens"] == 980


def test_ohne_cache_feld_kein_cache_tokens():
    """The silent case, the rule of the whole reading: a server that names
    no cache reading gets none — not a zero, which would claim the cache
    had missed."""
    nutzung = _nutzung({"input_tokens": 1200, "output_tokens": 40})
    assert "prompt_tokens_details" not in nutzung
    assert "cache_tokens" not in einlesen_ermitteln(None, nutzung)


# --- The finished answer's cache share -------------------------------------


def test_der_fertige_anteil_teilt_durch_die_ganze_prompt():
    """The two halves llama.cpp names are what the share divides — NOT
    `cache_tokens` over `prompt_tokens`: on that wire `prompt_tokens` falls
    back to the freshly-read half alone, and the share came out far above
    hundred (measured: 977 of 1501 cached read as 186 %)."""
    assert _cache_share({"cache_n": 977, "prompt_n": 524}, None) == {
        "prompt_cache_percent": 65
    }


def test_der_fertige_anteil_nimmt_die_promptzahl_aus_usage():
    """Where the server names the whole prompt beside the cached half — the
    OpenAI form — those two divide, the same reading the live path sends."""
    assert _cache_share(
        None, {"prompt_tokens": 1500, "prompt_tokens_details": {"cached_tokens": 978}}
    ) == {"prompt_cache_percent": 65}


def test_ein_ganz_gefundener_prompt_ist_hundert_prozent():
    """Everything stood in the cache: nothing had to be read in, and a
    freshly-read half of zero is a reading, not a missing one."""
    assert _cache_share({"cache_n": 1501, "prompt_n": 0}, None) == {
        "prompt_cache_percent": 100
    }


def test_ohne_cache_kein_fertiger_anteil():
    """The silent case: a server that names no cache level gets no share in
    its stats — not a zero, which would claim the cache had missed."""
    assert _cache_share({"prompt_n": 500}, None) == {}


def _routes(monkeypatch, answers: dict, modell=None) -> OpenAIKompatiblerProvider:
    """A server answering only the given paths (suffix -> JSON); every other
    path is a 404, the way a server without that route answers."""
    def handler(request):
        for suffix, body in answers.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json=body)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    echt = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: echt(transport=transport, **kw))
    return OpenAIKompatiblerProvider(EndpointConfig(
        id="x", base_url="http://127.0.0.1:9/v1", modell=modell, parameter_dialect="openai",
    ))


async def test_every_catalogue_model_carries_its_own_window(monkeypatch):
    """oMLX names a window per model, in the list and on the status rows:
    each model gets its own, the list first."""
    provider = _routes(monkeypatch, {
        "/v1/models": {"data": [
            {"id": "qwen-4b", "max_model_len": 262144},
            {"id": "qwen-27b", "max_model_len": 131071},
            {"id": "bare"},
        ]},
        "/v1/models/status": {"models": [
            {"id": "qwen-4b", "max_context_window": 1},
            {"id": "bare", "max_context_window": 32768},
        ]},
    })
    assert await provider.context_per_model(1.0) == {
        "qwen-4b": 262144,
        "qwen-27b": 131071,
        "bare": 32768,
    }


async def test_lm_studio_names_the_loaded_window(monkeypatch):
    """LM Studio: the window the model was loaded with, otherwise its most."""
    provider = _routes(monkeypatch, {"/api/v0/models": {"data": [
        {"id": "gemma", "max_context_length": 131072, "loaded_context_length": 8192},
        {"id": "phi", "max_context_length": 16384},
    ]}})
    assert await provider.kontextgroesse(1.0, "gemma") == 8192


async def test_lm_studio_without_a_loaded_window_names_its_most(monkeypatch):
    provider = _routes(monkeypatch, {"/api/v0/models": {"data": [
        {"id": "gemma", "max_context_length": 131072, "loaded_context_length": 8192},
        {"id": "phi", "max_context_length": 16384},
    ]}})
    assert await provider.kontextgroesse(1.0, "phi") == 16384


async def test_ollama_names_the_running_window(monkeypatch):
    """Ollama: the window the running model was started with."""
    provider = _routes(monkeypatch, {"/api/ps": {"models": [
        {"name": "llama3:latest", "model": "llama3:latest", "context_length": 4096},
        {"name": "qwen3:8b", "model": "qwen3:8b", "context_length": 40960},
    ]}})
    assert await provider.kontextgroesse(1.0, "qwen3:8b") == 40960


async def test_a_server_without_any_of_the_routes_names_no_window(monkeypatch):
    """Silence probe: nothing answers, nothing is invented — the fallback
    in app/fenstergroesse.py stands as before."""
    provider = _routes(monkeypatch, {"/v1/models": {"data": [{"id": "m"}]}})
    assert await provider.kontextgroesse(1.0, "m") is None
    assert await provider.context_per_model(1.0) == {}


async def test_the_omlx_status_row_names_no_answer_limit(monkeypatch):
    """oMLX's `max_tokens` on the status row is the length its profile uses
    when a request names none — a request may ask for more. It is no limit
    and caps nothing."""
    provider = _routes(monkeypatch, {
        "/v1/models": {"data": [{"id": "qwen-27b", "max_model_len": 131071}]},
        "/v1/models/status": {"models": [{"id": "qwen-27b", "max_tokens": 1024}]},
    })
    assert await provider.hoechste_antwort(1.0, "qwen-27b") is None


async def test_a_limit_from_a_refusal_still_binds_beside_the_omlx_row(monkeypatch):
    """Silence probe: the status row's default is no limit, but a limit a
    refusal of this request named still binds it."""
    from app import antwortgrenze

    provider = _routes(monkeypatch, {
        "/v1/models": {"data": [{"id": "qwen-27b", "max_model_len": 131071}]},
        "/v1/models/status": {"models": [{"id": "qwen-27b", "max_tokens": 1024}]},
    })
    zustand = SimpleNamespace(
        provider=provider, gemeldeter_name="qwen-27b", endpunkt=provider.endpunkt,
    )
    zustand.hersteller_max_tokens = await antwortgrenze.serverseitig_aufloesen(
        zustand, None, 1.0,
    )
    assert zustand.hersteller_max_tokens is None
    zug = antwortgrenze.Zug(max_tokens=4096)
    assert antwortgrenze.geltender_deckel(zustand, None, zug) == 4096


async def test_every_listed_model_carries_only_its_own_answer_limit(monkeypatch):
    """A limit the list names belongs to its own entry; a model without one
    has none."""
    provider = _routes(monkeypatch, {"/v1/models": {"data": [
        {"id": "a", "max_completion_tokens": 8192},
        {"id": "b", "max_model_len": 131071},
    ]}})
    assert await provider.answer_limit_per_model(1.0) == {"a": 8192}


async def test_the_list_s_own_limit_beats_the_status_row(monkeypatch):
    """Silence probe: where the list names the limit, that one stands."""
    provider = _routes(monkeypatch, {
        "/v1/models": {"data": [{"id": "qwen-27b", "max_completion_tokens": 8192}]},
        "/v1/models/status": {"models": [{"id": "qwen-27b", "max_tokens": 32768}]},
    })
    assert await provider.hoechste_antwort(1.0, "qwen-27b") == 8192


async def test_ollama_a_name_without_a_tag_means_latest(monkeypatch):
    """Asked for "llama3.2", /api/ps names "llama3.2:latest": the same model,
    because a missing tag means `latest`."""
    provider = _routes(monkeypatch, {"/api/ps": {"models": [
        {"name": "llama3.2:latest", "model": "llama3.2:latest", "context_length": 8192},
    ]}})
    assert await provider.kontextgroesse(1.0, "llama3.2") == 8192


async def test_ollama_another_tag_of_the_same_model_is_not_a_match(monkeypatch):
    """Silence probe: "llama3.2:3b" is another tag, not the `latest` one."""
    provider = _routes(monkeypatch, {"/api/ps": {"models": [
        {"name": "llama3.2:latest", "model": "llama3.2:latest", "context_length": 8192},
    ]}})
    assert await provider.kontextgroesse(1.0, "llama3.2:3b") is None


async def test_ollama_with_another_model_loaded_names_no_window(monkeypatch):
    """The one running model is not the one asked for: its window is not
    taken — it belongs to somebody else."""
    provider = _routes(monkeypatch, {"/api/ps": {"models": [
        {"name": "nomic-embed:latest", "model": "nomic-embed:latest", "context_length": 2048},
    ]}})
    assert await provider.kontextgroesse(1.0, "qwen3:8b") is None


async def test_an_unanswered_list_is_no_answer_per_model(monkeypatch):
    """No list at all: `None`, so discovery asks again — not an empty
    mapping that would stand for good."""
    provider = _routes(monkeypatch, {})
    assert await provider.context_per_model(1.0) is None


def _mlx_status(monkeypatch, rows: list[dict]) -> OpenAIKompatiblerProvider:
    def handler(request):
        if request.url.path.endswith("/models/status"):
            return httpx.Response(200, json={"models": rows})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    echt = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: echt(transport=transport, **kw))
    return OpenAIKompatiblerProvider(EndpointConfig(
        id="omlx", base_url="http://127.0.0.1:9/v1", parameter_dialect="mlx",
    ))


async def test_an_alias_carries_the_family_of_its_model(monkeypatch):
    """/v1/models names the alias; the status row names the family under the
    id. The alias gets it too, and the folder with the template."""
    provider = _mlx_status(monkeypatch, [{
        "id": "Qwen3.5-4B-MLX", "model_alias": "MLX Assistant",
        "config_model_type": "qwen3_5", "model_path": "/models/Qwen3.5-4B-MLX",
    }])
    quellen = await provider.denkquellen(1.0)
    assert quellen["familien"] == {"Qwen3.5-4B-MLX": "qwen3_5", "MLX Assistant": "qwen3_5"}
    assert quellen["template_paths"] == {
        "Qwen3.5-4B-MLX": "/models/Qwen3.5-4B-MLX",
        "MLX Assistant": "/models/Qwen3.5-4B-MLX",
    }


async def test_a_row_without_alias_is_named_once(monkeypatch):
    """Silence probe: no alias, one name, as before."""
    provider = _mlx_status(monkeypatch, [{
        "id": "Qwen3.8-27B", "model_alias": None, "config_model_type": "qwen3_5",
    }])
    assert await provider.denkquellen(1.0) == {"familien": {"Qwen3.8-27B": "qwen3_5"}}


async def test_status_rows_named_by_their_key_carry_their_family(monkeypatch):
    """A status answer shaped as a mapping of model name to row: the name
    comes from the key, as for the window per model."""
    def handler(request):
        if request.url.path.endswith("/models/status"):
            return httpx.Response(200, json={"Qwen3.8-27B": {
                "config_model_type": "qwen3_5", "model_path": "/models/q38",
            }})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    echt = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: echt(transport=transport, **kw))
    provider = OpenAIKompatiblerProvider(EndpointConfig(
        id="omlx", base_url="http://127.0.0.1:9/v1", parameter_dialect="mlx",
    ))
    assert await provider.denkquellen(1.0) == {
        "familien": {"Qwen3.8-27B": "qwen3_5"},
        "template_paths": {"Qwen3.8-27B": "/models/q38"},
    }


def _phase_stream(phase, text="Text"):
    """One message item opened with ``phase``, then a text delta for it."""
    item = {"type": "message", "id": "msg_1", "role": "assistant"}
    if phase is not None:
        item["phase"] = phase
    return [
        {"type": "response.output_item.added", "output_index": 0, "item": item},
        {"type": "response.output_text.delta", "output_index": 0, "item_id": "msg_1", "delta": text},
    ]


def _final_answer(text="Answer", index=1):
    return [
        {
            "type": "response.output_item.added",
            "output_index": index,
            "item": {"type": "message", "id": f"msg_{index + 1}", "role": "assistant", "phase": "final_answer"},
        },
        {
            "type": "response.output_text.delta",
            "output_index": index,
            "item_id": f"msg_{index + 1}",
            "delta": text,
        },
    ]


COMPLETED = {"type": "response.completed", "response": {"status": "completed", "output": []}}


def _deltas(events):
    from app.providers.openai_responses import Leser

    reader = Leser()
    return [p["choices"][0]["delta"] for e in events for p in reader.pakete(e)]


def test_the_commentary_phase_goes_as_thinking():
    """Commentary is the model narrating between its steps; the phase is
    named when the item opens, the text follows after. Beside an answer it
    is thinking."""
    assert _deltas(_phase_stream("commentary") + _final_answer()) == [
        {"reasoning": "Text"},
        {"content": "Answer"},
    ]
    assert _deltas(_phase_stream("analysis")) == [{"reasoning": "Text"}]


def test_text_without_a_phase_stays_the_answer():
    """Silence probe: a message item without a phase is the answer, as before."""
    assert _deltas(_phase_stream(None)) == [{"content": "Text"}]


def test_commentary_after_a_summary_starts_a_paragraph():
    """A narrating item is a new part of the thinking: its first text starts
    on its own paragraph after the summary before it."""
    events = [
        {"type": "response.reasoning_summary_text.delta", "delta": "Plan"},
        *_phase_stream("commentary"),
        *_final_answer(),
    ]
    assert _deltas(events) == [
        {"reasoning": "Plan"},
        {"reasoning": "\n\nText"},
        {"content": "Answer"},
    ]


def test_the_phase_belongs_to_its_item():
    """Two message items open before their text arrives; each delta is read
    by the item it names, not by whichever item opened last."""
    events = [
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {"type": "message", "id": "msg_1", "role": "assistant", "phase": "commentary"},
        },
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {"type": "message", "id": "msg_2", "role": "assistant", "phase": "final_answer"},
        },
        {"type": "response.output_text.delta", "output_index": 0, "item_id": "msg_1", "delta": "Note"},
        {"type": "response.output_text.delta", "output_index": 1, "item_id": "msg_2", "delta": "Answer"},
    ]
    assert _deltas(events) == [{"reasoning": "Note"}, {"content": "Answer"}]


def test_commentary_without_an_answer_is_the_answer_only():
    """A round that ends on commentary alone, with no answer text and no
    call, has that commentary as its answer — shown once, as the answer, not
    as thinking beside it."""
    deltas = _deltas(_phase_stream("commentary") + [COMPLETED])
    assert [d for d in deltas if d] == [{"content": "Text"}]


def test_cut_off_commentary_is_the_answer_only():
    """The same for a round cut off with commentary alone."""
    events = _phase_stream("commentary") + [
        {
            "type": "response.incomplete",
            "response": {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
        }
    ]
    deltas = _deltas(events)
    assert [d for d in deltas if "content" in d or "reasoning" in d] == [{"content": "Text"}]


def test_commentary_beside_an_answer_or_call_stays_thinking():
    """Silence probe: with an answer, or with a call, the commentary is
    thinking only, once."""
    with_answer = _deltas(_phase_stream("commentary") + _final_answer() + [COMPLETED])
    assert [d for d in with_answer if "content" in d] == [{"content": "Answer"}]
    assert [d for d in with_answer if "reasoning" in d] == [{"reasoning": "Text"}]
    with_call = _deltas(
        _phase_stream("commentary")
        + [
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {"type": "function_call", "id": "fc_1", "call_id": "c1", "name": "clock"},
            },
            {
                "type": "response.completed",
                "response": {"status": "completed", "output": [{"type": "function_call"}]},
            },
        ]
    )
    assert not [d for d in with_call if "content" in d]
    assert [d for d in with_call if "reasoning" in d] == [{"reasoning": "Text"}]



def test_new_thinking_sends_the_held_commentary_first():
    """Summary text arriving while commentary is held: the commentary goes
    out first, as thinking, and the summary starts a paragraph after it."""
    events = [
        *_phase_stream("commentary"),
        {"type": "response.reasoning_summary_text.delta", "delta": "Plan"},
    ]
    assert _deltas(events) == [{"reasoning": "Text"}, {"reasoning": "\n\nPlan"}]


def test_a_failed_round_drops_the_held_commentary():
    """A round that fails has no answer: the commentary held back for it is
    not sent at all."""
    import pytest as _pytest

    from app.providers.base import ProviderFehler
    from app.providers.openai_responses import Leser

    reader = Leser()
    sent = []
    for event in _phase_stream("commentary"):
        sent.extend(reader.pakete(event))
    with _pytest.raises(ProviderFehler):
        reader.pakete({"type": "error", "code": "server_error", "message": "boom"})
    assert sent == []



def test_analysis_sends_the_held_commentary_first():
    """Analysis text arriving while commentary is held: the commentary goes
    out first, as thinking, and the analysis starts a paragraph after it."""
    events = [
        *_phase_stream("commentary"),
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {"type": "message", "id": "msg_2", "role": "assistant", "phase": "analysis"},
        },
        {"type": "response.output_text.delta", "output_index": 1, "item_id": "msg_2", "delta": "Check"},
    ]
    assert _deltas(events) == [{"reasoning": "Text"}, {"reasoning": "\n\nCheck"}]
