"""The search tool: find a pattern inside the shared folders, nothing else.

What matters is the narrowness: the boundary of ``grenzen.py`` holds, the
result is capped instead of endless, binary files and dependency folders are
skipped, and a broken regex still searches instead of erroring out — the
model meant the text literally.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.tools import datei_suchen, dateiwerkzeuge, grenzen


def lauf(coro):
    return asyncio.run(coro)


@pytest.fixture()
def ordner(tmp_path):
    (tmp_path / "notizen").mkdir()
    (tmp_path / "notizen" / "liste.md").write_text(
        "eins\nzwei TREFFER\ndrei\n", encoding="utf-8"
    )
    (tmp_path / "lied.txt").write_text("kein treffer hier\n", encoding="utf-8")
    return [str(tmp_path)]


def test_gehoert_zur_werkzeuggruppe():
    assert datei_suchen in dateiwerkzeuge.MODULE
    assert "search_files" in dateiwerkzeuge.NAMEN


def test_findet_muster_mit_datei_und_zeile(ordner):
    antwort = lauf(datei_suchen.ausfuehren({"pattern": "TREFFER"}, ordner))
    assert f"{Path('notizen', 'liste.md')}:2:" in antwort
    assert "zwei TREFFER" in antwort


def test_gross_klein_egal_ohne_schalter(ordner):
    antwort = lauf(datei_suchen.ausfuehren({"pattern": "treffer"}, ordner))
    assert "liste.md" in antwort
    assert "lied.txt" in antwort


def test_gross_klein_mit_schalter(ordner):
    antwort = lauf(
        datei_suchen.ausfuehren({"pattern": "treffer", "case_sensitive": True}, ordner)
    )
    assert "lied.txt:1:" in antwort
    assert "liste.md" not in antwort


def test_kaputtes_regex_wird_woertlich_gesucht(ordner, tmp_path):
    (tmp_path / "code.py").write_text("wert = liste[0\n", encoding="utf-8")
    antwort = lauf(datei_suchen.ausfuehren({"pattern": "liste[0"}, ordner))
    assert "code.py:1:" in antwort


def test_ohne_muster_wird_abgelehnt(ordner):
    with pytest.raises(grenzen.GrenzeVerletzt):
        lauf(datei_suchen.ausfuehren({}, ordner))


def test_ohne_freigabe_bleibt_zu():
    with pytest.raises(grenzen.GrenzeVerletzt):
        lauf(datei_suchen.ausfuehren({"pattern": "x"}, []))


def test_pfad_ausserhalb_fragt_nach(ordner):
    assert datei_suchen.braucht_bestaetigung({"pattern": "x", "path": "/etc"}, ordner) is True
    assert datei_suchen.braucht_bestaetigung({"pattern": "x"}, ordner) is False


def test_binaerdateien_werden_uebersprungen(ordner, tmp_path):
    (tmp_path / "roh.bin").write_bytes(b"TREFFER\x00TREFFER")
    antwort = lauf(datei_suchen.ausfuehren({"pattern": "TREFFER"}, ordner))
    assert "roh.bin" not in antwort


def test_versteckte_bulk_ordner_werden_uebersprungen(ordner, tmp_path):
    for name in (".git", "node_modules", "__pycache__"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "drin.txt").write_text("TREFFER\n", encoding="utf-8")
    antwort = lauf(datei_suchen.ausfuehren({"pattern": "TREFFER"}, ordner))
    assert "drin.txt" not in antwort


def test_trefferzahl_ist_begrenzt(ordner, tmp_path):
    (tmp_path / "lang.txt").write_text("wort\n" * 500, encoding="utf-8")
    antwort = lauf(datei_suchen.ausfuehren({"pattern": "wort"}, ordner))
    assert antwort.count("lang.txt:") == datei_suchen.MAX_TREFFER
    assert f"stopped at {datei_suchen.MAX_TREFFER}" in antwort


def test_lange_zeilen_werden_gekappt(ordner, tmp_path):
    (tmp_path / "einzeiler.js").write_text("wort " * 500, encoding="utf-8")
    antwort = lauf(datei_suchen.ausfuehren({"pattern": "wort", "path": "einzeiler.js"}, ordner))
    zeile = next(z for z in antwort.splitlines() if z.startswith("einzeiler.js"))
    assert len(zeile) < datei_suchen.MAX_ZEILE_ZEICHEN + 50
    assert zeile.endswith("…")


def test_einzelne_datei_als_ziel(ordner):
    antwort = lauf(
        datei_suchen.ausfuehren({"pattern": "TREFFER", "path": "notizen/liste.md"}, ordner)
    )
    assert "liste.md:2:" in antwort


def test_ohne_treffer_sagt_es_das(ordner):
    antwort = lauf(datei_suchen.ausfuehren({"pattern": "gibtesnicht"}, ordner))
    assert "No matches" in antwort
