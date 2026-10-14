"""Writes the history: the head, the user's lines, an answer as it streams in.

Text that has scrolled up cannot be taken back, so nothing is written
before it is finished. An answer goes out block by block, a block being
whatever a blank line or the closing fence of a code block ends; what is
still growing waits, and the end of the answer writes the rest. A tool gets
its one line when it has come back, with how long it took and how it went.
What is still going on — the thinking, the tool that runs — stands in the
line above the status line, which can be drawn again.

Everything of the conversation hangs in two columns: a narrow one for the
sign that says whose line it is, and the text beside it.
"""

from __future__ import annotations

import json
import math
import shutil
import textwrap
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from rich import box
from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, Group, JustifyMethod, RenderableType, RenderResult
from rich.markdown import (
    BlockQuote,
    CodeBlock,
    Heading,
    HorizontalRule,
    ImageItem,
    ListItem,
    Markdown,
    MarkdownElement,
    TableElement,
)
from rich.rule import Rule
from rich.segment import Segment
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from cli import glyphs, prefs, themes, wordmark
from cli.client import ServiceError
from cli.interfaces import Context, Event, Renderer

# How many lines of a tool's result stand below its line.
RESULT_LINES = 3

# How many lines of the thinking stand in the line above the status line
# while it goes on.
THINKING_LINES = 3

# The two characters a fenced code block may be opened with.
_FENCE_CHARACTERS = ("`", "~")

# What a block of the history is, for the space between two of them.
_ANSWER = "answer"
_USER = "user"
_LINE = "line"

# The width a line of thinking is broken at where the terminal's is unknown.
_FALLBACK_COLUMNS = 80

# From how many columns the head shows the wordmark as block letters; below
# that, the name in one line. And how many empty columns stand to the left
# of the letters.
WORDMARK_FROM = 60
WORDMARK_MARGIN = 2

# How many of the chats the head lists, newest first.
RECENT_CHATS = 3

# The number the tip about opening a chat names.
TIP_CHAT_NUMBER = 2

# How a chat's time of last change is written, in the head and in a list.
_TIME_FORMAT = "%Y-%m-%d %H:%M"

# The sources of a speed reading that measured it; any other only counted
# pieces, and a piece is no token.
_MEASURED_SPEED = ("server", "gemessen")

# The clock the durations are read from.
_now = time.monotonic

# The characters that steer a terminal instead of showing in it: everything
# below the space except the line break and the tab, the delete character
# and the second set of control characters above it. Text that came from a
# model or a tool is written without them — otherwise a page somebody
# fetched could clear the screen or recolour it.
_STEERING = dict.fromkeys(
    [code for code in range(0x20) if code not in (0x09, 0x0A)] + list(range(0x7F, 0xA0))
)


def show_head(ctx: Context) -> None:
    """Writes the head as the client stands right now: with the version the
    service named at start and the address it is reached at."""
    ctx.renderer.header(str(ctx.session.health.get("version") or ""), ctx.client.address)


def build_renderer(ctx: Context) -> Renderer:
    # Whether the icon-font signs are wanted is one of the remembered
    # choices; it is read here, once per start.
    glyphs.use_nerd(prefs.load(ctx.prefs_path).get("nerd") is True)
    return HistoryRenderer(ctx)


def _fence(stripped: str) -> tuple[str, int] | None:
    """The fence a line opens or closes — its character and how many of them
    it starts with — or ``None`` for a line that is no fence."""
    character = stripped[:1]
    if character not in _FENCE_CHARACTERS:
        return None
    length = len(stripped) - len(stripped.lstrip(character))
    if length < 3:
        return None
    if character == "`" and "`" in stripped[length:]:
        # Backticks further on in the line make it a piece of inline code.
        return None
    return (character, length)


def split_blocks(text: str) -> tuple[list[str], str]:
    """Cuts what has arrived so far into the blocks that are finished and
    the rest that is still growing.

    A blank line ends a block. Inside a fenced code block it ends nothing:
    the block runs on to its closing fence and is finished with it — a line
    of nothing but the opening character, at least as many as opened it. A
    line without its line break is still being written and stays in the rest.
    """
    blocks: list[str] = []
    current: list[str] = []
    fence: tuple[str, int] | None = None
    position = 0
    finished = 0
    for line in text.splitlines(keepends=True):
        if not line.endswith("\n"):
            break
        position += len(line)
        stripped = line.strip()
        marker = _fence(stripped)
        if fence is not None:
            current.append(line)
            closes = (
                marker is not None
                and marker[0] == fence[0]
                and marker[1] >= fence[1]
                and not stripped.strip(fence[0])
            )
            if closes:
                fence = None
                blocks.append("".join(current))
                current = []
                finished = position
        elif marker is not None:
            fence = marker
            current.append(line)
        elif stripped:
            current.append(line)
        else:
            if current:
                blocks.append("".join(current))
                current = []
            finished = position
    return blocks, text[finished:]


def clock(seconds: float) -> str:
    """A duration as ``m:ss``. What is no duration at all reads as none."""
    whole = max(0, int(seconds)) if math.isfinite(seconds) else 0
    return f"{whole // 60}:{whole % 60:02d}"


def _number(value: Any) -> float | None:
    """``value`` if it is a number one can reckon with, else ``None`` — the
    service's numbers arrive as JSON, which may say anything."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _shown(text: str) -> str:
    """``text`` without the characters that steer a terminal."""
    return text.translate(_STEERING)


def _short(value: Any) -> str:
    """One value on one line, for the end of a tool's line."""
    if isinstance(value, str):
        return " ".join(_shown(value).split())
    return _shown(json.dumps(value, ensure_ascii=False))


def _first_argument(arguments: Any) -> str:
    """The short form of a call's arguments: its first field."""
    if isinstance(arguments, Mapping) and arguments:
        return _short(next(iter(arguments.values())))
    return ""


# --- The two columns ----------------------------------------------------------


def _trimmed(line: list[Segment]) -> list[Segment]:
    """The line without the empty space rich fills it up with at its end —
    space that would wrap into empty lines once the window gets narrower."""
    kept = list(line)
    while kept:
        last = kept[-1]
        if last.control or (last.style is not None and last.style.bgcolor is not None):
            break
        text = last.text.rstrip(" ")
        if text:
            kept[-1] = Segment(text, last.style)
            break
        kept.pop()
    return kept


def _beside(
    console: Console,
    options: ConsoleOptions,
    body: RenderableType,
    first: Segment,
    further: Segment | None = None,
) -> RenderResult:
    """``body`` with ``first`` in front of its first line and ``further`` —
    by default as much empty space — in front of every other one. Empty
    lines above and below the body are left out: the space around a block is
    the history's to give."""
    width = cell_len(first.text)
    further = further or Segment(" " * width)
    inner = options.update(width=max(1, options.max_width - width))
    lines = [_trimmed(line) for line in console.render_lines(body, inner, pad=False)]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    for number, line in enumerate(lines):
        yield first if number == 0 else further
        yield from line
        yield Segment.line()


def _sign_column(console: Console, sign: str, style: str) -> Segment:
    """The narrow column: the sign and one space — or, without a sign, the
    space a sign would take."""
    if not sign:
        return Segment("  ")
    return Segment(sign + " ", console.get_style(style, default="none"))


class Beside:
    """Text in the text column: its sign in front of the first line, and
    every line it wraps into below that line's text, not below the sign."""

    def __init__(self, text: Text, sign: str = "", sign_style: str = "none") -> None:
        self.text = text
        self.sign = sign
        self.sign_style = sign_style

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        column = _sign_column(console, self.sign, self.sign_style)
        yield from _beside(console, options, self.text, column)


class OneLine:
    """Text that is cut at the edge of the window instead of wrapping. The
    console only leaves a text its own way of ending a line when the text
    comes to it inside something else — hence this something."""

    def __init__(self, text: Text) -> None:
        text.no_wrap = True
        text.overflow = glyphs.overflow()
        self.text = text

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield self.text


# --- Markdown in the look's colours and signs ---------------------------------


class _Code(CodeBlock):
    """A block of code in the look's own code colours, with a fine line down
    its side instead of a ground painted behind it."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()
        syntax = Syntax(code, self.lexer_name, theme=themes.current().syntax_theme(), word_wrap=True)
        bar = Segment(glyphs.glyph("gutter") + " ", console.get_style("markdown.hr", default="none"))
        yield from _beside(console, options, syntax, bar, bar)


class _Quote(BlockQuote):
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        bar = Segment(glyphs.glyph("quote") + " ", self.style)
        yield from _beside(console, options, self.elements, bar, bar)


class _Item(ListItem):
    def render_bullet(self, console: Console, options: ConsoleOptions) -> RenderResult:
        style = console.get_style("markdown.item.bullet", default="none")
        yield from _beside(console, options, self.elements, Segment(f" {glyphs.glyph('bullet')} ", style))

    def render_number(
        self, console: Console, options: ConsoleOptions, number: int, last_number: int
    ) -> RenderResult:
        style = console.get_style("markdown.item.number", default="none")
        # As wide as the list's last number, so the items stand in one
        # column. What rich hands over is the number after the last one.
        numeral = f"{number}.".rjust(len(str(last_number - 1)) + 2) + " "
        yield from _beside(console, options, self.elements, Segment(numeral, style))


class _Heading(Heading):
    """Every heading starts at the left edge of the text column."""

    LEVEL_ALIGN: ClassVar[dict[str, JustifyMethod]] = {}


class _Line(HorizontalRule):
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        style = console.get_style("markdown.hr", default="none")
        yield Rule(style=style, characters=glyphs.glyph("rule") or "-")


class _Table(TableElement):
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        table = Table(
            box=box.SIMPLE if glyphs.speaks_unicode() else box.ASCII,
            pad_edge=False,
            style="markdown.table.border",
            show_edge=True,
            collapse_padding=True,
        )
        if self.header is not None and self.header.row is not None:
            for column in self.header.row.cells:
                heading = column.content.copy()
                heading.stylize("markdown.table.header")
                table.add_column(heading)
        if self.body is not None:
            for row in self.body.rows:
                table.add_row(*[cell.content for cell in row.cells])
        yield table


class _Picture(ImageItem):
    """A picture in an answer: the tools' sign for one and its title — the
    picture itself belongs to the window."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        title = self.text or Text(self.destination.strip("/").rsplit("/", 1)[-1])
        yield Text.assemble(glyphs.tool_glyph("draw_image") + " ", title, " ", end="")


class _MarkdownBody:
    """What rich itself would write for a piece of Markdown."""

    def __init__(self, markdown: Markdown) -> None:
        self._markdown = markdown

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        return Markdown.__rich_console__(self._markdown, console, options)


class AnswerBlock(Markdown):
    """One block of an answer, as Markdown, in the text column. The block an
    answer opens with carries the model's sign beside its first line."""

    elements: ClassVar[dict[str, type[MarkdownElement]]] = {
        **Markdown.elements,
        "fence": _Code,
        "code_block": _Code,
        "blockquote_open": _Quote,
        "list_item_open": _Item,
        "heading_open": _Heading,
        "hr": _Line,
        "table_open": _Table,
        "image": _Picture,
    }

    def __init__(self, markup: str, *, opens: bool = False) -> None:
        # A link is written out with its address: not every terminal can
        # make a word clickable, and an address that is not shown is lost.
        super().__init__(markup, hyperlinks=False)
        self.opens = opens

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        sign = glyphs.glyph("assistant") if self.opens else ""
        yield from _beside(
            console, options, _MarkdownBody(self), _sign_column(console, sign, "exe.accent")
        )


# --- The renderer -------------------------------------------------------------


@dataclass
class _Call:
    """A tool that was called and has not come back yet."""

    name: str
    server: str = ""
    arguments: Any = None
    since: float = field(default_factory=lambda: _now())


class Head:
    """The program's mark as the head shows it, decided by the width it is
    drawn into: the block letters, with their margin, where the window is
    wide enough for them and the output carries them; the name in one
    line, in bold, everywhere else. An empty line stands above the mark,
    another between it and the line that says where the client stands."""

    def __init__(self, stand: Text) -> None:
        self._stand = stand

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield Text("")
        # The block letters are Unicode: an output without it gets the
        # name, whatever its width.
        if glyphs.speaks_unicode() and options.max_width >= WORDMARK_FROM:
            margin = " " * WORDMARK_MARGIN
            letters = "\n".join(margin + line for line in wordmark.WORDMARK)
            yield Text(letters, style="exe.text", no_wrap=True, overflow="crop")
        else:
            name = Text(wordmark.WORDMARK_PLAIN, style="exe.text", no_wrap=True)
            name.stylize("bold")
            yield name
        yield Text("")
        yield self._stand


def local_time(stamp: Any) -> str:
    """A time of the service in the clock of this machine."""
    try:
        return datetime.fromisoformat(str(stamp)).astimezone().strftime(_TIME_FORMAT)
    except ValueError:
        return str(stamp or "")


class HistoryRenderer(Renderer):
    """The history in the look's colours: signs, Markdown, one line per tool."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx
        # What of the answer's text is still growing.
        self._answer = ""
        # The thinking of the stretch that is going on, and when it began.
        self._thinking = ""
        self._thinking_since: float | None = None
        # The calls that have not come back, by the id the service gave
        # them — in the order they were made, should two share one.
        self._calls: dict[str, list[_Call]] = {}
        # What was written last, for the space in front of the next block.
        self._last: str | None = None
        # Whether the numbers of this answer have already said it was stopped.
        self._stop_said = False

    def _emit(self, kind: str, *renderables: RenderableType) -> None:
        """Writes one block. Text gets an empty line around it; lines about
        what happened stand close together."""
        speaks = (_ANSWER, _USER)
        if self._last is not None and (kind in speaks or self._last in speaks):
            renderables = (Text(""), *renderables)
        self._last = kind
        self._ctx.screen.print_above(*renderables)

    def _line(self, sign: str, text: str, style: str) -> OneLine:
        """One line in one style — a sign and its words, or words alone —
        that is cut at the edge of the window instead of wrapping."""
        return OneLine(Text(f"{sign} {text}" if sign else text, style=style))

    # --- The client's own lines ---

    def header(self, version: str, address: str) -> None:
        """The head: the mark, where the client stands, the newest chats
        with the number each one can be opened by, and the tips under
        their heading — no list of the commands, that is what /help is for."""
        ctx = self._ctx
        texts = ctx.texts
        separator = glyphs.glyph("separator")
        title = texts.t("cli.titel")

        # Where the client stands: the version, the address, the model the
        # first message goes to — the one chosen, as the status line names
        # it — and how many tools run without asking. A listed model goes
        # by its entry's name. One that is chosen but not listed, because
        # its server does not answer, has no entry here: it goes by the
        # name the status line holds for it.
        standing = [f"{title} {version}" if version else title, address]
        chosen = ctx.session.model()
        model = chosen.get("name") if chosen else ctx.status.model_name()
        if model:
            standing.append(str(model))
        always = self._asked("/permissions/always-allow")
        if isinstance(always, dict):
            standing.append(texts.t("cli.tools_always_allowed", n=len(always)))
        stand = Text(f" {separator} ".join(standing), style="exe.muted", no_wrap=True, overflow=glyphs.overflow())

        shown: list[RenderableType] = [Head(stand), Text("")]
        listed = self._asked("/chats")
        chats = [chat for chat in listed if isinstance(chat, dict)] if isinstance(listed, list) else []
        if isinstance(listed, list):
            # The numbers below are the ones /chats takes from here on, also
            # once the service lists the chats in another order.
            ctx.session.shown_chats = chats
        if chats:
            # The newest first, as the service lists them: the number is the
            # one /chats takes. The title takes the room the window has; in a
            # window too narrow for it, the title alone gives way — cut short
            # at the edge, never wrapped — and the number and the time stay
            # whole beside it.
            rows = Table.grid(padding=(0, 2))
            rows.add_column(no_wrap=True)
            rows.add_column(overflow=glyphs.overflow())
            rows.add_column(no_wrap=True)
            for position, chat in enumerate(chats[:RECENT_CHATS], start=1):
                rows.add_row(
                    Text(str(position), style="exe.accent"),
                    Text(
                        _shown(str(chat.get("title") or "")),
                        style="exe.text",
                        no_wrap=True,
                        overflow=glyphs.overflow(),
                    ),
                    Text(local_time(chat.get("updated_at")), style="exe.muted"),
                )
            shown += [Text(texts.t("cli.recent_chats"), style="exe.muted"), rows, Text("")]
        # The tips, each on a line of its own, under their heading. The one
        # about opening a chat names a number: it stands there only where
        # the list above has a chat of that number.
        tips = ["cli.tip_new", "cli.tip_help"]
        if len(chats[:RECENT_CHATS]) >= TIP_CHAT_NUMBER:
            tips.insert(0, "cli.tip_open")
        shown.append(Text(texts.t("cli.tips_title"), style="exe.muted"))
        # In a group: the console rebuilds a text it is handed on its own
        # into a new one that keeps neither its no_wrap nor its overflow, and
        # a tip wider than the window would run into a second line. A group
        # is drawn line by line, each text as it is.
        shown.append(
            Group(
                *(
                    Text(texts.t(key), style="exe.text", no_wrap=True, overflow=glyphs.overflow())
                    for key in tips
                )
            )
        )
        shown.append(Text(""))
        ctx.screen.print_above(*shown)
        self._last = None

    def _asked(self, path: str) -> Any:
        """What the service answers at ``path`` — nothing where it refuses:
        the head is not worth ending the client over."""
        try:
            return self._ctx.client.get(path)
        except ServiceError:
            return None

    def notice(self, text: str) -> None:
        # The client's own word stands above the input field, not in the
        # history: it is for the moment, and the next line takes it away.
        self._ctx.screen.set_notice(text)

    def remark(self, text: str) -> None:
        self._emit(_LINE, Text(text, style="exe.muted"))

    def shell_line(self, text: str) -> None:
        # Typed while an answer runs, the line stands below what of the
        # answer had arrived, not inside it. Read as a terminal reads it:
        # the colours a command prints stay, every other control sequence
        # goes.
        self._close_open()
        self._emit(_LINE, Text.from_ansi(text, style="exe.text"))

    def error(self, text: str) -> None:
        # An error in the middle of an answer stands below what had arrived.
        self._close_open()
        words = Text(_shown(text), style="exe.red")
        self._emit(_LINE, Beside(words, glyphs.glyph("error"), "exe.red"))

    def user_message(self, text: str) -> None:
        words = Text(_shown(text), style="exe.text")
        self._emit(_USER, Beside(words, glyphs.glyph("user"), "exe.prompt"))

    # --- One answer ---

    def start(self, event: Event) -> None:
        self._answer = ""
        self._thinking = ""
        self._thinking_since = None
        self._calls.clear()
        self._stop_said = False

    def _close_open(self) -> None:
        """Whatever of the answer is still held back is written, in the
        order it came: the thinking, the calls that never came back, the
        rest of the text."""
        self._close_thinking()
        self._close_calls()
        self._flush_answer()

    # Thinking

    def reasoning(self, text: str) -> None:
        if self._thinking_since is None:
            self._thinking_since = since = _now()
            self._thinking = ""
            # While it goes on, the thinking stands where it can be drawn
            # again: beside the spinner, cut to its last lines.
            self._ctx.screen.set_activity(lambda: self._thinking_now(since))
        self._thinking += _shown(text)

    def _thinking_now(self, since: float) -> str:
        """The line beside the spinner while the model thinks: how long it
        has been at it, and below that the last lines of what it thought."""
        if self._thinking_since != since:
            # That stretch of thinking is over, and nothing else has taken
            # the line since: the answer goes on.
            return self._ctx.texts.t("status.erzeugt_antwort")
        head = self._ctx.texts.t(
            "nachricht.gedankengang_laeuft", zeit=clock(_now() - since)
        )
        columns = shutil.get_terminal_size((_FALLBACK_COLUMNS, 24)).columns
        # The spinner and its space stand in front of every line.
        width = max(20, columns - 2)
        # Only the end can show, so the paragraphs are broken into lines
        # from the last one backwards, until there are enough. Each is
        # broken from its own start: a line that is full stays as it is
        # while the next one grows.
        rows: list[str] = []
        for paragraph in reversed(self._thinking.splitlines()):
            rows[:0] = textwrap.wrap(paragraph, width)
            if len(rows) >= THINKING_LINES:
                break
        return "\n".join([head, *rows[-THINKING_LINES:]])

    def _close_thinking(self) -> None:
        """Thinking ended: one quiet line says how long it took."""
        if self._thinking_since is None:
            return
        took = clock(_now() - self._thinking_since)
        self._thinking_since = None
        self._thinking = ""
        self._thought(took)

    def _thought(self, took: str | None) -> None:
        words = self._ctx.texts.t("nachricht.gedankengang")
        if took is not None:
            words += f" {glyphs.glyph('separator')} {took}"
        self._emit(_LINE, self._line(glyphs.glyph("thinking"), words, "exe.muted"))

    # Text

    def content(self, text: str) -> None:
        self._close_thinking()
        self._close_calls()
        self._answer += _shown(text)
        blocks, self._answer = split_blocks(self._answer)
        for block in blocks:
            self._block(block)

    def _block(self, markup: str) -> None:
        self._emit(_ANSWER, AnswerBlock(markup, opens=self._last != _ANSWER))

    def _flush_answer(self) -> None:
        rest, self._answer = self._answer, ""
        if rest.strip():
            self._block(rest)

    # Tools

    def tool_call(self, event: Event) -> None:
        self._close_thinking()
        self._flush_answer()
        name = str(event.get("name") or "")
        call = _Call(name, str(event.get("server") or ""), event.get("argumente"))
        self._calls.setdefault(str(event.get("aufruf_id") or name), []).append(call)
        # The call gets its line when it has come back. Until then it
        # stands beside the spinner, with what it was called with below it.
        self._ctx.screen.set_activity(lambda: self._running(call))

    def _running(self, call: _Call) -> str:
        running = self._ctx.texts.t("werkzeug.laeuft", name=call.name)
        lines = [f"{running} {clock(_now() - call.since)}"]
        argument = _first_argument(call.arguments)
        if argument:
            lines.append(argument)
        return "\n".join(lines)

    def tool_result(self, event: Event) -> None:
        name = str(event.get("name") or "")
        key = str(event.get("aufruf_id") or name)
        waiting = self._calls.get(key)
        duration = _number(event.get("dauer_sekunden"))
        if waiting:
            call = waiting.pop(0)
            if not waiting:
                del self._calls[key]
            if duration is None:
                duration = _now() - call.since
        else:
            # A result whose call was never announced still gets its line.
            call = _Call(name, str(event.get("server") or ""), event.get("argumente"))
        self._called(
            call,
            duration=duration,
            failed=bool(event.get("fehlgeschlagen")),
            result=str(event.get("text") or ""),
        )

    def _close_calls(self) -> None:
        """The calls that never came back get their line without an end."""
        calls, self._calls = self._calls, {}
        for waiting in calls.values():
            for call in waiting:
                self._called(call, duration=None, failed=None, result="")

    def _called(
        self, call: _Call, *, duration: float | None, failed: bool | None, result: str
    ) -> None:
        """A call's one line — sign, name, server, the short form of its
        arguments, and at the right edge how long it took and how it went —
        with the first lines of its result below. ``failed`` is ``None`` for
        a call that never came back."""
        head = Text(no_wrap=True, overflow=glyphs.overflow())
        head.append(glyphs.tool_glyph(call.name, call.server) + " ", style="exe.tool")
        head.append(_shown(call.name), style="exe.tool")
        if call.server:
            head.append(f" {glyphs.glyph('separator')} {_shown(call.server)}", style="exe.muted")
        argument = _first_argument(call.arguments)
        if argument:
            head.append("  " + argument, style="exe.text")

        tail = Text(no_wrap=True)
        if duration is not None:
            tail.append(clock(duration) + " ", style="exe.muted")
        if failed is None:
            tail.append(glyphs.glyph("waiting"), style="exe.muted")
        elif failed:
            tail.append(glyphs.glyph("error"), style="exe.red")
        else:
            tail.append(glyphs.glyph("ok"), style="exe.green")

        line = Table.grid(expand=True, padding=(0, 1))
        line.add_column(ratio=1, no_wrap=True, overflow=glyphs.overflow())
        line.add_column(justify="right", no_wrap=True)
        line.add_row(head, tail)

        rows = [row.rstrip() for row in _shown(result).splitlines() if row.strip()]
        style = "exe.red" if failed else "exe.muted"
        below: list[RenderableType] = [
            self._line("", "    " + row, style) for row in rows[:RESULT_LINES]
        ]
        if len(rows) > RESULT_LINES:
            more = f"    {glyphs.glyph('more')} {RESULT_LINES}/{len(rows)}"
            below.append(self._line("", more, "exe.muted"))
        self._emit(_LINE, line, *below)

    # The end

    def stats(self, data: Mapping[str, Any]) -> None:
        # The numbers close the answer, so everything of it stands above them.
        self._close_open()
        texts = self._ctx.texts
        parts: list[str] = []
        duration = _number(data.get("dauer_sekunden"))
        if duration is not None:
            parts.append(clock(duration))
        speed = _number(data.get("tokens_pro_sekunde"))
        if speed is not None and data.get("tempo_quelle") in _MEASURED_SPEED:
            parts.append(f"{round(speed)} {texts.t('nachricht.tps')}")
        used = _number(data.get("gesamt_tokens"))
        window = _number((self._ctx.session.model() or {}).get("context_tokens"))
        if used is not None and window:
            parts.append(texts.t("kontext.auslastung", genutzt=round(used), gesamt=round(window)))
        if data.get("abgebrochen"):
            parts.append(texts.t("nachricht.abgebrochen_kurz"))
            self._stop_said = True
        lines: list[RenderableType] = []
        if parts:
            separator = f" {glyphs.glyph('separator')} "
            lines.append(Beside(Text(separator.join(parts), style="exe.muted")))
        lines.extend(self._marks(data))
        if lines:
            self._emit(_LINE, *lines)

    def _marks(self, data: Mapping[str, Any]) -> list[RenderableType]:
        """How the answer ended, where it did not simply end: each mark the
        service set, written out in its own sentence."""
        texts = self._ctx.texts
        sentences: list[str] = []
        # Of the ways an answer can be cut short, the one that explains the
        # most is named — the order the window names them in.
        used_up = data.get("denken_aufgebraucht")
        if data.get("antwortlaenge_zu_gross") is True:
            sentences.append(texts.t("nachricht.antwortlaenge_zu_gross"))
        elif data.get("kontextfenster_voll") is True:
            sentences.append(texts.t("nachricht.kontextfenster_voll"))
        elif isinstance(used_up, str) and used_up:
            sentences.append(texts.t(f"nachricht.{used_up}"))
        elif data.get("anbietergrenze") is True:
            sentences.append(texts.t("nachricht.anbietergrenze"))
        elif data.get("abgeschnitten") is True:
            sentences.append(texts.t("nachricht.abgeschnitten"))
        # This one can stand beside any of the above.
        if data.get("komprimieren_fehlgeschlagen") is True:
            sentences.append(texts.t("nachricht.komprimieren_fehlgeschlagen"))
        sign = glyphs.glyph("warning")
        return [
            Beside(Text(sentence, style="exe.red"), sign, "exe.red") for sentence in sentences
        ]

    def done(self, event: Event) -> None:
        self._close_open()
        if event.get("abgebrochen") and not self._stop_said:
            stopped = self._ctx.texts.t("nachricht.abgebrochen_kurz")
            self._emit(_LINE, Beside(Text(stopped, style="exe.muted")))
        self._stop_said = False

    # --- A chat that already has messages ---

    def stored_message(self, message: Mapping[str, Any]) -> None:
        content = _shown(str(message.get("content") or ""))
        if message.get("role") == "user":
            self.user_message(content)
            return
        if message.get("reasoning"):
            # How long it took is not kept with the message.
            self._thought(None)
        stats = message.get("stats")
        tools = stats.get("werkzeuge") if isinstance(stats, Mapping) else None
        for tool in tools if isinstance(tools, list) else []:
            if not isinstance(tool, Mapping):
                continue
            self._called(
                _Call(str(tool.get("name") or ""), str(tool.get("server") or ""), tool.get("argumente")),
                duration=_number(tool.get("dauer_sekunden")),
                failed=bool(tool.get("fehlgeschlagen")),
                result=str(tool.get("ergebnis") or ""),
            )
        if content.strip():
            self._block(content)
