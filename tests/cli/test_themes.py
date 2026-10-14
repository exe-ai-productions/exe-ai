"""The five looks: every one carries every colour, builds the styles of both
halves of the screen, is switched at once, remembered on request, paints
the terminal's ground and its cursor for as long as the client runs — and
shows no colour where the environment asks for none. The first of them has
no accent of its own. A sixth name follows the machine: it is the dark look
or the light one, as the machine was set when it was chosen."""

from __future__ import annotations

import io
import plistlib
import sys
import threading
from pathlib import Path

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console
from rich.style import Style

from cli import appearance, prefs, themes
from cli.client import KEY_HEADER
from cli.main import main

LOOKS = ("exe", "darkmatter", "moune", "heaven", "pearl")
# The one that follows the machine, and the two it can be.
AUTO, AUTO_DARK, AUTO_LIGHT = "auto", "exe", "pearl"
# The accent of each look that has one of its own, and the three colours
# that say how something stands in the look that has none.
ACCENTS = {"darkmatter": "#b18cff", "moune": "#688a57", "heaven": "#517bba", "pearl": "#928057"}
STATES_OF_EXE = {"green": "#6b8e6f", "yellow": "#c9a227", "red": "#bb655d"}
# Two Markdown styles of rich's that no look touches: nothing is written in them.
RICHS_OWN = ("markdown.h1.border", "markdown.h7")
KEY = "key-of-this-run"
PAGE = f'<html><head><script>window.__SITZUNGSSCHLUESSEL__="{KEY}";</script></head></html>'
ENTER = "\r"
ESCAPE = "\x1b"

# If a run never leaves by itself, the input is closed after this many
# seconds: the test then fails on what it asserts instead of hanging.
SAFETY_NET_SECONDS = 20


@pytest.fixture(autouse=True)
def the_default_look_and_colours(monkeypatch):
    # Whatever the machine the tests run on asks for, a test starts with
    # colours on and says itself when it wants them off.
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv(themes.WINDOW_VARIABLE, raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    yield
    themes.set_look(themes.DEFAULT_LOOK)


class Terminal(io.StringIO):
    """Stands in for the standard output of a terminal: what is written is
    kept, and it says it is a terminal."""

    def isatty(self) -> bool:
        return True


# What gives a terminal its own cursor colour, ground and text colour back.
OWN_CURSOR_BACK = f"{ESCAPE}]112{ESCAPE}\\"
OWN_GROUND_BACK = f"{OWN_CURSOR_BACK}{ESCAPE}]111{ESCAPE}\\{ESCAPE}]110{ESCAPE}\\"


def service(request: httpx.Request) -> httpx.Response:
    """The addresses a start talks to."""
    path = request.url.path
    if path == "/app/":
        return httpx.Response(200, text=PAGE)
    if request.headers.get(KEY_HEADER) != KEY:
        return httpx.Response(401, json={"detail": "Invalid or missing session key"})
    if path == "/api/v1/health":
        return httpx.Response(200, json={"status": "ok", "version": "9.8.7"})
    if path == "/api/v1/models":
        return httpx.Response(200, json=[{"id": "local", "name": "Local Model", "erreichbar": True}])
    if path == "/api/v1/chats" and request.method == "POST":
        return httpx.Response(201, json={"id": "chat-1", "title": "A fresh chat"})
    return httpx.Response(404, json={"detail": "No such address"})


def start(*arguments: str, prefs_path: Path) -> int:
    """Starts the whole client, lets it leave at once and returns its exit code."""
    with create_pipe_input() as pipe:
        pipe.send_text("/quit" + ENTER)
        safety_net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        safety_net.start()
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                return main(
                    ["--url", "http://service.test", "--lang", "en", *arguments],
                    http=httpx.Client(transport=httpx.MockTransport(service)),
                    prefs_path=prefs_path,
                )
        finally:
            safety_net.cancel()


def written(theme: themes.Theme) -> str:
    """What a terminal that shows every colour is sent when lines in the
    look's accent and in its tool colour are written."""
    sent = io.StringIO()
    console = Console(
        file=sent,
        force_terminal=True,
        color_system="truecolor",
        no_color=False,
        legacy_windows=False,
    )
    console.push_theme(theme.rich_theme())
    console.print("accent", style="exe.accent")
    console.print("tool", style="exe.tool")
    return sent.getvalue()


def own_styles(theme: themes.Theme) -> dict[str, Style]:
    """The styles the look itself sets for the history — its named ones and
    the ones Markdown is written in — without the ones rich brings along."""
    return {
        name: style
        for name, style in theme.rich_theme().styles.items()
        if name.startswith((themes.RICH_PREFIX, "markdown.")) and name not in RICHS_OWN
    }


def machine(monkeypatch: pytest.MonkeyPatch, dark: bool | None) -> None:
    """Makes the machine say dark, light or — with ``None`` — nothing."""
    monkeypatch.setattr(appearance, "machine_is_dark", lambda: dark)


def colour_of(style: str) -> str:
    """The colour a style string names, as the looks write it."""
    return next((word for word in style.split() if word.startswith("#")), "")


def test_the_look_that_follows_the_machine_comes_first_and_the_default_is_still_exe():
    assert themes.available() == (AUTO, *LOOKS)
    assert themes.DEFAULT_LOOK == "exe"
    assert themes.current().name == "exe"


@pytest.mark.parametrize("name", LOOKS)
def test_every_look_carries_every_colour_and_builds_both_styles(name):
    theme = themes.get(name)
    assert theme.name == name
    assert set(theme.colours) == set(themes.COLOUR_NAMES)
    for colour in theme.colours.values():
        assert len(colour) == 7 and colour.startswith("#") and int(colour[1:], 16) >= 0

    history = theme.rich_theme()
    fixed_block = theme.prompt_style()
    for style_name in themes.STYLE_NAMES:
        assert themes.RICH_PREFIX + style_name in history.styles
        # Every name is a colour in both halves of the screen.
        assert history.styles[themes.RICH_PREFIX + style_name].color is not None
        assert fixed_block.get_attrs_for_style_str(f"class:{style_name}").color


@pytest.mark.parametrize("name", LOOKS)
def test_a_look_paints_no_ground_into_the_history(name):
    # Only foregrounds: the terminal keeps the ground it has.
    styles = own_styles(themes.get(name))
    assert len(styles) >= len(themes.STYLE_NAMES) + 20
    for style_name, style in styles.items():
        assert style.color is not None and style.bgcolor is None, style_name


@pytest.mark.parametrize("name", LOOKS)
def test_the_context_bar_has_four_colours_of_its_own_in_every_look(name):
    """How full the window is reads off the colour of the used cells, and
    the free ones stand apart from each of the three."""
    colours = themes.get(name).colours
    of_the_bar = [colours[colour] for colour in ("green", "yellow", "red", "muted")]
    assert len(set(of_the_bar)) == 4
    assert colours["ground"] not in of_the_bar


def test_the_looks_differ_in_their_accent():
    assert len({themes.get(name).colours["accent"] for name in LOOKS}) == len(LOOKS)


# --- The look without an accent ---------------------------------------------------


def test_the_look_exe_draws_in_green_only_what_says_how_something_stands():
    theme = themes.get("exe")
    green, text, muted = STATES_OF_EXE["green"], theme.colours["text"], theme.colours["muted"]
    styles = theme.styles()
    # What the other looks draw in their accent stands in the text colour,
    # the lines around the input field in the quiet tone.
    assert colour_of(styles["accent"]) == text
    assert styles["prompt"] == f"{text} bold"
    assert colour_of(styles["rule"]) == muted
    wearing_green = [name for name, style in styles.items() if colour_of(style) == green]
    assert wearing_green == ["green"]
    # Nothing Markdown is written in is green either: headings, bullets
    # and numbers stand in the text colour.
    history = theme.rich_theme().styles
    as_green = Style(color=green).color
    markdown = [name for name in history if name.startswith("markdown.")]
    assert markdown and not [name for name in markdown if history[name].color == as_green]
    for name in ("markdown.h1", "markdown.h2", "markdown.item.bullet", "markdown.item.number"):
        assert history[name].color == Style(color=text).color, name
    # The chosen row of the list of completions lies on the text colour.
    chosen = theme.prompt_style().get_attrs_for_style_str("class:completion-menu.completion.current")
    assert chosen.bgcolor == text[1:] and chosen.color == theme.colours["ground"][1:]


def test_the_look_exe_draws_the_lines_of_the_history_in_the_quiet_tone():
    """A table's border, a rule and the bar beside a block of code stand in
    the quiet tone, where the line colour lies on the ground of the window
    so close that none of them can be seen. The bar of a quote and the
    lines of a code block's gutter keep what they had."""
    theme = themes.get("exe")
    history = theme.rich_theme().styles
    quiet = Style(color=theme.colours["muted"]).color
    assert history["markdown.hr"].color == quiet
    assert history["markdown.table.border"].color == quiet
    assert history["markdown.hr"].color != Style(color=theme.colours["line"]).color
    assert history["markdown.block_quote"].color == quiet
    assert theme.styles()["line"] == theme.colours["line"]


@pytest.mark.parametrize("name", sorted(ACCENTS))
def test_a_look_with_an_accent_keeps_its_line_colour_for_the_lines_of_the_history(name):
    theme = themes.get(name)
    history = theme.rich_theme().styles
    line = Style(color=theme.colours["line"]).color
    assert history["markdown.hr"].color == line
    assert history["markdown.table.border"].color == line


def test_what_says_how_something_stands_keeps_its_colour_in_the_look_exe():
    theme = themes.get("exe")
    for name, colour in STATES_OF_EXE.items():
        assert theme.colours[name] == colour
        assert theme.styles()[name] == colour


@pytest.mark.parametrize("name", sorted(ACCENTS))
def test_a_look_with_an_accent_of_its_own_still_draws_in_it(name):
    theme = themes.get(name)
    accent = ACCENTS[name]
    assert theme.colours["accent"] == accent != theme.colours["text"]
    styles = theme.styles()
    assert styles["accent"] == accent and styles["rule"] == accent
    assert styles["prompt"] == f"{accent} bold"
    history = theme.rich_theme().styles
    for markdown in ("markdown.h1", "markdown.h2", "markdown.item.bullet", "markdown.item.number"):
        assert history[markdown].color == Style(color=accent).color, markdown
    chosen = theme.prompt_style().get_attrs_for_style_str("class:completion-menu.completion.current")
    assert chosen.bgcolor == accent[1:]


def test_a_recording_is_shown_on_the_looks_own_ground():
    theme = themes.get("pearl")
    recording = theme.terminal_theme()
    assert recording is not None
    assert recording.background_color.hex == theme.colours["ground"]
    assert recording.foreground_color.hex == theme.colours["text"]


def test_a_switch_shows_at_once():
    assert themes.set_look("heaven") is themes.get("heaven")
    assert themes.current().name == "heaven"


def test_a_switch_that_is_to_be_remembered_is_written_to_the_file(tmp_path):
    file = tmp_path / "cli.json"
    prefs.save({"language": "de"}, file)
    themes.set_look("moune", remember=True, prefs_path=file)
    assert themes.current().name == "moune"
    # The choice stands beside what was remembered before.
    assert prefs.load(file) == {"look": "moune", "language": "de", "url": None, "keys": None}


def test_a_switch_alone_writes_nothing(tmp_path):
    file = tmp_path / "cli.json"
    themes.set_look("moune", prefs_path=file)
    assert not file.exists()


def test_a_name_no_look_has_is_refused_and_changes_nothing(tmp_path):
    file = tmp_path / "cli.json"
    themes.set_look("heaven", remember=True, prefs_path=file)
    before = file.read_text(encoding="utf-8")
    with pytest.raises(KeyError):
        themes.set_look("neon", remember=True, prefs_path=file)
    assert themes.current().name == "heaven"
    assert file.read_text(encoding="utf-8") == before


def test_a_file_that_cannot_be_written_is_said_after_the_switch(tmp_path):
    in_the_way = tmp_path / "a-file"
    in_the_way.write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        themes.set_look("moune", remember=True, prefs_path=in_the_way / "cli.json")
    assert themes.current().name == "moune"


def test_a_refused_name_does_not_create_the_file(tmp_path):
    file = tmp_path / "cli.json"
    with pytest.raises(KeyError):
        themes.set_look("neon", remember=True, prefs_path=file)
    assert not file.exists()


def test_the_look_named_at_start_is_remembered_and_the_next_start_comes_up_in_it(tmp_path):
    file = tmp_path / "cli.json"
    assert start("--theme", "pearl", prefs_path=file) == 0
    assert themes.current().name == "pearl"
    assert prefs.load(file)["look"] == "pearl"

    themes.set_look("exe")
    assert start(prefs_path=file) == 0
    assert themes.current().name == "pearl"


def test_a_start_without_a_remembered_look_comes_up_in_the_default_one(tmp_path):
    themes.set_look("heaven")
    assert start(prefs_path=tmp_path / "cli.json") == 0
    assert themes.current().name == "exe"


def test_the_full_colours_are_written_where_the_terminal_shows_them():
    red, green, blue = (int(themes.get("exe").colours["accent"][i : i + 2], 16) for i in (1, 3, 5))
    assert f"{ESCAPE}[38;2;{red};{green};{blue}m" in written(themes.get("exe"))


@pytest.mark.parametrize("environment", [{"NO_COLOR": "1"}, {"NO_COLOR": ""}, {"TERM": "dumb"}])
def test_where_no_colours_are_wanted_neither_half_of_the_screen_carries_one(
    environment, monkeypatch
):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert themes.colours_enabled() is False
    for name in LOOKS:
        theme = themes.get(name)
        # Nothing written into a recording carries a colour code …
        assert ESCAPE + "[3" not in written(theme) and "38;" not in written(theme)
        for style_name, style in own_styles(theme).items():
            assert style.color is None and style.bgcolor is None, style_name
        # … and the fixed block has none either, the list of completions included.
        fixed_block = theme.prompt_style()
        for class_name in (*themes.STYLE_NAMES, "completion-menu.completion.current"):
            attrs = fixed_block.get_attrs_for_style_str(f"class:{class_name}")
            assert not attrs.color and not attrs.bgcolor
        assert theme.syntax_theme().get_style_for_token(("Keyword",)).color is None  # type: ignore[arg-type]
        # A recording is not drawn on the look's ground either.
        assert theme.terminal_theme() is None


def test_what_stands_out_keeps_its_weight_without_colours(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    theme = themes.get("exe")
    assert theme.prompt_style().get_attrs_for_style_str("class:prompt").bold
    assert theme.rich_theme().styles["markdown.strong"].bold


def test_a_look_that_names_no_colours_keeps_the_terminals_own():
    bare = themes.Theme("bare")
    assert bare.terminal_theme() is None
    assert all(style.color is None for style in own_styles(bare).values())
    assert not bare.prompt_style().get_attrs_for_style_str("class:accent").color
    assert bare.ground() == ""


# --- The terminal's ground ------------------------------------------------------


@pytest.mark.parametrize("name", LOOKS)
def test_a_look_asks_the_terminal_for_its_ground_its_text_colour_and_a_cursor_in_that_colour(name):
    theme = themes.get(name)
    ground, text = theme.colours["ground"], theme.colours["text"]
    assert theme.ground() == (
        f"{ESCAPE}]12;{text}{ESCAPE}\\{ESCAPE}]11;{ground}{ESCAPE}\\{ESCAPE}]10;{text}{ESCAPE}\\"
    )


def test_the_cursor_takes_the_text_colour_of_every_look_switched_to_and_the_terminals_own_at_the_end(
    monkeypatch,
):
    terminal = Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    for name in ("darkmatter", "pearl"):
        themes.set_look(name)
        themes.paint()
        assert terminal.getvalue().endswith(themes.get(name).ground())
        assert f"{ESCAPE}]12;{themes.get(name).colours['text']}{ESCAPE}\\" in terminal.getvalue()
    assert OWN_CURSOR_BACK not in terminal.getvalue()
    themes.unpaint()
    assert terminal.getvalue().count(OWN_CURSOR_BACK) == 1


def test_at_start_the_terminal_takes_the_looks_ground_and_gets_its_own_back_at_the_end(
    tmp_path, monkeypatch
):
    terminal = Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    assert start("--theme", "moune", prefs_path=tmp_path / "cli.json") == 0
    written = terminal.getvalue()
    taken = themes.get("moune").ground()
    # Before anything else is written, and given back once the client has left.
    assert written.startswith(taken)
    assert written.endswith(OWN_GROUND_BACK)
    assert written.count(taken) == 1 and written.count(OWN_GROUND_BACK) == 1


def test_a_switch_asks_the_terminal_for_the_new_looks_ground(monkeypatch):
    terminal = Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    themes.set_look("pearl")
    themes.paint()
    assert terminal.getvalue() == themes.get("pearl").ground()
    themes.unpaint()
    assert terminal.getvalue().endswith(OWN_GROUND_BACK)


@pytest.mark.parametrize("environment", [{"NO_COLOR": "1"}, {themes.WINDOW_VARIABLE: "1"}])
def test_in_the_window_and_without_colours_the_terminal_keeps_its_ground(
    environment, tmp_path, monkeypatch
):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    terminal = Terminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    assert start("--theme", "moune", prefs_path=tmp_path / "cli.json") == 0
    assert ESCAPE + "]1" not in terminal.getvalue()


def test_an_output_that_is_no_terminal_is_not_painted():
    plain = io.StringIO()
    themes.paint(plain)
    themes.unpaint(plain)
    assert plain.getvalue() == ""
    assert not themes.owns_ground(plain) and themes.owns_ground(Terminal())


# --- The look that follows the machine ---------------------------------------------


@pytest.mark.parametrize(
    ("dark", "like"), [(True, AUTO_DARK), (False, AUTO_LIGHT), (None, AUTO_DARK)]
)
def test_auto_is_the_dark_look_on_a_dark_machine_and_the_light_one_on_a_light_one(
    monkeypatch, dark, like
):
    machine(monkeypatch, dark)
    theme = themes.set_look(AUTO)
    assert themes.current() is theme and theme.name == AUTO
    assert theme.colours == themes.get(like).colours
    assert theme.styles() == themes.get(like).styles()
    assert theme.ground() == themes.get(like).ground()


def test_auto_keeps_its_colours_until_it_is_chosen_again(monkeypatch):
    machine(monkeypatch, True)
    chosen = themes.set_look(AUTO)
    # The machine is switched to light while the client runs.
    machine(monkeypatch, False)
    assert themes.current() is chosen
    assert themes.current().colours == themes.get(AUTO_DARK).colours
    # Chosen again, it is looked up again.
    again = themes.set_look(AUTO)
    assert again is not chosen and again.colours == themes.get(AUTO_LIGHT).colours
    # And where nothing changed, it is the very same look: nothing to redraw.
    assert themes.set_look(AUTO) is again


def test_auto_is_remembered_by_its_own_name_and_looked_up_at_the_next_start(
    tmp_path, monkeypatch
):
    file = tmp_path / "cli.json"
    machine(monkeypatch, True)
    themes.set_look(AUTO, remember=True, prefs_path=file)
    assert prefs.load(file)["look"] == AUTO

    machine(monkeypatch, False)
    themes.set_look("heaven")
    assert start(prefs_path=file) == 0
    assert themes.current().name == AUTO
    assert themes.current().colours == themes.get(AUTO_LIGHT).colours


def test_the_switch_at_start_takes_auto_like_any_other_name_and_it_is_remembered(
    tmp_path, monkeypatch
):
    file = tmp_path / "cli.json"
    machine(monkeypatch, False)
    assert start("--theme", AUTO, prefs_path=file) == 0
    assert themes.current().name == AUTO
    assert themes.current().colours == themes.get(AUTO_LIGHT).colours
    assert prefs.load(file)["look"] == AUTO


def test_the_five_looks_with_colours_of_their_own_do_not_ask_the_machine(monkeypatch):
    def asked() -> bool:
        raise AssertionError("the machine was asked")

    monkeypatch.setattr(appearance, "machine_is_dark", asked)
    for name in LOOKS:
        assert themes.set_look(name) is themes.get(name) and themes.current().name == name


@pytest.mark.parametrize(
    ("entries", "like"),
    [({"AppleInterfaceStyle": "Dark"}, AUTO_DARK), ({"AppleLanguages": ["en"]}, AUTO_LIGHT)],
)
def test_auto_follows_what_the_preferences_of_a_mac_say(tmp_path, monkeypatch, entries, like):
    file = tmp_path / "Library" / "Preferences" / ".GlobalPreferences.plist"
    file.parent.mkdir(parents=True)
    with file.open("wb") as written_to:
        plistlib.dump(entries, written_to)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert themes.set_look(AUTO).colours == themes.get(like).colours


def test_on_a_machine_that_says_nothing_auto_is_the_dark_look(tmp_path, monkeypatch):
    # A Mac without preferences, and a system that has no such setting.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert themes.set_look(AUTO).colours == themes.get(AUTO_DARK).colours
    monkeypatch.setattr(sys, "platform", "linux")
    assert themes.set_look(AUTO).colours == themes.get(AUTO_DARK).colours
