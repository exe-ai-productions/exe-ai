"""The signs: Unicode where the output speaks UTF-8, ASCII everywhere else,
the Nerd Font icons only once they are switched on — and a mark in the head
whose lines are all equally wide."""

from __future__ import annotations

import sys

import pytest
from rich.cells import cell_len

from cli import glyphs

NAMES = (
    "prompt",
    "user",
    "rule",
    "assistant",
    "thinking",
    "tool",
    "ok",
    "error",
    "warning",
    "waiting",
    "connected",
    "disconnected",
    "in_use",
    "separator",
    "bullet",
    "quote",
    "gutter",
    "more",
    "arrow",
    "line_chat",
    "bar_used",
    "bar_free",
)
TOOLS = (
    "web_search",
    "read_webpage",
    "run_command",
    "read_file",
    "deliver_file",
    "search_files",
    "write_file",
    "edit_file",
    "list_dir",
    "create_folder",
    "ask_user",
    "draw_image",
    "remove_background",
    "memory_save",
)
SERVERS = ("shell", "memory", "skills", "searxng", "notion", "github", "gmail", "figma", "sentry")

# The stretch of code points the Nerd Font icons live in.
ICON_RANGE = range(0xE000, 0xF900)


class Output:
    """Stands in for what the client writes to: all that counts is its encoding."""

    def __init__(self, encoding: str | None) -> None:
        self.encoding = encoding


@pytest.fixture
def output(monkeypatch):
    def use(encoding: str | None) -> None:
        monkeypatch.setattr(sys, "stdout", Output(encoding))

    return use


@pytest.fixture(autouse=True)
def icons_off():
    yield
    glyphs.use_nerd(False)


def every_sign() -> list[str]:
    signs = [glyphs.glyph(name) for name in NAMES]
    signs += [glyphs.tool_glyph(tool) for tool in TOOLS]
    signs += [glyphs.tool_glyph("a_tool_of_its_own", server) for server in SERVERS]
    signs += list(glyphs.spinner_frames())
    return signs


def has_icon(sign: str) -> bool:
    return any(ord(character) in ICON_RANGE for character in sign)


@pytest.mark.parametrize("encoding", ["utf-8", "UTF-8", "utf8", "cp65001", "utf-8-sig"])
def test_an_output_that_speaks_utf8_gets_the_unicode_signs(output, encoding):
    output(encoding)
    assert glyphs.speaks_unicode()
    assert glyphs.glyph("prompt") == "❯"
    assert glyphs.glyph("rule") == "─"
    assert glyphs.glyph("ok") == "✓" and glyphs.glyph("error") == "✗"
    assert glyphs.tool_glyph("web_search") == "⊕"
    assert not any(sign.isascii() for sign in glyphs.spinner_frames()[1:])
    assert glyphs.glyph("bar_used") == "█" and glyphs.glyph("bar_free") == "░"


def test_the_context_bar_is_full_blocks_for_used_and_shaded_blocks_for_free(output):
    output("utf-8")
    used, free = glyphs.glyph("bar_used"), glyphs.glyph("bar_free")
    # Both fill the height of the line, so an empty bar shows as a bar.
    assert (used, free) == ("█", "░")
    # Two of them, so a bar reads without colours — in plain signs as well.
    assert used != free
    output("ascii")
    assert (glyphs.glyph("bar_used"), glyphs.glyph("bar_free")) == ("#", ".")


def test_every_unicode_sign_takes_one_cell(output):
    output("utf-8")
    for name in NAMES:
        assert cell_len(glyphs.glyph(name)) == 1, name
    for tool in TOOLS:
        assert cell_len(glyphs.tool_glyph(tool)) == 1, tool
    for frame in glyphs.spinner_frames():
        assert cell_len(frame) == 1, frame


def test_the_spinner_is_a_star_that_swells_and_shrinks(output):
    output("utf-8")
    frames = glyphs.spinner_frames()
    assert "✦" in frames and "✺" in frames
    # It comes back to where it began, so the turn has no jump in it.
    assert frames[1:] == tuple(reversed(frames[1:]))
    assert glyphs.SPINNER_INTERVAL == 0.1


@pytest.mark.parametrize("encoding", ["ascii", "latin-1", "cp1252", "cp437"])
def test_an_output_without_utf8_is_sent_nothing_it_cannot_carry(output, encoding):
    output(encoding)
    assert not glyphs.speaks_unicode()
    for sign in every_sign():
        assert sign.isascii(), sign
    assert glyphs.glyph("prompt") == ">"
    assert glyphs.spinner_frames() == ("-", "\\", "|", "/")
    assert glyphs.glyph("bar_used") == "#" and glyphs.glyph("bar_free") == "."


@pytest.mark.parametrize("encoding", ["gb18030", "utf-16"])
def test_an_output_that_could_carry_more_than_ascii_still_turns_the_ascii_spinner(output, encoding):
    """Two stages and no third: an output that does not speak UTF-8 gets
    the four strokes, whatever else it could carry."""
    output(encoding)
    "⠋⠙⠹".encode(encoding)
    assert glyphs.spinner_frames() == ("-", "\\", "|", "/")
    assert glyphs.glyph("prompt") == ">" and glyphs.glyph("bar_used") == "#"


@pytest.mark.parametrize("encoding", [None, "", "no-such-encoding"])
def test_an_output_nobody_knows_the_encoding_of_gets_ascii(output, encoding):
    output(encoding)
    assert all(sign.isascii() for sign in every_sign())


def test_an_output_that_is_missing_altogether_gets_ascii(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    assert glyphs.glyph("prompt") == ">"


def test_out_of_the_box_no_sign_is_an_icon_of_the_nerd_font(output):
    output("utf-8")
    assert not any(has_icon(sign) for sign in every_sign())


def test_switched_on_the_signs_that_have_an_icon_use_it(output):
    output("utf-8")
    glyphs.use_nerd(True)
    for name in ("thinking", "tool", "ok", "error", "warning", "waiting", "connected", "disconnected"):
        assert has_icon(glyphs.glyph(name)), name
    for tool in TOOLS:
        assert has_icon(glyphs.tool_glyph(tool)), tool
    assert has_icon(glyphs.tool_glyph("create_issue", "github"))
    assert has_icon(glyphs.tool_glyph("a_tool_nobody_knows"))
    # The signs without an icon stay as they were, and so does the spinner.
    assert glyphs.glyph("prompt") == "❯" and glyphs.glyph("rule") == "─"
    assert not any(has_icon(frame) for frame in glyphs.spinner_frames())

    glyphs.use_nerd(False)
    assert not any(has_icon(sign) for sign in every_sign())


def test_icons_are_not_sent_to_an_output_without_utf8(output):
    output("ascii")
    glyphs.use_nerd(True)
    assert all(sign.isascii() for sign in every_sign())


@pytest.mark.parametrize("encoding", ["utf-8", "ascii"])
def test_the_two_cells_of_the_bar_are_one_cell_each_and_tell_apart(output, encoding):
    output(encoding)
    used, free = glyphs.glyph("bar_used"), glyphs.glyph("bar_free")
    assert cell_len(used) == 1 and cell_len(free) == 1
    assert used != free


def test_the_entry_in_use_of_a_selection_is_marked_by_a_circle_and_by_a_star_without_utf8(output):
    output("utf-8")
    assert glyphs.glyph("in_use") == "●"
    output("ascii")
    assert glyphs.glyph("in_use") == "*"


def test_the_users_lines_carry_the_mark_they_were_typed_at(output):
    for encoding in ("utf-8", "ascii"):
        output(encoding)
        assert glyphs.glyph("user") == glyphs.glyph("prompt")


def test_a_tool_nobody_gave_a_sign_wears_the_general_one(output):
    for encoding in ("utf-8", "ascii"):
        output(encoding)
        assert glyphs.tool_glyph("a_tool_nobody_knows") == glyphs.glyph("tool") != ""
        assert glyphs.tool_glyph("") == glyphs.glyph("tool")
        assert glyphs.tool_glyph("a_tool_nobody_knows", "a_server_nobody_knows") == glyphs.glyph("tool")


def test_a_tool_without_a_sign_of_its_own_wears_its_servers(output):
    output("utf-8")
    assert glyphs.tool_glyph("create_issue", "github") == "⎇"
    # Its own name decides before the server does.
    assert glyphs.tool_glyph("web_search", "github") == "⊕"


def test_a_name_without_a_sign_is_an_empty_string(output):
    output("utf-8")
    assert glyphs.glyph("no-such-sign") == ""
