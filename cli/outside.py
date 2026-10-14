"""A command of the chat, run from outside it.

``exe theme pearl`` runs the code behind ``/theme pearl``: the same handler,
with the screen, the lines and the question swapped for ones that suit a
program that writes its result and ends. A line goes to the standard
output, an error to the standard error. A selection — what the command
opens where its word is missing — opens in a small block of its own at the
terminal's bottom and is gone once picked from. Where there is no terminal
to pick in, ``NeedsTerminal`` is raised and the caller says so.

A command that opens a chat — ``chats`` — hands that over: the screen only
records which one, and the caller starts the client with it, the way
``--chat`` does.
"""

from __future__ import annotations

import sys
import getpass
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from prompt_toolkit.application import Application, get_app_or_none
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from rich.console import Console, RenderableType

from cli import themes
from cli.dialogs import TerminalAsker
from cli.interfaces import Context, Entry, Renderer, Screen


class NeedsTerminal(Exception):
    """A selection was asked for where no terminal can show one."""


def has_terminal() -> bool:
    """Whether input and output are both a terminal — the one place that
    can show a selection and take a choice."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def input_line(prompt: str) -> str:
    """One line typed at the terminal, the prompt written to the error
    output."""
    print(prompt, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().rstrip("\n")


class OutsideScreen(Screen):
    """The screen of a program that writes its result and ends: what the
    chat would add to its history is written out at once."""

    def __init__(self) -> None:
        # Kept, so that ``export`` can write what this run wrote.
        self._console = Console(record=True, theme=themes.current().rich_theme())
        # The chat a command opened: its record, or ``None``.
        self.opened: dict[str, Any] | None = None
        # The last line of activity that was written, so that one that
        # stays the same is not written again.
        self._last_activity: str | None = None

    def print_above(self, *renderables: RenderableType) -> None:
        for renderable in renderables:
            self._console.print(renderable)

    def invalidate(self) -> None:
        # A selection that is open redraws itself.
        app = get_app_or_none()
        if app is not None:
            app.invalidate()

    def set_notice(self, text: str | None) -> None:
        if text:
            print(text)

    def set_activity(self, text: str | Callable[[], str] | None) -> None:
        # What stands in the line above the status line in the chat is a
        # line of its own here, written when it changes: how far a fetch is
        # is shown the same way as in the chat, one line after the other.
        if isinstance(text, str) and text and text != self._last_activity:
            print(text, file=sys.stderr)
        self._last_activity = text if isinstance(text, str) else None

    def open_chat(self, chat: Any) -> None:
        self.opened = dict(chat)

    def export(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._console.save_html(
            str(path), theme=themes.current().terminal_theme(), clear=False
        )


class PlainRenderer(Renderer):
    """The client's own lines as plain text: no history to stand in, no
    colour of the look. An error sets ``failed``, which becomes the exit
    code."""

    def __init__(self) -> None:
        self.failed = False

    def notice(self, text: str) -> None:
        print(text)

    def remark(self, text: str) -> None:
        print(text)

    def shell_line(self, text: str) -> None:
        print(text)

    def error(self, text: str) -> None:
        self.failed = True
        print(text, file=sys.stderr)


class OutsideAsker(TerminalAsker):
    """Opens a selection in a block of its own: a small application that
    ends with the choice. The questions of the service never arrive here —
    no answer runs — so only a selection is ever asked."""

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self._block: Application[None] | None = None

    def choose(self, entries: Sequence[Entry], head: str = "") -> int | None:
        if not has_terminal():
            raise NeedsTerminal
        return super().choose(entries, head)

    def ask_text(self, head: str, *, secret: bool = False) -> str | None:
        """A line typed at the terminal's own prompt: hidden for a secret,
        and the head in front of it on the error output, so that the
        command's result alone stands on the standard output."""
        if not has_terminal():
            raise NeedsTerminal
        prompt = f"{head} "
        try:
            typed = getpass.getpass(prompt) if secret else input_line(prompt)
        except EOFError:
            return None
        return typed.strip() or None

    def _ask(self, question: Any) -> dict[str, Any] | None:
        if question.entries is None:
            return None
        with self._lock:
            self._open = question
        field = Window(BufferControl(Buffer()), height=1)
        block: Application[None] = Application(
            layout=Layout(
                HSplit(
                    [
                        Window(FormattedTextControl(self.fragments), dont_extend_height=True),
                        field,
                    ]
                ),
                focused_element=field,
            ),
            key_bindings=self.key_bindings(),
            style=themes.current().prompt_style(),
            full_screen=False,
            erase_when_done=True,
        )
        self._block = block
        try:
            block.run()
        finally:
            self._block = None
        return question.answer

    def _settle(
        self, question: Any, answer: dict[str, Any], marked: int | None, typed: str
    ) -> None:
        super()._settle(question, answer, marked, typed)
        block = self._block
        if block is not None and block.is_running:
            block.exit()
