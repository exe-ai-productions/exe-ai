"""The manual's chapter on the terminal client names what the client knows:
every command ``/help`` lists and every word and switch ``--help`` lists, in
both languages — so a command added to the client and left out of the
manual is a red test, not a reader's surprise. Beside each of them stands
the sentence the client itself prints, word for word: a sentence changed in
the catalogue and not in the manual is a red test as well. And the page
counts the chapter in: its number, the total every chapter names, the
sidebar."""

from __future__ import annotations

import html
import re
from pathlib import Path

import httpx
import pytest

from cli import commands
from cli.client import ServiceClient
from cli.interfaces import Context
from cli.main import help_text
from cli.texts import Texts

ROOT = Path(__file__).resolve().parents[2]
PAGES = {"en": ROOT / "static" / "help" / "index.html", "de": ROOT / "static" / "help" / "de" / "index.html"}

# How the page breaks a line inside a cell.
LINE_BREAK = "<br>"

languages = pytest.mark.parametrize("language", sorted(PAGES))


def _page(language: str) -> str:
    return PAGES[language].read_text(encoding="utf-8")


def _chapter(language: str) -> str:
    found = re.search(r'<section class="chapter" id="terminal".*?</section>', _page(language), re.S)
    assert found, "the manual has no chapter on the terminal client"
    return found.group(0)


def _code(language: str) -> list[str]:
    """Everything the chapter sets as code, as the reader sees it."""
    return [html.unescape(piece) for piece in re.findall(r"<code>(.*?)</code>", _chapter(language))]


def _rows(language: str, *beginnings: str) -> list[tuple[str, str]]:
    """The rows of the chapter's tables whose first cell sets as code only
    names that start with one of ``beginnings``: each name with the sentence
    beside it, both as the reader sees them, in the order they stand in. A
    sentence of two lines stands in one cell, the second line below the
    first; it is read back with the line break between them."""
    found: list[tuple[str, str]] = []
    for first, second in re.findall(r"<tr><td>(.*?)</td><td>(.*?)</td></tr>", _chapter(language)):
        names = [html.unescape(name) for name in re.findall(r"<code>(.*?)</code>", first)]
        if names and all(name.startswith(beginnings) for name in names):
            sentence = html.unescape(second.replace(LINE_BREAK, "\n"))
            found += [(name, sentence) for name in names]
    return found


def _registry(tmp_path: Path, language: str = "en") -> commands.Commands:
    """The commands the client registers, with their sentences in that
    language."""
    client = ServiceClient(
        "http://service.test", language,
        http=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404))),
    )
    ctx = Context(client=client, texts=Texts(language), prefs_path=tmp_path / "cli.json")
    registry = commands.build_commands(ctx)
    assert isinstance(registry, commands.Commands)
    return registry


def _command_names(tmp_path: Path) -> list[str]:
    """The names the client registers — the list ``/help`` prints."""
    return _registry(tmp_path).names()


@languages
def test_the_chapter_names_every_command_of_the_chat(language: str, tmp_path: Path) -> None:
    named = {piece[1:] for piece in _code(language) if re.fullmatch(r"/[a-z]+", piece)}
    assert named == set(_command_names(tmp_path))


@languages
def test_the_chapter_names_every_word_and_switch_of_the_command_line(language: str) -> None:
    listed = re.findall(r"^  (\S+(?: \S+)?)\s{2,}\S", help_text(Texts(language)), re.M)
    words = {name for name in listed if not name.startswith("-")}
    switches = {name for name in listed if name.startswith("-")}
    assert words and switches
    code = _code(language)
    assert {
        piece.removeprefix("exe ") for piece in code if re.fullmatch(r"exe [a-z]+(?: [a-z]+)?", piece)
    } == words
    assert {piece for piece in code if re.fullmatch(r"-{1,2}[a-z][a-z-]*", piece)} == switches


@languages
def test_the_command_line_table_repeats_what_help_prints_word_for_word(language: str) -> None:
    printed = re.findall(r"^  (.+?)\s{2,}(.+)$", help_text(Texts(language)), re.M)
    assert printed
    # The rows that name a word or a switch of the command line.
    said = [(name.removeprefix("exe "), sentence) for name, sentence in _rows(language, "exe ", "-")]
    assert said == printed


@languages
def test_the_chat_table_repeats_what_the_help_command_lists_word_for_word(
    language: str, tmp_path: Path
) -> None:
    registry = _registry(tmp_path, language)
    listed = [
        (f"/{command.name}", registry.summary(command))
        for name in registry.names()
        for command in registry.matching(name)
        if command.name == name
    ]
    # The rows that name a command, each of them once; the line for the
    # shell is the manual's own.
    assert sorted(_rows(language, "/")) == sorted(listed)


@languages
def test_a_sentence_of_two_lines_stands_in_the_chapter_with_both(language: str, tmp_path: Path) -> None:
    """Silence probe for the comparison above: it reads the second line too.
    The sentences that have one are in the chapter with it, below the first
    line and in the same cell."""
    registry = _registry(tmp_path, language)
    two_lines = {
        f"/{command.name}": registry.summary(command)
        for name in registry.names()
        for command in registry.matching(name)
        if command.name == name and "\n" in registry.summary(command)
    }
    assert set(two_lines) == {"/chats", "/rename", "/archive", "/project", "/ps", "/mcp", "/skills", "/image", "/rollback", "/server", "/download", "/provider", "/setup", "/theme", "/settings", "/agents", "/cron", "/tools", "/dir", "/compact", "/export"}
    said = dict(_rows(language, "/"))
    for name, sentence in two_lines.items():
        first, second = sentence.split("\n")
        assert said[name] == sentence
        assert f"<td>{html.escape(first, quote=False)}{LINE_BREAK}{html.escape(second, quote=False)}</td>" in _chapter(language)


@languages
def test_the_two_commands_that_went_are_gone_from_the_chapter(language: str) -> None:
    named = [name for name, _ in _rows(language, "/")]
    assert "/chat" not in named and "/look" not in named
    assert "/chats" in named and "/theme" in named


@languages
def test_the_page_counts_the_chapter_in(language: str) -> None:
    """Every chapter says "n / total" with the same total, numbered without
    a gap in the order they stand in; the overview names that total, and
    the sidebar lists each chapter under its number."""
    page = _page(language)
    chapters = re.findall(r'<section class="chapter" id="([a-z-]+)"', page)
    counts = re.findall(r'<p class="chapter-count">\S+ (\d+) / (\d+)</p>', page)
    total = len(chapters)
    assert "terminal" in chapters
    assert [(int(number), int(of)) for number, of in counts] == [(number, total) for number in range(1, total + 1)]
    assert re.search(rf"<span>{total} \S+</span>", page), "the overview names another total"
    sidebar = re.findall(r'<a class="nav-link" href="#([a-z-]+)"><b>(\d+)</b>', page)
    assert sidebar == [(name, f"{number:02d}") for number, name in enumerate(chapters, 1)]


def test_both_languages_carry_the_same_chapters() -> None:
    """The silence probe for the other chapters: adding one changed neither
    their names nor their order, in either language."""
    english, german = (re.findall(r'<section class="chapter" id="([a-z-]+)"', _page(language)) for language in ("en", "de"))
    assert english == german
    assert english[-2:] == ["terminal", "hakt"]
    assert len(english) == 17


def test_the_german_manual_calls_the_choice_of_appearance_by_one_word() -> None:
    """App, first start and command table say "Erscheinungsbild"; a chapter
    that says "Look" for the same thing is a second word for it."""
    page = _page("de")
    assert not re.search(r"\bLooks?\b", page)
    assert "sechs Erscheinungsbilder" in page
