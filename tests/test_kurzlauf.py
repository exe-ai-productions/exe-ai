"""Flagging a run that ends far under budget."""

from __future__ import annotations

from app import kurzlauf


def test_weit_unter_beiden_grenzen_ist_kurz():
    assert kurzlauf.kurz(12, 400, 35, 420) is True


def test_nahe_an_der_rundengrenze_ist_nicht_kurz():
    assert kurzlauf.kurz(28, 30, 1, 420) is False


def test_nahe_an_der_zeitgrenze_ist_nicht_kurz():
    assert kurzlauf.kurz(1, 400, 18, 20) is False


def test_beide_grenzen_muessen_zutreffen():
    """Only the round side is far under — the minute side alone reaching
    the threshold must not be enough on its own."""
    assert kurzlauf.kurz(29, 30, 1, 420) is False


def test_genau_an_der_schwelle_zaehlt_noch_nicht_als_kurz():
    assert kurzlauf.kurz(10, 100, 10, 100) is False


def test_ohne_erlaubte_runden_oder_minuten_ist_nichts_kurz():
    assert kurzlauf.kurz(0, 0, 0, 20) is False
    assert kurzlauf.kurz(0, 30, 0, 0) is False


def test_ein_standard_agent_mit_dreissig_runden_loest_nie_aus():
    """1 of 30 rounds is 3.3%, well under SCHWELLE — but 30 stays below
    MINDEST_RUNDEN, so the default agent budget must never trigger this."""
    assert kurzlauf.kurz(1, 30, 1, 20) is False


def test_der_nachtlauf_ueber_der_mindestgrenze_loest_weiterhin_aus():
    assert kurzlauf.kurz(12, 400, 35, 420) is True


def test_hinweis_nennt_beide_zahlenpaare():
    text = kurzlauf.hinweis(12, 400, 35.0, 420)
    assert "12" in text
    assert "400" in text
    assert "35.0" in text
    assert "420" in text
