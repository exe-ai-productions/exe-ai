"""The empty rows right above the fixed block, and the use of them.

The block stands on the last rows of the window, and at the start of a run
the rows between the head of the history and the block are empty: that is
what pushed it down. A block that grows — a list of completions, a question,
one more line of input — needs rows below its top, and at the bottom of the
window there are none, so the terminal would scroll and the head of the
history with it, for something that is not part of the history. Where those
empty rows are known, the block takes them first: it is taken off, the
cursor goes up into them, and it is drawn again from there.

What is known is a number the screen keeps. It rises by the rows a push
down wrote, it falls by the rows a growing block took, and it is gone as
soon as anything else may have written above the block: everything the
terminal is given while the block is off the screen — text for the history,
a cleared window, a new size — passes through the renderer's ``erase``, and
that is the one place the number is dropped.

A block that grows past the last row has no empty rows to take: the terminal
scrolls the history up for it, and when the block is smaller again those rows
are empty below it — and the history is above them, not in them. The screen
counts what the terminal scrolled away for the block, from how far the block's
top moved up between two drawings, under the same erase; with the block
smaller it moves the window's content down by that many rows, instead of
writing empty lines between the history and the block.
"""

from __future__ import annotations

from prompt_toolkit.application import Application
from prompt_toolkit.renderer import HeightIsUnknownError, Renderer


def layout_rows(app: Application[None]) -> tuple[int, int]:
    """How many rows the window has and how many the block asks for, the
    second never more than the first."""
    size = app.output.get_size()
    block = app.layout.container.preferred_height(size.columns, size.rows).preferred
    return size.rows, min(block, size.rows)


class FreeRows:
    """The rows right above the block that are known to be empty."""

    def __init__(self, renderer: Renderer) -> None:
        self._count = 0
        # What the count was just before the block was last taken off: the
        # push that writes its rows right after its own erase adds to it.
        self._before_erase = 0
        # The rows the terminal scrolled off the top for the block, which
        # are empty below it once it is smaller again; and the rows above
        # the block as the last drawing left them, the measure of that.
        self._scrolled = 0
        self._scrolled_before_erase = 0
        self._above: int | None = None
        erase = renderer.erase

        def erase_block(leave_alternate_screen: bool = True) -> None:
            self._before_erase, self._count = self._count, 0
            self._scrolled_before_erase, self._scrolled = self._scrolled, 0
            self._above = None
            erase(leave_alternate_screen)

        renderer.erase = erase_block  # type: ignore[method-assign]

    def drew(self, above: int) -> None:
        """Called after every drawing with the rows above the block. A block
        that stands higher than at the drawing before, with nothing taken
        off in between, was scrolled up by the terminal: those rows of the
        history are gone from the window, and the block's rows stand where
        they were."""
        if self._above is not None and above < self._above:
            self._scrolled += self._above - above
        self._above = above

    def scrolled_away(self, missing: int) -> int:
        """Of ``missing`` empty rows below the block, how many the terminal
        scrolled away for it earlier."""
        return min(missing, self._scrolled)

    def pushed(self, rows: int, shifted: int = 0) -> None:
        """Called by the push down, from inside the run that took the block
        off: the rows it left empty before and the ones just written stand
        side by side above the block. ``shifted`` rows of what it made good
        were scrolled ones, which no empty row stands for."""
        self._count = self._before_erase + rows
        self._scrolled = max(0, self._scrolled_before_erase - shifted)

    def grow(self, app: Application[None]) -> bool:
        """Called before every drawing. Moves the block up into the known
        empty rows as far as the drawing needs more rows than the window has
        below the block's top — only as many as are missing, and never more
        than are known. Returns whether it moved the block."""
        if self._count <= 0 or app.is_done:
            return False
        renderer = app.renderer
        if not renderer.height_is_known:
            return False
        try:
            above = renderer.rows_above_layout
        except HeightIsUnknownError:
            return False
        window, block = layout_rows(app)
        rows = min(above + block - window, self._count, above)
        if rows <= 0:
            return False
        known, scrolled = self._count, self._scrolled
        renderer.erase(leave_alternate_screen=False)
        app.output.cursor_up(rows)
        app.output.flush()
        self._count = known - rows
        self._scrolled = scrolled
        # The cursor stands on the block's new top; where the terminal
        # answers is where the next drawing is measured from.
        renderer.request_absolute_cursor_position()
        return True
