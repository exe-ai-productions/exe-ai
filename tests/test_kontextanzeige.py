"""How full the context is, WHILE the answer is being written.

The defect these guard against: the reading only ever left the service with
the ``stats`` event, one line before ``done``. So the bar in the window
stood still for the whole answer and then jumped — which is exactly when it
is least useful, because the point of it is to see the room running out
BEFORE the request that fails.

The load-bearing idea is that a reading is not a sum over rounds. The prompt
of round N already carries every round before it and every tool result in
between, so each round reports the whole standing on its own; adding them up
would count the same tokens once per round.

What is exact and what is estimated differs per provider, and the difference
is carried rather than flattened — see ``_kontextstand``.
"""

from __future__ import annotations

import json

import pytest

from app.api.v1.generierung import _kontextstand
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen
from tests import test_openai_provider
from tests.test_openai_provider import _einsammeln, _provider

# The stub OpenAI-compatible server, borrowed as a fixture.
modellserver = test_openai_provider.modellserver


def _ereignisse(antwort) -> list[dict]:
    """The SSE lines of a finished stream, as objects."""
    return [
        json.loads(zeile[5:].strip())
        for zeile in antwort.text.splitlines()
        if zeile.startswith("data:")
    ]


def _kontexte(antwort) -> list[dict]:
    return [e for e in _ereignisse(antwort) if e["typ"] == "kontext"]


def _losschicken(client, chat_id: str):
    return client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
    )


# --- The reading itself ---------------------------------------------------


def test_eine_genaue_zahl_wird_benutzt_wie_sie_ist():
    """Anthropic's `input_tokens`, a server's own `usage`. Prompt plus what
    the round has written so far, and nothing added on top."""
    assert _kontextstand(
        {"prompt_tokens": 1500, "prompt_genau": True, "erzeugte_tokens": 40}, None
    ) == 1540


def test_eine_genaue_zahl_wird_nicht_angehoben():
    """The case that makes the distinction necessary at all: a compaction
    leaves the prompt SMALLER than the reading before it. A rule that only
    ever grows would keep showing the old, bigger number."""
    assert _kontextstand(
        {"prompt_tokens": 1000, "prompt_genau": True, "erzeugte_tokens": 1}, 9000
    ) == 1001


def test_ohne_eigene_zahl_dient_der_letzte_stand_als_schaetzung():
    """The new prompt is the old total plus whatever this turn added, so the
    last reading stands in for it. An estimate, and named as one."""
    assert _kontextstand(
        {"prompt_tokens": None, "prompt_genau": False, "erzeugte_tokens": 12}, 4000
    ) == 4012


def test_von_zwei_untergrenzen_gilt_die_hoehere():
    """`timings.prompt_n` counts only what was not already cached, the last
    total does not know what this turn added — both are lower bounds on the
    same number, so the larger one is the better one."""
    assert _kontextstand(
        {"prompt_tokens": 512, "prompt_genau": False, "erzeugte_tokens": 3}, 4000
    ) == 4003
    assert _kontextstand(
        {"prompt_tokens": 6000, "prompt_genau": False, "erzeugte_tokens": 3}, 4000
    ) == 6003


def test_ohne_jede_haelfte_wird_nichts_gemeldet():
    """The first round of a fresh chat on a server that reports no prompt.
    A count of the output alone is not a context reading, and reporting it
    as one would make the bar say something false."""
    assert _kontextstand(
        {"prompt_tokens": None, "prompt_genau": False, "erzeugte_tokens": 9}, None
    ) is None


# --- Through the whole chain ----------------------------------------------


def test_der_stand_geht_waehrend_der_antwort_hinaus(client, chat_id):
    provider_setzen(
        client,
        MockProvider(
            haeppchen=["eins ", "zwei"],
            kontext_melden=True,
            kontext_prompt=1500,
        ),
    )
    antwort = _losschicken(client, chat_id)

    typen = [e["typ"] for e in _ereignisse(antwort)]
    assert "kontext" in typen
    # Not last: it used to arrive one line before `done` and nowhere else.
    assert typen.index("kontext") < typen.index("stats")
    assert _kontexte(antwort)[0]["gesamt_tokens"] == 1501


def test_der_stand_landet_auch_in_der_zeile(client, chat_id):
    """A window that opens the chat cold mid-run reads the row, not the
    stream. `tokenstand_setzen` touches that one column alone, so it cannot
    lose a text write happening beside it."""
    provider_setzen(
        client,
        MockProvider(
            haeppchen=["eins "], kontext_melden=True, kontext_prompt=1500
        ),
    )
    _losschicken(client, chat_id)

    seite = client.get(f"/api/v1/chats/{chat_id}/messages").json()
    antwortzeile = next(n for n in seite["nachrichten"] if n["role"] == "assistant")
    assert antwortzeile["gesamt_tokens"] == 1501


def test_die_zeile_wird_nicht_bei_jeder_meldung_geschrieben(client, chat_id):
    """The stream reports the reading about twice a second, and every write
    of the column is a transaction with a sync behind it — a ten-minute
    answer was a thousand commits for one integer. The stream still carries
    every reading; the row gets one at the autosave's pace, and the exact
    number at the round's end."""
    from app.providers.base import Stueck, kontext_stueck

    class _Dauermelder(MockProvider):
        async def streamen(self, anfrage):
            for nr in range(1, 21):
                yield Stueck("content", f"w{nr} ")
                yield kontext_stueck(1500, True, nr)
            yield Stueck("stats", daten={"dauer_sekunden": 0.0, "haeppchen": 20,
                                         "prompt_tokens": 1500, "erzeugte_tokens": 20})

    provider_setzen(client, _Dauermelder(mock_endpunkt("test")))
    repositories = client.app.state.repositories
    schreibungen = []
    echt = repositories.messages.tokenstand_setzen
    repositories.messages.tokenstand_setzen = lambda kennung, stand: (
        schreibungen.append(stand), echt(kennung, stand)
    )

    antwort = _losschicken(client, chat_id)

    staende = [e["gesamt_tokens"] for e in _kontexte(antwort)]
    assert len(staende) == 20, "the stream lost readings"
    assert len(schreibungen) <= 2, schreibungen
    seite = client.get(f"/api/v1/chats/{chat_id}/messages").json()
    antwortzeile = next(n for n in seite["nachrichten"] if n["role"] == "assistant")
    assert antwortzeile["gesamt_tokens"] == staende[-1]


def test_ohne_eigene_prompt_zahl_schaetzt_der_dienst(client, chat_id):
    """The cloud mid-stream: it cannot count its own prompt yet, so the
    chat's last known reading stands in for it."""
    client.app.state.repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="Vorher", gesamt_tokens=4000
    )
    provider_setzen(
        client,
        MockProvider(
            haeppchen=["eins "], kontext_melden=True, kontext_prompt=None
        ),
    )
    antwort = _losschicken(client, chat_id)
    assert _kontexte(antwort)[0]["gesamt_tokens"] == 4001


def test_eine_genaue_zahl_schlaegt_den_alten_stand(client, chat_id):
    """Same chain, the other way round: a provider that DOES know its
    prompt is believed, even when the older reading is bigger."""
    client.app.state.repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="Vorher", gesamt_tokens=9000
    )
    provider_setzen(
        client,
        MockProvider(
            haeppchen=["eins "], kontext_melden=True, kontext_prompt=1000
        ),
    )
    antwort = _losschicken(client, chat_id)
    assert _kontexte(antwort)[0]["gesamt_tokens"] == 1001


def test_ein_verdichteter_stand_dient_nicht_mehr_als_schaetzung(client, chat_id):
    """A row a summary already speaks for is no longer in the prompt, so
    its reading must not stand in for the size of one — compaction FREES
    room, and an estimate that kept the old number would report the room as
    still taken."""
    repositories = client.app.state.repositories
    alt = repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="Lang und breit",
        gesamt_tokens=9000,
    )
    repositories.messages.verdichten(
        chat_id=chat_id, text="Kurz gefasst.", ersetzte_ids=[alt.id]
    )
    provider_setzen(
        client,
        MockProvider(
            haeppchen=["eins "], kontext_melden=True, kontext_prompt=None
        ),
    )
    antwort = _losschicken(client, chat_id)
    # Nothing left to estimate from — the folded row is out, and the summary
    # standing in its place has no reading of its own yet.
    assert _kontexte(antwort) == []


def test_ein_stiller_anbieter_meldet_weiter_nichts(client, chat_id):
    """Nothing known and nothing stored — the run says nothing rather than
    reporting the answer's own length as a context reading."""
    provider_setzen(client, MockProvider(haeppchen=["eins "], kontext_melden=True))
    antwort = _losschicken(client, chat_id)
    assert _kontexte(antwort) == []


@pytest.mark.asyncio
async def test_die_zahlen_kommen_am_echten_strom_schon_unterwegs_an(laufender_server):
    """The one thing the collected response cannot show: that a reading is
    on the wire while the answer is still being written.

    Deliberately against a real uvicorn — the ASGI test transport hands the
    whole response over at once, and "during" is not a question it can
    answer.
    """
    import httpx

    app, basis = laufender_server
    provider = MockProvider(
        mock_endpunkt("test"),
        haeppchen=[f"Teil{i} " for i in range(30)],
        verzoegerung=0.05,
        kontext_melden=True,
        kontext_prompt=1200,
    )
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True

    kopfzeilen = {"X-Sitzungsschluessel": app.state.sitzungsschluessel}
    async with httpx.AsyncClient(
        base_url=basis, timeout=30, headers=kopfzeilen
    ) as client:
        chat_id = (
            await client.post("/api/v1/chats", json={"title": "Kontext"})
        ).json()["id"]

        gelesen: list[dict] = []
        async with client.stream(
            "POST",
            "/api/v1/chat/completions",
            json={"chat_id": chat_id, "endpoint_id": "test", "content": "Los"},
        ) as antwort:
            async for zeile in antwort.aiter_lines():
                if zeile.startswith("data:"):
                    gelesen.append(json.loads(zeile[5:].strip()))

        typen = [e["typ"] for e in gelesen]
        kontexte = [e for e in gelesen if e["typ"] == "kontext"]
        # About two a second through the throttle, and this answer runs for
        # about a second and a half.
        assert len(kontexte) >= 2
        # And the first one was followed by more answer text — so it was on
        # the wire DURING the answer, not tacked onto its end.
        assert "content" in typen[typen.index("kontext") + 1:]
        # It grows as the answer does, and it starts above the prompt.
        assert kontexte[0]["gesamt_tokens"] > 1200
        assert kontexte[-1]["gesamt_tokens"] > kontexte[0]["gesamt_tokens"]

        nachrichten = (
            await client.get(f"/api/v1/chats/{chat_id}/messages")
        ).json()["nachrichten"]
        # The live readings stand in the row, and the closing write does not
        # wipe them: this dummy's metrics carry no usage block, so there is
        # no exact number to replace them with.
        assert nachrichten[1]["gesamt_tokens"] == kontexte[-1]["gesamt_tokens"]



# --- llama.cpp's two halves, read whole -----------------------------------
#
# llama.cpp counts the prompt in two: `prompt_n`, what had to be read in,
# and `cache_n`, what stood in the cache. Only their sum is the prompt; the
# reading mid-answer used to take `prompt_n` alone and stood too low for
# the whole answer whenever the cache was warm.


async def _readings(stub, timings: dict) -> list:
    """Every chunk of one answer whose packets carry these timings."""
    stub.rohpakete([
        {"choices": [{"delta": {"content": "Guten "}, "index": 0}], "timings": timings},
        {"choices": [{"delta": {"content": "Tag"}, "index": 0}], "timings": timings},
    ])
    return await _einsammeln(_provider(stub.basis))


def _live(chunks) -> list[dict]:
    return [c.daten for c in chunks if c.sorte == "kontext"]


@pytest.mark.asyncio
async def test_cached_tokens_count_towards_the_live_prompt(modellserver):
    """524 read in, 977 from the cache: the prompt is 1501, from the first
    reading on, plus what the answer has written so far."""
    live = _live(await _readings(modellserver, {"prompt_n": 524, "cache_n": 977}))
    assert live
    totals = [_kontextstand(reading, None) for reading in live]
    assert all(total is not None and total > 1501 for total in totals)
    assert totals[0] - 1501 < 10, "the reading carries more than the prompt and the answer"


@pytest.mark.asyncio
async def test_both_halves_make_an_exact_prompt(modellserver):
    """Both halves named, the server has counted the whole prompt: it is
    used as it stands and not raised by an older, larger reading — a chat
    that was just compacted has a smaller prompt than the reading before."""
    first = _live(await _readings(modellserver, {"prompt_n": 524, "cache_n": 977}))[0]
    assert first["prompt_tokens"] == 1501
    assert first["prompt_genau"] is True
    assert _kontextstand(first, 9000) == 1501 + first["erzeugte_tokens"]


@pytest.mark.asyncio
async def test_the_round_ends_on_the_same_whole_prompt(modellserver):
    """The round's stats read the prompt the way the live readings do: a
    server that sends no usage block must not drop the number under the
    finished answer back to the fresh half alone."""
    chunks = await _readings(modellserver, {
        "prompt_n": 524, "cache_n": 977, "predicted_n": 2, "predicted_ms": 40,
    })
    stats = [c.daten for c in chunks if c.sorte == "stats"][-1]
    assert stats["prompt_tokens"] == 1501


@pytest.mark.asyncio
async def test_the_round_ends_on_the_whole_prompt_without_a_speed(modellserver):
    """The packets name the prompt's halves and never a complete speed pair:
    the stats still carry the whole prompt the live readings showed."""
    chunks = await _readings(modellserver, {"prompt_n": 524, "cache_n": 977})
    assert _live(chunks)[0]["prompt_tokens"] == 1501
    assert [c.daten for c in chunks if c.sorte == "stats"][-1]["prompt_tokens"] == 1501


@pytest.mark.asyncio
async def test_a_late_block_of_zeros_does_not_shrink_the_prompt(modellserver):
    """A closing block that names the halves as 0 beside a speed — the
    measured shape the round's stand already keeps its values against —
    leaves the whole prompt standing."""
    modellserver.rohpakete([
        {"choices": [{"delta": {"content": "Guten "}, "index": 0}],
         "timings": {"prompt_n": 524, "cache_n": 977}},
        {"choices": [{"delta": {"content": "Tag"}, "index": 0}],
         "timings": {"prompt_n": 0, "cache_n": 0, "predicted_n": 2, "predicted_ms": 40}},
    ])
    chunks = await _einsammeln(_provider(modellserver.basis))
    assert [c.daten for c in chunks if c.sorte == "stats"][-1]["prompt_tokens"] == 1501


@pytest.mark.asyncio
async def test_prompt_n_alone_stays_a_floor(modellserver):
    """Silence probe: a server naming `prompt_n` alone reads as before — a
    floor, raised by what the service already knows, live and at the end."""
    chunks = await _readings(modellserver, {
        "prompt_n": 524, "predicted_n": 2, "predicted_ms": 40,
    })
    first = _live(chunks)[0]
    assert first["prompt_tokens"] == 524
    assert first["prompt_genau"] is False
    assert _kontextstand(first, 9000) == 9000 + first["erzeugte_tokens"]
    assert [c.daten for c in chunks if c.sorte == "stats"][-1]["prompt_tokens"] == 524


@pytest.mark.asyncio
async def test_the_cached_half_alone_is_no_prompt(modellserver):
    """Partial: `cache_n` without `prompt_n` is half a prompt, not a whole
    one — nothing is claimed from it, the same as the cache share does."""
    first = _live(await _readings(modellserver, {"cache_n": 977}))[0]
    assert first["prompt_tokens"] is None
    assert first["prompt_genau"] is False
