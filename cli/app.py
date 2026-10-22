"""The screen: the history above, the fixed block below it, on the whole
window.

The client runs on a full screen, as every program that keeps a field for
what the user types does. Above stands the field of the history, which alone
scrolls — on the mouse wheel and on page up and page down. Below it stands
the block that never moves: the line that says what is going on, a rule, the
input field, a rule, and the three status lines. The input field never
moves either; it only grows with what is typed, line by line, up to its
limit, and takes no room beyond that.

The history begins at the top of its field. Where it is shorter than the
field, the rest stays empty: no blank line is written to fill it, and
nothing grows by itself. What is written follows the end of the history for
as long as the field has not been scrolled; a field scrolled up stays where
it is. Where the block grows — a list of completions, a question, one more
line of input — the field gives it the rows. On leaving, the terminal gets
back the screen it had before; the history is not left behind in it.

Nothing the user sends is handled on the screen's own thread. A line goes
into a queue, a worker takes one after the other, and the screen stays
responsive whatever the service takes its time over.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
import io
import queue
import re
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, TypeVar

from prompt_toolkit.application import Application, run_in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, ThreadedCompleter, merge_completers
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples, to_formatted_text
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding import (
    ConditionalKeyBindings,
    KeyBindings,
    KeyBindingsBase,
    KeyPressEvent,
    merge_key_bindings,
)
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Container,
    HSplit,
    Window,
    to_container,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.screen import Char
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.styles import BaseStyle, DynamicStyle
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.widgets import TextArea
from rich.console import Console, RenderableType
from rich.text import Text

from cli import attachments, chat, glyphs, history_view, render, shell, status, themes
from cli.client import ServiceError, ServiceUnreachable
from cli.interfaces import Context, Fragments, Screen

# Behind every line the field draws one more cell: where the cursor stands
# once it is at the end of the line.
CURSOR_CELL = " "

# How many of the waiting messages the line above the field shows.
_WAITING_SHOWN = 3

# The input field grows with what is typed, up to this many lines; beyond
# that it scrolls.
MAX_INPUT_LINES = 8

# The list of completions below the input field: how many rows it may take,
# and how many stay visible around the chosen one.
COMPLETION_ROWS = 12
COMPLETION_MARGIN = 1

# The status lines below the input field: the chat's, the mode's, and the
# context bar.
STATUS_LINES = 3

# What the probe of the terminal answers where it shows the full colours.
FULL_COLOURS = "truecolor"

_T = TypeVar("_T")


class LeaveAsked(BaseException):
    """A request to end the process that came while the client was still
    starting. No screen runs yet that could take it, so it is raised in the
    main thread and ends the start where it stands; whoever started the
    client catches it and leaves the way a user would. Not an
    ``Exception``: nothing on the way of the start may take it for a
    failure of its own."""


class CliApp(Screen):
    """The running screen. Everything that was shown is kept, for
    ``export``."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

        # The history is rendered into a buffer and written out as one piece
        # of text: that text can be handed to the terminal from any thread,
        # and it reads the same whichever console the client runs in. The
        # probe says how many colours the terminal the client was started in
        # can show. The width is the window's, read before every piece is
        # rendered — into a buffer the console cannot measure it, and would
        # set every line in eighty columns whatever the window has.
        self._rendered = io.StringIO()
        self._console = Console(
            file=self._rendered,
            force_terminal=True,
            color_system=Console().color_system,  # type: ignore[arg-type]
            legacy_windows=False,
            record=True,
            highlight=False,
        )
        self._console_theme: themes.Theme | None = None
        self._print_lock = threading.Lock()
        # What was written into the history, and the field that shows it.
        self._history = history_view.History()
        # Whether the screen has run: the history of a client that ended
        # before it did is written to the terminal when that is known.
        self._ran = False

        # What the worker has not taken yet: a line the user sent, or a job
        # that has to wait its turn behind them. ``None`` ends the worker.
        self._inputs: queue.Queue[str | Callable[[], None] | None] = queue.Queue()
        # The messages typed while an answer runs and not sent yet, each with
        # the number its turn in ``_inputs`` carries; guarded by the lock,
        # which the worker, the keys and the screen's threads all take.
        self._waiting: list[tuple[int, str]] = []
        self._waiting_serial = 0
        self._waiting_lock = threading.Lock()
        # The numbers of the waiting messages the running answer was stopped
        # for already, and whether that stop is still on its way: once per
        # answer, however many messages wait. Both guarded by the lock.
        self._covered: set[int] = set()
        self._stop_in_flight = False
        self._leaving = threading.Event()
        # Whether the client is still in its start: until the screen takes
        # over, or until whoever started the client says the start is over
        # some other way. A plain value and no event, like the note below:
        # the signal handler reads the one and writes the other, and a
        # handler takes no lock.
        self.starting = True
        # Whether a request to end the process came.
        self._leave_asked = False
        # Every thread the screen started, so that leaving can wait until
        # they are over.
        self._threads: list[threading.Thread] = []
        # The one of them that takes the waiting lines, one after the other.
        self._worker: threading.Thread | None = None
        # Held while a redraw waits its turn behind a running answer: one is
        # enough, however often it was asked for since.
        self._redraw_waits = threading.Lock()

        self._activity: str | Callable[[], str] | None = None
        # The client's last quiet word, shown above the field while nothing
        # runs; the next line sent takes it away.
        self._notice: str | None = None
        # The shell lines run here, one at a time; the interrupt key ends
        # the one that runs.
        self._shell = shell.Shell()
        self._frame = 0
        # Set while something runs. The spinner's thread sleeps on it, so an
        # idle screen is never drawn again by a timer.
        self._spinning = threading.Event()

        self._style_theme: themes.Theme | None = None
        self._style: BaseStyle | None = None

        self._input = TextArea(
            multiline=True,
            wrap_lines=True,
            style="class:input",
            history=InMemoryHistory(),
            completer=self._completer(ctx),
            complete_while_typing=True,
            # What a question asks for hidden is typed without a sign of it.
            password=Condition(lambda: ctx.asker.secret()),
            accept_handler=self._accept,
            get_line_prefix=self._line_prefix,
            height=self._input_height,
            # The screen hands the block more rows than it asks for — the
            # rows below the cursor when the client started. Without this
            # the field would take them all, up to its limit, and stand
            # eight lines tall around one line of text.
            dont_extend_height=True,
        )
        # A selection that searches takes up every change of the field.
        self._input.buffer.on_text_changed += lambda buffer: self._ctx.asker.typed(buffer.text)
        self._app: Application[None] = Application(
            layout=Layout(
                HSplit([self._history_field(), self._block()]), focused_element=self._input
            ),
            key_bindings=self._key_bindings(),
            style=DynamicStyle(self._prompt_style),
            # The whole window is the screen's; the terminal gets back what
            # it showed before when the client leaves.
            full_screen=True,
            # The wheel scrolls the history, and a click opens an address.
            mouse_support=True,
            color_depth=self._colour_depth(),
        )
        self._app.before_render += self._keep_cursor_in_field

    @staticmethod
    def _completer(ctx: Context) -> Completer:
        """The commands behind a slash and the paths behind an ``@``, asked
        on a thread of their own: the second reads the disk, and the screen
        must not wait for it."""
        completers: list[Completer] = [attachments.MentionCompleter()]
        commands_completer = ctx.commands.completer()
        if commands_completer is not None:
            completers.insert(0, commands_completer)
        return ThreadedCompleter(merge_completers(completers))

    def _colour_depth(self) -> ColorDepth | None:
        """How many colours the fixed block is drawn in. Where the terminal
        reports the full colours — the probe the history's colours come
        from — the block takes them too; left to itself it would stop at
        256 and stand in other tones than the history above it. Everywhere
        else, and wherever the environment names a depth of its own or asks
        for no colours, the choice stays the screen's own."""
        if ColorDepth.from_env() is not None:
            return None
        if self._console.color_system == FULL_COLOURS:
            return ColorDepth.TRUE_COLOR
        return None

    # --- The history field ----------------------------------------------------

    def _history_field(self) -> Window:
        """The field above the block: the rows of the history from its top
        downwards. It takes every row the block does not."""
        return Window(
            history_view.HistoryControl(self._history, self.invalidate),
            height=Dimension(min=0),
            wrap_lines=False,
            always_hide_cursor=True,
        )

    # --- The fixed block ------------------------------------------------------

    def _block(self) -> HSplit:
        asker = self._ctx.asker
        # The parts that stand whether or not something is asked above
        # them: how many rows they take is what a question has to leave.
        self._below_question: list[Container] = [
            to_container(part)
            for part in (
                Window(
                    FormattedTextControl(self._activity_fragments),
                    height=self._activity_height,
                    wrap_lines=False,
                    style="class:thinking",
                ),
                self._rule(),
                self._input,
                CompletionsMenu(max_height=COMPLETION_ROWS, scroll_offset=COMPLETION_MARGIN),
                self._rule(),
                Window(
                    FormattedTextControl(self._status_fragments),
                    height=STATUS_LINES,
                    wrap_lines=False,
                    style="class:status",
                ),
            )
        ]
        self._question = ConditionalContainer(
            Window(
                FormattedTextControl(asker.fragments),
                wrap_lines=True,
                dont_extend_height=True,
                # The library paints what it calls a dialog on a blue ground
                # of its own. A question stands on the terminal's ground
                # like the rest of the block.
                style="class:dialog bg:default",
            ),
            filter=Condition(asker.pending),
        )
        self._fixed = HSplit([self._question, *self._below_question], height=self._block_height)
        return self._fixed

    def _block_height(self) -> Dimension:
        """Exactly the rows the parts of the block ask for: the history field
        above it takes all the rest, so the block stands on the last rows and
        a list that opens in it does not stretch to its limit."""
        size = self._app.output.get_size()
        rows = sum(
            part.preferred_height(size.columns, size.rows).preferred
            for part in (self._question, *self._below_question)
        )
        return Dimension(min=1, max=max(1, rows), preferred=max(1, rows))

    def _rule(self) -> Window:
        return Window(char=self._rule_character, height=1, style="class:rule")

    def _rule_character(self) -> str:
        return glyphs.glyph("rule")[:1] or " "

    def _columns(self) -> int:
        return self._app.output.get_size().columns

    def _prompt_mark(self) -> str:
        return glyphs.glyph("prompt") + " "

    def _line_prefix(self, line_number: int, wrap_count: int) -> StyleAndTextTuples:
        """The mark in front of the first line; every further line is
        indented by its width, so the text stands in one column."""
        mark = self._prompt_mark()
        if line_number == 0 and wrap_count == 0:
            return [("class:prompt", mark)]
        return [("", " " * get_cwidth(mark))]

    def _field_columns(self) -> int:
        """The columns a row of the field has for the text, behind the mark
        or the indent that stands for it."""
        return max(1, self._columns() - get_cwidth(self._prompt_mark()))

    def _input_height(self) -> Dimension:
        """As many rows as the field draws its text in — the text's own line
        breaks, the ones the window's width forces, and behind every line
        the cell the cursor stands in at the end of it — at least one and
        never more than the limit. The field takes exactly that: it grows
        with the next row and shrinks again when the text is gone. A line
        that fills its row to the last cell takes one row more, for the
        cursor behind it."""
        rows = _field_rows(self._input.text, self._field_columns())
        return Dimension(min=1, max=MAX_INPUT_LINES, preferred=min(MAX_INPUT_LINES, rows))

    def _keep_cursor_in_field(self, app: Application[None]) -> None:
        """Called before every drawing. Where one line is taller than the
        field, the field shows a part of it, and it works that part out from
        the text in front of the cursor alone. A cursor on the first cell of
        a row has no text in front of it in that row — at the end of a line
        that fills its last row, it is the cell behind the text — and the
        part then ends one row above the cursor. Here the part is moved on
        to the cursor's row; the field keeps it from there.

        The field is as high as it was drawn the last time — a low window
        gives it fewer rows than it asks for — and as high as it asks for
        while it has not been drawn."""
        document = self._input.document
        # At the end of a line the cursor stands in the cell behind it,
        # whether the text ends there or goes on in the next line.
        under_cursor = CURSOR_CELL if document.is_cursor_at_the_end_of_line else document.current_char
        rows = _drawn_rows(document.current_line_before_cursor + under_cursor, self._field_columns())
        window = self._input.window
        drawn = window.render_info
        height = drawn.window_height if drawn is not None else self._input_height().preferred
        window.vertical_scroll_2 = max(window.vertical_scroll_2, rows - height)

    def _activity_lines(self, with_waiting: bool = True) -> list[str]:
        """What stands above the input field: what runs, while something
        runs; else the client's last notice; else nothing — and below that
        the messages that wait."""
        activity = self._activity
        if callable(activity):
            activity = activity()
        if activity:
            lines = activity.splitlines()
        else:
            lines = self._notice.splitlines() if self._notice else []
        return lines + self._waiting_lines() if with_waiting else lines

    def _waiting_lines(self) -> list[str]:
        """The messages that wait to be sent, one line each: the sign of
        waiting and the first line of the message, cut to the window."""
        with self._waiting_lock:
            waiting = [text for _, text in self._waiting]
        sign = glyphs.glyph("waiting") + " "
        room = max(1, self._columns() - get_cwidth(sign))
        lines = []
        # A few lines at most: every one takes a row of the fixed block.
        for text in waiting[:_WAITING_SHOWN]:
            first, *rest = text.split("\n")
            # Blanks and tabs drawn to single blanks: the line stays one row.
            line = status.one_line(first) + (" " + glyphs.glyph("more") if rest else "")
            if get_cwidth(line) > room:
                line = status.cut(line, room, glyphs.glyph("more"))
            lines.append(sign + line)
        if len(waiting) > _WAITING_SHOWN:
            lines.append(f"{sign}+{len(waiting) - _WAITING_SHOWN}")
        return lines

    def hint_line(self) -> str:
        """The line above the input field as it stands right now."""
        return "\n".join(self._activity_lines())

    def _activity_height(self) -> int:
        return max(1, len(self._activity_lines()))

    def _activity_fragments(self, with_waiting: bool = True) -> Fragments:
        """The line above the input field, set against the right edge: the
        spinner and the first line of what goes on, every further line
        below it, each as far to the right as it goes. A notice stands
        there without the spinner."""
        lines = self._activity_lines(with_waiting)
        if not lines:
            return []
        frames = glyphs.spinner_frames()
        frame = frames[self._frame % len(frames)] + " " if self._activity else ""
        width = self._columns()
        fragments: Fragments = []
        for number, line in enumerate(lines):
            lead = frame if number == 0 else ""
            room = " " * max(0, width - get_cwidth(lead) - get_cwidth(line))
            if number:
                fragments.append(("", "\n"))
            fragments.append(("", room))
            if lead:
                fragments.append(("class:accent", lead))
            fragments.append(("", line))
        return fragments

    def _status_fragments(self) -> Fragments:
        return self._ctx.status.fragments(self._columns())

    def rows_for_question(self) -> int | None:
        size = self._app.output.get_size()
        below = sum(
            part.preferred_height(size.columns, size.rows).preferred
            for part in self._below_question
        )
        return max(0, size.rows - below)

    def _prompt_style(self) -> BaseStyle:
        theme = themes.current()
        if self._style is None or theme is not self._style_theme:
            self._style_theme = theme
            self._style = theme.prompt_style()
        return self._style

    # --- Keys -----------------------------------------------------------------

    def _key_bindings(self) -> KeyBindingsBase:
        keys = KeyBindings()
        keys.add("enter")(self._on_enter)
        keys.add("escape", "enter")(self._on_newline)
        keys.add("c-j")(self._on_newline)
        keys.add(Keys.BracketedPaste)(self._on_paste)
        keys.add("c-c")(self._on_interrupt)
        # The history scrolls a page at a time; the two keys are the
        # history's, also while the field holds several lines.
        keys.add("c-l")(lambda event: self.clear())
        keys.add("pageup")(lambda event: self._scroll_history(-1))
        keys.add("pagedown")(lambda event: self._scroll_history(1))
        # While a message waits, the key takes it back into the field.
        keys.add("escape", filter=Condition(lambda: bool(self._waiting)))(self._on_take_back)
        # With text in the field the key keeps its usual meaning there:
        # delete the character under the cursor.
        keys.add("c-d", filter=Condition(lambda: not self._input.text))(self._on_leave)
        asked = self._ctx.asker.key_bindings()
        if asked is None:
            return keys
        # Merged last, so a key the open question claims wins over the same
        # key above.
        return merge_key_bindings(
            [keys, ConditionalKeyBindings(asked, Condition(self._ctx.asker.pending))]
        )

    def _scroll_history(self, direction: int) -> None:
        self._history.page(direction)
        self.invalidate()

    def _on_enter(self, event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        document = buffer.document
        if document.is_cursor_at_the_end_of_line and document.current_line.endswith("\\"):
            # A backslash at the end of the line carries the input on to the
            # next line instead of sending it. Anywhere else in the line it
            # is an ordinary character.
            buffer.delete_before_cursor(1)
            buffer.insert_text("\n")
            return
        buffer.validate_and_handle()

    def _on_newline(self, event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    def _on_paste(self, event: KeyPressEvent) -> None:
        """A pasted text goes into the field as it is — but one that is
        nothing but the paths of existing files, which is what a file
        dropped on the terminal pastes, becomes a mention for each."""
        pasted = event.data.replace("\r\n", "\n").replace("\r", "\n")
        mentions = attachments.paths_as_mentions(pasted)
        event.current_buffer.insert_text(pasted if mentions is None else mentions)

    def _on_leave(self, event: KeyPressEvent) -> None:
        self.exit()

    def _on_interrupt(self, event: KeyPressEvent) -> None:
        """Ends the shell command that runs; else ends the wait for a model
        server that is starting; else stops the running answer; with none
        of them running, empties a field that holds text and leaves from an
        empty one. An open selection takes the key before all of this: its
        own binding is merged after this one and closes it."""
        if self._shell.interrupt():
            return
        cancel_wait = self._ctx.session.cancel_wait
        if cancel_wait is not None:
            cancel_wait()
            return
        if self._ctx.session.answering:
            # What waits behind the answer is not sent into the stop: it goes
            # back into the field.
            self._take_back_waiting(self._input.buffer)
            with self._waiting_lock:
                # This stop is the one the messages typed from now on are
                # covered by.
                self._stop_in_flight = True
            # Off this thread: the request may take a moment, and the screen
            # must not stand still for it.
            self._start(chat.stop, self._ctx)
        elif self._input.text:
            # What was typed goes, the client stays: leaving on this key
            # would take a long text with it at one slip of the hand.
            self._input.buffer.reset()
        else:
            self.exit()

    def _on_take_back(self, event: KeyPressEvent) -> None:
        """Takes the waiting messages out of the line and puts them into the
        field, in front of what stands there."""
        self._take_back_waiting(event.current_buffer)

    def _take_back_waiting(self, buffer: Buffer) -> None:
        with self._waiting_lock:
            taken = [text for _, text in self._waiting]
            self._waiting.clear()
            self._covered.clear()
        if not taken:
            return
        typed = buffer.text
        buffer.text = "\n".join(taken + ([typed] if typed else []))
        buffer.cursor_position = len(buffer.text)
        self.invalidate()

    def _accept(self, buffer: Buffer) -> bool:
        text = buffer.text.strip()
        if text:
            self.submit(text)
        # Returning false empties the field for the next line.
        return False

    # --- Input and the worker -------------------------------------------------

    def submit(self, text: str) -> None:
        """Takes one line as if the user had typed and sent it.

        A message typed while an answer runs stops that answer — a tool that
        is running is waited for — and goes out after it; until then it
        stands above the field. A command does not wait: it runs at once,
        beside the answer — otherwise the one that stops an answer could only
        run after it. A shell line runs at once as well: it has nothing to do
        with the answer.
        """
        # The last notice has had its time: a new line went in.
        self._notice = None
        is_message = not text.startswith(("/", shell.MARK))
        if is_message and self._ctx.session.answering:
            self._wait_for_the_answer(text)
            return
        self._record_block(text)
        if not is_message and self._ctx.session.answering:
            self._start(self._handle, text)
        else:
            self._inputs.put(text)

    def _wait_for_the_answer(self, text: str) -> None:
        """A message typed while an answer runs: it stands above the field
        and goes out after the answer, which is stopped for it at once — a
        tool that is running is waited for, its result stops the answer."""
        with self._waiting_lock:
            self._waiting_serial += 1
            number = self._waiting_serial
            self._waiting.append((number, text))
            if self._stop_in_flight:
                # The answer is already being stopped: this message is
                # covered by that stop.
                self._covered.add(number)
        self._inputs.put(lambda: self._send_waiting(number))
        self.invalidate()
        if not self._ctx.session.open_calls:
            self._stop_for_waiting()

    def _stop_for_waiting(self) -> None:
        """Stops the running answer for the messages that wait and no stop
        was made for yet — once per answer, and only while one runs: a stop
        that came after the answer had ended would cut the next one."""
        with self._waiting_lock:
            if self._stop_in_flight or not self._ctx.session.answering:
                return
            if all(number in self._covered for number, _ in self._waiting):
                return
            self._stop_in_flight = True
            self._covered.update(number for number, _ in self._waiting)
        # Off this thread: the request may take a moment.
        self._start(self._stop_and_remember)

    def _stop_and_remember(self) -> None:
        """The stop request; one that did not reach the service leaves the
        answer running, so the next message may ask again."""
        if chat.stop(self._ctx) is False:
            with self._waiting_lock:
                self._stop_in_flight = False
                self._covered.clear()

    def _send_waiting(self, number: int) -> None:
        """Its turn: sends the message, unless it was taken back meanwhile —
        or the client is leaving."""
        if self._leaving.is_set():
            return
        with self._waiting_lock:
            self._covered.discard(number)
            found = [text for waiting, text in self._waiting if waiting == number]
            self._waiting[:] = [entry for entry in self._waiting if entry[0] != number]
        if found:
            self._record_block(found[0])
            self._do(found[0])

    def tool_finished(self) -> None:
        self._stop_for_waiting()

    def _start(self, work: Callable[..., object], *arguments: Any) -> threading.Thread:
        """Runs ``work`` in a thread of its own and keeps the thread, so
        that leaving can wait for it. The ones that are over are let go."""
        thread = threading.Thread(target=work, args=arguments, daemon=True)
        self._threads = [kept for kept in self._threads if kept.is_alive()]
        self._threads.append(thread)
        thread.start()
        return thread

    def _work(self) -> None:
        while True:
            item = self._inputs.get()
            if item is None:
                return
            self._handle(item)
            # Whatever the item was, no answer of it is running any more.
            with self._waiting_lock:
                self._stop_in_flight = False

    def _handle(self, item: str | Callable[[], None]) -> None:
        try:
            self._do(item)
        finally:
            # Whatever the line did, the status lines read anew what the
            # service says now: a mode, a stage or a tool may have changed.
            # Not on the way out: the client is being closed behind it.
            if not self._leaving.is_set():
                self._ctx.status.refresh()
                chat.follow_context_size(self._ctx)
                self.invalidate()

    def _do(self, item: str | Callable[[], None]) -> None:
        ctx = self._ctx
        try:
            if callable(item):
                item()
            elif item.startswith("/"):
                ctx.commands.run(item)
            elif shell.is_shell_line(item):
                self._shell.run(ctx, item)
            else:
                chat.send(ctx, item)
            return
        except ServiceUnreachable as error:
            failure = ctx.texts.t("fehler.dienst_antwortet_nicht", error=error.address)
        except ServiceError as error:
            failure = error.detail
        except Exception as error:  # noqa: BLE001
            # One line that fails must not take the worker with it — every
            # later line would then vanish into a queue nobody reads. The
            # failure is shown instead.
            failure = f"{type(error).__name__}: {error}"
        # Where even that cannot be written — the terminal is gone — there is
        # nobody left to tell, and the worker still has to see the next line.
        with contextlib.suppress(Exception):
            ctx.renderer.error(failure)

    def _spin(self) -> None:
        while not self._leaving.is_set():
            self._spinning.wait()
            if self._leaving.is_set():
                return
            self._frame += 1
            self.invalidate()
            self._leaving.wait(glyphs.SPINNER_INTERVAL)

    # --- The screen, as the other modules use it ------------------------------

    def print_above(self, *renderables: RenderableType) -> None:
        with self._print_lock:
            if self._leaving.is_set():
                # Nothing more is shown once the screen is leaving. A thread
                # that still wrote to the output while the program ends
                # would hold the output just when the interpreter wants to
                # close it, and the interpreter gives up on that with an
                # error of its own.
                return
            self._use_current_look()
            self._use_current_width()
            self._print_each(renderables)
            text = _without_trailing_blanks(self._rendered.getvalue())
            self._rendered.seek(0)
            self._rendered.truncate()
            # Taken under the lock, so two threads never interleave their
            # lines: what is written here appears in the field of the
            # history, at its end.
            self._history.add(text)
        self.invalidate()

    def _print_each(self, renderables: Iterable[RenderableType]) -> None:
        """Every renderable on lines of its own — handed over together, the
        console would set pieces of text side by side on one line."""
        for renderable in renderables:
            self._console.print(renderable)

    def _use_current_look(self) -> None:
        theme = themes.current()
        if theme is self._console_theme:
            return
        if self._console_theme is not None:
            self._console.pop_theme()
        self._console.push_theme(theme.rich_theme())
        self._console_theme = theme

    def _use_current_width(self) -> None:
        """The console sets its lines as wide as the window is right now,
        so text, lists and titles take the whole width and follow every
        change of it."""
        self._console.width = self._columns()

    def invalidate(self) -> None:
        self._app.invalidate()

    def set_activity(self, text: str | Callable[[], str] | None) -> None:
        self._activity = text or None
        if self._activity:
            self._spinning.set()
        else:
            self._spinning.clear()
        self.invalidate()

    def set_notice(self, text: str | None) -> None:
        self._notice = text or None
        self.invalidate()

    def update_status(self, **fields: Any) -> None:
        self._ctx.status.update(**fields)
        self.invalidate()

    def clear(self) -> None:
        self._empty_in_order()

    def redraw(self) -> None:
        if threading.current_thread() is self._worker:
            # The worker's own turn: nothing else writes into the history.
            self._redraw()
            return
        # Beside a running answer. The window is emptied at once, so nothing
        # stays in colours that were chosen for another ground; the history
        # follows in its turn, once the answer is over and stored — once,
        # however many redraws were asked for until then.
        self._begin_anew()
        if self._redraw_waits.acquire(blocking=False):
            self._inputs.put(self._redraw_in_turn)

    def _redraw_in_turn(self) -> None:
        # Let go first: what is asked for from here on is not covered by
        # the history about to be read.
        self._redraw_waits.release()
        self._redraw()

    def _redraw(self) -> None:
        self._begin_anew()
        ctx = self._ctx
        opened = ctx.session.chat
        if opened is None or not chat.show_history(ctx, opened):
            # Nothing has been said in the open chat yet. What stood in the
            # window then was the head, and that is what is written again.
            render.show_head(ctx)

    def _begin_anew(self) -> None:
        """Empties the window for a history that is written again, and lets
        go of what is kept for ``export``: the pieces kept so far carry the
        colours they were written in, and the ones written from here on
        would follow them a second time. Both in one go: a piece another
        thread writes is either gone with the window or kept with the new
        beginning."""
        with self._print_lock:
            self._console.export_text(clear=True)
            self._empty_window()

    def _empty_in_order(self) -> None:
        """Empties the window in its place among the pieces of the history:
        what was written before goes with it, what is written after stands
        in the emptied window. Emptied on the screen's own thread, the
        window would be empty ahead of a piece that was written a moment
        before and is still on its way to the terminal, and that piece
        would then stand in it after all. The block is taken off for the
        emptying like for any piece of the history and drawn again behind
        it, at the top of the emptied window — from where it is pushed to
        the last rows."""
        with self._print_lock:
            self._empty_window()

    def _empty_window(self) -> None:
        """Called with the lock of the history held: the field of the
        history is empty, and what is written from here on stands at its
        top."""
        if self._leaving.is_set():
            return
        self._history.clear()
        self.invalidate()

    def open_chat(self, opened: Mapping[str, Any]) -> None:
        # Through the queue, so the switch never lands in the middle of an
        # answer that is still being written into the history.
        self._inputs.put(lambda: chat.open_chat(self._ctx, opened))

    def new_chat(self) -> None:
        # Through the queue as well: the lines typed before it still go into
        # the chat that was open when they were typed.
        self._inputs.put(lambda: chat.new_chat(self._ctx))

    def queue(self, work: Callable[[], None]) -> None:
        """Hands ``work`` to the worker, behind what already waits: it runs
        in its turn once the screen is up — before the start the queue only
        collects."""
        self._inputs.put(work)

    def exit(self) -> None:
        self._leaving.set()
        self._spinning.set()
        self._inputs.put(None)
        self._on_screen_thread(self._leave)

    def _leave(self) -> None:
        if self._app.is_running and not self._app.is_done:
            self._app.exit()

    def _screen_is_up(self) -> None:
        # Only a screen that came up shows the history; one that failed to
        # start leaves it to ``show_unseen``.
        self._ran = True
        self._history.keep_no_pieces()
        self._leave_if_asked()

    def _leave_if_asked(self) -> None:
        """Called once the screen runs: a request to leave that came before
        it did found nothing to end, and is carried out now."""
        if self._leave_asked:
            # Only noted so far, by a signal on the screen's way up. The
            # screen's loop runs by now and takes it from here.
            self.exit()
        elif self._leaving.is_set():
            self._leave()

    def wait(self, until: float) -> None:
        """Waits until every thread the screen started is over — no longer
        than until ``until`` on the monotonic clock. For leaving, once the
        screen has left and the client has hung up: by then no stream holds
        a thread, and each one ends by itself. One that is still held then
        — by a request the service never answers — is left behind; it
        writes nothing any more."""
        current = threading.current_thread()
        for thread in list(self._threads):
            if thread is not current:
                thread.join(max(0.0, until - time.monotonic()))

    def hand_over(self, work: Callable[[], _T]) -> _T:
        """Gives the terminal to ``work`` — from a thread of the worker —
        and waits for it: the block is taken off the screen, ``work`` runs on
        a thread of its own so that the screen does not stand still, and the
        block is drawn again afterwards. What is written to the history in
        the meantime waits behind it, as the output is held while the
        terminal is lent."""
        loop = self._app.loop
        if not (self._app.is_running and loop is not None):
            return work()
        done: concurrent.futures.Future[_T] = concurrent.futures.Future()

        async def lend() -> None:
            try:
                done.set_result(await run_in_terminal(work, in_executor=True))
            except BaseException as error:  # handed on to the caller below
                done.set_exception(error)

        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(lend()))
        return done.result()

    def _on_screen_thread(self, action: Callable[[], None]) -> None:
        loop = self._app.loop
        if self._app.is_running and loop is not None:
            loop.call_soon_threadsafe(action)

    # --- Running and exporting ------------------------------------------------

    def run(self) -> None:
        """Shows the fixed block and stays until the user leaves."""
        # What the status lines say about the service, read once before the
        # block is drawn for the first time.
        self._ctx.status.refresh()
        # The start has asked the service all it had to ask. From here on a
        # request to end the process is noted instead of raised, and carried
        # out as soon as the screen runs: raised while the screen is on its
        # way up, it would tear a loop that is only half built.
        self.starting = False
        self._worker = self._start(self._work)
        self._start(self._spin)
        try:
            with self._stdout_to_the_screen():
                self._app.run(pre_run=self._screen_is_up)
        except EOFError:
            # The terminal went away; that is a way of leaving too.
            pass
        finally:
            self._leaving.set()
            self._spinning.set()
            self._inputs.put(None)
            # A shell command that still runs ends with the screen that
            # showed what it printed.
            self._shell.interrupt()
            # So does a selection nobody picked from: the command that
            # opened it still waits for the pick, and is let go.
            self._ctx.asker.close()
            # Whoever was writing a piece into the history when the screen
            # left finishes it here; after that nobody writes any more.
            with self._print_lock:
                pass

    @contextlib.contextmanager
    def _stdout_to_the_screen(self) -> Iterator[None]:
        """While the screen runs, what the program writes to standard output
        — the colour sequences of a look — goes out through the screen's own
        output, on its own thread: it reaches the terminal between two
        drawings, never in the middle of one."""
        former = sys.stdout
        sys.stdout = _ScreenOutput(self._app, former)  # type: ignore[assignment]
        try:
            yield
        finally:
            sys.stdout = former

    def history_text(self) -> str:
        """What the field of the history holds right now, as a console wrote
        it: everything written since the window was last emptied."""
        return self._history.text()

    def show_unseen(self) -> None:
        """For a client that ended without its screen having run — a start
        that failed, a chat that was not found: writes what the history holds
        to the terminal the way an ordinary program does, so that the words
        that say what went wrong are not lost with a screen that never
        came."""
        if self._ran:
            return
        text = self._history.text()
        if text:
            with contextlib.suppress(OSError):
                sys.stdout.write(text)
                sys.stdout.flush()

    def leave_on_signals(self) -> Callable[[], None]:
        """A request to end the process — or, where the system knows it, a
        terminal that hung up — leaves the way the user would: the block is
        erased and whatever follows the run still happens. Returns what
        puts the former handlers back.

        Taken by whoever starts the client, before the start does anything
        that leaving has to undo, and given back as soon as the client
        leaves. A request finds the client in its start, on the screen's
        way up, with the screen running, or already leaving, and each of
        the four has its answer. In the start it is raised as
        ``LeaveAsked``: whoever took the handlers catches it, and sets
        ``starting`` to false once the start is over, before giving them
        back."""
        wanted = [signal.SIGTERM]
        if hasattr(signal, "SIGHUP"):
            wanted.append(signal.SIGHUP)
        former: dict[int, Any] = {}

        def leave(*_: Any) -> None:
            # A handler runs in the middle of whatever the main thread was
            # doing, so it takes no lock that thread may be holding.
            if self._leave_asked or self._leaving.is_set():
                # Asked before, or leaving anyway: what is ending is not
                # interrupted a second time.
                return
            self._leave_asked = True
            loop = self._app.loop
            if self._app.is_running and loop is not None:
                # The screen runs: its own loop carries the request out.
                loop.call_soon_threadsafe(self.exit)
            elif self.starting:
                # No screen that would ever take the request. Raised here,
                # it ends the start where it stands — also inside a question
                # the service never answers.
                raise LeaveAsked
            # Else the screen is on its way up, and finds the note as soon
            # as it runs.

        def restore() -> None:
            for number, handler in former.items():
                try:
                    # A handler set outside Python reads back as nothing and
                    # cannot be set again: the default stands in for it.
                    signal.signal(number, signal.SIG_DFL if handler is None else handler)
                except (ValueError, OSError):
                    pass

        # Held back while the handlers are set, where the system knows how:
        # a request that comes in the middle would run its handler before
        # this has the former ones to give back. It is carried out at the
        # release below, when they are all known. The mask the process had
        # is the one that comes back.
        hold = getattr(signal, "pthread_sigmask", None)
        mask_before = None
        if hold is not None:
            try:
                mask_before = hold(signal.SIG_BLOCK, wanted)
            except (ValueError, OSError):
                pass
        try:
            for number in wanted:
                # Read before it is replaced: a request that comes between
                # the replacing and the noting must not lose it.
                former[number] = signal.getsignal(number)
                try:
                    signal.signal(number, leave)
                except (ValueError, OSError):
                    # Signals can only be taken on the main thread; elsewhere
                    # the process keeps whatever it had.
                    del former[number]
        except BaseException:
            # The request came while the handlers were taken — raised by the
            # handler that is already set: whoever called never gets the way
            # back, so the former handlers are given back here, and the
            # request goes on as it was raised.
            restore()
            raise
        finally:
            if mask_before is not None:
                with contextlib.suppress(ValueError, OSError):
                    hold(signal.SIG_SETMASK, mask_before)  # type: ignore[misc]

        return restore

    def _record_block(self, typed: str) -> None:
        """Adds the fixed block, as it stands when a line is sent, to what is
        kept for ``export`` only. The block is erased on leaving, so without
        this an export would never show the status line or what was typed."""
        mark = self._prompt_mark()
        indent = " " * get_cwidth(mark)
        field = Text(style="exe.input")
        for number, line in enumerate(typed.split("\n")):
            field.append(mark if number == 0 else "\n" + indent, style="exe.prompt")
            field.append(line)
        block: list[RenderableType] = []
        if self._activity_lines(with_waiting=False):
            block.append(_as_text(self._activity_fragments(with_waiting=False), "exe.thinking"))
        with self._print_lock:
            self._use_current_look()
            # Under the lock: the width must not change under a piece that
            # another thread is rendering right now.
            self._use_current_width()
            width = self._console.width
            rule = Text(self._rule_character() * width, style="exe.rule")
            block.extend([rule, field, rule])
            block.append(_as_text(self._ctx.status.fragments(width), "exe.status"))
            self._print_each(block)
            # Only the export keeps it; nothing of it goes to the terminal.
            self._rendered.seek(0)
            self._rendered.truncate()

    def export(self, path: Path) -> None:
        """Writes everything shown since the history was last written again
        as one HTML page, on the ground of the look in use. What was shown
        stays kept: the next export carries it again, with what came after."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._print_lock:
            self._console.save_html(
                str(path), theme=themes.current().terminal_theme(), clear=False
            )


class _ScreenOutput:
    """Standard output while the screen runs. What is written is handed to
    the screen's loop and goes to the terminal through the screen's own
    output; everything else a stream is asked is answered by the stream it
    stands in for."""

    def __init__(self, app: Application[None], stream: Any) -> None:
        self._app = app
        self._stream = stream

    def write(self, text: str) -> int:
        loop = self._app.loop
        if self._app.is_running and loop is not None:
            try:
                loop.call_soon_threadsafe(self._send, text)
                return len(text)
            except RuntimeError:
                # The loop closed between the check and the call: the screen
                # is gone, and the stream it stands in for takes the text.
                pass
        self._stream.write(text)
        return len(text)

    def _send(self, text: str) -> None:
        output = self._app.output
        output.write_raw(text)
        output.flush()

    def flush(self) -> None:
        return None

    @property
    def encoding(self) -> str | None:
        """What the screen's output encodes with: the signs the client may
        write are the signs that output can take."""
        return self._app.output.encoding()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


@functools.lru_cache(maxsize=4096)
def _cells(sign: str) -> int:
    """The cells the screen draws one sign in, by the screen's own measure:
    a wide sign takes two, and so does a control sign, which stands as two
    signs."""
    return Char(sign).width


def _drawn_rows(signs: str, columns: int) -> int:
    """The rows ``signs`` are drawn in, in ``columns`` columns. They go on
    in the next row where the next sign no longer fits; a sign two cells
    wide that meets the last cell of a row leaves that cell empty, so the
    number of cells alone does not say how many rows there are."""
    rows, used = 1, 0
    for sign in signs:
        width = _cells(sign)
        if used + width > columns:
            rows, used = rows + 1, 0
        used += width
    return rows


@functools.lru_cache(maxsize=4)
def _field_rows(text: str, columns: int) -> int:
    """The rows the field draws ``text`` in: line by line, each with the
    cell behind it. Kept for the text and the width it was worked out for:
    the field is asked for its height several times for every drawing."""
    return sum(_drawn_rows(line + CURSOR_CELL, columns) for line in text.split("\n"))


# What stands at the end of a line of the history: blanks, and the codes that
# set or end a colour between them and behind them.
_END_OF_LINE = re.compile(r"(?:[ ]|\x1b\[[0-9;:]*m)+$", re.MULTILINE)
_COLOUR_CODE = re.compile(r"\x1b\[[0-9;:]*m")


def _without_trailing_blanks(text: str) -> str:
    """``text`` with no blank at the end of any line. A list is set in
    columns of the width of its widest cell, so every line of it goes to the
    terminal filled up with blanks to the same width; drawn narrower, the
    terminal breaks each of them and sets what is left — nothing but blanks
    — in a row of its own. The history has no background colour, so a blank
    at the end of a line is never seen; the colour codes between the blanks
    stay, so what follows is drawn as before, and a line of blanks only
    stays a line."""
    return _END_OF_LINE.sub(lambda end: "".join(_COLOUR_CODE.findall(end.group(0))), text)


def _as_text(fragments: Fragments, base: str) -> Text:
    """A line of the fixed block as the history writes it: every piece in
    the style its last known class names."""
    text = Text(style=base, no_wrap=True, overflow="crop")
    for style, piece, *_ in to_formatted_text(fragments):
        names = [
            part[len("class:"):]
            for part in style.split()
            if part.startswith("class:") and part[len("class:"):] in themes.STYLE_NAMES
        ]
        text.append(piece, style=themes.RICH_PREFIX + names[-1] if names else None)
    return text
