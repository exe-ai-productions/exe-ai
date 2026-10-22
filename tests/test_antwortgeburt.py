"""The answer row's early birth, and where a document is uploaded now.

Documents used to upload and get read inside senden() itself, which is why
the answer row was born before that read — its own wait would otherwise
have pushed the chat's one mark slot down mid-wait. Now a
document is uploaded the moment it is attached (Eingabeleiste.svelte), not
on send: senden() receives it already read, so that early-birth step is
gone from there — antwortHolen()'s own normal placeholder creation covers
every message the same way now, document or not. Source-text guards below
for what is still true: where the upload call itself lives, and that the
chat stays marked busy for the stretch an image upload can still take.
"""

from __future__ import annotations

import re
from pathlib import Path
from tests.fensterquelle import BAR_SOURCE, WINDOW_SOURCE

WURZEL = Path(__file__).resolve().parent.parent
APP = WINDOW_SOURCE.read_text()
EINGABELEISTE = BAR_SOURCE.read_text()


def test_dokument_upload_lebt_in_der_eingabeleiste_nicht_mehr_in_app():
    """senden() takes `dokumente` as already-read meta — the network call
    that used to sit inside it moved to where the attachment happens."""
    assert "api.dokumentHochladen" in EINGABELEISTE, (
        "dokumentSetzen no longer calls the upload route"
    )
    senden = APP[APP.index("async function senden("):APP.index("\n  async function antwortHolen(")]
    assert "api.dokumentHochladen" not in senden, (
        "senden() still uploads documents itself"
    )


def test_der_upload_haelt_den_chat_besetzt():
    """Between enter and the run, `laufVon` is empty; a second enter used
    to walk straight into senden() again and bear a second row with the
    same placeholder id. The send marks the chat in `zustand.sendet` for
    that stretch: the input bar queues on it, the queue waits on it, and
    the finally releases it whatever happened."""
    assert re.search(
        r"const sendeChat = zustand\.aktiverChat\n.*?zustand\.sendet\[sendeChat\] = true\n\s+try \{",
        APP,
        re.S,
    ), "senden() no longer claims the chat before the upload"
    assert "delete zustand.sendet[sendeChat]" in APP, "the lock is never released"
    assert "laufVon(chatId) || zustand.sendet[chatId]) return" in APP, (
        "the queue fires into the lock"
    )
    assert "zustand.sendet[zustand.aktiverChat]" in EINGABELEISTE, (
        "the input bar does not queue during the upload"
    )
