"""The context ring measures against the window the model reports — also
when that window is the fallback of 128,000 tokens a server without any
source of its own gets (`app/fenstergroesse.py`, ``ERSATZ``).

The backend half is pinned in tests/test_discovery.py (the test of the
fallback value without any source); nothing pinned the display
half. `kontextStand` from `frontend/src/lib/zustand.svelte.js` is lifted out,
with the three functions it reads, and run in node, the same way
tests/test_seitenleiste_schmales_fenster.py runs `seitenleisteSchalten`. The
numbers are written here rather than imported: what is checked is the share
of the window the model reports, whatever the backend fills in.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend/src/lib/zustand.svelte.js"
FALLBACK_WINDOW = 128_000

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="no node on this machine"
)


@functools.cache
def _snippets() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    parts = []
    for name, pattern in (
        ("aktuellesModell", r"\nexport function aktuellesModell\(\) \{\n.*?\n\}\n"),
        ("nachrichtenAnzeige", r"\nexport function nachrichtenAnzeige\(\) \{\n.*?\n\}\n"),
        ("gesamtTokensVon", r"\nfunction gesamtTokensVon\(nachricht\) \{\n.*?\n\}\n"),
        ("kontextStand", r"\nexport function kontextStand\(\) \{\n.*?\n\}\n"),
    ):
        match = re.search(pattern, source, re.S)
        assert match, f"{name} not found in {SOURCE.name}"
        parts.append(match.group(0).strip() + "\n")
    return "".join(parts)


def _context(
    model: dict,
    messages: list[dict],
    running: dict | None = None,
    rows_of: str = "c",
) -> dict:
    """``kontextStand()`` for one model, the rows in the list (belonging to
    chat ``rows_of``; the open chat is "c") and, if given, the placeholder of
    an answer still running."""
    state = {
        "modelle": [{"id": "m", **model}],
        "modellId": "m",
        "aktiverChat": "c",
        "nachrichtenChatId": rows_of,
        "nachrichten": messages,
        "laufenderPlatzhalter": {"c": running} if running else {},
    }
    script = f"""
const zustand = {json.dumps(state)};
{_snippets()}
console.log(JSON.stringify(kontextStand()));
"""
    run = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30
    )
    assert run.returncode == 0, f"{run.stderr}\n{run.stdout}"
    return json.loads(run.stdout)


def _answer(tokens: int) -> dict:
    return {"rolle": "assistant", "zustand": "fertig", "gesamt_tokens": tokens}


def test_half_of_the_fallback_window_is_fifty_percent():
    state = _context({"context_tokens": FALLBACK_WINDOW}, [_answer(64_000)])
    assert state == {"genutzt": 64_000, "gesamt": FALLBACK_WINDOW, "anteil": 50}


def test_a_running_answer_is_measured_against_the_same_window():
    """While an answer runs, its placeholder is the reading, not the last
    finished row."""
    state = _context(
        {"context_tokens": FALLBACK_WINDOW},
        [_answer(10_000)],
        running={"rolle": "assistant", "zustand": "laeuft", "gesamt_tokens": 96_000},
    )
    assert state == {"genutzt": 96_000, "gesamt": FALLBACK_WINDOW, "anteil": 75}


def test_without_a_reported_window_there_is_no_total_and_no_share():
    """The silence probe: no window — or a window of zero — gives no total
    and no share. ContextRing.svelte shows nothing without a total."""
    for model in ({}, {"context_tokens": 0}):
        state = _context(model, [_answer(64_000)])
        assert state["gesamt"] is None, model
        assert state["anteil"] == 0, model


def test_more_used_than_the_window_holds_stops_at_one_hundred():
    state = _context({"context_tokens": FALLBACK_WINDOW}, [_answer(200_000)])
    assert state["anteil"] == 100


def test_rows_of_another_chat_are_not_read():
    """The list still holds the previous chat while the new one loads; its
    reading must not show up here."""
    state = _context(
        {"context_tokens": FALLBACK_WINDOW}, [_answer(64_000)], rows_of="previous"
    )
    assert state["genutzt"] == 0 and state["anteil"] == 0
