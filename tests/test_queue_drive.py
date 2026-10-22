"""What sets the message queue in motion is one module, called by both pages.

The queue moved only on the desktop page: the phone page never woke it when a
run ended or a chat was switched into, and never stopped a running answer for
a message that waits. Both pages now call `useQueueDrive` while they are made,
so a waiting message goes out the same way on both.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"


def _source(path: str) -> str:
    return (SRC / path).read_text(encoding="utf-8")


def test_both_pages_call_the_drive_once_while_they_are_made():
    for page in ("App.svelte", "phone/ChatView.svelte"):
        text = _source(page)
        assert text.count("useQueueDrive()") == 1, page
        assert re.search(r"import \{ useQueueDrive \} from '(\.\./|\./)lib/queueDrive\.svelte\.js'", text), page


def test_the_drive_holds_the_two_effects_and_the_pages_hold_none_of_them():
    drive = _source("lib/queueDrive.svelte.js")
    assert "untrack(warteschlangeWeiter)" in drive
    assert "untrack(() => interruptForQueued(chatId))" in drive
    assert drive.count("$effect(") == 2
    for page in ("App.svelte", "phone/ChatView.svelte"):
        text = _source(page)
        assert "warteschlangeWeiter" not in text, page
        assert "interruptForQueued" not in text, page


def test_a_message_the_service_turns_away_stays_in_line_and_has_no_way_back_to_the_field_of_its_own():
    run = _source("lib/chatlauf.svelte.js")
    assert "gleichWiederAbgewiesen" not in run and "abgewiesenUm" not in run
    # the one way back to the field from the line is the person's stop
    assert run.count("eingabe.takeBackAll(entries, chatId)") == 1
    assert "if (zurueckInReihe && !run) await pauseOrStop(HALTEPRUEFUNG_MS, wartet.signal)" in run
