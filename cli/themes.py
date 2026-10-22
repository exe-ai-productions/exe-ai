"""The looks of the terminal client.

A look is one table of named colours — the same five looks the window has,
each with the colours the window gives it — and a sixth name, ``auto``, that
is the dark one of them or the light one, whichever the machine is set to.
From that table come the styles of both halves of the screen: the history,
where a name is written ``exe.<name>`` in a rich style or markup, and the
fixed block at the bottom, where it is the class ``class:<name>`` of a
prompt_toolkit fragment. So a module that writes a quiet line uses
``muted`` in either half and never names a colour itself.

The styles set only foregrounds; the one place they paint a ground is the
list of completions, which lies over the history and has to cover it. The
terminal's own ground belongs to the look as a whole: at start and on a
switch the terminal is asked to take the look's ground and text colour, and
to draw its cursor in the look's mark colour (below); when the client leaves
it is given its own three back. A terminal that does not take the request
keeps what it has. In the window the terminal lies on the window's own
ground and its ground and text colour are left alone — only the cursor is
asked for, so it has the same colour there as in a terminal; an output that
is no terminal, and one that is to stay without colours, is left alone
altogether.

The program's mark — the big block letters of the head — and the cursor
carry the text colour with a fifth of the look's accent in it, one colour
for both (``mark_colour``). A look without an accent of its own, the first,
keeps both in the text colour.

A terminal that cannot show the full colours gets the nearest ones it has —
both libraries pick them. Where the environment asks for no colours at all,
every style keeps its weight and slant and loses its colour.
"""

from __future__ import annotations

import errno
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TextIO

from prompt_toolkit.styles import Style
from pygments.token import Comment, Keyword, Name, Number, Operator, String, Token
from rich.color import Color
from rich.style import Style as RichStyle
from rich.syntax import ANSISyntaxTheme, SyntaxTheme
from rich.terminal_theme import TerminalTheme
from rich.theme import Theme as RichTheme

from cli import appearance, prefs

# The names every look answers to. The first twelve say what a piece of
# text is; the last five are the parts of the fixed block, set as the class
# of a whole line there.
STYLE_NAMES = (
    "text",
    "muted",
    "rule",
    "line",
    "accent",
    "tool",
    "green",
    "yellow",
    "red",
    "blue",
    "violet",
    "mark",
    "thinking",
    "status",
    "input",
    "prompt",
    "dialog",
)

# The colours every look carries. The first ten are the look itself; the
# last six colour a block of code, which the window also gives colours of
# its own rather than borrowing the ones that say how something stands.
COLOUR_NAMES = (
    "ground",
    "text",
    "muted",
    "line",
    "accent",
    "green",
    "yellow",
    "red",
    "blue",
    "violet",
    "code",
    "keyword",
    "string",
    "comment",
    "number",
    "call",
)

# In front of a name wherever the history uses it, so a look's ``red`` never
# shadows the colour word ``red`` in somebody's markup.
RICH_PREFIX = "exe."

DEFAULT_LOOK = "exe"

# The environment's two ways of asking for a screen without colours.
_NO_COLOUR_VARIABLE = "NO_COLOR"
_PLAIN_TERMINAL = "dumb"

# The mark the window sets in the environment of a client it starts: there
# the terminal lies on the window's ground, and the look leaves it alone.
WINDOW_VARIABLE = "EXE_AI_WINDOW_TERMINAL"

# What asks a terminal to draw its cursor in a colour and to take a ground
# and a text colour, and what gives it its own three back.
_TAKE_CURSOR = "\x1b]12;{colour}\x1b\\"
_TAKE_GROUND = "\x1b]11;{colour}\x1b\\"
_TAKE_TEXT = "\x1b]10;{colour}\x1b\\"
_OWN_CURSOR = "\x1b]112\x1b\\"
_OWN_GROUND = "\x1b]111\x1b\\"
_OWN_TEXT = "\x1b]110\x1b\\"


def colours_enabled() -> bool:
    """Whether the environment lets the client show colours at all."""
    return (
        _NO_COLOUR_VARIABLE not in os.environ and os.environ.get("TERM") != _PLAIN_TERMINAL
    )


@dataclass(frozen=True)
class Theme:
    """One look: its name and the colour behind each colour name. A colour
    the look does not name keeps whatever the terminal itself shows."""

    name: str
    colours: Mapping[str, str] = field(default_factory=dict)

    def _colour(self, colour_name: str) -> str | None:
        """The colour of that name as it may be shown: ``None`` where the
        look names none, or the screen is to stay without colours."""
        return self.colours.get(colour_name) if colours_enabled() else None

    def _paint(self, colour_name: str, *words: str) -> str:
        """A style: that colour as the foreground, plus the given words
        (``bold``, ``italic``, ``underline``). Without a colour, the words
        alone."""
        colour = self._colour(colour_name)
        return " ".join([*([colour] if colour else []), *words])

    def mark_colour(self) -> str | None:
        """The colour of the program's mark and of the cursor: the text
        colour with a fifth of the accent in it. A look that sets things
        apart by brightness alone has no accent to give, and its mark stays
        in the text colour. ``None`` where the look names no text colour."""
        text, accent = self.colours.get("text"), self.colours.get("accent")
        if not text:
            return None
        if not accent or not self._has_accent():
            return text
        return _mixed(accent, text, MARK_ACCENT_SHARE)

    def _has_accent(self) -> bool:
        """Whether the look sets things apart in a colour of its own. One
        whose accent is its text colour sets them apart by brightness
        alone."""
        return self.colours.get("accent") != self.colours.get("text")

    def _mark_style(self) -> str:
        """The style of the mark: its colour, or nothing where the screen is
        to stay without colours."""
        colour = self.mark_colour() if colours_enabled() else None
        return colour or ""

    def styles(self) -> dict[str, str]:
        """The style behind each style name — a string both libraries read
        the same way."""
        return {
            "text": self._paint("text"),
            "muted": self._paint("muted"),
            # The two lines around the input field and the marks between
            # the parts of a status line wear the look's accent, the way the
            # window draws the edge of its chat in it. A look without an
            # accent of its own draws them in its quiet tone: the window
            # draws the edge of that look's fields in a faint share of its
            # text colour.
            "rule": self._paint("accent" if self._has_accent() else "muted"),
            # The look's line colour as it stands.
            "line": self._paint("line"),
            "accent": self._paint("accent"),
            # A tool stands in the text colour: no look has a tone of its own
            # for tools.
            "tool": self._paint("text"),
            "green": self._paint("green"),
            "yellow": self._paint("yellow"),
            "red": self._paint("red"),
            "blue": self._paint("blue"),
            "violet": self._paint("violet"),
            "mark": self._mark_style(),
            "thinking": self._paint("muted"),
            "status": self._paint("muted"),
            "input": self._paint("text"),
            "prompt": self._paint("accent", "bold"),
            "dialog": self._paint("text"),
        }

    def rich_theme(self) -> RichTheme:
        """The look for the history: the named styles, and the styles rich
        writes Markdown in."""
        styles = {RICH_PREFIX + name: style or "none" for name, style in self.styles().items()}
        # The lines of a table, a rule and the bar beside a block of code.
        # A look with an accent of its own keeps its line colour; one
        # without sets things apart by brightness, and its line colour lies
        # on the ground of the window so close that a table stands without a
        # grid: its lines stand in the quiet tone, like those around the
        # input field.
        edge = "line" if self._has_accent() else "muted"
        markdown = {
            "markdown.paragraph": self._paint("text"),
            "markdown.text": self._paint("text"),
            "markdown.em": self._paint("text", "italic"),
            "markdown.emph": self._paint("text", "italic"),
            "markdown.strong": self._paint("text", "bold"),
            "markdown.s": self._paint("muted", "strike"),
            "markdown.code": self._paint("call"),
            "markdown.code_block": self._paint("code"),
            "markdown.block_quote": self._paint("muted", "italic"),
            "markdown.list": self._paint("text"),
            "markdown.item": self._paint("text"),
            "markdown.item.bullet": self._paint("accent", "bold"),
            "markdown.item.number": self._paint("accent"),
            "markdown.hr": self._paint(edge),
            "markdown.h1": self._paint("accent", "bold", "underline"),
            "markdown.h2": self._paint("accent", "bold"),
            "markdown.h3": self._paint("text", "bold"),
            "markdown.h4": self._paint("muted", "bold"),
            "markdown.h5": self._paint("muted", "bold"),
            "markdown.h6": self._paint("muted", "italic"),
            "markdown.link": self._paint("blue"),
            "markdown.link_url": self._paint("blue", "underline"),
            "markdown.kbd": self._paint("text", "bold"),
            "markdown.table.border": self._paint(edge),
            "markdown.table.header": self._paint("text", "bold"),
        }
        styles.update({name: style or "none" for name, style in markdown.items()})
        return RichTheme(styles)

    def prompt_style(self) -> Style:
        """The look for the fixed block at the bottom."""
        styles = self.styles()
        ground, line, text, muted, accent = (
            self._colour(name) for name in ("ground", "line", "text", "muted", "accent")
        )
        if ground and line and text and muted and accent:
            # The list of completions lies over the history, so it carries a
            # ground of its own: the look's line colour, the chosen row in
            # the accent.
            styles.update(
                {
                    "completion-menu": f"bg:{line} {text}",
                    "completion-menu.completion": f"bg:{line} {text}",
                    "completion-menu.completion.current": f"bg:{accent} {ground} bold noreverse",
                    "completion-menu.meta.completion": f"bg:{line} {muted}",
                    "completion-menu.meta.completion.current": f"bg:{accent} {ground} noreverse",
                    "scrollbar.background": f"bg:{line}",
                    "scrollbar.button": f"bg:{muted}",
                }
            )
        return Style.from_dict(styles)

    def syntax_theme(self) -> SyntaxTheme:
        """The colours of a block of code. No ground is painted behind it."""

        def ink(colour_name: str, *, italic: bool = False) -> RichStyle:
            return RichStyle(color=self._colour(colour_name), italic=italic or None)

        return ANSISyntaxTheme(
            {
                Token: ink("code"),
                Comment: ink("comment", italic=True),
                Keyword: ink("keyword"),
                Operator.Word: ink("keyword"),
                Name.Tag: ink("keyword"),
                String: ink("string"),
                Number: ink("number"),
                Name.Function: ink("call"),
                Name.Class: ink("call"),
                Name.Builtin: ink("call"),
                Name.Decorator: ink("call"),
                Name.Attribute: ink("call"),
            }
        )

    def ground(self) -> str:
        """What asks a terminal to take this look's ground and text colour
        and to draw its cursor in the mark colour — an empty string for a
        look that names no ground or no text colour."""
        ground, text = self.colours.get("ground"), self.colours.get("text")
        if not ground or not text:
            return ""
        return (
            self.cursor()
            + _TAKE_GROUND.format(colour=ground)
            + _TAKE_TEXT.format(colour=text)
        )

    def cursor(self) -> str:
        """What asks a terminal to draw its cursor in the mark colour — the
        one request the window's tab takes from the look — or an empty
        string for a look that names no text colour."""
        colour = self.mark_colour()
        return _TAKE_CURSOR.format(colour=colour) if colour else ""

    def terminal_theme(self) -> TerminalTheme | None:
        """The terminal a recording of this look is shown on — the look's
        ground, its text colour and its sixteen colours — or ``None`` for
        the one rich brings along, where the look names no ground or the
        screen is to stay without colours."""
        # Black, red, green, yellow, blue, magenta, cyan, white.
        sixteen = ("line", "red", "green", "yellow", "blue", "violet", "call", "text")
        if not colours_enabled():
            return None
        if any(name not in self.colours for name in ("ground", "text", *sixteen)):
            return None

        def rgb(colour_name: str) -> tuple[int, int, int]:
            red, green, blue = Color.parse(self.colours[colour_name]).get_truecolor()
            return (red, green, blue)

        colours = [rgb(name) for name in sixteen]
        return TerminalTheme(rgb("ground"), rgb("text"), colours, colours)


# How much of the text colour the quiet tone keeps; the rest is the ground.
_QUIET_SHARE = 0.62

# How much of the accent the program's mark and the cursor carry; the rest is
# the text colour.
MARK_ACCENT_SHARE = 0.2


def _mixed(colour: str, other: str, share: float) -> str:
    """``share`` of ``colour`` and the rest of ``other``, channel by channel."""
    first = Color.parse(colour).get_truecolor()
    second = Color.parse(other).get_truecolor()
    channels = (round(a * share + b * (1 - share)) for a, b in zip(first, second, strict=True))
    return "#" + "".join(f"{channel:02x}" for channel in channels)


# The least contrast a text colour has against the ground in a light look
# (WCAG 1.4.3, normal text), and how finely the share of the text colour that
# gets a tone there is searched for.
READABLE_CONTRAST = 4.5
_READABLE_STEPS = 256

# What a light look leaves as it is: the ground is no text, and the line is
# drawn as a character that is only to show, not to be read.
_NOT_READ = ("ground", "line")


def _luminance(colour: str) -> float:
    """The relative luminance of a colour, as WCAG defines it."""

    def linear(channel: int) -> float:
        share = channel / 255
        return share / 12.92 if share <= 0.03928 else ((share + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in Color.parse(colour).get_truecolor())
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(colour: str, ground: str) -> float:
    """The contrast ratio of two colours, from 1 for the same one to 21."""
    lighter, darker = sorted((_luminance(colour), _luminance(ground)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _readable(colour: str, text: str, ground: str) -> str:
    """The colour itself where it reads against the ground, else with the
    smallest share of the text colour in it that makes it read. The text
    colour is the end of the search: a look whose text does not read has no
    tone that does."""
    for step in range(_READABLE_STEPS + 1):
        mixed = colour if step == 0 else _mixed(text, colour, step / _READABLE_STEPS)
        if contrast(mixed, ground) >= READABLE_CONTRAST:
            return mixed
    return text


def _look(
    name: str,
    ground: str,
    text: str,
    line: str,
    accent: str | None,
    *values: str,
    readable: bool = False,
) -> Theme:
    # The quiet tone is not a colour of its own: like the window's reading
    # beside a name, it is the text colour taken back towards the ground. A
    # look's second ink stands too close to the first to read as quiet in a
    # terminal, where no surface sets the two apart.
    muted = _mixed(text, ground, _QUIET_SHARE)
    # A look that names no accent sets things apart in its text colour.
    named = (ground, text, muted, line, accent or text, *values)
    colours = dict(zip(COLOUR_NAMES, named, strict=True))
    if readable:
        # A light look puts its tones on a ground that is nearly as bright as
        # they are: each one that falls short is taken towards the text.
        colours = {
            colour_name: colour
            if colour_name in _NOT_READ
            else _readable(colour, text, ground)
            for colour_name, colour in colours.items()
        }
    return Theme(name, colours)


# The five looks, in the colours the window's stylesheet gives each of them:
# ground, text, line, accent, green, yellow, red, blue, violet, then
# the six of a block of code. A light look marked ``readable`` draws each of
# these tones, and the quiet one, in the least of its text colour that makes
# it read against the ground: the table holds the colours of the stylesheet,
# the look the ones that are drawn. As text the four state colours stand in the
# form the stylesheet keeps for text; the line is its stronger one, the only
# one that still shows when it is drawn as a character; the accent is the
# colour the look draws the edge of its chat or of its fields in. The first
# look has no such colour and names none: it sets things apart by
# brightness, and its green says only how something stands.
_THEMES: dict[str, Theme] = {
    theme.name: theme
    for theme in (
        _look(
            "exe",
            "#1c1c1a", "#ecebe6", "#3b3a36", None,
            "#6b8e6f", "#c9a227", "#bb655d", "#5b8dbe", "#9b8ac4",
            "#dedbd3", "#d9a05b", "#8fc099", "#8a877c", "#c1a3d8", "#8ab4d8",
        ),
        _look(
            "darkmatter",
            "#0b0817", "#e9e6f7", "#443a76", "#b18cff",
            "#7ea885", "#d6b13f", "#e0687e", "#8bb8ff", "#b18cff",
            "#e3def5", "#e0a86a", "#8fd6a8", "#8781a8", "#c9a3f0", "#8ab8f5",
        ),
        _look(
            "moune",
            "#e0e7d6", "#1f2d22", "#b1a687", "#688a57",
            "#4f7d57", "#725c16", "#95453f", "#3e6183", "#8d78bd",
            "#2a2620", "#8a5a2b", "#3f6b4a", "#7d7a71", "#7a5c8f", "#2f5d80",
            readable=True,
        ),
        _look(
            "heaven",
            "#e8eef8", "#22304a", "#a2b7d8", "#517bba",
            "#4f7357", "#81681e", "#ac5048", "#3f6da5", "#7f68b8",
            "#253248", "#8a5a2b", "#3f6b4a", "#78809a", "#7a5c8f", "#2f5d80",
            readable=True,
        ),
        _look(
            "pearl",
            "#e0d7c3", "#201c14", "#b1a687", "#928057",
            "#4b644e", "#725c16", "#95453f", "#3e6183", "#846db8",
            "#2a2620", "#8a5a2b", "#3f6b4a", "#7d7a71", "#7a5c8f", "#2f5d80",
            readable=True,
        ),
        _look(
            "snow",
            "#eaeaea", "#1c1c1c", "#b8b8b8", "#828282",
            "#4b644e", "#725c16", "#95453f", "#3e6183", "#846db8",
            "#272727", "#8a5a2b", "#3f6b4a", "#7a7a7a", "#7a5c8f", "#2f5d80",
            readable=True,
        ),
    )
}


# The look that follows the machine, and the two it is: the dark one where
# the machine is set to dark, the light one where it is set to light.
AUTO_LOOK = "auto"
_AUTO_DARK = replace(_THEMES["exe"], name=AUTO_LOOK)
_AUTO_LIGHT = replace(_THEMES["snow"], name=AUTO_LOOK)

# The look in use. One screen per process, so one look is all there is to
# hold. Held as the look itself: which of its two the one that follows the
# machine is, was decided when it was made the look in use.
_current = _THEMES[DEFAULT_LOOK]


def available() -> tuple[str, ...]:
    """The names of the looks: the one that follows the machine, then the
    five with colours of their own."""
    return (AUTO_LOOK, *_THEMES)


def get(name: str) -> Theme:
    """The look of that name; ``KeyError`` for a name no look has. The one
    that follows the machine is looked up as the machine stands now: the
    light look where it is set to light, the dark one where it is set to
    dark or says nothing."""
    if name == AUTO_LOOK:
        return _AUTO_LIGHT if appearance.machine_is_dark() is False else _AUTO_DARK
    return _THEMES[name]


def current() -> Theme:
    """The look in use. The screen asks this every time it draws, so a
    switch shows at once."""
    return _current


def _shows_colours(out: TextIO) -> bool:
    """Whether ``out`` is a terminal and the screen may show colours."""
    is_terminal = getattr(out, "isatty", None)
    return colours_enabled() and is_terminal is not None and bool(is_terminal())


def owns_ground(out: TextIO | None = None) -> bool:
    """Whether the look paints the ground of ``out`` (the standard output
    where none is named): not in the window, not where the screen is to
    stay without colours, and not where the output is no terminal."""
    out = sys.stdout if out is None else out
    return _shows_colours(out) and WINDOW_VARIABLE not in os.environ


def _owns_cursor_only(out: TextIO) -> bool:
    """Whether ``out`` is the window's terminal, where the look asks for the
    cursor and nothing else."""
    return _shows_colours(out) and WINDOW_VARIABLE in os.environ


def paint(out: TextIO | None = None) -> None:
    """Asks the terminal behind ``out`` to take the ground and text colour
    of the look in use and to draw its cursor in the mark colour — where the
    look owns the ground; in the window's tab only the cursor."""
    out = sys.stdout if out is None else out
    if owns_ground(out):
        sequence = current().ground()
    elif _owns_cursor_only(out):
        sequence = current().cursor()
    else:
        return
    if sequence:
        out.write(sequence)
        out.flush()


def unpaint(out: TextIO | None = None) -> None:
    """Gives the terminal behind ``out`` its own cursor colour, ground and
    text colour back — where the look owns the ground, which is where they
    were taken; in the window's tab the cursor colour. A terminal that is
    gone has nothing left to give back."""
    out = sys.stdout if out is None else out
    if owns_ground(out):
        sequence = _OWN_CURSOR + _OWN_GROUND + _OWN_TEXT
    elif _owns_cursor_only(out):
        sequence = _OWN_CURSOR
    else:
        return
    try:
        out.write(sequence)
        out.flush()
    except OSError as error:
        if not went_away(error):
            raise


def went_away(error: OSError) -> bool:
    """Whether writing failed because the terminal is gone: its window was
    closed, or the connection it came over ended."""
    return error.errno == errno.EIO


def set_look(name: str, *, remember: bool = False, prefs_path: Path | None = None) -> Theme:
    """Makes that look the one in use; ``KeyError`` for a name no look has —
    the look in use stays, and nothing is written. The one that follows the
    machine becomes what the machine is set to at this moment, and stays
    that until it is made the look in use again.

    With ``remember`` the choice is also written to the file the client
    keeps its choices in (``prefs_path``, or the user's own), so the next
    start comes up in it. A start that only applies what it read there
    leaves ``remember`` off. Where the file cannot be written, the
    ``OSError`` is raised after the switch: the look holds for this run.
    """
    global _current
    theme = get(name)
    _current = theme
    if remember:
        prefs.remember(prefs_path, look=name)
    return theme
