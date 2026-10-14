"""The history of a running agent, cut into sentences and rounds, run rather than read.

``lib/agentenverlauf.js`` is plain JavaScript: it turns the lines a run wrote
(thinking, calls, results, sentences) into what stands in view — the agent's
sentences and, between two of them, one row naming the tools of that stretch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
MODUL = FRONTEND / "src/lib/agentenverlauf.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="no Node on this machine",
)

SCHRITTE = [
    {"nummer": 1, "typ": "status", "inhalt": "gestartet"},
    {"nummer": 2, "typ": "reasoning", "inhalt": "ich lese zuerst"},
    {"nummer": 3, "typ": "text", "inhalt": "Ich lese zuerst."},
    {"nummer": 4, "typ": "tool_call", "inhalt": json.dumps({"name": "read_file"})},
    {"nummer": 5, "typ": "tool_result", "inhalt": json.dumps({"name": "read_file", "fehlgeschlagen": False})},
    {"nummer": 6, "typ": "tool_call", "inhalt": json.dumps({"name": "grep"})},
    {"nummer": 7, "typ": "tool_result", "inhalt": json.dumps({"name": "grep", "fehlgeschlagen": True})},
    {"nummer": 8, "typ": "text", "inhalt": "Jetzt schreibe ich."},
    {"nummer": 9, "typ": "werkzeug", "inhalt": "write_file schreibt … 12 Zeichen"},
    {"nummer": 10, "typ": "tool_call", "inhalt": json.dumps({"name": "write_file"})},
]


def _fahren(laeuft: bool, schritte: list[dict] | None = None) -> list[dict]:
    treiber = FRONTEND / f"verlauf-{os.getpid()}.pruefung.mjs"
    treiber.write_text(
        f"""
import {{ verlaufBauen }} from './src/lib/agentenverlauf.js'
const e = verlaufBauen({json.dumps(SCHRITTE if schritte is None else schritte)}, {str(laeuft).lower()})
console.log('---BERICHT---' + JSON.stringify(e.map((x) => x.art === 'satz'
  ? {{ art: 'satz', text: x.text }}
  : {{ art: 'runde', anzahl: x.anzahl, laufend: x.laufend, zustand: x.zustand, schritte: x.schritte.length }})))
""",
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(["node", treiber.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60)
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    return json.loads(lauf.stdout.split("---BERICHT---", 1)[1].strip())


def test_saetze_und_je_runde_eine_zeile_mit_den_werkzeugen():
    bericht = _fahren(laeuft=False)
    assert bericht == [
        {"art": "runde", "anzahl": 0, "laufend": "", "zustand": "still", "schritte": 2},
        {"art": "satz", "text": "Ich lese zuerst."},
        # two calls, one of them failed: the worst state wins
        {"art": "runde", "anzahl": 2, "laufend": "", "zustand": "rot", "schritte": 4},
        {"art": "satz", "text": "Jetzt schreibe ich."},
        # a call that was being written and then made: one call, not two
        {"art": "runde", "anzahl": 1, "laufend": "", "zustand": "gruen", "schritte": 2},
    ]


def test_nur_die_letzte_runde_eines_laufenden_laufs_laeuft():
    bericht = _fahren(laeuft=True)
    # Silence probe: the finished stretches never claim to be running.
    assert [r["laufend"] for r in bericht if r["art"] == "runde"] == ["", "", "write_file"]
    assert bericht[-1]["zustand"] == "blau"


def _aufruf(nummer: int, name: str) -> list[dict]:
    return [
        {"nummer": nummer, "typ": "tool_call", "inhalt": json.dumps({"name": name})},
        {"nummer": nummer + 1, "typ": "tool_result", "inhalt": json.dumps({"name": name, "fehlgeschlagen": False})},
    ]


@pytest.mark.parametrize("leer", ["\n\n", "", "  \n\t", "\u00a0\n"])
def test_ein_leerer_satz_ist_kein_satz_und_teilt_die_runde_nicht(leer):
    """A line break before a call is a `text` step with nothing to read: no
    ring, and the two calls stay in one row."""
    schritte = [
        *_aufruf(1, "read_file"),
        {"nummer": 3, "typ": "text", "inhalt": leer},
        *_aufruf(4, "grep"),
    ]
    bericht = _fahren(laeuft=False, schritte=schritte)
    # the empty step stays among the steps of the row, behind the click
    assert bericht == [{"art": "runde", "anzahl": 2, "laufend": "", "zustand": "gruen", "schritte": 5}]


def test_vier_aufrufe_mit_je_einem_umbruch_dazwischen_sind_eine_zeile():
    schritte: list[dict] = []
    nummer = 1
    for index, name in enumerate(["a", "b", "c", "d"]):
        if index:
            schritte.append({"nummer": nummer, "typ": "text", "inhalt": "\n"})
            nummer += 1
        schritte += _aufruf(nummer, name)
        nummer += 2
    bericht = _fahren(laeuft=False, schritte=schritte)
    assert bericht == [{"art": "runde", "anzahl": 4, "laufend": "", "zustand": "gruen", "schritte": 11}]


def test_ein_leerer_satz_vor_dem_ersten_aufruf_steht_bei_den_schritten():
    schritte = [{"nummer": 1, "typ": "text", "inhalt": "\n"}, *_aufruf(2, "grep")]
    bericht = _fahren(laeuft=False, schritte=schritte)
    assert bericht == [{"art": "runde", "anzahl": 1, "laufend": "", "zustand": "gruen", "schritte": 3}]


def test_ein_satz_mit_sichtbarem_text_teilt_weiter_und_bleibt_im_wortlaut():
    """Silence probe: a sentence with something to read keeps splitting, and
    its text is not trimmed."""
    schritte = [
        *_aufruf(1, "read_file"),
        {"nummer": 3, "typ": "text", "inhalt": "  Jetzt der zweite.\n"},
        *_aufruf(4, "grep"),
    ]
    bericht = _fahren(laeuft=False, schritte=schritte)
    assert bericht == [
        {"art": "runde", "anzahl": 1, "laufend": "", "zustand": "gruen", "schritte": 2},
        {"art": "satz", "text": "  Jetzt der zweite.\n"},
        {"art": "runde", "anzahl": 1, "laufend": "", "zustand": "gruen", "schritte": 2},
    ]
