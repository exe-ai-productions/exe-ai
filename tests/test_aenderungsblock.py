"""The shared change block edit_file and write_file both attach to their
one-sentence summary — built with difflib, checked on its own so the two
tools do not each need to prove the same shape.
"""

from __future__ import annotations

from app.tools import aenderungsblock


def test_ohne_unterschied_bleibt_es_leer():
    assert aenderungsblock.bauen("gleich\n", "gleich\n") == ""


def test_beginnt_bei_der_ersten_kurzstelle_ohne_dateikopf():
    block = aenderungsblock.bauen("eins\nzwei\ndrei\n", "eins\nZWEI\ndrei\n")
    zeilen = block.splitlines()
    assert zeilen[0].startswith("@@")
    assert "-zwei" in zeilen
    assert "+ZWEI" in zeilen
    assert " eins" in zeilen  # context line, untouched


def test_sehr_grosse_aenderung_wird_sichtbar_gekuerzt():
    alt = "\n".join(f"zeile {n}" for n in range(300)) + "\n"
    neu = "\n".join(f"ZEILE {n}" for n in range(300)) + "\n"
    block = aenderungsblock.bauen(alt, neu)
    zeilen = block.splitlines()
    assert len(zeilen) == aenderungsblock.ZEILENGRENZE + 1
    assert zeilen[-1].startswith("… ") and "more lines" in zeilen[-1]
