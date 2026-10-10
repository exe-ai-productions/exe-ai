"""Reading how full the context is from a round's stats chunk."""

from __future__ import annotations

from app import kontextverbrauch as kv


def test_anthropic_form_gesamt_tokens():
    assert kv.tokens_aus_messwerten({"gesamt_tokens": 1234, "prompt_tokens": 1000}) == 1234


def test_openai_form_total_tokens_in_nutzung():
    assert kv.tokens_aus_messwerten({"nutzung": {"total_tokens": 555}}) == 555


def test_openai_form_ohne_total_tokens_wird_addiert():
    daten = {"nutzung": {"prompt_tokens": 300, "completion_tokens": 40}}
    assert kv.tokens_aus_messwerten(daten) == 340


def test_nur_eine_haelfte_gemeldet_zaehlt_trotzdem():
    """One half missing is not the same as both missing — a server that
    only reports one side still said something usable."""
    assert kv.tokens_aus_messwerten({"nutzung": {"prompt_tokens": 300}}) == 300
    assert kv.tokens_aus_messwerten({"nutzung": {"completion_tokens": 40}}) == 40


def test_ohne_brauchbare_zahlen_gibt_es_nichts():
    for messwerte in (None, {}, {"nutzung": None}, {"nutzung": {}}, {"dauer_sekunden": 1.0}):
        assert kv.tokens_aus_messwerten(messwerte) is None


def test_kaputte_zahlen_vom_server_stuerzen_nicht_ab():
    """A malformed usage field is a reason to skip that one field, not to
    blow up the round it arrived with."""
    assert kv.tokens_aus_messwerten({"gesamt_tokens": "viele"}) is None
    assert kv.tokens_aus_messwerten({"nutzung": {"total_tokens": "n/a"}}) is None
    assert kv.tokens_aus_messwerten({"nutzung": {"total_tokens": [1, 2]}}) is None
    # One half malformed, the other usable: the good half still counts,
    # same as when a half is absent rather than garbled.
    assert kv.tokens_aus_messwerten(
        {"nutzung": {"prompt_tokens": "x", "completion_tokens": 5}}
    ) == 5
    assert kv.tokens_aus_messwerten(
        {"nutzung": {"prompt_tokens": "x", "completion_tokens": "y"}}
    ) is None


def test_nan_und_unendlich_stuerzen_nicht_ab():
    """int() raises on both — a malformed float must not either."""
    assert kv.tokens_aus_messwerten({"gesamt_tokens": float("nan")}) is None
    assert kv.tokens_aus_messwerten({"gesamt_tokens": float("inf")}) is None
    assert kv.tokens_aus_messwerten({"gesamt_tokens": float("-inf")}) is None


def test_nachkommastellen_werden_gerundet_nicht_abgeschnitten():
    assert kv.tokens_aus_messwerten({"gesamt_tokens": 149.9}) == 150
    assert kv.tokens_aus_messwerten({"gesamt_tokens": 149.4}) == 149


def test_stand_rechnet_den_prozentsatz():
    ergebnis = kv.stand({"gesamt_tokens": 50_000}, 200_000)
    assert ergebnis.tokens == 50_000
    assert ergebnis.kontextgroesse == 200_000
    assert ergebnis.prozent == 25.0


def test_stand_ohne_kontextgroesse_hat_keinen_prozentsatz():
    ergebnis = kv.stand({"gesamt_tokens": 50_000}, None)
    assert ergebnis.tokens == 50_000
    assert ergebnis.kontextgroesse is None
    assert ergebnis.prozent is None


def test_stand_ohne_messwerte_ist_nichts():
    assert kv.stand(None, 200_000) is None
    assert kv.stand({}, 200_000) is None
