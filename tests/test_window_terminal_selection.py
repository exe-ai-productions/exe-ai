"""The tab's terminal marks text with the Option key held down, on a Mac.

The client runs on a full screen and takes the mouse — its wheel scrolls
the history, a click opens an address — so a drag alone is the client's.
The drawing marks regardless of that only where it is told to: this is read
off the source, as the neighbouring tests of the terminal do."""

from __future__ import annotations

from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "lib" / "windowTerminal.js"


def test_the_option_key_forces_the_selection_where_the_client_takes_the_mouse():
    assert "macOptionClickForcesSelection: true" in SOURCE.read_text(encoding="utf-8")


def test_the_option_click_does_not_move_the_cursor_of_the_client():
    """Marking with the Option key would otherwise send arrow keys to the
    client, which recalls old lines into its input field."""
    assert "altClickMovesCursor: false" in SOURCE.read_text(encoding="utf-8")
