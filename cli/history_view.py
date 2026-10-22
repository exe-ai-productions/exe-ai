"""The field of the history: the part of the full screen above the fixed
block, which alone scrolls.

What the client writes into the history arrives as the text a console wrote
for a terminal — lines with colour codes, and the links of the console as
the sequences of a terminal that knows them. Here it is read back into
lines of coloured runs, set to the width of the field, and drawn from the
top: a history that is shorter than its field leaves the rest of the field
empty, and nothing is written to fill it up.

The field follows the end of the history for as long as it has not been
scrolled. A field scrolled up stays where it is when more is written; it
follows the end again once it is scrolled down to it.

The screen never draws a link itself, so a click on an address is taken
here: the run under the pointer knows the address it links to.
"""

from __future__ import annotations

import bisect
import re
import threading
import webbrowser
from collections.abc import Callable
from typing import NamedTuple

from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import ANSI, StyleAndTextTuples, to_formatted_text
from prompt_toolkit.layout.controls import UIContent, UIControl
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
from prompt_toolkit.utils import get_cwidth

# How many rows one step of the mouse wheel moves the field.
WHEEL_ROWS = 3

# The sequence of a terminal that opens a link, and the one that closes it
# again. The screen's own reader of colour codes does not know them and would
# leave their letters in the text, so they are put into signs of the private
# use area before it reads: one that opens a link — followed by the sign that
# stands for the number of the address in the piece — and one that closes it.
_OPENS_LINK = re.compile(r"\x1b\]8;[^;\x1b\x07]*;([^\x1b\x07]+)(?:\x1b\\|\x07)")
_CLOSES_LINK = re.compile(r"\x1b\]8;[^;\x1b\x07]*;(?:\x1b\\|\x07)")
LINK_OPEN = ""
LINK_CLOSE = ""
_ADDRESS_BASE = 0xE100
_ADDRESSES_PER_PIECE = 0x1000


class Run(NamedTuple):
    """A stretch of one line that stands in one style, and the address it
    links to where it is a link."""

    style: str
    text: str
    link: str | None


Row = list[Run]


def _read(piece: str) -> list[Row]:
    """The lines of a piece of text with colour codes: one list of runs for
    every line. A piece that does not end in a line break still has its
    last line."""
    addresses: list[str] = []

    def opened(found: re.Match[str]) -> str:
        if len(addresses) >= _ADDRESSES_PER_PIECE:
            return ""
        addresses.append(found.group(1))
        return LINK_OPEN + chr(_ADDRESS_BASE + len(addresses) - 1)

    marked = _OPENS_LINK.sub(opened, piece)
    marked = _CLOSES_LINK.sub(LINK_CLOSE, marked)
    lines: list[Row] = [[]]
    link: str | None = None
    pending_address = False
    for style, sign, *_ in to_formatted_text(ANSI(marked)):
        if sign == LINK_OPEN:
            pending_address = True
            continue
        if pending_address:
            pending_address = False
            link = addresses[ord(sign) - _ADDRESS_BASE]
            continue
        if sign == LINK_CLOSE:
            link = None
            continue
        if sign == "\n":
            lines.append([])
            continue
        row = lines[-1]
        if row and row[-1].style == style and row[-1].link == link:
            row[-1] = Run(style, row[-1].text + sign, link)
        else:
            row.append(Run(style, sign, link))
    # The line break at the end of a piece closes its last line; what comes
    # after it is no line.
    if len(lines) > 1 and not lines[-1]:
        lines.pop()
    return lines


def _wrap(line: Row, columns: int) -> list[Row]:
    """``line`` in rows of at most ``columns`` cells. A sign two cells wide
    that meets the last cell of a row goes to the next row."""
    if sum(get_cwidth(run.text) for run in line) <= columns:
        return [line]
    rows: list[Row] = [[]]
    used = 0
    for run in line:
        for sign in run.text:
            width = get_cwidth(sign)
            if used + width > columns:
                rows.append([])
                used = 0
            row = rows[-1]
            if row and row[-1].style == run.style and row[-1].link == run.link:
                row[-1] = Run(run.style, row[-1].text + sign, run.link)
            else:
                row.append(Run(run.style, sign, run.link))
            used += width
    return rows


class History:
    """What was written, and the part of it the field shows."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # The pieces as they were written, for a client that ends before its
        # screen ran; dropped once it did, so that the history is kept once.
        self._pieces: list[str] = []
        self._keeps_pieces = True
        self._lines: list[Row] = []
        # The rows of the lines worked out for ``_columns``, how many lines
        # that covers, and the first row of every line among them.
        self._columns: int | None = None
        self._rows: list[Row] = []
        self._first_row: list[int] = []
        # The first row the field shows; ``None`` while it follows the end.
        self._top: int | None = None
        # The line that stands on that row, so that the place holds when the
        # rows are worked out anew for another width.
        self._anchor = 0
        self._height = 0

    # --- Writing --------------------------------------------------------------

    def add(self, piece: str) -> None:
        """Appends a piece of text, as a console wrote it."""
        if not piece:
            return
        with self._lock:
            if self._keeps_pieces:
                self._pieces.append(piece)
            self._lines.extend(_read(piece))

    def clear(self) -> None:
        with self._lock:
            self._pieces.clear()
            self._lines.clear()
            self._columns = None
            self._rows = []
            self._first_row = []
            self._top = None
            self._anchor = 0

    def keep_no_pieces(self) -> None:
        """From here on only the lines are kept: the screen shows the
        history, and nothing is left to write out to a terminal."""
        with self._lock:
            self._keeps_pieces = False
            self._pieces.clear()

    def text(self) -> str:
        """Everything written, as it was written — as plain text once the
        pieces are no longer kept."""
        with self._lock:
            if self._keeps_pieces:
                return "".join(self._pieces)
            return "".join("".join(run.text for run in line) + "\n" for line in self._lines)

    def is_empty(self) -> bool:
        with self._lock:
            return not self._lines

    # --- Reading --------------------------------------------------------------

    def _work_out(self, columns: int) -> None:
        if columns != self._columns:
            self._columns = columns
            self._rows = []
            self._first_row = []
        done = len(self._first_row)
        for line in self._lines[done:]:
            self._first_row.append(len(self._rows))
            self._rows.extend(_wrap(line, columns))
        if self._top is not None:
            # The rows may have been worked out again: the field holds on to
            # the line that stood on its top row.
            anchor = min(self._anchor, len(self._first_row) - 1)
            self._top = self._first_row[anchor] if anchor >= 0 else 0

    def rows(self, columns: int, height: int) -> list[Row]:
        """The rows the field shows, from its top downwards: as many as the
        field has rows, or fewer where the history is shorter."""
        with self._lock:
            self._height = height
            self._work_out(columns)
            total = len(self._rows)
            last_top = max(0, total - height)
            top = last_top if self._top is None else min(self._top, last_top)
            if self._top is not None:
                self._top = top
                self._anchor = max(0, bisect.bisect_right(self._first_row, top) - 1)
            return self._rows[top : top + height]

    def scroll(self, rows: int) -> None:
        """Moves the field by ``rows`` rows — up where negative. A field
        that reaches the last row follows the end again."""
        with self._lock:
            if self._columns is None:
                return
            total = len(self._rows)
            last_top = max(0, total - self._height)
            top = last_top if self._top is None else self._top
            top = max(0, min(last_top, top + rows))
            if top >= last_top:
                self._top = None
                return
            self._top = top
            self._anchor = max(0, bisect.bisect_right(self._first_row, top) - 1)

    def page(self, direction: int) -> None:
        """A page up (``-1``) or down (``1``): the field's height, less one
        row so that a line of the old page stays in sight."""
        self.scroll(direction * max(1, self._height - 1))

    def follows_the_end(self) -> bool:
        with self._lock:
            return self._top is None


class HistoryControl(UIControl):
    """The field as a control of the screen: it draws the rows the history
    names, scrolls on the wheel and opens an address that is clicked."""

    def __init__(
        self,
        history: History,
        changed: Callable[[], None],
        open_address: Callable[[str], None] | None = None,
    ) -> None:
        self._history = history
        self._changed = changed
        self._open_address = open_address or open_in_browser
        # The rows as they were drawn last, so that a click finds the run
        # under the pointer.
        self._drawn: list[Row] = []

    def is_focusable(self) -> bool:
        return False

    def create_content(self, width: int, height: int) -> UIContent:
        rows = self._history.rows(max(1, width), height)
        self._drawn = rows

        def line(number: int) -> StyleAndTextTuples:
            return [(run.style, run.text) for run in rows[number]]

        return UIContent(get_line=line, line_count=len(rows), show_cursor=False)

    def mouse_handler(self, mouse_event: MouseEvent) -> object:
        kind = mouse_event.event_type
        if kind == MouseEventType.SCROLL_UP:
            self._history.scroll(-WHEEL_ROWS)
            self._changed()
            return None
        if kind == MouseEventType.SCROLL_DOWN:
            self._history.scroll(WHEEL_ROWS)
            self._changed()
            return None
        if kind == MouseEventType.MOUSE_UP and mouse_event.button == MouseButton.LEFT:
            address = self._address_at(mouse_event.position)
            if address is not None:
                self._open_address(address)
                return None
        return NotImplemented

    def _address_at(self, position: Point) -> str | None:
        drawn = self._drawn
        if not 0 <= position.y < len(drawn):
            return None
        column = 0
        for run in drawn[position.y]:
            column += get_cwidth(run.text)
            if position.x < column:
                return run.link
        return None


def open_in_browser(address: str) -> None:
    """Opens an address in the browser of the system, on a thread of its
    own: the call may take a moment, and the screen must not wait for it.
    Only web addresses."""
    if not re.match(r"https?://", address, re.IGNORECASE):
        return

    def open_it() -> None:
        try:
            webbrowser.open(address)
        except Exception:  # noqa: BLE001 - nobody is left to report it to
            pass

    threading.Thread(target=open_it, daemon=True).start()
