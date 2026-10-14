"""The numbers under an answer that took several rounds: the speed is the speed
of the rounds that wrote its text, and the cache share counts every round.

Two readings used to disagree under one answer: a round that only called a
tool lifted the speed to thousands per second, and the share stood at the last
round's 99 % beside a waiting time that was the first round's.
"""

from __future__ import annotations

from app.api.v1.generierung import _messwerte_mergen
from app.cache_over_rounds import cache_halves, cache_over_rounds
from app.providers import mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from app.tempo_without_text import without_tempo
from tests.conftest import GrosseWerkzeugkette, GrossesErgebnis, provider_setzen, senden
from tests.test_auftraege_api import mcp_client as _mcp_client

mcp_client = _mcp_client


def _tool_round(**more) -> dict:
    """A round that only called a tool: a handful of tokens that a server
    timed in milliseconds and named a rate for."""
    return {
        "dauer_sekunden": 0.4,
        "haeppchen": 1,
        "erzeugte_tokens": 32,
        "tempo_tokens": 32,
        "tempo_sekunden": 0.005,
        "erzeugungs_sekunden": 0.005,
        "tokens_pro_sekunde": 6400.0,
        "tempo_quelle": "server",
        **more,
    }


def _text_round(**more) -> dict:
    """A round that wrote the answer: 420 tokens over 10.06 s."""
    return {
        "dauer_sekunden": 10.5,
        "haeppchen": 420,
        "erzeugte_tokens": 420,
        "tempo_tokens": 420,
        "tempo_sekunden": 10.06,
        "erzeugungs_sekunden": 10.06,
        "tokens_pro_sekunde": 41.75,
        "tempo_quelle": "server",
        **more,
    }


# --- The speed ---------------------------------------------------------------


def test_rounds_that_only_call_a_tool_do_not_count_into_the_speed():
    merged = _messwerte_mergen(None, _tool_round(), wrote_text=False)
    merged = _messwerte_mergen(merged, _tool_round(), wrote_text=False)
    merged = _messwerte_mergen(merged, _text_round(), wrote_text=True)

    assert merged["tokens_pro_sekunde"] == 41.75
    assert merged["tempo_quelle"] == "server"
    # What the rounds took is still counted: duration and tokens produced.
    assert merged["dauer_sekunden"] == 11.3
    assert merged["erzeugte_tokens"] == 484


def test_a_tool_round_after_the_text_does_not_count_either():
    merged = _messwerte_mergen(None, _text_round(), wrote_text=True)
    merged = _messwerte_mergen(merged, _tool_round(), wrote_text=False)

    assert merged["tokens_pro_sekunde"] == 41.75


def test_an_answer_whose_rounds_wrote_no_text_shows_no_speed():
    merged = _messwerte_mergen(None, _tool_round(), wrote_text=False)
    merged = _messwerte_mergen(merged, _tool_round(), wrote_text=False)

    assert merged["tokens_pro_sekunde"] is None
    assert merged["tempo_quelle"] is None


def test_a_single_round_without_text_shows_no_speed_either():
    stats = _messwerte_mergen(None, _tool_round(), wrote_text=False)

    assert stats["tokens_pro_sekunde"] is None
    assert stats["erzeugte_tokens"] == 32


def test_silence_rounds_that_wrote_text_add_up_as_before():
    first = _text_round(tempo_tokens=100, tempo_sekunden=2.0, erzeugte_tokens=100,
                        erzeugungs_sekunden=2.0, tokens_pro_sekunde=50.0)
    second = _text_round(tempo_tokens=300, tempo_sekunden=10.0, erzeugte_tokens=300,
                         erzeugungs_sekunden=10.0, tokens_pro_sekunde=30.0)

    merged = _messwerte_mergen(first, second)

    assert merged["tokens_pro_sekunde"] == 33.33


def test_without_tempo_keeps_everything_but_the_speed():
    stats = without_tempo(_tool_round(prompt_tokens=900))

    assert stats["prompt_tokens"] == 900
    assert stats["erzeugte_tokens"] == 32
    assert (stats["tempo_tokens"], stats["tokens_pro_sekunde"]) == (None, None)


# --- The cache share ---------------------------------------------------------


def _llama_round(fresh: int, cached: int, seconds: float, first: float, **more) -> dict:
    """A round on llama.cpp's wire: both halves of its prompt named."""
    return {
        "dauer_sekunden": 5.0,
        "haeppchen": 3,
        "erzeugte_tokens": 3,
        "erstes_token_nach_sekunden": first,
        "cache_tokens": cached,
        "eingelesen_tokens": fresh,
        "einlese_sekunden": seconds,
        "prompt_cache_percent": round(cached * 100 / (cached + fresh)),
        **more,
    }


def test_the_cache_share_counts_every_round_and_the_wait_stays_the_first_ones():
    first = _llama_round(fresh=8000, cached=0, seconds=70.0, first=70.5)
    second = _llama_round(fresh=100, cached=8000, seconds=1.0, first=1.2)

    merged = _messwerte_mergen(first, second)

    # 8000 of 16100 read from the cache — not the last round's 99.
    assert merged["prompt_cache_percent"] == 50
    assert (merged["cache_tokens"], merged["eingelesen_tokens"]) == (8000, 8100)
    assert merged["einlese_sekunden"] == 71.0
    assert merged["erstes_token_nach_sekunden"] == 70.5


def test_three_rounds_are_summed_in_one_go():
    merged = _messwerte_mergen(None, _llama_round(fresh=1000, cached=0, seconds=10.0, first=11.0))
    merged = _messwerte_mergen(merged, _llama_round(fresh=100, cached=1000, seconds=1.0, first=1.0))
    merged = _messwerte_mergen(merged, _llama_round(fresh=100, cached=1100, seconds=1.0, first=1.0))

    # 2100 of 3300.
    assert merged["prompt_cache_percent"] == 64
    assert merged["erstes_token_nach_sekunden"] == 11.0


def test_a_server_that_names_the_whole_prompt_is_summed_the_same_way():
    """The OpenAI form: ``prompt_tokens`` is the whole prompt and
    ``cache_tokens`` the cached part of it, with no fresh count named."""
    first = {"prompt_tokens": 8000, "cache_tokens": 0, "prompt_cache_percent": 0,
             "dauer_sekunden": 1.0, "haeppchen": 1}
    second = {"prompt_tokens": 8100, "cache_tokens": 8000, "prompt_cache_percent": 99,
              "dauer_sekunden": 1.0, "haeppchen": 1}

    merged = _messwerte_mergen(first, second)

    assert merged["prompt_cache_percent"] == 50
    assert (merged["cache_tokens"], merged["eingelesen_tokens"]) == (8000, 8100)


def test_a_round_that_names_no_cache_takes_no_part_in_the_share():
    unknown = {"prompt_tokens": 5000, "dauer_sekunden": 1.0, "haeppchen": 1}
    named = _llama_round(fresh=100, cached=900, seconds=1.0, first=1.0)

    merged = _messwerte_mergen(unknown, named)

    assert merged["prompt_cache_percent"] == 90


def test_silence_without_any_cache_named_the_stats_have_no_share():
    one = {"prompt_tokens": 5000, "dauer_sekunden": 1.0, "haeppchen": 1}
    two = {"prompt_tokens": 5100, "dauer_sekunden": 1.0, "haeppchen": 1}

    merged = _messwerte_mergen(one, two)

    assert "prompt_cache_percent" not in merged
    assert "cache_tokens" not in merged


def test_a_real_miss_in_every_round_is_a_real_zero():
    first = _llama_round(fresh=500, cached=0, seconds=5.0, first=5.0)
    second = _llama_round(fresh=600, cached=0, seconds=6.0, first=6.0)

    assert _messwerte_mergen(first, second)["prompt_cache_percent"] == 0


def test_cache_halves_read_what_the_server_named():
    assert cache_halves({"cache_tokens": 10, "eingelesen_tokens": 5}) == (10, 5)
    assert cache_halves({"cache_tokens": 10, "prompt_tokens": 25}) == (10, 15)
    # A cached count beside a smaller whole is a contradiction, not a reading.
    assert cache_halves({"cache_tokens": 30, "prompt_tokens": 25}) is None
    assert cache_halves({"cache_tokens": True, "eingelesen_tokens": 5}) is None
    assert cache_halves({"eingelesen_tokens": 5}) is None
    assert cache_over_rounds({}, {}) == {}


# --- Through the chat --------------------------------------------------------


class _RoundsWithNumbers(GrosseWerkzeugkette):
    """Two rounds that only call a tool and a last one that writes the
    answer, each naming its numbers the way a llama.cpp server does."""

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        number = len(self.alle_anfragen)
        if number <= 2:
            yield Stueck(
                "stats",
                daten=_tool_round(
                    cache_tokens=(number - 1) * 8000,
                    eingelesen_tokens=8000 if number == 1 else 100,
                    prompt_cache_percent=0 if number == 1 else 99,
                ),
            )
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[Werkzeugaufruf(id=f"w{number}", name="riesig", argumente={})],
            )
            return
        yield Stueck("content", text="done")
        yield Stueck(
            "stats",
            daten=_text_round(cache_tokens=8100, eingelesen_tokens=50, prompt_cache_percent=99),
        )


def test_the_numbers_under_a_tool_answer_come_from_the_text_and_from_every_round(mcp_client):
    mcp_client.app.state.werkzeuge = GrossesErgebnis(gross="result")
    provider_setzen(mcp_client, _RoundsWithNumbers(mock_endpunkt("test"), runden=2))
    chat_id = mcp_client.post("/api/v1/chats", json={"title": "x"}).json()["id"]

    events = senden(mcp_client, chat_id)

    stats = next(e for e in events if e["typ"] == "stats")["daten"]
    # The speed of the round that wrote the text — not 6400 from the calls.
    assert stats["tokens_pro_sekunde"] == 41.75
    # 16100 cached of 24250 read over all three rounds, not the last one's 99 %.
    assert (stats["cache_tokens"], stats["eingelesen_tokens"]) == (16100, 8150)
    assert stats["prompt_cache_percent"] == 66
