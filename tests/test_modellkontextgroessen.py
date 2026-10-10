"""The known-models table: a substring lookup, and nothing invented."""

from __future__ import annotations

from app.modellkontextgroessen import nachschlagen


def test_claude_modelle_werden_gefunden():
    assert nachschlagen("claude-sonnet-5") == 200_000
    assert nachschlagen("claude-opus-5-20260101") == 200_000


def test_gross_klein_schreibung_ist_egal():
    assert nachschlagen("Claude-Sonnet-5") == 200_000


def test_unbekanntes_modell_ergibt_nichts():
    assert nachschlagen("gpt-4o") is None
    assert nachschlagen("llama-3") is None


def test_fehlender_name_ergibt_nichts():
    assert nachschlagen(None) is None
    assert nachschlagen("") is None
