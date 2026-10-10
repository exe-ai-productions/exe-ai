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
}
console.log('---BERICHT---' + JSON.stringify(bericht))
"""


def test_die_formen_eines_zeitplans():
    treiber = FRONTEND / "terminform.pruefung.mjs"
    treiber.write_text(TREIBER % MODUL.as_uri(), encoding="utf-8")
    try:
        lauf = subprocess.run(["node", treiber.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60)
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    bericht = json.loads(lauf.stdout.split("---BERICHT---", 1)[1].strip())
    assert bericht["uhrzeit"] == ["08:00", "", "09:30", ""]
    assert bericht["datum"] == ["", "2026-09-04"]
