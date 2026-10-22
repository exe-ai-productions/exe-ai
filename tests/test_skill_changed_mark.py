"""The mark on a shipped skill the user has changed: plain quiet text saying
"Benutzer" / "User", no badge. The mark and the condition for it are as they
were; the CLI list `/skills` carries the same key and so the same words.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend" / "src" / "teile" / "Skillmaske.svelte"


def _catalogue(language: str) -> dict:
    return json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))


def _rule() -> str:
    return SOURCE.read_text(encoding="utf-8").split("<style>", 1)[1].split("\n  .vermerk {", 1)[1].split("}", 1)[0]


def test_the_changed_mark_says_user_in_both_languages():
    assert _catalogue("de")["skills"]["geaendert"] == "Benutzer"
    assert _catalogue("en")["skills"]["geaendert"] == "User"


def test_the_changed_mark_is_plain_quiet_text_without_a_badge():
    rule = _rule()
    assert "font-size: 12.5px" in rule
    assert "color: var(--text-leise)" in rule
    for gone in ("border", "background", "border-radius", "padding"):
        assert gone not in rule, gone


def test_the_mark_still_stands_behind_the_name_of_a_changed_shipped_skill_only():
    markup = SOURCE.read_text(encoding="utf-8").split("<style>", 1)[0]
    assert "{#if zeile.mitgeliefert && zeile.eigen}" in markup
    assert "<span class=\"vermerk\">{t('skills.geaendert')}</span>" in markup


def test_the_cli_list_reads_the_same_key():
    cli = (ROOT / "cli" / "skills.py").read_text(encoding="utf-8")
    assert 'ctx.texts.t("skills.geaendert")' in cli
