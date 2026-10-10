"""An answer that ran the context window out — without anybody refusing it.

The refusal path has its own file (``tests/test_kontextvoll.py``): there a
provider says "too long" before or instead of answering, and the request is
folded and sent again. This file is about the other half, the one that was
silent until now. A window filling up MID-ANSWER is not a refusal at all:
an OpenAI-compatible server simply reports an ordinary length stop, and the
program used to tell the user their answer-length setting had been reached
— a setting that, under Auto, was never a setting.

So the chat writes the same flag its refusal already writes, and a job ends
with the same reason its refusal already gives it. Both read one function
(``app/antwortende.py``) and the numbers the round itself reported.
"""

from __future__ import annotations

import json

import pytest

from app import fenstergroesse
from app.providers import MockProvider, mock_endpunkt
from app.providers.base import Stueck, Werkzeugaufruf
from tests.conftest import provider_setzen
from tests.test_auftraege_api import agent_schreiben, auf_ende_warten

# A window and a round that fills it to the last token — the shape measured
# on a llama-server, in numbers a request of this program really fits into.
# The measured pair itself (150 + 106 against 256) is checked where it can be
# checked without a whole chat around it: tests/test_antwortende.py. A window
# of 256 here would fold every request before it ever went out, because a
# system prompt alone is larger than that (app/antwortgrenze.py).
FENSTER = 100_000
VOLL_PROMPT = 99_900
VOLL_ANTWORT = 100
# The same round with room to spare behind it.
KLEIN_PROMPT = 150
KLEIN_ANTWORT = 106


class AmFensterEnde(MockProvider):
    """Answers, then reports the end reason and the usage block a real
    server reports — the two halves the verdict is made of.

    ``werkzeug_runden`` asks for a tool that many times first, so a job's
    round loop can be driven past its first round.
    """

    def __init__(
        self,
        *args,
        ende_grund: str = "length",
        prompt_tokens: int = VOLL_PROMPT,
        completion_tokens: int = VOLL_ANTWORT,
        werkzeug_runden: int = 0,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.ende_grund = ende_grund
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.werkzeug_runden = werkzeug_runden
        self.runden = 0

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        self.runden += 1
        if self.runden <= self.werkzeug_runden:
            yield Stueck("content", text="looking")
            yield Stueck(
                "tool_call",
                werkzeugaufrufe=[
                    Werkzeugaufruf(
                        id=f"w{self.runden}", name="addieren", argumente={"a": 1, "b": 1}
                    )
                ],
            )
            return
        yield Stueck("content", text="answer")
        # The exact shape an OpenAI-compatible provider emits
        # (app/providers/openai_kompatibel.py): the raw usage block under
        # `nutzung`, the end reason, and the two readings that were already
        # made of it.
        yield Stueck(
            "stats",
            daten={
                "dauer_sekunden": 0.0,
                "haeppchen": 1,
                "endpunkt": self.id,
                "nutzung": {
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens,
                    "total_tokens": self.prompt_tokens + self.completion_tokens,
                },
                "ende_grund": self.ende_grund,
                "abgeschnitten": self.ende_grund in ("length", "max_tokens"),
                "kontextfenster_voll": self.ende_grund == "model_context_window_exceeded",
            },
        )


def _fenster_setzen(client, tokens: int) -> None:
    """A fixed window for the test, marked as entered by hand so nothing a
    round reports can teach a different one mid-run (app/fenstergroesse.py)."""
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.context_tokens = tokens
    zustand.kontext_quelle = fenstergroesse.QUELLE_EINGETRAGEN


def _senden(client, chat_id: str, **felder) -> list[dict]:
    antwort = client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "Frage", **felder},
    )
    assert antwort.status_code == 200
    return [
        json.loads(zeile[5:].strip())
        for zeile in antwort.text.splitlines()
        if zeile.startswith("data:")
    ]


def _stats(client, chat_id: str) -> dict:
    return client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"][-1]["stats"]


# --- Chat -----------------------------------------------------------------


def test_chat_llama_cpp_fuellt_das_fenster_und_sagt_es(client, chat_id):
    """`length`, and prompt plus answer reach the window exactly. The
    ceiling was the user's own — the window was simply the smaller of the
    two, and that is what the hint has to say."""
    provider_setzen(client, AmFensterEnde(mock_endpunkt("test")))
    _fenster_setzen(client, FENSTER)

    _senden(client, chat_id, max_tokens=4_096)

    assert _stats(client, chat_id)["kontextfenster_voll"] is True


def test_chat_mit_luft_bleibt_beim_laengen_hinweis(client, chat_id):
    """The same end reason, the same self-set ceiling, a window with room to
    spare: then the length really was the reason."""
    provider_setzen(client, AmFensterEnde(
        mock_endpunkt("test"),
        prompt_tokens=KLEIN_PROMPT,
        completion_tokens=KLEIN_ANTWORT,
    ))
    _fenster_setzen(client, FENSTER)

    _senden(client, chat_id, max_tokens=64)

    assert _stats(client, chat_id)["kontextfenster_voll"] is False


def test_chat_unter_auto_mit_luft_ist_die_grenze_des_anbieters(client, chat_id):
    """Nothing set, and the window still had room: then what ended the
    answer was a limit of the PROVIDER's — a maker's number, a learned cap,
    or a server deciding the length itself. Pointing at the window would be
    wrong, and pointing at the answer-length slider would point at a slider
    that was never touched."""
    provider_setzen(client, AmFensterEnde(
        mock_endpunkt("test"),
        prompt_tokens=KLEIN_PROMPT,
        completion_tokens=KLEIN_ANTWORT,
    ))
    _fenster_setzen(client, FENSTER)

    _senden(client, chat_id)

    stats = _stats(client, chat_id)
    assert stats.get("kontextfenster_voll") is not True
    assert stats["anbietergrenze"] is True


def test_chat_unter_auto_am_vollen_fenster_bleibt_das_fenster(client, chat_id):
    """The same setting, the numbers the other way round: prompt and answer
    reach the window, and then it IS the window."""
    provider_setzen(client, AmFensterEnde(mock_endpunkt("test")))
    _fenster_setzen(client, FENSTER)

    _senden(client, chat_id)

    stats = _stats(client, chat_id)
    assert stats["kontextfenster_voll"] is True
    assert stats.get("anbietergrenze") is not True


def test_chat_schweigt_beim_normalen_ende(client, chat_id):
    """The silence probe: a finished answer says nothing, however full the
    window was when it finished."""
    provider_setzen(client, AmFensterEnde(mock_endpunkt("test"), ende_grund="stop"))
    _fenster_setzen(client, FENSTER)

    _senden(client, chat_id)

    assert _stats(client, chat_id)["kontextfenster_voll"] is False


class NurGedacht(MockProvider):
    """Thinks, says nothing, and reports a length stop — the shape a model
    takes when its thinking pass spends the whole answer budget."""

    def __init__(self, *args, ende_grund: str = "length", **kwargs):
        super().__init__(*args, **kwargs)
        self.ende_grund = ende_grund

    async def streamen(self, anfrage):
        self.letzte_anfrage = anfrage
        self.alle_anfragen.append(anfrage)
        yield Stueck("reasoning", text="Let me work this out step by step")
        yield Stueck(
            "stats",
            daten={
                "dauer_sekunden": 0.0,
                "haeppchen": 1,
                "endpunkt": self.id,
                "nutzung": {
                    "prompt_tokens": KLEIN_PROMPT,
                    "completion_tokens": KLEIN_ANTWORT,
                    "total_tokens": KLEIN_PROMPT + KLEIN_ANTWORT,
                },
                "ende_grund": self.ende_grund,
                "abgeschnitten": True,
            },
        )


def test_chat_denken_braucht_die_eingestellte_laenge_auf(client, chat_id):
    """Thinking, no visible text, a length stop — and a ceiling the user set:
    the hint names that length."""
    provider_setzen(client, NurGedacht(mock_endpunkt("test")))
    _fenster_setzen(client, FENSTER)

    _senden(client, chat_id, max_tokens=64)

    stats = _stats(client, chat_id)
    assert stats["denken_aufgebraucht"] == "denken_aufgebraucht_eigene_grenze"
    assert stats.get("kontextfenster_voll") is not True


def test_chat_denken_braucht_unter_auto_die_anbietergrenze_auf(client, chat_id):
    """The same shape under Auto: nobody set a length, so the one that ran
    out was the provider's."""
    provider_setzen(client, NurGedacht(mock_endpunkt("test")))
    _fenster_setzen(client, FENSTER)

    _senden(client, chat_id)

    assert _stats(client, chat_id)["denken_aufgebraucht"] == "denken_aufgebraucht"


def test_chat_mit_sichtbarem_text_bleibt_beim_laengen_hinweis(client, chat_id):
    """Silence probe: thinking AND a visible answer is the ordinary cut-off
    note, not this one."""
    provider_setzen(client, AmFensterEnde(
        mock_endpunkt("test"),
        prompt_tokens=KLEIN_PROMPT,
        completion_tokens=KLEIN_ANTWORT,
    ))
    _fenster_setzen(client, FENSTER)

    _senden(client, chat_id, max_tokens=64)

    stats = _stats(client, chat_id)
    assert "denken_aufgebraucht" not in stats
    assert stats["abgeschnitten"] is True


def test_auftrag_denken_braucht_die_laenge_auf(client, config):
    """The same shape in a run: it ends, and its reason names whose length
    the thinking used up."""
    provider = NurGedacht(mock_endpunkt("test"))

    daten = _auftrag(client, config, provider, FENSTER, kopf_zusatz="\nmax_tokens: 4096")

    assert daten["end_reason"] == "denken_aufgebraucht_eigene_grenze"
    assert daten["state"] == "gescheitert"


def test_auftrag_denken_unter_auto_nennt_den_anbieter(client, config):
    """Nothing set: the length that ran out was the provider's."""
    provider = NurGedacht(mock_endpunkt("test"))

    daten = _auftrag(client, config, provider, FENSTER)

    assert daten["end_reason"] == "denken_aufgebraucht"


# --- Job ------------------------------------------------------------------


def _auftrag(client, config, provider, fenster: int, kopf_zusatz: str = "") -> dict:
    agent_schreiben(config, kopf="model: test\nmax_rounds: 20" + kopf_zusatz)
    provider_setzen(client, provider)
    _fenster_setzen(client, fenster)
    kennung = client.post(
        "/api/v1/jobs", json={"agent": "recherche", "task": "Go"}
    ).json()["id"]
    return auf_ende_warten(client, kennung)


def test_auftrag_endet_am_vollen_fenster_statt_fertig_zu_werden(client, config):
    """No refusal anywhere: the round simply ends at the window. Until now
    that was booked as a finished run over a cut-off answer."""
    provider = AmFensterEnde(mock_endpunkt("test"), werkzeug_runden=1)

    daten = _auftrag(client, config, provider, FENSTER)

    assert daten["end_reason"] == "kontext_voll"
    assert daten["state"] == "gescheitert"
    # Not an error, and nothing thrown away: the reason is the ending's own
    # word rather than a provider's sentence (a run that died on one carries
    # "fehler: …" here instead), and BOTH rounds are in the result — the
    # round that ran the window out included. Spelled out rather than merely
    # asked to be non-empty: the first round alone would satisfy that, and
    # the ending is decided after the cut-off round's text has been kept,
    # which is the order this test is here to hold.
    assert daten["result"] == "looking\n\nanswer"


def test_auftrag_unter_auto_mit_luft_endet_an_der_anbietergrenze(client, config):
    """A length stop, nothing set, and the window still had room: the run
    ends — but with the provider's limit as its reason, not the window."""
    provider = AmFensterEnde(
        mock_endpunkt("test"),
        werkzeug_runden=1,
        prompt_tokens=KLEIN_PROMPT,
        completion_tokens=KLEIN_ANTWORT,
    )

    daten = _auftrag(client, config, provider, FENSTER)

    assert daten["end_reason"] == "anbietergrenze"
    assert daten["state"] == "gescheitert"


def test_auftrag_mit_luft_im_fenster_wird_fertig(client, config):
    """The other side of the same claim: a run whose window still has room
    ends the way it always did."""
    provider = AmFensterEnde(
        mock_endpunkt("test"),
        ende_grund="stop",
        prompt_tokens=KLEIN_PROMPT,
        completion_tokens=KLEIN_ANTWORT,
    )

    daten = _auftrag(client, config, provider, FENSTER)

    assert daten["state"] == "fertig"
    assert daten["end_reason"] != "kontext_voll"


@pytest.mark.parametrize("grund", ["model_context_window_exceeded", "length"])
def test_auftrag_erkennt_beide_woerter_fuer_dasselbe(client, config, grund):
    """Anthropic has a word for it and reports it as a perfectly normal end
    of stream; everybody else reports a length stop and leaves the numbers
    to say the rest. Both end the run the same way."""
    provider = AmFensterEnde(mock_endpunkt("test"), ende_grund=grund)

    daten = _auftrag(client, config, provider, FENSTER)

    assert daten["end_reason"] == "kontext_voll"


def test_auftrag_mit_eigener_grenze_und_luft_wird_fertig(client, config):
    """A job whose agent head names an answer length of its own, ending at
    that length with the window still half empty: that is the length the
    agent asked for, not a full window, and the run finishes."""
    provider = AmFensterEnde(
        mock_endpunkt("test"),
        prompt_tokens=KLEIN_PROMPT,
        completion_tokens=KLEIN_ANTWORT,
    )

    daten = _auftrag(client, config, provider, FENSTER, kopf_zusatz="\nmax_tokens: 4096")

    assert daten["state"] == "fertig"
    assert daten["end_reason"] != "kontext_voll"
