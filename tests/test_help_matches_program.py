"""The manual and the skill that answers from it stay at the program.

A manual that names a place the program no longer has sends a reader on a
search for it, and the skill that answers from it does the same for the
assistant. So what the program lists is read from the program — the groups
and rows of the settings, the signs of the two bars, the built-in tools with
their sentences — and each of them has to stand in the manual, in both
languages, with the text the catalogue gives it, and in the skill in English.
A page that still calls the models "Local" and "Cloud" in the left sidebar is
a red test, not a reader's surprise.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = {"en": ROOT / "static" / "help" / "index.html", "de": ROOT / "static" / "help" / "de" / "index.html"}
SKILL = ROOT / "skills" / "help" / "SKILL.md"
SETTINGS_LIST = ROOT / "frontend" / "src" / "lib" / "einstellungsliste.js"
LEFT_BAR = ROOT / "frontend" / "src" / "teile" / "Seitenleiste.svelte"
RIGHT_BAR = ROOT / "frontend" / "src" / "teile" / "ToolSigns.svelte"

languages = pytest.mark.parametrize("language", sorted(PAGES))


def _catalogue(language: str) -> dict:
    return json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))


def _text_of(catalogue: dict, key: str) -> str:
    value = catalogue
    for part in key.split("."):
        value = value[part]
    assert isinstance(value, str), key
    return value


def _chapter(language: str, name: str) -> str:
    page = PAGES[language].read_text(encoding="utf-8")
    found = re.search(rf'<section class="chapter" id="{name}".*?</section>', page, re.DOTALL)
    assert found, f"the manual has no chapter {name}"
    return found.group(0)


def _plain(markup: str) -> str:
    """What the reader sees: no tags, entities resolved, one space between
    words."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup)))


def _settings_keys() -> list[str]:
    """The catalogue keys of the groups, the rows and the six servers of the
    settings, as the list names them (up to the pages' own table)."""
    source = SETTINGS_LIST.read_text(encoding="utf-8")
    source = source[: source.index("export const SEITEN")]
    return sorted(set(re.findall(r"titel: '([a-z_]+\.[a-z_]+)'", source)))


def _left_bar_keys() -> list[str]:
    source = LEFT_BAR.read_text(encoding="utf-8")
    snippet = source[source.index("{#snippet fusszeichen()}"): source.index("{/snippet}")]
    return re.findall(r"title=\{t\('([a-z_.]+)'\)\}", snippet)


def _right_bar_keys() -> list[str]:
    source = RIGHT_BAR.read_text(encoding="utf-8")
    found = re.search(r"export const ORDER = \[(.*?)\]", source, re.DOTALL)
    assert found
    order = re.findall(r"'([a-z]+)'", found.group(1))
    labels = dict(re.findall(r"(\w+): '([a-z_.]+)',", source[source.index("const LABELS"):]))
    return [labels[name] for name in order]


def test_the_lists_are_read_from_the_program() -> None:
    """Silence probe: a regex that finds nothing would let every test below
    pass over an empty list."""
    assert len(_settings_keys()) >= 30
    assert len(_left_bar_keys()) == 5
    assert len(_right_bar_keys()) == 7


@languages
def test_the_settings_chapter_names_every_group_and_row(language: str) -> None:
    chapter = _plain(_chapter(language, "einstellungen"))
    catalogue = _catalogue(language)
    missing = [_text_of(catalogue, key) for key in _settings_keys() if _text_of(catalogue, key) not in chapter]
    assert not missing


def test_the_skill_names_every_group_and_row_of_the_settings() -> None:
    skill = re.sub(r"\s+", " ", SKILL.read_text(encoding="utf-8"))
    catalogue = _catalogue("en")
    missing = [_text_of(catalogue, key) for key in _settings_keys() if _text_of(catalogue, key) not in skill]
    assert not missing


@languages
def test_the_window_chapter_names_the_signs_of_both_bars(language: str) -> None:
    chapter = _plain(_chapter(language, "fenster"))
    catalogue = _catalogue(language)
    keys = _left_bar_keys() + _right_bar_keys()
    missing = [_text_of(catalogue, key) for key in keys if _text_of(catalogue, key) not in chapter]
    assert not missing


def test_the_skill_names_the_signs_of_both_bars() -> None:
    skill = re.sub(r"\s+", " ", SKILL.read_text(encoding="utf-8"))
    catalogue = _catalogue("en")
    keys = _left_bar_keys() + _right_bar_keys()
    missing = [_text_of(catalogue, key) for key in keys if _text_of(catalogue, key) not in skill]
    assert not missing


@languages
def test_the_tools_chapter_lists_every_built_in_tool_with_its_sentence(language: str) -> None:
    chapter = _chapter(language, "werkzeuge")
    sentences = _catalogue(language)["werkzeuge"]["eingebaut_satz"]
    for name, sentence in sentences.items():
        row = f"<code>{name}</code></td><td>{html.escape(sentence, quote=False)}</td>"
        assert row in chapter, name


def test_the_skill_names_every_built_in_tool() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    sentences = _catalogue("en")["werkzeuge"]["eingebaut_satz"]
    assert [name for name in sentences if f"`{name}`" not in skill] == []


# The words by which the manual and the skill used to name places that the
# settings and the left sidebar no longer have.
GONE_PLACES = (
    "Connections & keys", "Assistant behavior", "Prompts & agents", "Verbindungen & Schlüssel",
    "Prompts & Agenten",
)


@languages
def test_the_manual_names_no_place_that_is_gone(language: str) -> None:
    page = _plain(PAGES[language].read_text(encoding="utf-8"))
    assert [place for place in GONE_PLACES if place in page] == []
    for chapter in ("erste-schritte", "fenster", "hakt"):
        markup = _chapter(language, chapter)
        assert not re.search(r'<b class="k">(Local|Lokal|Cloud)</b>', markup), chapter
        assert not re.search(r"<td>(Local|Lokal|Cloud)</td>", markup), chapter


def test_the_skill_names_no_place_that_is_gone() -> None:
    skill = re.sub(r"\s+", " ", SKILL.read_text(encoding="utf-8"))
    assert [place for place in GONE_PLACES if place in skill] == []
    assert "Local window" not in skill and "Cloud window" not in skill
    assert "six signs" not in skill


@languages
def test_the_chapters_say_where_the_files_of_the_program_live(language: str) -> None:
    """The storage locations stand in the chapter on folders with the
    folders of the program, each with the subfolders the code reads."""
    from app import bildrunner, bildwahlen, modellrunner

    chapter = _chapter(language, "ordner")
    for folder in (
        bildrunner.VAE_ORDNER, bildrunner.TEXTVERSTEHER_ORDNER, bildwahlen.LORA_ORDNER,
        bildwahlen.EMBEDDING_ORDNER, bildrunner.UPSCALER_ORDNER, modellrunner.MTP_ORDNER,
        modellrunner.VISION_ORDNER,
    ):
        assert f"<code>{folder}/</code>" in chapter, folder


def test_the_skill_names_the_subfolders_the_code_reads() -> None:
    from app import bildrunner, bildwahlen, modellrunner

    skill = SKILL.read_text(encoding="utf-8")
    for folder in (
        bildrunner.VAE_ORDNER, bildrunner.TEXTVERSTEHER_ORDNER, bildwahlen.LORA_ORDNER,
        bildwahlen.EMBEDDING_ORDNER, modellrunner.MTP_ORDNER, modellrunner.VISION_ORDNER,
    ):
        assert f"`{folder}/`" in skill, folder


# --- What the program does with keys, snapshots, standing permissions and agents -------


def _snapshot_switch() -> str:
    """The command the program itself gives for switching snapshots on."""
    found = re.search(r"(/settings \S+ true)", _catalogue("en")["cli"]["rollback_inactive"])
    assert found, "the catalogue no longer names the switch"
    return found.group(1)


def _agent_limit_fields() -> list[str]:
    source = (ROOT / "app" / "agenten.py").read_text(encoding="utf-8")
    fields = re.findall(r"^\s+(reasoning_budget|max_command_seconds):", source, re.MULTILINE)
    assert sorted(fields) == ["max_command_seconds", "reasoning_budget"], fields
    return sorted(fields)


def _all_three() -> dict[str, str]:
    """The text of both manuals, as the reader sees it, and of the skill."""
    texts = {language: _plain(PAGES[language].read_text(encoding="utf-8")) for language in PAGES}
    texts["skill"] = re.sub(r"\s+", " ", SKILL.read_text(encoding="utf-8"))
    return texts


def test_the_program_names_what_the_tests_below_look_for() -> None:
    """Silence probe: a program that stopped giving the switch or the fields
    would let the tests below look for nothing."""
    assert _snapshot_switch() == "/settings global.checkpoints.enabled true"
    assert _agent_limit_fields() == ["max_command_seconds", "reasoning_budget"]


def test_the_manuals_and_the_skill_say_how_snapshots_are_switched_on_and_got_back() -> None:
    for name, text in _all_three().items():
        assert _snapshot_switch() in text, name
        assert "/rollback" in text, name


def test_the_manuals_and_the_skill_say_how_an_always_allow_is_taken_back() -> None:
    for name, text in _all_three().items():
        assert "/tools forget" in text, name
        assert "berechtigungen.json" in text, name


def test_the_manuals_and_the_skill_name_both_agent_limits_of_the_file() -> None:
    for name, text in _all_three().items():
        for field in _agent_limit_fields():
            assert field in text, (name, field)


def test_the_manuals_and_the_skill_say_where_the_keys_live_and_promise_nothing_false() -> None:
    for name, text in _all_three().items():
        assert ".env" in text, name
        for promise in ("never displayed again", "never shown again", "nie wieder angezeigt"):
            assert promise not in text, (name, promise)


def test_the_manuals_and_the_skill_say_what_a_chat_picture_goes_out_with() -> None:
    from app import bildwahlen

    strength = {"en": f"{bildwahlen.PICTURE_STRENGTH}", "de": f"{bildwahlen.PICTURE_STRENGTH}".replace(".", ",")}
    texts = _all_three()
    assert f"strength {strength['en']}" in texts["en"]
    assert f"Stärke {strength['de']}" in texts["de"]
    assert f"strength {strength['en']}" in texts["skill"]


def test_silence_probe_both_manuals_keep_the_same_chapters_and_anchors() -> None:
    """The new section has its anchor in both languages, and the two pages
    still carry the same chapters."""
    anchors = {
        language: re.findall(r'<section class="chapter" id="([a-z-]+)"', PAGES[language].read_text(encoding="utf-8"))
        for language in PAGES
    }
    assert anchors["en"] == anchors["de"] and len(anchors["en"]) == 17
    for language in PAGES:
        assert 'id="snapshots"' in PAGES[language].read_text(encoding="utf-8"), language
