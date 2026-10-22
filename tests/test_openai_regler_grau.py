"""Seed and the two penalties at OpenAI's own host: shown locked, with the reason.

Every request to OpenAI's host that carries tools or a thinking stage goes over
the Responses wire, which has no field for these three
(`app/providers/openai_responses.py`, `CHAT_ONLY_FIELDS`). The model window
therefore draws them locked with the line that says when they do nothing —
and only there: another server that speaks the same dialect keeps them
free, and a stored value is untouched.
"""

from __future__ import annotations

import pytest

from app.config import EndpointConfig
from app.discovery import EndpunktZustand
from app.i18n import t
from app.parameter import NO_EFFECT_AT_OPENAI, pruefen, uebersetzen, unterstuetzte
from app.providers.openai_responses import CHAT_ONLY_FIELDS

DREI = ("seed", "presence_penalty", "frequency_penalty")


def _modell(base_url: str, sprache: str = "de", dialekt: str = "openai") -> dict[str, dict]:
    endpunkt = EndpointConfig(id="x", base_url=base_url, parameter_dialect=dialekt)
    zustand = EndpunktZustand(endpunkt=endpunkt, provider=None)
    reihen = zustand.als_dict("gpt-test", sprache)["parameter"]
    return {reihe["name"]: reihe for reihe in reihen}


def test_the_names_are_the_ones_the_responses_wire_drops():
    assert set(DREI) == set(CHAT_ONLY_FIELDS)


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_the_three_are_locked_at_openais_own_host_with_the_reason(sprache):
    reihen = _modell("https://api.openai.com/v1", sprache)
    deutsch, englisch = t(NO_EFFECT_AT_OPENAI, "de"), t(NO_EFFECT_AT_OPENAI, "en")
    grund = englisch if sprache == "en" else deutsch
    for name in DREI:
        assert reihen[name]["aktiv"] is False, name
        assert reihen[name]["grund"] == grund, name
    assert deutsch == "Wirkt bei OpenAI nicht, wenn Werkzeuge oder Denken aktiv sind."
    assert englisch == "Has no effect with OpenAI when tools or thinking are active."


@pytest.mark.parametrize(
    "adresse",
    ["https://api.openai.com/v1", "https://API.OPENAI.COM/v1", "https://eu.api.openai.com/v1"],
)
def test_the_host_is_read_as_a_host(adresse):
    assert all(_modell(adresse)[name]["aktiv"] is False for name in DREI)


@pytest.mark.parametrize(
    "adresse",
    [
        "http://127.0.0.1:8080/v1",
        "https://api.openai.com.example.net/v1",
        "https://proxy.test/api.openai.com/v1",
    ],
)
def test_another_server_of_the_same_dialect_keeps_the_three_free(adresse):
    """Silence probe: nothing changes where the host is not OpenAI's own."""
    reihen = _modell(adresse)
    for name in DREI:
        assert reihen[name]["aktiv"] is True, name
        assert reihen[name]["grund"] is None, name


def test_temperature_top_p_and_the_length_stay_free_at_openai():
    reihen = _modell("https://api.openai.com/v1")
    for name in ("temperature", "top_p", "max_tokens"):
        assert reihen[name]["aktiv"] is True, name
        assert reihen[name]["grund"] is None, name


def test_the_thinking_length_keeps_its_own_reason_at_openai():
    reihe = _modell("https://api.openai.com/v1")["reasoning_budget"]
    assert reihe["aktiv"] is False
    assert reihe["grund"] != t(NO_EFFECT_AT_OPENAI, "de")


def test_a_stored_value_is_untouched_and_goes_out_on_the_chat_wire():
    """The lock is a display: the value is kept and still translated, and the
    row stays in the list — locked, never removed."""
    werte = {"seed": 7, "presence_penalty": 0.5, "frequency_penalty": 0.25}
    assert pruefen(werte) == werte
    assert uebersetzen("openai", werte) == werte
    assert set(DREI) <= set(_modell("https://api.openai.com/v1"))


def test_a_dialect_that_does_not_know_a_name_still_leaves_it_out():
    """Nothing is added for a dialect that never offered the knob."""
    namen = {p.name for p in unterstuetzte("anthropic", None, None, DREI)}
    assert not namen & set(DREI)


def test_without_the_names_the_answer_is_unchanged():
    assert unterstuetzte("openai") == unterstuetzte("openai", None, None, ())
    assert all(p.aktiv for p in unterstuetzte("openai") if p.name in DREI)
