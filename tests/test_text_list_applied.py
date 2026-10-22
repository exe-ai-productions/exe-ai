"""The checked list of text changes stands in the catalogues, the greeting
asks one of three sentences per start, and a saved state is a commit.

``text_list_applied.json`` holds ``changes``, each entry of the list: the
catalogue (``lang``), the key, the text that stood before and the text that
stands now; and ``kept``, the ten entries of the list that stay as they were,
because the old wording was chosen as it stands. The three questions of the
greeting are in neither: they have their own test below.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "app" / "locales"
DATA = json.loads((Path(__file__).parent / "text_list_applied.json").read_text(encoding="utf-8"))
LIST = DATA["changes"]
KEPT = DATA["kept"]
CATALOGUES = {lang: json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8")) for lang in ("de", "en")}
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _find(tree: dict, key: str):
    """The value under a dotted key; a segment of the key may hold dots itself."""
    parts = key.split(".")

    def walk(node, rest):
        for n in range(len(rest), 0, -1):
            head = ".".join(rest[:n])
            if head in node:
                if n == len(rest):
                    return node[head]
                if isinstance(node[head], dict):
                    found = walk(node[head], rest[n:])
                    if found is not None:
                        return found
        return None

    return walk(tree, parts)


@pytest.mark.parametrize("entry", LIST, ids=lambda e: f"{e['lang']}:{e['key']}")
def test_the_new_text_of_the_list_stands_under_its_key(entry):
    assert _find(CATALOGUES[entry["lang"]], entry["key"]) == entry["new"]


@pytest.mark.parametrize("entry", LIST, ids=lambda e: f"{e['lang']}:{e['key']}")
def test_silence_the_new_text_keeps_the_placeholders_of_the_old(entry):
    assert PLACEHOLDER.findall(entry["old"]) == PLACEHOLDER.findall(entry["new"])


@pytest.mark.parametrize("entry", KEPT, ids=lambda e: f"{e['lang']}:{e['key']}")
def test_silence_an_entry_with_a_wording_chosen_as_it_stands_keeps_its_old_text(entry):
    assert _find(CATALOGUES[entry["lang"]], entry["key"]) == entry["text"]


def test_the_list_holds_what_the_order_counts():
    langs = [e["lang"] for e in LIST]
    assert langs.count("de") == 198 and langs.count("en") == 48
    assert len(KEPT) == 10


# --- The greeting --------------------------------------------------------

SENTENCES = {
    "de": ["was kann ich heute für dich tun?", "wobei kann ich dir heute helfen?", "lass uns anfangen."],
    "en": ["what can I do for you today?", "what can I help you with today?", "let's get started."],
}
SENTENCE_KEYS = ["greeting.ask_today", "greeting.ask_help", "greeting.lets_start"]


@pytest.mark.parametrize("lang", ["de", "en"])
def test_the_three_sentences_of_the_greeting_stand_in_both_catalogues(lang):
    found = [_find(CATALOGUES[lang], key) for key in SENTENCE_KEYS]
    assert found == SENTENCES[lang]


@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize("part", ["morgen", "tag", "abend"])
def test_the_greeting_line_names_the_part_of_day_the_name_and_the_sentence(lang, part):
    line = _find(CATALOGUES[lang], f"gruss.frage_{part}")
    assert "{name}" in line and "{sentence}" in line


def _node(script: str) -> str:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT / "frontend" / "src" / "lib", check=True,
    )
    return result.stdout.strip()


@needs_node
def test_the_pick_takes_one_of_the_three_sentences_by_the_random_number():
    out = _node(
        "import { pickGreeting } from './greetingpick.js';"
        "console.log(JSON.stringify([0, 0.34, 0.5, 0.67, 0.999].map((r) => pickGreeting(() => r))))"
    )
    assert json.loads(out) == [
        "greeting.ask_today", "greeting.ask_help", "greeting.ask_help", "greeting.lets_start", "greeting.lets_start",
    ]


@needs_node
def test_the_pick_stays_the_same_until_the_next_start():
    out = _node(
        "import { greetingKey } from './greetingpick.js';"
        "console.log(JSON.stringify([greetingKey, greetingKey]))"
    )
    first, second = json.loads(out)
    assert first == second and first in SENTENCE_KEYS


def test_the_greeting_corner_shows_the_question_line_with_the_picked_sentence():
    corner = (ROOT / "frontend" / "src" / "teile" / "Begruessungsecke.svelte").read_text(encoding="utf-8")
    assert "greetingKey" in corner and "sentence:" in corner
    module = (ROOT / "frontend" / "src" / "lib" / "begruessung.svelte.js").read_text(encoding="utf-8")
    assert "`gruss.frage_${teil}`" in module


# --- Git words -------------------------------------------------------------

GIT_KEYS = [
    "fehler.checkpoints_unknown_folder", "fehler.checkpoints_unknown_snapshot", "fehler.checkpoints_too_many",
    "fehler.checkpoints_failed", "cli.cmd_rollback", "cli.rollback_inactive", "cli.rollback_none",
]


@pytest.mark.parametrize("key", GIT_KEYS)
def test_a_saved_state_is_a_commit_in_german(key):
    text = _find(CATALOGUES["de"], key)
    assert "Commit" in text
    assert not re.search(r"\bStand\b|\bStände", text), text


@pytest.mark.parametrize("key", GIT_KEYS)
def test_a_saved_state_is_a_commit_in_english(key):
    text = _find(CATALOGUES["en"], key)
    assert "commit" in text.lower()
    assert "snapshot" not in text.lower(), text


def test_silence_the_setting_name_stays_as_it_was():
    for lang in ("de", "en"):
        assert "global.checkpoints.enabled" in _find(CATALOGUES[lang], "cli.rollback_inactive")
