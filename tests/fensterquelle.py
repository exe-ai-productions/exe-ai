"""The source a test reads to ask what the chat window does.

The window (`frontend/src/App.svelte`) hands the run of the chat — sending,
the answer, stopping, the queue — to `frontend/src/lib/chatlauf.svelte.js`,
and what the list shows of it — the waiting mark, the clocks, the picture
tiles — to `frontend/src/lib/chatansicht.svelte.js`; what sets the queue in motion lives in
`frontend/src/lib/queueDrive.svelte.js`; the phone page uses all three. A test that lifts one of those
functions out of the window's text reads the files as one text, so it keeps
asking the same question: what does the window do when a question is sent.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOW = ROOT / "frontend/src/App.svelte"
RUN = ROOT / "frontend/src/lib/chatlauf.svelte.js"
VIEW = ROOT / "frontend/src/lib/chatansicht.svelte.js"
DRIVE = ROOT / "frontend/src/lib/queueDrive.svelte.js"
BAR = ROOT / "frontend/src/teile/Eingabeleiste.svelte"
BAR_STORE = ROOT / "frontend/src/lib/eingabe.svelte.js"
BAR_CARD = ROOT / "frontend/src/lib/fragekarte.svelte.js"


class WindowSource:
    """Stands in for the window's file: `read_text()` gives the window and
    the three modules one after the other."""

    name = WINDOW.name

    def read_text(self, encoding: str = "utf-8") -> str:
        return "\n".join(path.read_text(encoding=encoding) for path in (WINDOW, RUN, VIEW, DRIVE))

    def __str__(self) -> str:
        return str(WINDOW)


WINDOW_SOURCE = WindowSource()


class BarSource:
    """The same for the bar under a chat (`frontend/src/teile/Eingabeleiste.svelte`):
    its draft, attachments, send and dictation live in
    `frontend/src/lib/eingabe.svelte.js`, the question card in
    `frontend/src/lib/fragekarte.svelte.js`; the phone page fills both as well."""

    name = BAR.name

    def read_text(self, encoding: str = "utf-8") -> str:
        # The store first: the bar keeps thin wrappers of the same names.
        return "\n".join(path.read_text(encoding=encoding) for path in (BAR_STORE, BAR_CARD, BAR))

    def __str__(self) -> str:
        return str(BAR)


BAR_SOURCE = BarSource()
