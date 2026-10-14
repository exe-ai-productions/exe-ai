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
        erase = renderer.erase

        def erase_block(leave_alternate_screen: bool = True) -> None:
            self._before_erase, self._count = self._count, 0
            erase(leave_alternate_screen)

        renderer.erase = erase_block  # type: ignore[method-assign]

    def pushed(self, rows: int) -> None:
        """Called by the push down, from inside the run that took the block
        off: the rows it left empty before and the ones just written stand
        side by side above the block."""
        self._count = self._before_erase + rows

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
        known = self._count
        renderer.erase(leave_alternate_screen=False)
        app.output.cursor_up(rows)
        app.output.flush()
        self._count = known - rows
        # The cursor stands on the block's new top; where the terminal
        # answers is where the next drawing is measured from.
        renderer.request_absolute_cursor_position()
        return True
