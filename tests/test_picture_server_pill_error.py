"""The picture server's page has no pill: its state is the start button and its
dot. The word "failed" ("Fehler" in German) stays for a server that was
started and is gone, in the server overview. Checked at the source, since
there is no Svelte runtime harness here."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend/src/teile/Bildserver.svelte"
CATALOGUE = ROOT / "app/locales"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_the_picture_server_page_carries_no_pill_any_more():
    """The page says nothing of its state in words: the start button and its
    dot do. The word for a failed server stays with the overview."""
    source = _source()
    for gone in ("serverText", "standtext", "standfarbe", "SERVER_COLOURS", "Standpille"):
        assert gone not in source, gone


def test_a_server_is_running_while_ready_or_drawing_and_never_while_failed():
    """The silence side: the button says "Stop" with its green dot while the
    server is ready or drawing, and "Start" otherwise — a failed one included."""
    running = re.search(r"const serverRunning = \$derived\((.*?)\)\n", _source())
    assert running
    assert "'bereit'" in running.group(1) and "'zeichnet'" in running.group(1)
    assert "'fehler'" not in running.group(1)
    assert "punkt: serverRunning ? 'gruen' : 'still'" in _source()


def test_the_failed_word_stands_in_both_languages():
    words = {
        language: json.loads((CATALOGUE / f"{language}.json").read_text(encoding="utf-8"))["status"]
        for language in ("de", "en")
    }
    assert words["de"]["fehler"] == "Fehler"
    assert words["en"]["fehler"] == "failed"
    # Beside the two it sits with: the same group, nothing else changed.
    assert words["de"]["aktiv"] == "aktiv" and words["de"]["inaktiv"] == "inaktiv"
    assert words["en"]["aktiv"] == "active" and words["en"]["inaktiv"] == "inactive"
    # The notice word of the reporting stays as it is.
    notices = {
        language: json.loads((CATALOGUE / f"{language}.json").read_text(encoding="utf-8"))["meldewesen"]
        for language in ("de", "en")
    }
    assert notices["en"]["fehler"] == "Failed"
