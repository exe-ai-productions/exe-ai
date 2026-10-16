"""``exe -p "question"``: one message, the answer written out, the program
ended — for a script.

Nobody is there to answer: a tool that asks for permission is allowed just
this once, and a question of the model gets the answer a closed question
box gives — an empty one, and the model goes on without it. What stands on
the standard output is the text of the answer and nothing else; whatever
the program says on its own — the start of the service, a notice, an error
— goes to the error output, and the exit code says how it went.
"""

from __future__ import annotations

import sys
from typing import Any

from cli import chat
from cli.client import ServiceError, ServiceUnreachable
from cli.interfaces import Asker, Context, Event, Renderer, Screen

# What a run that went wrong, or was ended from the keyboard, returns.
FAILED = 1


class PrintRenderer(Renderer):
    """Writes the answer's text as it comes and nothing of the rest: no
    thinking, no tool lines, no figures. An error is said on the error
    output and fails the run."""

    def __init__(self) -> None:
        self.failed = False
        # Whether the last thing written to the output was a line break.
        self._at_line_start = True
        self._wrote = False

    def content(self, text: str) -> None:
        if not text:
            return
        sys.stdout.write(text)
        sys.stdout.flush()
        self._wrote = True
        self._at_line_start = text.endswith("\n")

    def done(self, event: Event) -> None:
        # The answer ends with a line break, so that the shell's prompt does
        # not stand on its last line.
        if self._wrote and not self._at_line_start:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._at_line_start = True

    def notice(self, text: str) -> None:
        print(text, file=sys.stderr)

    def remark(self, text: str) -> None:
        print(text, file=sys.stderr)

    def error(self, text: str) -> None:
        self.failed = True
        print(text, file=sys.stderr)


class AutoAsker(Asker):
    """Answers the service's questions without asking anybody."""

    def confirm_tool(self, event: Event) -> dict[str, Any] | None:
        # Just this once: nothing is allowed for good from here.
        return {"erlaubt": True, "dauerhaft": False}

    def ask_user(self, event: Event) -> dict[str, Any] | None:
        # What Esc gives in the chat: an empty answer, the model goes on.
        return {"antwort": ""}


class PrintScreen(Screen):
    """A screen with nothing to draw: a quiet word of the program goes to the
    error output, the line of activity is not written at all."""

    def set_notice(self, text: str | None) -> None:
        if text:
            print(text, file=sys.stderr)


def message(question: str, piped: str) -> str:
    """The text that goes out: the piped text in front, the question on a
    line of its own behind it — or the question alone."""
    piped = piped.rstrip("\n")
    return f"{piped}\n{question}" if piped.strip() else question


def run(ctx: Context, question: str, piped: str, renderer: PrintRenderer) -> int:
    """Sends the message and follows the answer to its end. 0 where it came
    out whole; 1 after an error of the stream, a refusal, a service that does
    not answer, or the interrupt key."""
    try:
        chat.new_chat(ctx)
        # A mention with an ``@`` is text here: nothing is attached.
        chat.send(ctx, message(question, piped), attach=False)
    except KeyboardInterrupt:
        # The answer is ended the way the chat ends it, and the program with
        # the code of a wait that was ended from the keyboard.
        try:
            chat.stop(ctx)
        except KeyboardInterrupt:
            pass
        return FAILED
    except ServiceUnreachable as error:
        print(ctx.texts.t("fehler.dienst_antwortet_nicht", error=error.address), file=sys.stderr)
        return FAILED
    except ServiceError as error:
        print(error.detail, file=sys.stderr)
        return FAILED
    return FAILED if renderer.failed else 0
