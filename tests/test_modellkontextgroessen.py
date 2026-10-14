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


def test_deepseek_v4_models_carry_a_million():
    for name in (
        "deepseek-v4-pro",
        "deepseek-flash",
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
        "DeepSeek-V4-Pro",
    ):
        assert nachschlagen(name) == 1_000_000, name


def test_deepseek_table_entry_is_the_source_of_the_window():
    from app import fenstergroesse

    assert fenstergroesse.aufloesen(
        "deepseek-flash", eingetragen=None, server=None, gelernt=None
    ) == (1_000_000, fenstergroesse.QUELLE_TABELLE)


def test_retired_and_unknown_deepseek_names_stay_without_an_entry():
    """Silence probe: the retired names and a bare unknown one fall through
    to the fallback; a Claude entry and an entered window are untouched."""
    from app import fenstergroesse

    assert nachschlagen("deepseek-chat") is None
    assert nachschlagen("deepseek-reasoner") is None
    assert nachschlagen("deepseek-coder-6.7b") is None
    assert nachschlagen("claude-sonnet-5") == 200_000
    assert fenstergroesse.aufloesen(
        "deepseek-chat", eingetragen=None, server=None, gelernt=None
    ) == (fenstergroesse.ERSATZ, fenstergroesse.QUELLE_ERSATZ)
    assert fenstergroesse.aufloesen(
        "deepseek-flash", eingetragen=64_000, server=None, gelernt=None
    ) == (64_000, fenstergroesse.QUELLE_EINGETRAGEN)
    assert fenstergroesse.aufloesen(
        "deepseek-flash", eingetragen=None, server=256_000, gelernt=None
    ) == (256_000, fenstergroesse.QUELLE_SERVER)
