"""The picture server's pill says "failed" (English; "Fehler" in German) when
the server was started and is gone: its dot is red, and the word follows the
colour. Checked at the
source, since there is no Svelte runtime harness here."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend/src/teile/Bildserver.svelte"
CATALOGUE = ROOT / "app/locales"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_the_pill_word_for_a_failed_server_is_the_failed_word():
    source = _source()
    derived = re.search(r"const serverText = \$derived\((.*?)\n  \)", source, re.S)
    assert derived, "the pill's word is not derived in one place"
    expression = derived.group(1)
    assert re.search(
        r"server\?\.zustand === 'fehler'\s*\?\s*t\('status\.fehler'\)", expression
    ), "a failed server does not say 'status.fehler'"
    assert "standtext={serverText}" in source


def test_the_other_states_keep_active_and_inactive():
    """The silence side: off is inactive, ready and drawing are active."""
    expression = re.search(r"const serverText = \$derived\((.*?)\n  \)", _source(), re.S).group(1)
    assert re.search(r"serverRunning\s*\?\s*t\('status\.aktiv'\)\s*:\s*t\('status\.inaktiv'\)", expression)
    running = re.search(r"const serverRunning = \$derived\((.*?)\)\n", _source())
    assert running
    assert "'bereit'" in running.group(1) and "'zeichnet'" in running.group(1)
    assert "'fehler'" not in running.group(1)


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
