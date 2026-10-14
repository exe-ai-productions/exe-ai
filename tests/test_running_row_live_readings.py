"""Under a running answer, speed and cache share come only from the readings
of the running round.

A window that fetches the running row fresh (reload, a second window) holds
the service's snapshot of the rounds so far in the row's `stats`. Those are
added-up numbers of earlier rounds, not the speed of this one, and drawn as
if they were they read as a live figure until the window attaches again —
which it does not while its own send is on the way in the same chat.

The two derived values are lifted out of `Nachricht.svelte` by their real
text and run in node.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.test_hausregeln import _node, _stueck

MESSAGE = Path(__file__).resolve().parent.parent / "frontend/src/teile/Nachricht.svelte"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

# What the service writes into a row that is still running: the readings of
# the rounds so far, added together.
SNAPSHOT = {
    "tokens_pro_sekunde": 50,
    "tempo_quelle": "server",
    "prompt_cache_percent": 98,
    "erstes_token_nach_sekunden": 1.4,
}


def _shown(laeuft: bool, nachricht: dict) -> dict:
    speed = _stueck(
        MESSAGE, r"  const speedReading = \$derived\(.*?\n  \)\n", "speedReading"
    )
    tempo = _stueck(MESSAGE, r"  const tempoWert = \$derived\(.*?\n  \)\n", "tempoWert")
    cache = _stueck(
        MESSAGE, r"  const cachePercent = \$derived\(.*?\n  \)\n", "cachePercent"
    )
    import json

    return _node(f"""
const tempoGemessen = (quelle) => Boolean(quelle)
const $derived = (wert) => wert
const zeigen = (laeuft, nachricht) => {{
  const stats = nachricht.stats || {{}}
{speed}
{tempo}
{cache}
  return {{ tempo: tempoWert, cache: cachePercent }}
}}
console.log(JSON.stringify(zeigen({json.dumps(laeuft)}, {json.dumps(nachricht)})))
""")


@needs_node
def test_a_freshly_fetched_running_row_shows_no_figure_it_did_not_measure_itself():
    got = _shown(True, {"stats": SNAPSHOT, "zustand": "laeuft"})
    assert got == {"tempo": None, "cache": None}


@needs_node
def test_a_running_row_shows_the_readings_of_the_running_round():
    got = _shown(
        True,
        {
            "stats": SNAPSHOT,
            "liveSpeed": {"wert": 31.4, "quelle": "server"},
            "liveShare": 12,
        },
    )
    assert got == {"tempo": 31, "cache": 12}


@needs_node
def test_a_running_row_with_only_one_reading_shows_only_that_one():
    got = _shown(True, {"stats": SNAPSHOT, "liveShare": 0})
    assert got == {"tempo": None, "cache": 0}
    got = _shown(True, {"stats": SNAPSHOT, "liveSpeed": {"wert": 20, "quelle": "server"}})
    assert got == {"tempo": 20, "cache": None}


@needs_node
def test_a_finished_row_shows_the_figures_of_its_stats_as_before():
    got = _shown(False, {"stats": SNAPSHOT})
    assert got == {"tempo": 50, "cache": 98}


@needs_node
def test_a_finished_row_ignores_a_reading_left_over_from_the_run():
    got = _shown(
        False,
        {
            "stats": SNAPSHOT,
            "liveSpeed": {"wert": 31.4, "quelle": "server"},
            "liveShare": 12,
        },
    )
    assert got == {"tempo": 50, "cache": 98}


@needs_node
def test_a_finished_row_without_figures_shows_none():
    assert _shown(False, {"stats": {}}) == {"tempo": None, "cache": None}


def test_the_wait_until_the_first_token_still_comes_from_the_stats():
    """Not touched by this: the figure is the row's own and stays."""
    source = MESSAGE.read_text(encoding="utf-8")
    assert "typeof stats.erstes_token_nach_sekunden === 'number'" in source
