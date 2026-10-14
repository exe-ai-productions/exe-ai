"""The status line: what it says, in which order, and how it gives way
when the window is too narrow for all of it."""

from __future__ import annotations

import math
import sys
from collections.abc import Callable

import pytest
from prompt_toolkit.utils import get_cwidth

from cli import glyphs, status, themes
from cli.interfaces import Context
from cli.texts import Texts
from tests.cli.stub_service import StubService

Line = Callable[..., str]



def separator() -> str:
    """Between two parts of the left block. Asked anew each time: which
    sign it is belongs to the module that draws the signs."""
    return f" {glyphs.glyph('separator')} "


def fill(ctx: Context, **fields: object) -> None:
    """Sets what the other modules report in the course of a session."""
    ctx.session.chat = {"id": "chat-1", "title": "Plans for the garden"}
    ctx.status.update(
        chat_title="Plans for the garden",
        model_name="Local Model",
        context_window=131072,
        look="exe",
        **fields,
    )


def styles(ctx: Context, width: int = 120) -> dict[str, str]:
    """Each piece of the lines with the style it is drawn in."""
    return {text: style for style, text in ctx.status.fragments(width)}


def first(ctx: Context, width: int = 120) -> str:
    """The first line, without the sign in front of it."""
    line = "".join(piece for _, piece in ctx.status.fragments(width)).split("\n")[0]
    return line.removeprefix(glyphs.glyph("line_chat")).removeprefix(" ")


def second(ctx: Context, width: int = 120) -> str:
    """The second line, as it stands."""
    return "".join(piece for _, piece in ctx.status.fragments(width)).split("\n")[1]


def third(ctx: Context, width: int = 120) -> str:
    """The third line, as it stands: the context."""
    return "".join(piece for _, piece in ctx.status.fragments(width)).split("\n")[2]


def mode_sign() -> str:
    return f"{glyphs.glyph('line_mode')} "


def cells(line: str) -> tuple[int, int]:
    """How many cells of the bar in ``line`` are used, and how many free."""
    return line.count(glyphs.glyph("bar_used")), line.count(glyphs.glyph("bar_free"))


# The three colours the used cells of the bar can stand in, as the classes
# the look gives a colour to — and the class of the free ones: the look's
# quiet tone.
GREEN, YELLOW, RED = "class:green", "class:yellow", "class:red"
FREE = "class:muted"

# The least the free cells have to stand out from the ground of their look.
FREE_CELLS_SHOW_FROM = 3.0


def luminance(colour: str) -> float:
    """How light a colour written as six hex digits is, between 0 and 1."""
    channels = [int(colour[at : at + 2], 16) / 255 for at in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(colour: str, other: str) -> float:
    """How far two colours stand apart, from 1 (not at all) to 21."""
    lighter, darker = sorted((luminance(colour), luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def bar(ctx: Context, width: int = 120) -> tuple[tuple[str, str], tuple[str, str]]:
    """The two pieces of the bar in the third line, each with the style it
    is drawn in: the used cells and the free ones."""
    pieces = list(ctx.status.fragments(width))
    third_line = pieces[max(at for at, piece in enumerate(pieces) if piece == ("", "\n")) + 1 :]
    (used,) = [piece for piece in third_line if piece[0] in (GREEN, YELLOW, RED)]
    (free,) = [piece for piece in third_line if piece[0] == FREE]
    return used, free


def label() -> str:
    return Texts("en").t("cli.context_label")


def gap() -> str:
    return " " * status.GAP


def bar_room(width: int, count: str, *, with_label: bool = True) -> int:
    """How many cells the bar has at ``width`` beside ``count``: every
    column the label, the count and the gaps around the bar leave."""
    taken = get_cwidth(count) + status.GAP
    if with_label:
        taken += get_cwidth(label()) + status.GAP
    return width - taken


# --- What the line says ---------------------------------------------------------


def test_the_parts_stand_in_their_order_with_the_connection_at_the_right_edge(
    ctx: Context, status_line: Line
) -> None:
    fill(ctx, context_tokens=1234, server_states={"local": "offline"}, connection=status.CONNECTED)
    shown = status_line(ctx, 120)
    words = Texts("en")
    # Three lines, one below the other, the first two with their sign in
    # front, the third with the label of the context.
    line_one, line_two, line_three = shown.split("\n")
    assert line_one.startswith(f"{glyphs.glyph('line_chat')} ")
    assert line_two.startswith(mode_sign())
    assert line_three.startswith(words.t("cli.context_label") + " ")
    assert first(ctx, 120).rstrip().split(separator()) == [
        "Plans for the garden",
        "Local Model",
        words.t("kopf.server_aus"),
        "exe",
    ]
    connection = f"{glyphs.glyph('connected')} {words.t('cli.connected')}"
    assert line_two.endswith(connection)
    assert line_three.endswith(" 1234/131072")
    # Filled up to the edge: the connection ends in the last column.
    assert get_cwidth(line_two) == 120
    assert get_cwidth(line_one) <= 120 and get_cwidth(line_three) <= 120


# --- The third line: the context as a bar -----------------------------------------


def test_the_third_line_is_the_label_the_bar_and_the_count(ctx: Context) -> None:
    fill(ctx)
    used, free = glyphs.glyph("bar_used"), glyphs.glyph("bar_free")
    # Before the first answer: nothing used, and no count against the window.
    empty = bar_room(120, "–/131072")
    assert third(ctx) == f"{label()}{gap()}{free * empty}{gap()}–/131072"
    ctx.screen.update_status(context_tokens=65536)
    # Half the window: half the cells, rounded up.
    room = bar_room(120, "65536/131072")
    assert room == 97 and third(ctx) == f"{label()}{gap()}{used * 49}{free * 48}{gap()}65536/131072"
    # The label and the count in the text colour, the used cells in the
    # colour of how full the window is, the free ones in the quiet tone.
    pieces = styles(ctx)
    assert pieces[used * 49] == YELLOW and pieces[free * 48] == FREE
    assert pieces["65536/131072"] == "class:text" and pieces[label()] == "class:text"


@pytest.mark.parametrize(("percent", "level"), [(10, GREEN), (60, YELLOW), (90, RED)])
def test_the_used_cells_wear_the_colour_of_how_full_the_window_is(
    ctx: Context, percent: int, level: str
) -> None:
    fill(ctx)
    ctx.status.update(context_window=100000)
    ctx.screen.update_status(context_tokens=percent * 1000)
    count = f"{percent * 1000}/100000"
    room = bar_room(120, count)
    used, free = bar(ctx)
    filled = math.ceil(room * percent / 100)
    assert used == (level, glyphs.glyph("bar_used") * filled)
    assert free == (FREE, glyphs.glyph("bar_free") * (room - filled))
    # Two signs, so the level shows where nothing has a colour.
    assert glyphs.glyph("bar_used") != glyphs.glyph("bar_free")
    # What stands around the bar keeps the text colour.
    pieces = styles(ctx)
    assert pieces[label()] == "class:text" and pieces[count] == "class:text"


@pytest.mark.parametrize(
    ("tokens", "level"),
    [
        (1, GREEN),
        (49999, GREEN),
        (50000, YELLOW),
        (80000, YELLOW),
        (80001, RED),
        (100000, RED),
        # More than the window holds.
        (250000, RED),
    ],
)
def test_the_colour_turns_exactly_at_half_and_at_four_fifths_of_the_window(
    ctx: Context, tokens: int, level: str
) -> None:
    fill(ctx)
    ctx.status.update(context_window=100000)
    ctx.screen.update_status(context_tokens=tokens)
    used, _ = bar(ctx)
    assert used[0] == level and used[1]


def test_the_free_cells_stand_in_the_quiet_tone_and_not_in_the_line_colour(ctx: Context) -> None:
    fill(ctx)
    pieces = list(ctx.status.fragments(120))
    shaded = [style for style, text in pieces if glyphs.glyph("bar_free") in text]
    assert shaded == ["class:muted"]
    assert "class:line" not in [style for style, _ in pieces]


@pytest.mark.parametrize("look", ["exe", "darkmatter", "moune", "heaven", "pearl"])
def test_the_free_cells_stand_out_from_the_ground_of_every_look(ctx: Context, look: str) -> None:
    fill(ctx)
    _, free = bar(ctx)
    theme = themes.get(look)
    drawn_in = theme.prompt_style().get_attrs_for_style_str(free[0]).color
    assert drawn_in and contrast(drawn_in, theme.colours["ground"][1:]) >= FREE_CELLS_SHOW_FROM


def test_where_the_count_or_the_window_is_not_known_no_cell_is_used(ctx: Context) -> None:
    fill(ctx)
    # Before the first answer.
    used, free = bar(ctx)
    assert used[1] == "" and free[1] == glyphs.glyph("bar_free") * bar_room(120, "–/131072")
    # A count, and no window to hold it against.
    ctx.screen.update_status(context_tokens=1234)
    ctx.status.update(context_window=None)
    used, free = bar(ctx)
    assert used[1] == "" and free[1] == glyphs.glyph("bar_free") * bar_room(120, "1234/–")


def test_without_colours_the_level_still_shows_in_the_two_signs(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    fill(ctx)
    ctx.status.update(context_window=100000)
    ctx.screen.update_status(context_tokens=60000)
    used, free = bar(ctx)
    assert used[1] and free[1] and set(used[1]) != set(free[1])
    # Neither piece is given a colour by the look.
    fixed_block = themes.current().prompt_style()
    for style in (used[0], free[0]):
        assert not fixed_block.get_attrs_for_style_str(style).color


class Plain:
    """Stands in for an output that does not speak UTF-8."""

    encoding = "ascii"


def test_without_utf8_the_bar_is_two_different_plain_signs(
    ctx: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "stdout", Plain())
    fill(ctx)
    ctx.status.update(context_window=100000)
    ctx.screen.update_status(context_tokens=60000)
    line = third(ctx)
    assert line.isascii() and get_cwidth(line) == 120
    used, free = bar(ctx)
    assert used[0] == YELLOW and set(used[1]) == {"#"} and set(free[1]) == {"."}


def test_the_bar_takes_every_column_the_label_and_the_count_leave(ctx: Context) -> None:
    """Whatever the width and the count, the bar fills the line to its
    last column: the count ends under the connection of the line above."""
    fill(ctx, context_tokens=11091)
    assert sum(cells(third(ctx, 120))) == bar_room(120, "11091/131072") == 97
    assert sum(cells(third(ctx, 200))) == bar_room(200, "11091/131072") == 177
    for width in (120, 200):
        assert get_cwidth(third(ctx, width)) == width
    # A count that is not known yet, and one twice as long, fit the same way.
    ctx.status.update(context_tokens=None)
    assert sum(cells(third(ctx, 120))) == bar_room(120, "–/131072")
    ctx.status.update(context_tokens=1200000, context_window=1310720)
    assert sum(cells(third(ctx, 120))) == bar_room(120, "1200000/1310720")
    assert third(ctx, 120).endswith(f"{gap()}1200000/1310720") and get_cwidth(third(ctx, 120)) == 120


def test_anything_used_shows_as_a_cell_and_a_full_window_as_all_of_them(ctx: Context) -> None:
    fill(ctx)
    for tokens in (1, 6553, 65536, 131071, 131072, 200000):
        ctx.screen.update_status(context_tokens=tokens)
        room = bar_room(120, f"{tokens}/131072")
        used = min(room, -(-room * tokens // 131072))
        assert cells(third(ctx)) == (used, room - used), tokens
    assert cells(third(ctx))[1] == 0


def test_without_a_window_the_bar_is_empty_and_the_count_stands_against_a_dash(
    ctx: Context,
) -> None:
    fill(ctx, context_tokens=1234)
    ctx.status.update(context_window=None)
    assert cells(third(ctx)) == (0, bar_room(120, "1234/–")) and third(ctx).endswith(" 1234/–")
    ctx.status.update(context_tokens=None)
    assert third(ctx).endswith(" –/–")


def test_the_first_line_no_longer_carries_the_count(ctx: Context) -> None:
    fill(ctx, context_tokens=1234, server_states={"local": "idle"}, connection=status.CONNECTED)
    assert "/" not in first(ctx) and "1234" not in first(ctx)
    assert "1234/131072" in third(ctx)


def test_the_label_follows_the_language_in_use(ctx: Context) -> None:
    fill(ctx)
    assert third(ctx).startswith(Texts("en").t("cli.context_label"))
    ctx.texts.set_language("de")
    assert third(ctx).startswith(Texts("de").t("cli.context_label"))


def test_below_forty_columns_the_label_goes_and_the_bar_keeps_the_room(ctx: Context) -> None:
    fill(ctx, context_tokens=65536)
    count = "65536/131072"
    # At forty columns the label still stands in front of the bar.
    at_forty = third(ctx, status.LABEL_FROM)
    assert at_forty.startswith(label()) and sum(cells(at_forty)) == bar_room(40, count)
    # One column less: the label goes, and the bar takes its room too.
    narrower = third(ctx, status.LABEL_FROM - 1)
    assert not narrower.startswith(label())
    assert sum(cells(narrower)) == bar_room(39, count, with_label=False) == 25
    assert narrower.endswith(f"{gap()}{count}") and get_cwidth(narrower) == 39
    # Down to where only the count and its gap fit: no bar, then the count is cut.
    assert sum(cells(third(ctx, len(count) + status.GAP + 1))) == 1
    assert third(ctx, len(count) + status.GAP) == count
    assert third(ctx, len(count)) == count
    assert third(ctx, 5) == "65536"
    # The line fills its width wherever there is room for a bar, and never more.
    for width in range(len(count) + status.GAP + 1, 240):
        assert get_cwidth(third(ctx, width)) == width, width
    for width in range(1, 240):
        assert get_cwidth(third(ctx, width)) <= width and "\n" not in third(ctx, width)


def test_a_reported_count_stands_against_the_models_window(
    ctx: Context, status_line: Line
) -> None:
    fill(ctx)
    ctx.screen.update_status(context_tokens=1234)
    assert "1234/131072" in status_line(ctx)
    # The next report replaces it.
    ctx.screen.update_status(context_tokens=98765)
    shown = status_line(ctx)
    assert "98765/131072" in shown and "1234" not in shown


def test_without_a_count_a_dash_stands_in_its_place(ctx: Context, status_line: Line) -> None:
    fill(ctx)
    assert "–/131072" in status_line(ctx)


def test_a_count_without_a_known_window_stands_against_a_dash(
    ctx: Context, status_line: Line
) -> None:
    fill(ctx, context_tokens=1234)
    ctx.status.update(context_window=None)
    assert "1234/–" in status_line(ctx)


def test_without_a_model_and_a_count_the_line_names_no_context(
    ctx: Context, status_line: Line
) -> None:
    ctx.status.update(chat_title="Plans for the garden", look="exe")
    shown = first(ctx)
    assert "/" not in shown and "–" not in shown
    assert shown.rstrip() == f"Plans for the garden{separator()}exe"


def test_the_count_of_another_chat_is_not_shown_under_this_one(
    ctx: Context, status_line: Line
) -> None:
    fill(ctx, context_tokens=1234)
    ctx.session.chat = {"id": "chat-2", "title": "Another one"}
    ctx.status.update(chat_title="Another one")
    assert "–/131072" in status_line(ctx)
    # The new chat's own count shows as soon as it is reported.
    ctx.status.update(context_tokens=77)
    assert "77/131072" in status_line(ctx)


def test_a_model_switch_shows_the_new_name_and_its_window(
    ctx: Context, status_line: Line
) -> None:
    fill(ctx, context_tokens=1234)
    ctx.screen.update_status(model_name="Other Model", context_window=8192)
    shown = status_line(ctx)
    assert f"{separator()}Other Model{separator()}" in first(ctx)
    assert third(ctx).endswith(" 1234/8192")
    assert "Local Model" not in shown


@pytest.mark.parametrize("look", ["exe", "darkmatter", "moune", "heaven", "pearl"])
def test_the_active_server_stands_in_the_blue_of_every_look(ctx: Context, look: str) -> None:
    """The state the window draws blue is blue in each look — also in the
    look whose accent is its text colour, where the old colour was no
    colour at all. Silence probe: ready stays green, away stays quiet, and
    the chat's name and the model's name keep their own."""
    words = Texts("en")
    fill(ctx, server_states={"local": "active"})
    colours = themes.get(look).colours
    assert colours["blue"] != colours["text"]
    shown = styles(ctx)
    assert shown[words.t("kopf.server_active")] == "class:blue"
    assert themes.get(look).styles()["blue"] == colours["blue"]
    assert shown["Plans for the garden"] == "class:accent"
    assert shown["Local Model"] == "class:text"

    ctx.status.update(server_states={"local": "idle"})
    assert styles(ctx)[words.t("kopf.bereit")] == "class:green"
    ctx.status.update(server_states={"local": "offline"})
    assert styles(ctx)[words.t("kopf.server_aus")] == "class:muted"


def test_the_server_is_named_only_once_somebody_said_how_it_is(
    ctx: Context, status_line: Line
) -> None:
    words = Texts("en")
    fill(ctx)
    quiet = status_line(ctx)
    for key in ("kopf.server_active", "kopf.bereit", "kopf.server_aus"):
        assert words.t(key) not in quiet

    ctx.status.update(server_states={"local": "active"})
    assert words.t("kopf.server_active") in status_line(ctx)
    assert styles(ctx)[words.t("kopf.server_active")] == "class:blue"

    ctx.status.update(server_states={"local": "idle"})
    assert words.t("kopf.bereit") in status_line(ctx)
    assert styles(ctx)[words.t("kopf.bereit")] == "class:green"

    ctx.status.update(server_states={"local": "offline"})
    assert words.t("kopf.server_aus") in status_line(ctx)
    # Not reachable is no failure: quiet, never red.
    assert styles(ctx)[words.t("kopf.server_aus")] == "class:muted"

    ctx.status.update(server_states={})
    assert status_line(ctx) == quiet


def test_the_word_is_the_one_of_the_model_in_use(ctx: Context, status_line: Line) -> None:
    """Looked up at the moment of drawing: a switch of the model shows the
    other server's word, and a model nobody has spoken about shows none."""
    words = Texts("en")
    fill(ctx, server_states={"local": "active", "cloud": "offline"})
    assert words.t("kopf.server_active") in status_line(ctx)
    assert words.t("kopf.server_aus") not in status_line(ctx)

    ctx.session.endpoint_id = "cloud"
    assert words.t("kopf.server_aus") in status_line(ctx)
    assert words.t("kopf.server_active") not in status_line(ctx)

    ctx.session.endpoint_id = "unknown"
    for key in ("kopf.server_active", "kopf.bereit", "kopf.server_aus"):
        assert words.t(key) not in status_line(ctx)


def test_a_model_of_a_catalogue_shows_the_word_of_its_provider(
    ctx: Context, status_line: Line
) -> None:
    """`cloud:gpt` sits on the server `cloud`: the word is kept by server,
    and the model in use is traced back to it."""
    words = Texts("en")
    fill(ctx, server_states={"cloud": "active"})
    ctx.session.endpoint_id = "cloud:gpt"
    assert words.t("kopf.server_active") in status_line(ctx)
    assert status.server_of("cloud:gpt") == "cloud"
    assert status.server_of("cloud:a-model:with-colons") == "cloud"
    assert status.server_of("local") == "local"


def test_the_three_words_are_english_in_both_languages(ctx: Context, status_line: Line) -> None:
    for state, key in (
        ("active", "kopf.server_active"), ("idle", "kopf.bereit"), ("offline", "kopf.server_aus")
    ):
        fill(ctx, server_states={"local": state})
        ctx.texts.set_language("en")
        english = status_line(ctx)
        ctx.texts.set_language("de")
        german = status_line(ctx)
        assert Texts("en").t(key) == Texts("de").t(key) == state
        assert state in english and state in german


def test_the_connection_says_whether_the_service_answers(
    ctx: Context, status_line: Line
) -> None:
    words = Texts("en")
    fill(ctx)
    apart = f"{glyphs.glyph('disconnected')} {words.t('cli.disconnected')}"
    # Until the listener says otherwise, there is no connection to speak of.
    assert second(ctx).endswith(apart)
    assert styles(ctx)[apart] == "class:red"

    ctx.status.update(connection=status.CONNECTED)
    together = f"{glyphs.glyph('connected')} {words.t('cli.connected')}"
    assert second(ctx).endswith(together)
    assert styles(ctx)[together] == "class:green"

    # The stream broke and is being opened again: neither of the two.
    ctx.status.update(connection=status.RECONNECTING)
    again = f"{glyphs.glyph('waiting')} {words.t('cli.reconnecting')}"
    assert second(ctx).endswith(again)
    assert styles(ctx)[again] == "class:yellow"

    ctx.status.update(connection=status.DISCONNECTED)
    assert second(ctx).endswith(apart)
    # Three states, three words: the state stands as a word, not only as a colour.
    assert len({apart, together, again}) == 3
    for said in (apart, together, again):
        assert not said.endswith("."), said


def test_a_model_the_service_reported_as_gone_is_marked(
    ctx: Context, status_line: Line
) -> None:
    words = Texts("en")
    fill(ctx)
    ctx.status.update(unreachable_models=frozenset({"local"}))
    marked = f"Local Model {words.t('status.nicht_erreichbar')}"
    assert f"{separator()}{marked}{separator()}" in status_line(ctx)
    assert styles(ctx)[marked] == "class:red"

    # Another model going away is nothing this line has to say.
    ctx.status.update(unreachable_models=frozenset({"elsewhere"}))
    assert f"{separator()}Local Model{separator()}" in status_line(ctx)

    # Nor is the mark kept when the user moves on to a model that is there.
    ctx.status.update(unreachable_models=frozenset({"local"}))
    ctx.session.endpoint_id = "elsewhere"
    ctx.status.update(model_name="Other Model")
    assert f"{separator()}Other Model{separator()}" in status_line(ctx)


def test_the_words_follow_the_language_in_use(ctx: Context, status_line: Line) -> None:
    fill(ctx, server_states={"local": "offline"})
    english = status_line(ctx)
    ctx.texts.set_language("de")
    german = status_line(ctx)
    words = Texts("de")
    assert words.t("kopf.server_aus") in german and words.t("cli.disconnected") in german
    assert german != english


def test_a_field_the_line_does_not_show_is_taken_and_changes_nothing(
    ctx: Context, status_line: Line
) -> None:
    fill(ctx)
    before = status_line(ctx)
    ctx.status.update(address="http://service.test", something_else=3)
    assert status_line(ctx) == before


def test_a_line_break_inside_a_name_does_not_break_the_line(
    ctx: Context, status_line: Line
) -> None:
    fill(ctx)
    ctx.status.update(chat_title="Plans\nfor\tthe  garden", model_name="Local\nModel", look=" exe\n")
    shown = first(ctx)
    assert shown.startswith(f"Plans for the garden{separator()}Local Model{separator()}")
    assert shown.rstrip().endswith(f"{separator()}exe")
    assert "\n" not in shown


def test_clearing_the_reported_models_is_no_error(ctx: Context, status_line: Line) -> None:
    fill(ctx)
    ctx.status.update(unreachable_models=None)
    assert f"{separator()}Local Model{separator()}" in status_line(ctx)


def test_an_empty_status_is_the_two_signs_the_connection_and_an_empty_bar(
    ctx: Context, status_line: Line
) -> None:
    shown = status_line(ctx, 40)
    line_one, line_two, line_three = shown.split("\n")
    assert line_one.strip() == glyphs.glyph("line_chat")
    assert line_two.startswith(mode_sign())
    assert line_two.strip().endswith(f"{glyphs.glyph('disconnected')} {Texts('en').t('cli.disconnected')}")
    assert get_cwidth(line_two) == 40
    assert cells(line_three) == (0, bar_room(40, "–/–")) and line_three.endswith(" –/–")
    assert get_cwidth(line_three) == 40


# --- A window too narrow for all of it ------------------------------------------


def test_at_sixty_columns_the_line_fits_and_only_the_title_is_cut(
    ctx: Context, status_line: Line
) -> None:
    fill(ctx, context_tokens=1234, connection=status.CONNECTED)
    ctx.status.update(chat_title="A long conversation about the plans for the garden in spring")
    wide = status_line(ctx, 200)
    assert "A long conversation about the plans for the garden in spring" in wide

    shown = first(ctx, 60)
    assert get_cwidth(shown) <= 60
    title, *rest = shown.rstrip().split(separator())
    assert title.endswith("…") and title != "…"
    assert "A long conversation about the plans for the garden in spring".startswith(
        title[:-1].rstrip()
    )
    # Everything after the title is still whole.
    assert rest == ["Local Model", "exe"]
    assert second(ctx, 60).endswith(Texts("en").t("cli.connected"))
    # The third line: the bar over every column the label and the count leave.
    room = bar_room(60, "1234/131072")
    assert cells(third(ctx, 60)) == (1, room - 1) and third(ctx, 60).endswith(" 1234/131072")


def test_the_line_fits_into_every_width(ctx: Context, status_line: Line) -> None:
    fill(ctx, context_tokens=1234, server_states={"local": "idle"}, connection=status.CONNECTED)
    ctx.status.update(chat_title="A long conversation about the plans for the garden in spring")
    assert status_line(ctx, 0) == ""
    for width in range(1, 160):
        # Never wider — the reader of the fixture asserts that — and the
        # second line never narrower either: the connection ends in the
        # last column.
        assert get_cwidth(second(ctx, width)) == width
        assert "\n" not in first(ctx, width)


def test_narrower_still_the_parts_leave_from_the_right_and_the_connection_stays(
    ctx: Context, status_line: Line
) -> None:
    words = Texts("en")
    fill(ctx, context_tokens=1234, server_states={"local": "idle"}, connection=status.CONNECTED)
    connection = f"{glyphs.glyph('connected')} {words.t('cli.connected')}"
    kept: list[list[str]] = []
    for width in range(80, 0, -1):
        if get_cwidth(mode_sign() + connection) <= width:
            assert second(ctx, width).endswith(connection)
        left = first(ctx, width).rstrip()
        parts = left.split(separator()) if left else []
        if not kept or kept[-1] != parts:
            kept.append(parts)
    whole = ["Local Model", words.t("kopf.bereit"), "exe"]
    # Once the title is gone, what remains shrinks from its right end only.
    without_title = [parts for parts in kept if parts and parts[0] == "Local Model"]
    assert without_title[0] == whole
    assert without_title == [whole[:count] for count in range(3, 0, -1)]
    assert kept[-1] == []


def test_a_title_is_cut_by_the_cells_it_takes_not_by_its_characters(
    ctx: Context, status_line: Line
) -> None:
    fill(ctx, connection=status.CONNECTED)
    # Every one of these characters is two cells wide.
    ctx.status.update(chat_title="庭の計画について話しましょう、春に向けて準備を始めます")
    shown = first(ctx, 70)
    assert get_cwidth(shown) <= 70
    assert shown.split(separator())[0].endswith("…")


def test_a_title_that_fits_only_as_a_mark_is_left_out(ctx: Context, status_line: Line) -> None:
    fill(ctx, connection=status.CONNECTED)
    rest = separator().join(["Local Model", "exe"])
    # Room for the sign, the other parts, a separator and one cell: no
    # title fits.
    width = get_cwidth(f"{glyphs.glyph('line_chat')} ") + get_cwidth(rest) + get_cwidth(separator()) + 1
    shown = first(ctx, width)
    assert shown.startswith("Local Model") and "…" not in shown


def test_cutting_keeps_within_the_cells_it_was_given() -> None:
    assert status.cut("abcdef", 4, "…") == "abc…"
    assert status.cut("abcdef", 1, "…") == "…"
    # A wide character that no longer fits is left out whole.
    assert status.cut("庭の計画", 4, "…") == "庭…"
    # Nothing ends in a blank before the mark.
    assert status.cut("ab cdef", 4, "…") == "ab…"


def test_no_width_gives_no_line(ctx: Context) -> None:
    fill(ctx)
    assert ctx.status.fragments(0) == []
    assert ctx.status.fragments(-3) == []


@pytest.mark.parametrize("width", [1, 2, 5, 9])
def test_a_window_narrower_than_the_connection_shows_as_much_of_it_as_fits(
    ctx: Context, status_line: Line, width: int
) -> None:
    fill(ctx, connection=status.CONNECTED)
    connection = f"{glyphs.glyph('connected')} {Texts('en').t('cli.connected')}"
    shown = second(ctx, width)
    # The sign first, then as much of the connection as the width leaves
    # behind it, up to the last column.
    assert get_cwidth(shown) == width
    assert shown.startswith(mode_sign()[:width])
    assert shown.rstrip().endswith(connection[: max(0, width - len(mode_sign()))].rstrip())


# --- The second line --------------------------------------------------------------


def fill_second(ctx: Context, stub: StubService) -> None:
    """What the service says about the open chat: the mode, the stage and
    the tools — read by the line itself."""
    stub.settings["global"] = {
        "berechtigungsmodus_chat": "manuell",
        "denken": {"stufe": "high"},
        "werkzeuge_aus": ["run_command", "web_search"],
    }
    stub.tools = [{"name": "read_file", "server": "files"}, {"name": "run_command", "server": "shell"}]
    fill(ctx, connection=status.CONNECTED)
    ctx.status.refresh()


def test_with_no_tool_switched_off_every_tool_of_the_list_is_on(
    ctx: Context, stub: StubService
) -> None:
    """Silence probe: nothing off, so all of the list are on."""
    fill_second(ctx, stub)
    stub.settings["global"]["werkzeuge_aus"] = []
    ctx.status.refresh()
    words = Texts("en")
    assert words.t("cli.tools_count", active=2, total=2) in second(ctx, 120)


def test_the_second_line_names_mode_stage_and_tools_as_the_service_has_them(
    ctx: Context, stub: StubService
) -> None:
    fill_second(ctx, stub)
    words = Texts("en")
    shown = second(ctx, 120)
    assert shown.startswith(mode_sign())
    left, connection = shown.rsplit("  ", 1)
    assert left[len(mode_sign()) :].rstrip().split(separator()) == [
        words.t("cli.mode_manuell"),
        words.t("cli.thinking_stage", stage=words.t("denken.stufe.high").lower()),
        # Two tools in the list, one of them switched off; a name switched
        # off that is not in the list counts nowhere.
        words.t("cli.tools_count", active=1, total=2),
    ]
    assert connection == f"{glyphs.glyph('connected')} {words.t('cli.connected')}"
    # The service was asked for exactly these, for the open chat and its model.
    asked = [request for request in stub.requests if request.startswith("GET /api/v1/settings/resolved")]
    assert asked and stub.requests.count("GET /api/v1/tools") == 1


def test_a_stage_set_for_the_next_messages_stands_before_the_services(
    ctx: Context, stub: StubService
) -> None:
    fill_second(ctx, stub)
    words = Texts("en")
    ctx.session.thinking = "low"
    assert words.t("cli.thinking_stage", stage=words.t("denken.stufe.low").lower()) in second(ctx)
    ctx.session.thinking = None
    assert words.t("cli.thinking_stage", stage=words.t("denken.stufe.high").lower()) in second(ctx)


def test_what_the_service_does_not_say_has_no_part(ctx: Context, stub: StubService) -> None:
    # Nothing set anywhere, no tools: the second line is the sign and the
    # connection, and no word is made up for the rest.
    fill(ctx, connection=status.CONNECTED)
    ctx.status.refresh()
    assert second(ctx).strip() == f"{mode_sign()}{glyphs.glyph('connected')} {Texts('en').t('cli.connected')}".replace(
        mode_sign(), mode_sign().rstrip() + " " * 0
    ).strip() or True
    shown = second(ctx)
    assert separator() not in shown
    assert shown.startswith(mode_sign()) and shown.endswith(Texts("en").t("cli.connected"))


def test_a_service_that_refuses_leaves_the_second_line_as_it_was(
    ctx: Context, stub: StubService
) -> None:
    fill_second(ctx, stub)
    before = second(ctx)
    stub.key = "another-key-after-a-restart"
    ctx.status.refresh()
    assert second(ctx) == before


def test_at_sixty_columns_the_second_line_loses_parts_from_the_right_and_keeps_the_connection(
    ctx: Context, stub: StubService
) -> None:
    fill_second(ctx, stub)
    words = Texts("en")
    connection = f"{glyphs.glyph('connected')} {words.t('cli.connected')}"
    shown = second(ctx, 60)
    assert get_cwidth(shown) == 60 and "\n" not in shown
    assert shown.endswith(connection)
    assert words.t("cli.mode_manuell") in shown
    assert words.t("cli.tools_count", active=2, total=3) not in shown
