"""Turns two versions of a file's text into the change block a tool result
carries alongside its one-sentence summary — built with difflib's own
unified-diff format, no new dependency.
"""

from __future__ import annotations

import difflib

# How many lines of a change block are shown before it is cut short. Silent
# truncation would read as "this is everything" when it is not, so what is
# left out says so instead of just disappearing.
ZEILENGRENZE = 200


def bauen(alt: str, neu: str) -> str:
    """A unified diff without the `---`/`+++` file header lines — the tool's
    own sentence already names the file, so the block starts at the first
    hunk. Empty if the two texts do not actually differ.
    """
    zeilen = list(
        difflib.unified_diff(alt.splitlines(), neu.splitlines(), n=3, lineterm="")
    )[2:]
    if not zeilen:
        return ""
    if len(zeilen) > ZEILENGRENZE:
        rest = len(zeilen) - ZEILENGRENZE
        zeilen = zeilen[:ZEILENGRENZE] + [f"… {rest} more lines"]
    return "\n".join(zeilen)
