"""Shapes shared by the commands that put rows in the history."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from rich.console import RenderableType
from rich.table import Table

from cli import glyphs


def grid(rows: Iterable[Iterable[RenderableType]], *, wide: int | None = None) -> Table:
    """Rows in columns, every column as wide as its widest cell.

    ``wide`` names the one column that gives way where the window is too
    narrow for all of them: its cells are carried on below, in their own
    column, so nothing of them is lost and the columns beside it keep their
    width. Without one, a row that does not fit is cut.
    """
    table = Table.grid(padding=(0, 2))
    for row in rows:
        cells = list(row)
        while len(table.columns) < len(cells):
            if len(table.columns) == wide:
                table.add_column(overflow="fold")
            else:
                table.add_column(no_wrap=True, overflow=glyphs.overflow())
        table.add_row(*cells)
    return table


def one_line(value: Any) -> str:
    """A value as it stands in one cell. A word stands as itself; an empty
    one is written out, so its cell does not look like a missing value."""
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    return json.dumps(value, ensure_ascii=False)
