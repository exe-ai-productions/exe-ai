"""The thinking does not count towards the speed.

Speed here means the speed of the ANSWER: how fast the text under the
question was written. A model that thinks for a minute and then writes
three lines quickly did write those three lines quickly, and the number
below them has to say so. So a chain of thought neither adds to the
counted tokens nor stamps the moment the answer began — that moment is the
anchor of the divisor, and thinking that set it would press the speed down
through the denominator even with the counting corrected.

The OpenAI-compatible route is the hard case, because it meets the chain of
thought in two entirely different shapes:

  * as a field of its own (``delta.reasoning`` / ``delta.reasoning_content``),
  * as markers inside the ordinary ``content`` text, which only the parser
    can tell apart (<think> tags, Harmony channels).

Both are checked here. A repair that covered only the field would leave
every server speaking in markers counting its thinking as before, and
nothing on the surface would show which of the two a run had used.

Every test also runs a second time WITHOUT the thinking: the number has to
come out the same. That is the actual claim — not "smaller than before",
but "the same as a run that never thought at all".
"""

from __future__ import annotations

import asyncio
import json
import socket

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from app.config import EndpointConfig
from app.providers import ChatNachricht, Generierungsanfrage
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider


class ModellServerAttrappe:
    """An OpenAI-compatible server, fed packet by packet from a test."""

    def __init__(self) -> None:
        self.pakete: list[dict] = []
        # Seconds to wait before the packet at this index goes out. This is
        # how a long chain of thought is imitated without a real model:
        # the pause is the time the run would have spent thinking, and it
        # is the only way to see whether that time lands in the divisor.
        self.pause_vor: dict[int, float] = {}
        self.app = FastAPI()

        @self.app.get("/v1/models")
        async def modelle():
            return {"object": "list", "data": [{"id": "testmodell"}]}

        @self.app.post("/v1/chat/completions")
        async def completions(request: Request):
            await request.json()

            async def strom():
                for nummer, paket in enumerate(self.pakete):
                    if pause := self.pause_vor.get(nummer):
                        await asyncio.sleep(pause)
                    yield f"data: {json.dumps(paket)}\n\n"
                    await asyncio.sleep(0)
                # The closing word every real server says. Without it the
                # stream reads as a provider that broke off mid-answer
                # (app/providers/openai_kompatibel.py), and these tests are
                # about the speed of a finished answer.
                ende = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                yield f"data: {json.dumps(ende)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(strom(), media_type="text/event-stream")


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


async def _messwerte(provider) -> dict:
    """Runs one stream and hands back the stats chunk plus the two texts."""
    anfrage = Generierungsanfrage(nachrichten=[ChatNachricht(role="user", content="Hallo")])
    stuecke = []
    async for stueck in provider.streamen(anfrage):
        stuecke.append(stueck)
    daten = dict(next(s for s in stuecke if s.sorte == "stats").daten)
    daten["_antwort"] = "".join(s.text for s in stuecke if s.sorte == "content")
    daten["_gedanke"] = "".join(s.text for s in stuecke if s.sorte == "reasoning")
    return daten


def _denkfeld(text: str) -> dict:
    return {"choices": [{"delta": {"reasoning": text}, "index": 0}]}


def _textfeld(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}, "index": 0}]}


# --- The chain of thought as a field of its own ---------------------------


async def test_eigenes_denkfeld_zaehlt_nicht_mit(modellserver):
    """Nine chunks of thinking, one of answer — counted is the one."""
    modellserver.pakete = [_denkfeld(f"Schritt {i} ") for i in range(9)] + [_textfeld("Antwort")]
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="native"))
    assert werte["haeppchen"] == 1
    assert werte["erzeugte_tokens"] == 1


async def test_ohne_denken_dieselbe_zahl_beim_eigenen_feld(modellserver):
    """The silence test: the same answer, no thinking, the same number.

    This is the whole claim in one line. "Fewer than before" would also be
    satisfied by a chain of thought that merely counts less; what is owed is
    a number that does not know whether the model thought at all.
    """
    modellserver.pakete = [_textfeld("Antwort")]
    ohne = await _messwerte(_provider(modellserver.basis, reasoning_format="native"))

    modellserver.pakete = [_denkfeld(f"Schritt {i} ") for i in range(9)] + [_textfeld("Antwort")]
    mit = await _messwerte(_provider(modellserver.basis, reasoning_format="native"))

    assert mit["haeppchen"] == ohne["haeppchen"] == 1


async def test_reasoning_content_zaehlt_ebenso_wenig(modellserver):
    """Some servers call the field reasoning_content — same rule."""
    modellserver.pakete = [
        {"choices": [{"delta": {"reasoning_content": "Gedanke"}, "index": 0}]},
        _textfeld("Antwort"),
    ]
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="native"))
    assert werte["haeppchen"] == 1


async def test_das_denken_geht_trotzdem_hinaus(modellserver):
    """Not counted is not swallowed: the reader still sees the thinking."""
    modellserver.pakete = [_denkfeld("Ich überlege"), _textfeld("Die Antwort")]
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="native"))
    assert werte["_gedanke"] == "Ich überlege"
    assert werte["_antwort"] == "Die Antwort"


async def test_erstes_token_ist_der_beginn_der_antwort(modellserver):
    """The moment the answer began, not the moment anything began.

    The half second of thinking sits BEFORE the first counted token, so it
    lands in the waiting time and not in the divisor. Were the first chunk
    of thinking still to stamp that moment, the whole think would end up in
    the generation time and press the speed down again — invisibly, because
    the counting would look correct.
    """
    modellserver.pakete = [_denkfeld(f"Schritt {i} ") for i in range(6)] + [
        _textfeld("Kurze "),
        _textfeld("Antwort"),
    ]
    modellserver.pause_vor = {6: 0.5}
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="native"))

    assert werte["haeppchen"] == 2
    assert werte["erstes_token_nach_sekunden"] >= 0.5
    # Everything after the first token of the ANSWER — the thinking is out.
    # Two chunks back to back can take less than the millisecond the window
    # rounds to, and then there is no generation time at all to report.
    assert (werte["erzeugungs_sekunden"] or 0) < 0.3


# --- The chain of thought as markers inside the text ----------------------


async def test_think_marker_zaehlen_nicht_mit(modellserver):
    """<think> … </think> arrives through the ordinary content field.

    Every one of these packets is a ``delta.content``, so a count taken
    before the parser has split them would count all six. Only the two that
    carry answer text may.
    """
    modellserver.pakete = [
        _textfeld("<think>"),
        _textfeld("Erst "),
        _textfeld("überlegen "),
        _textfeld("</think>"),
        _textfeld("Kurze "),
        _textfeld("Antwort"),
    ]
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="think"))
    assert werte["haeppchen"] == 2
    assert werte["_gedanke"] == "Erst überlegen "
    assert werte["_antwort"] == "Kurze Antwort"


async def test_ohne_denken_dieselbe_zahl_bei_markern(modellserver):
    """The silence test for the marker shape."""
    modellserver.pakete = [_textfeld("Kurze "), _textfeld("Antwort")]
    ohne = await _messwerte(_provider(modellserver.basis, reasoning_format="think"))

    modellserver.pakete = [
        _textfeld("<think>"),
        _textfeld("Erst "),
        _textfeld("überlegen "),
        _textfeld("</think>"),
        _textfeld("Kurze "),
        _textfeld("Antwort"),
    ]
    mit = await _messwerte(_provider(modellserver.basis, reasoning_format="think"))

    assert mit["haeppchen"] == ohne["haeppchen"] == 2


async def test_harmony_marker_zaehlen_nicht_mit(modellserver):
    """The same for the Harmony channels."""
    modellserver.pakete = [
        _textfeld("<|channel|>analysis<|message|>Denken lange<|end|>"),
        _textfeld("<|channel|>analysis<|message|>Und noch mehr<|end|>"),
        _textfeld("<|channel|>final<|message|>Antwort<|return|>"),
    ]
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="harmony"))
    assert werte["haeppchen"] == 1
    assert werte["_antwort"] == "Antwort"


async def test_gemischtes_haeppchen_zaehlt_einmal(modellserver):
    """One packet holding the end of the thinking and the start of the answer.

    It carried answer text, so it counts — once, like any other packet, and
    the thinking riding along in it adds nothing.
    """
    modellserver.pakete = [_textfeld("<think>Gedanke</think>Antwort")]
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="think"))
    assert werte["haeppchen"] == 1
    assert werte["_gedanke"] == "Gedanke"
    assert werte["_antwort"] == "Antwort"


async def test_marker_ueber_paketgrenzen_zaehlen_nicht_mit(modellserver):
    """A marker torn between two packets must not smuggle a count through.

    The parser holds back a tail that could still become a marker, so the
    packet ending in "</thi" produces nothing at all — and a packet that
    produced no answer text counts for nothing.
    """
    modellserver.pakete = [
        _textfeld("<thi"),
        _textfeld("nk>Gedanke</thi"),
        _textfeld("nk>Antwort"),
    ]
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="think"))
    assert werte["haeppchen"] == 1
    assert werte["_gedanke"] == "Gedanke"
    assert werte["_antwort"] == "Antwort"


async def test_erstes_token_bei_markern_ist_auch_die_antwort(modellserver):
    """The anchor of the divisor, in the marker shape as well."""
    modellserver.pakete = [
        _textfeld("<think>"),
        _textfeld("Lange überlegen"),
        _textfeld("</think>"),
        _textfeld("Antwort"),
    ]
    modellserver.pause_vor = {3: 0.5}
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="think"))

    assert werte["haeppchen"] == 1
    assert werte["erstes_token_nach_sekunden"] >= 0.5
    # One chunk of answer is written in well under a millisecond, so the
    # generation time is either a hair above zero or — rounded to the three
    # places the window shows — nothing at all. What it must not be is the
    # half second spent thinking.
    assert (werte["erzeugungs_sekunden"] or 0) < 0.3


# --- What deliberately keeps counting ------------------------------------


async def test_werkzeugargumente_zaehlen_weiterhin_mit(modellserver):
    """A tool call is written work, not thinking.

    Without it the speed display stood still for minutes while a long
    argument was being written. That stays as it is — only the chain of
    thought was taken out.
    """
    modellserver.pakete = [
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "W1", "type": "function",
             "function": {"name": "wetter", "arguments": "{"}}]}, "index": 0}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"ort":"Berlin"}'}}]}, "index": 0}]},
    ]
    werte = await _messwerte(_provider(modellserver.basis))
    assert werte["haeppchen"] == 2


# --- The whole way through, with a stream and a `usage` block --------------


async def test_stiller_server_faellt_im_strom_auf_die_haeppchen_zurueck(modellserver):
    """The oMLX case, end to end: thinking in the stream, no split in `usage`.

    Nine chunks of thinking and two of answer, from a server reporting 1000
    completion tokens without saying how many of them were thought. Those
    1000 cover the whole generation while the divisor holds the answer
    alone, so the counted tier drops out and the two answer chunks take
    over. Before, the 1000 went over the answer's seconds untouched.
    """
    modellserver.pakete = [_denkfeld(f"Schritt {i} ") for i in range(9)] + [
        _textfeld("Kurze "),
        _textfeld("Antwort"),
        {"choices": [], "usage": {"completion_tokens": 1000}},
    ]
    modellserver.pause_vor = {9: 0.3, 10: 0.2}
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="native"))

    assert werte["tempo_quelle"] == "geschaetzt"
    assert werte["erzeugte_tokens"] == 2
    # The thinking stays out of the divisor exactly as before.
    assert werte["erstes_token_nach_sekunden"] >= 0.3


async def test_marker_denken_faellt_im_strom_ebenso_zurueck(modellserver):
    """The marker shape reaches the tier the same way the dedicated field does.

    Nothing here arrives as `delta.reasoning`; only the parser knows that
    four of these six packets were thinking. A repair that watched the
    dedicated field alone would leave every server speaking in markers as
    broken as before, and nothing on the surface would show which of the two
    a run had used.
    """
    modellserver.pakete = [
        _textfeld("<think>"),
        _textfeld("Erst "),
        _textfeld("überlegen "),
        _textfeld("</think>"),
        _textfeld("Kurze "),
        _textfeld("Antwort"),
        {"choices": [], "usage": {"completion_tokens": 1000}},
    ]
    modellserver.pause_vor = {4: 0.3, 5: 0.2}
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="think"))

    assert werte["tempo_quelle"] == "geschaetzt"
    assert werte["erzeugte_tokens"] == 2


async def test_mit_aufteilung_bleibt_der_strom_auf_der_gemessenen_stufe(modellserver):
    """The same stream from a server that names the split: nothing steps down.

    This is what the tier is for, and it stays reachable — the run thought,
    and the real token count is still the better number because the server
    said which part of it was the answer.
    """
    modellserver.pakete = [_denkfeld(f"Schritt {i} ") for i in range(9)] + [
        _textfeld("Kurze "),
        _textfeld("Antwort"),
        {
            "choices": [],
            "usage": {
                "completion_tokens": 1000,
                "completion_tokens_details": {"reasoning_tokens": 900},
            },
        },
    ]
    modellserver.pause_vor = {9: 0.3, 10: 0.2}
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="native"))

    assert werte["tempo_quelle"] == "gemessen"
    assert werte["erzeugte_tokens"] == 100


async def test_ohne_denken_bleibt_der_strom_auf_der_gemessenen_stufe(modellserver):
    """The silence test for the tier: a run that never thought keeps its count.

    Nothing may be taken away from a plain answer because some other run,
    somewhere else, thought behind a quiet server.
    """
    modellserver.pakete = [
        _textfeld("Kurze "),
        _textfeld("Antwort"),
        {"choices": [], "usage": {"completion_tokens": 1000}},
    ]
    modellserver.pause_vor = {1: 0.2}
    werte = await _messwerte(_provider(modellserver.basis, reasoning_format="native"))

    assert werte["tempo_quelle"] == "gemessen"
    assert werte["erzeugte_tokens"] == 1000


# --- The counted tier: real token numbers from the server -------------------
#
# The chunk counter above is only the estimated tier. Where a server reports
# real numbers, `completion_tokens` counts the chain of thought in with the
# answer — while the divisor beside it starts at the moment the ANSWER
# started. Leaving that alone would have made the display wrong in the other
# direction than before: a model thinking for a minute and then writing one
# line would report an enormous speed for that line.

from app.providers.openai_kompatibel import tempo_ermitteln


def _gemessen(nutzung, *, haeppchen=0, denken_gesehen=False):
    """Eight seconds of thinking, two of answering."""
    return tempo_ermitteln(
        zeitmessung=None, nutzung=nutzung, haeppchen=haeppchen,
        dauer=10.0, erstes_token_nach=8.0, denken_gesehen=denken_gesehen,
    )


def test_die_denk_token_werden_abgezogen():
    """100 answer tokens in 2 seconds is 50 per second — by hand, and by the
    program."""
    werte = _gemessen(
        {"completion_tokens": 1000,
         "completion_tokens_details": {"reasoning_tokens": 900}},
        denken_gesehen=True,
    )
    assert werte["erzeugte_tokens"] == 100
    assert werte["erzeugungs_sekunden"] == 2.0
    assert werte["tokens_pro_sekunde"] == 50.0
    assert werte["tempo_quelle"] == "gemessen"


def test_ohne_aufteilung_bleibt_die_zahl_eines_denkfreien_laufs_wie_sie_war():
    """A server that reports no split gets nothing estimated on its behalf.

    For a run that did not think there is nothing to take off anyway: the
    number stays whole and stays exactly what it was. Inventing a share
    would be worse than leaving it alone — and so would throwing a perfectly
    good token count away because the server keeps quiet about a chain of
    thought that never happened."""
    werte = _gemessen({"completion_tokens": 1000})
    assert werte["erzeugte_tokens"] == 1000
    assert werte["tempo_quelle"] == "gemessen"


def test_ohne_denken_aendert_sich_nichts():
    """The silence test. Same answer, no thinking reported: same number."""
    ohne = _gemessen({"completion_tokens": 100})
    mit_null = _gemessen(
        {"completion_tokens": 100, "completion_tokens_details": {"reasoning_tokens": 0}}
    )
    assert ohne["tokens_pro_sekunde"] == mit_null["tokens_pro_sekunde"] == 50.0


def test_unfug_im_feld_wird_nicht_abgezogen():
    """A value that is not a count is no count. True is not a number here
    either — it would silently subtract one."""
    for unfug in (None, "viele", True, -5, {"a": 1}, float("nan"), float("inf")):
        werte = _gemessen(
            {"completion_tokens": 100, "completion_tokens_details": {"reasoning_tokens": unfug}}
        )
        assert werte["erzeugte_tokens"] == 100, unfug


def test_mehr_denken_als_gezaehlt_geht_nicht_ins_minus():
    """A server contradicting itself must not produce a negative count."""
    werte = _gemessen(
        {"completion_tokens": 10, "completion_tokens_details": {"reasoning_tokens": 99}},
        denken_gesehen=True,
    )
    assert werte["erzeugte_tokens"] == 0
    assert werte["tokens_pro_sekunde"] is None


# --- Counter and divisor have to answer about the same stretch of time -----
#
# The divisor always leaves the thinking out — it starts at the moment the
# answer started. `completion_tokens` only leaves it out where the server
# names the split. Where a run thought and the server said nothing, every
# thought token used to stand in the counter with not one thought second
# under it. Measured against oMLX: 163.01 tok/s reported for rounds the
# model server itself called 16.6 to 25.6 tok/s. The same run with the split
# reported came out at 20.
#
# There is no arithmetic that repairs this after the fact, so the tier drops
# out instead and the chunk count takes over: it counts answer chunks and
# nothing else, which is the divisor's own definition, and its name says
# that a chunk is not a token.


def test_denken_ohne_aufteilung_laesst_die_gemessene_stufe_fallen():
    """The bug itself: thinking reported by no one, counted by everyone.

    1000 tokens over the two seconds of answering would be 500 tok/s for an
    answer of 40 chunks. The tier steps down instead — and it reports the
    chunk count and the span it covers, but NO speed: a chunk is not a token,
    and with speculative decoding one carries several. Measured on an mlx
    server with MTP, 156 chunks over 19.3 s came out as 8.06 tok/s beside the
    same answer's own 64.42 — a factor of eight.
    """
    werte = _gemessen({"completion_tokens": 1000}, haeppchen=40, denken_gesehen=True)
    assert werte["tempo_quelle"] == "geschaetzt"
    assert werte["erzeugte_tokens"] == 40
    assert werte["erzeugungs_sekunden"] == 2.0
    assert werte["tokens_pro_sekunde"] is None  # 20.0 before, out of chunks


def test_ohne_haeppchen_bleibt_gar_keine_zahl():
    """Nothing left to step down to: then there is no speed, and that is said.

    Better an empty field than a number that describes two different
    stretches of time at once.
    """
    werte = _gemessen({"completion_tokens": 1000}, haeppchen=0, denken_gesehen=True)
    assert werte["erzeugte_tokens"] is None
    assert werte["tokens_pro_sekunde"] is None
    assert werte["tempo_quelle"] is None


def test_gemeldete_null_ist_kein_schweigen():
    """`reasoning_tokens: 0` is an answer, not the absence of one.

    A server that says "nothing was thought" has named the split, so its
    count stands even if the stream carried a chain of thought the server
    forgot to price. Only a server saying nothing at all costs the tier.
    """
    werte = _gemessen(
        {"completion_tokens": 100, "completion_tokens_details": {"reasoning_tokens": 0}},
        haeppchen=40, denken_gesehen=True,
    )
    assert werte["tempo_quelle"] == "gemessen"
    assert werte["erzeugte_tokens"] == 100


def test_unfug_im_feld_kostet_beim_denken_die_stufe():
    """Garbage in the field is silence, not a split.

    The counterpart to `test_unfug_im_feld_wird_nicht_abgezogen`: without a
    chain of thought nothing is lost by ignoring the garbage, but with one
    the count cannot be trusted beside this divisor.
    """
    for unfug in (None, "viele", True, -5, {"a": 1}):
        werte = _gemessen(
            {"completion_tokens": 100, "completion_tokens_details": {"reasoning_tokens": unfug}},
            haeppchen=40, denken_gesehen=True,
        )
        assert werte["tempo_quelle"] == "geschaetzt", unfug
        assert werte["erzeugte_tokens"] == 40, unfug


def test_die_servermessung_steht_ueber_allem():
    """A server that timed it itself is not affected by any of this.

    Its `timings` block carries tokens and generation time from the same
    machine and the same stretch of time, so the split is none of its
    business.
    """
    werte = tempo_ermitteln(
        zeitmessung={"predicted_n": 60, "predicted_ms": 2580.0},
        nutzung={"completion_tokens": 1000}, haeppchen=40,
        dauer=10.0, erstes_token_nach=8.0, denken_gesehen=True,
    )
    assert werte["tempo_quelle"] == "server"
    assert werte["tokens_pro_sekunde"] == 23.26


# --- A round that rounds to nothing ---------------------------------------


def test_zeit_die_auf_null_rundet_ergibt_kein_tempo():
    """Under a millisecond is not a short stretch of time — it is none.

    The seconds go into the window rounded to three places, so 0.0004 s
    shows up there as 0.0 while the division still used the unrounded value
    beneath it. Found in the database, each of them next to an
    `erzeugungs_sekunden` of 0.0: 23617, 10797 and 6904 tok/s.
    """
    werte = tempo_ermitteln(
        zeitmessung=None, nutzung={"completion_tokens": 7}, haeppchen=7,
        dauer=8.0004, erstes_token_nach=8.0,
    )
    assert werte["erzeugungs_sekunden"] is None
    assert werte["tokens_pro_sekunde"] is None
    # The count is real and stays — only the speed is missing.
    assert werte["erzeugte_tokens"] == 7


def test_auch_die_serverzeit_darf_nicht_auf_null_fallen():
    """The same rule for the server's own timing block."""
    werte = tempo_ermitteln(
        zeitmessung={"predicted_n": 5, "predicted_ms": 0.4},
        nutzung={}, haeppchen=5, dauer=2.0, erstes_token_nach=1.0,
    )
    assert werte["erzeugungs_sekunden"] is None
    assert werte["tokens_pro_sekunde"] is None


def test_das_tempo_passt_zu_den_angezeigten_sekunden():
    """What the window shows has to divide out to what the window shows.

    The seconds are reported to three places; dividing by the unrounded
    value put a speed beside them that does not follow from them. 2.5004999 s
    became "2.5 s" and 39.99 tok/s, where 100 over 2.5 is 40.
    """
    werte = tempo_ermitteln(
        zeitmessung=None, nutzung={"completion_tokens": 100}, haeppchen=100,
        dauer=3.0004999, erstes_token_nach=0.5,
    )
    assert werte["erzeugungs_sekunden"] == 2.5
    assert werte["tokens_pro_sekunde"] == 40.0


def test_eine_antwort_aus_einem_token_meldet_kein_tempo():
    """Measured: one chunk written in 1.169 s with the first token at
    1.168 s leaves a thousandth of a second of generating, and one divided
    by that reads as 1000 tokens per second. Two chunks already read as 67,
    five as 50, fifty as 12.5 — the nonsense is the very short answer alone,
    where the whole reading rests on how precisely one moment was stamped.

    A floor on the NUMBER would be a number this file invented. So the speed
    is simply not reported; the duration and the wait for the first token
    are still true and still go out.
    """
    werte = tempo_ermitteln(
        zeitmessung={}, nutzung={}, haeppchen=1, dauer=1.169, erstes_token_nach=1.168
    )
    assert werte["tokens_pro_sekunde"] is None
    assert werte["erzeugungs_sekunden"] == 0.001
    assert werte["erzeugte_tokens"] == 1


def test_ab_drei_token_wird_wieder_gemeldet():
    """Where the count floor lets go. Read on the `gemessen` tier, which is
    the lowest one that still reports a speed at all: the chunk tier below it
    counts chunks and says no speed whatever their number."""
    werte = tempo_ermitteln(
        zeitmessung={}, nutzung={"completion_tokens": 3}, haeppchen=3,
        dauer=1.8, erstes_token_nach=1.7,
    )
    assert werte["tempo_quelle"] == "gemessen"
    assert werte["tokens_pro_sekunde"] == 30.0


def test_die_eigene_messung_des_servers_gilt_auch_bei_zwei_tokens():
    """The floor is about OUR estimate. A server saying "two tokens in a
    hundred milliseconds" measured that itself and is not guessing at a
    moment — its twenty per second is a fact, however few tokens it counts.
    """
    werte = tempo_ermitteln(
        zeitmessung={"predicted_n": 2, "predicted_ms": 100.0},
        nutzung={"completion_tokens": 2},
        haeppchen=2, dauer=1.0, erstes_token_nach=0.5,
    )
    assert werte["tokens_pro_sekunde"] == 20.0
    assert werte["tempo_quelle"] == "server"


# --- The other end of the division ---------------------------------------
#
# The floor above guards the counter. It says nothing at all about the
# divisor, and the divisor is where the absurd numbers actually come from:
# tokens enough to clear the count, spread over a thousandth of a second,
# are still nonsense.


def test_genug_tokens_ueber_zu_wenig_zeit_meldet_kein_tempo():
    """Three tokens clear the count and still say nothing over three
    milliseconds.

    The exact shape the token floor cannot see: the count is fine, the
    reading is 1000 tok/s, and the only thing wrong with it is that the
    stretch of time under it is shorter than the uncertainty of the two
    moments it was measured between.
    """
    werte = tempo_ermitteln(
        zeitmessung={}, nutzung={}, haeppchen=3, dauer=1.003, erstes_token_nach=1.0
    )
    assert werte["erzeugte_tokens"] == 3          # the count is real and stays
    assert werte["erzeugungs_sekunden"] == 0.003  # so is the time
    assert werte["tokens_pro_sekunde"] is None    # 1000.0 before


def test_viele_tokens_ueber_zu_wenig_zeit_ebenfalls_nicht():
    """More tokens do not make a short measurement longer.

    Fifty chunks that arrived in one packet are read back out of the buffer
    in microseconds — measured, this process needs about 0.05 ms for fifty
    of them. Nothing was generated in that span, and 5000 tok/s says so.
    """
    werte = tempo_ermitteln(
        zeitmessung={}, nutzung={}, haeppchen=50, dauer=2.01, erstes_token_nach=2.0
    )
    assert werte["tokens_pro_sekunde"] is None  # 5000.0 before


def test_ab_einer_zwanzigstel_sekunde_wird_wieder_gemeldet():
    """Where the time floor lets go: at 0.05 s the half millisecond the
    divisor is rounded to is one percent of it — the last digit of what is
    shown. On the `gemessen` tier, for the same reason as the count floor
    above."""
    werte = tempo_ermitteln(
        zeitmessung={}, nutzung={"completion_tokens": 10}, haeppchen=10,
        dauer=1.05, erstes_token_nach=1.0,
    )
    assert werte["erzeugungs_sekunden"] == 0.05
    assert werte["tokens_pro_sekunde"] == 200.0


def test_die_zeitgrenze_gilt_ebenfalls_nicht_fuer_den_server():
    """A reading the server took itself is a fact, however short it is.

    It counted at the source and stamped no moment we could have got wrong,
    so neither of the two errors the floors guard against applies — the
    same reason the token floor already steps aside for it.
    """
    werte = tempo_ermitteln(
        zeitmessung={"predicted_n": 60, "predicted_ms": 20.0},
        nutzung={"completion_tokens": 60},
        haeppchen=60, dauer=1.0, erstes_token_nach=0.5,
    )
    assert werte["erzeugungs_sekunden"] == 0.02
    assert werte["tokens_pro_sekunde"] == 3000.0
    assert werte["tempo_quelle"] == "server"
