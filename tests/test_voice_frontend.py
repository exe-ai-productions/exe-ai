"""The page's side of the kept voice, pinned in the sources: the conversation
announces itself at its start and repeats the announcement, gives the voice
back when it ends or the page goes away, and the switch sits in the
conversation group directly under "Read answers aloud"."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.voice_service import HOLD_SECONDS

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"


def _read(*parts: str) -> str:
    return (SRC.joinpath(*parts)).read_text(encoding="utf-8")


def test_api_calls_both_routes_and_the_release_survives_the_page() -> None:
    api = _read("lib", "api.js")
    assert "'/sprachserver/voice/hold'" in api
    release = re.search(r"voiceRelease:[^\n]*", api)
    assert release is not None
    # The release is sent while the page is going away: it must outlive it.
    assert "keepalive: true" in release.group(0)
    assert "'/sprachserver/voice/release'" in release.group(0)


def test_announcement_repeats_often_enough_to_hold_for_the_whole_conversation() -> None:
    bar = _read("teile", "Eingabeleiste.svelte")
    found = re.search(r"const VOICE_HOLD_MS = ([\d_]+)", bar)
    assert found is not None
    interval = int(found.group(1).replace("_", ""))
    # Three announcements may be lost before the service lets go.
    assert interval * 3 <= HOLD_SECONDS * 1000
    assert "setInterval(announce, VOICE_HOLD_MS)" in bar


def test_conversation_announces_at_start_and_releases_at_end_and_on_page_exit() -> None:
    bar = _read("teile", "Eingabeleiste.svelte")
    start = re.search(r"gespraechAn = true\n(?:[^\n]*\n){0,6}?\s*voiceKeepStart\(\)", bar)
    assert start is not None, "the conversation must announce itself when it starts"
    ending = re.search(r"function gespraechBeenden\([^)]*\) \{(.*?)\n  \}", bar, re.S)
    assert ending is not None and "voiceKeepStop()" in ending.group(1)
    assert "addEventListener('pagehide', leave)" in bar
    assert "removeEventListener('pagehide', leave)" in bar


def test_switch_sits_directly_under_read_aloud_in_the_conversation_group() -> None:
    panel = _read("teile", "Sprachserver.svelte")
    read_aloud = panel.index("t('sprachserver.feld_vorlesen')")
    keep = panel.index("t('sprachserver.keep_model_loaded')")
    assert read_aloud < keep
    # Nothing else of the group lies between the two rows.
    between = panel[read_aloud:keep]
    assert between.count("<Schalter") <= 1
    assert "sichern({ keep_model_in_memory: neu })" in panel


def test_setting_is_mirrored_and_sent_with_the_whole_choice() -> None:
    store = _read("lib", "diktat.svelte.js")
    assert "keep_model_in_memory: null" in store
    assert "keep_model_in_memory: diktat.keep_model_in_memory" in store
    assert "typeof w.keep_model_in_memory === 'boolean'" in store


def test_texts_exist_in_both_catalogues() -> None:
    for name in ("de", "en"):
        catalogue = json.loads((ROOT / "app" / "locales" / f"{name}.json").read_text(encoding="utf-8"))
        assert catalogue["sprachserver"]["keep_model_loaded"].strip()
