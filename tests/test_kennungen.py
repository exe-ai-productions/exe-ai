"""Names that exist twice, once on each side of the wire.

A constant the service writes and the window reads is one name in two files.
Rename one and three readouts go quiet — the header's dot, the input bar's
lightning and its eye — without anything going red, because no test ever read
both files in the same breath. This one does.
"""

from __future__ import annotations

import re
from pathlib import Path

from app import runnerzustand

WURZEL = Path(__file__).resolve().parents[1]
SERVERZUSTAND = WURZEL / "frontend" / "src" / "lib" / "serverzustand.svelte.js"

# Loose on spelling, strict on the name: a semicolon, double quotes, an
# `export` in front or any reformatting must not turn "the two agree" into a
# false alarm. What has to be exact is the value.
CHAT_IM_FENSTER = re.compile(
    r"""^(?:export\s+)?const CHAT\s*=\s*['"]([^'"]*)['"];?\s*$""", re.MULTILINE
)


def test_der_chat_server_heisst_auf_beiden_seiten_gleich():
    """The announcement names the server it speaks for, and the window keeps
    only the announcements for this one. Two spellings mean silence."""
    quelle = SERVERZUSTAND.read_text(encoding="utf-8")
    treffer = CHAT_IM_FENSTER.findall(quelle)
    assert treffer == [runnerzustand.CHAT], (treffer, runnerzustand.CHAT)
