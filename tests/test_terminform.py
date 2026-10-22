"""The shapes of a schedule, read in one place (frontend/src/lib/terminform.js).

The schedule card and the form both read a schedule through this module: the
time a card leads with, and the day of a fixed moment. Run in Node, not
matched as text.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODUL = FRONTEND / "src/lib/terminform.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")

TREIBER = """
const m = await import(%r)
const bericht = {
  uhrzeit: ['08:00', '0 * * * *', '2026-09-04T09:30', 'unsinn'].map(m.uhrzeit),
  datum: ['08:00', '2026-09-04T09:30'].map(m.datum),
  gelesen: ['9:07', '09:07', '09.07', ' 9:07 ', '0:00', '23:59', '25:00', '9:60', '24:00', '907', '9', 'abc', '', null].map(m.readTime),
  zeiten: { anzahl: m.TIMES.length, erste: m.TIMES[0], letzte: m.TIMES[m.TIMES.length - 1], viertel: m.TIMES.slice(0, 5), gueltig: m.TIMES.every((t) => m.readTime(t) === t) },
}
console.log('---BERICHT---' + JSON.stringify(bericht))
"""


def _bericht() -> dict:
    treiber = FRONTEND / "terminform.pruefung.mjs"
    treiber.write_text(TREIBER % MODUL.as_uri(), encoding="utf-8")
    try:
        lauf = subprocess.run(["node", treiber.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60)
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    return json.loads(lauf.stdout.split("---BERICHT---", 1)[1].strip())


def test_die_formen_eines_zeitplans():
    bericht = _bericht()
    assert bericht["uhrzeit"] == ["08:00", "", "09:30", ""]
    assert bericht["datum"] == ["", "2026-09-04"]


def test_a_typed_time_is_read_and_an_impossible_one_is_not():
    bericht = _bericht()
    assert bericht["gelesen"] == [
        "09:07", "09:07", "09:07", "09:07", "00:00", "23:59",
        None, None, None, None, None, None, None, None,
    ]


def test_the_list_of_times_has_every_quarter_hour_and_each_one_reads_back():
    zeiten = _bericht()["zeiten"]
    assert zeiten["anzahl"] == 96
    assert (zeiten["erste"], zeiten["letzte"]) == ("00:00", "23:45")
    assert zeiten["viertel"] == ["00:00", "00:15", "00:30", "00:45", "01:00"]
    assert zeiten["gueltig"] is True
