"""The memory tool: what it writes, and what it refuses.

The interesting half is what it CANNOT do. A tool that can hand over whole
file contents can also wipe the memory in one call, and a rule that slips in
without a yes sits in every later request — that is the difference between a
memory and a permanent prompt injection.
"""

from __future__ import annotations

import asyncio

import pytest

from app.tools import memory
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten


# --- Writing the text, without a disk ----------------------------------------


def test_ein_faktum_landet_unter_seiner_ueberschrift():
    neu = memory.eintragen("", "Arbeitet an einem festen Schreibtisch.", memory.FAKTUM)
    assert "## Facts" in neu
    assert "- Arbeitet an einem festen Schreibtisch." in neu
    assert "## Rules" not in neu


def test_eine_regel_landet_unter_ihrer():
    neu = memory.eintragen("", "Kommentare auf Englisch.", memory.REGEL)
    assert neu.startswith("## Rules")
    assert "- Kommentare auf Englisch." in neu


def test_bestehendes_bleibt_stehen():
    alt = "## Rules\n- Erste Regel.\n\n## Facts\n- Erstes Faktum."
    neu = memory.eintragen(alt, "Zweites Faktum.", memory.FAKTUM)
    assert "- Erste Regel." in neu
    assert "- Erstes Faktum." in neu
    assert "- Zweites Faktum." in neu


def test_dasselbe_zweimal_bleibt_einmal():
    alt = "## Facts\n- Arbeitet am Schreibtisch."
    assert memory.eintragen(alt, "Arbeitet am Schreibtisch.", memory.FAKTUM).count("Arbeitet am Schreibtisch.") == 1


def test_ersetzen_tauscht_statt_anzuhaengen():
    """The case that decides whether the memory gets smarter or only fuller."""
    alt = "## Rules\n- Kommentare auf Deutsch."
    neu = memory.eintragen(
        alt, "Kommentare auf Englisch.", memory.REGEL, ersetzt="Kommentare auf Deutsch."
    )
    assert "Deutsch" not in neu
    assert "- Kommentare auf Englisch." in neu


def test_ersetzen_findet_den_eintrag_auch_unter_der_anderen_ueberschrift():
    """A sentence can change from being knowledge to being an instruction."""
    alt = "## Facts\n- Mag kurze Berichte."
    neu = memory.eintragen(
        alt, "Berichte kurz halten.", memory.REGEL, ersetzt="Mag kurze Berichte."
    )
    assert "Mag kurze Berichte." not in neu
    assert neu.startswith("## Rules")


def test_ein_teiltext_trifft_den_richtigen_eintrag():
    """The model rarely has the exact sentence in front of it — a short part
    of it is enough, and no second entry is left behind."""
    alt = "## Rules\n- Kommentare auf Deutsch.\n\n## Facts\n- Wohnt in Leipzig."
    neu = memory.eintragen(alt, "Wohnt in Dresden.", memory.FAKTUM, ersetzt="Leipzig")
    assert "Leipzig" not in neu
    assert neu.count("Wohnt in") == 1
    assert "- Kommentare auf Deutsch." in neu


def test_ein_ersetzt_wert_ohne_treffer_schreibt_nichts_und_nennt_die_eintraege():
    """Before: the old entry stayed, the new one came on top, and the answer
    was still "Replaced." Now nothing is written and the entries come back."""
    alt = "## Facts\n- Erstes Faktum."
    with pytest.raises(memory.ErsetztNichtEindeutig) as fehler:
        memory.eintragen(alt, "Zweites.", memory.FAKTUM, ersetzt="Gibt es nicht.")
    assert "No entry contains 'Gibt es nicht.'" in str(fehler.value)
    assert "- Erstes Faktum." in fehler.value.eintraege


def test_ein_mehrdeutiger_teiltext_schreibt_nichts():
    alt = "## Facts\n- Mag Kaffee.\n- Mag Tee."
    with pytest.raises(memory.ErsetztNichtEindeutig) as fehler:
        memory.eintragen(alt, "Mag Kakao.", memory.FAKTUM, ersetzt="Mag")
    assert "2 different entries contain 'Mag'" in str(fehler.value)
    assert "- Mag Kaffee." in fehler.value.eintraege and "- Mag Tee." in fehler.value.eintraege


def test_zwei_gleiche_eintraege_sind_kein_mehrdeutiger_treffer():
    """A hand-edited file can hold the same sentence twice, even under both
    headings; replacing it takes every copy, so no stale one stays behind."""
    alt = "## Rules\n- Mag Kaffee.\n\n## Facts\n- Mag Kaffee.\n- Mag Kaffee."
    neu = memory.eintragen(alt, "Mag Tee.", memory.FAKTUM, ersetzt="Kaffee")
    assert "Kaffee" not in neu
    assert neu.count("- Mag Tee.") == 1


def test_der_ganze_eintrag_trifft_auch_wenn_ein_laengerer_ihn_enthaelt():
    alt = "## Facts\n- Mag Tee.\n- Mag Tee nicht mehr morgens."
    neu = memory.eintragen(alt, "Mag Kakao.", memory.FAKTUM, ersetzt="Mag Tee.")
    assert "- Mag Tee.\n" not in neu + "\n"
    assert "- Mag Tee nicht mehr morgens." in neu
    assert "- Mag Kakao." in neu


def test_gross_klein_und_leerraum_entscheiden_nicht():
    alt = "## Facts\n- Wohnt in Leipzig."
    neu = memory.eintragen(alt, "Wohnt in Dresden.", memory.FAKTUM, ersetzt="wohnt  IN leipzig")
    assert "Leipzig" not in neu and "- Wohnt in Dresden." in neu


def test_kopien_in_anderer_schreibweise_sind_ein_eintrag():
    alt = "## Facts\n- Mag Kaffee.\n- mag  Kaffee."
    neu = memory.eintragen(alt, "Mag Tee.", memory.FAKTUM, ersetzt="Kaffee")
    assert "Kaffee" not in neu and neu.count("- Mag Tee.") == 1


def test_derselbe_text_als_ersatz_aendert_nichts():
    alt = "## Rules\n- Erste.\n- Zweite.\n- Dritte."
    assert memory.eintragen(alt, "Erste.", memory.REGEL, ersetzt="Erste.") == alt


def test_ein_blosser_strich_ist_kein_ersetzen(tmp_path):
    pfad = tmp_path / "memory.md"
    pfad.write_text("## Facts\n- Wohnt in Leipzig.\n", encoding="utf-8")
    antwort = asyncio.run(memory.ausfuehren(
        {"text": "Mag Tee.", "kind": "fact", "replaces": "- "}, pfad, zeigen=True
    ))
    assert antwort == "Saved."


def test_der_neue_eintrag_nimmt_den_platz_des_alten():
    """The order the user keeps in the settings window survives a
    correction — the entry is replaced where it stands."""
    alt = "## Rules\n- Erste.\n- Zweite.\n- Dritte."
    neu = memory.eintragen(alt, "Neue erste.", memory.REGEL, ersetzt="Erste")
    assert neu == "## Rules\n- Neue erste.\n- Zweite.\n- Dritte."


# --- Listing, and what it refuses -------------------------------------------


def test_ohne_text_wird_nichts_geschrieben(tmp_path):
    pfad = tmp_path / "memory.md"
    antwort = asyncio.run(memory.ausfuehren({"text": "  ", "kind": "fact"}, pfad, zeigen=True))
    assert "nothing was saved" in antwort
    assert "No entries stored yet." in antwort
    assert not pfad.exists()


def test_ohne_text_listet_es_die_eintraege(tmp_path):
    """The model's way to see what it holds, whether or not the memory block
    travels in its system prompt."""
    pfad = tmp_path / "memory.md"
    pfad.write_text("## Rules\n- Kurz antworten.\n\n## Facts\n- Wohnt in Leipzig.\n", encoding="utf-8")
    vorher = pfad.read_text(encoding="utf-8")
    antwort = asyncio.run(memory.ausfuehren({"text": "", "kind": "fact"}, pfad, zeigen=True))
    assert "## Rules\n- Kurz antworten." in antwort
    assert "## Facts\n- Wohnt in Leipzig." in antwort
    assert pfad.read_text(encoding="utf-8") == vorher


def test_wo_das_gedaechtnis_nicht_mitgeht_zeigt_es_auch_die_liste_nicht(tmp_path):
    """The switch keeps the memory off a side; a listing through the tool is
    the memory, so it stays off there too. Saving still works."""
    pfad = tmp_path / "memory.md"
    pfad.write_text("## Facts\n- Wohnt in Leipzig.\n", encoding="utf-8")
    antwort = asyncio.run(memory.ausfuehren({"text": "", "kind": "fact"}, pfad, zeigen=False))
    assert antwort == memory.VERBORGEN
    with pytest.raises(memory.MemoryVerboten) as fehler:
        asyncio.run(memory.ausfuehren(
            {"text": "Wohnt in Dresden.", "kind": "fact", "replaces": "Berlin"}, pfad, zeigen=False
        ))
    assert "Leipzig" not in str(fehler.value)
    assert memory.VERBORGEN in str(fehler.value)
    # Blind, a guessed part could hit a sentence the model never saw: there
    # only the whole entry names it, as before.
    with pytest.raises(memory.MemoryVerboten) as fehler:
        asyncio.run(memory.ausfuehren(
            {"text": "Wohnt in Dresden.", "kind": "fact", "replaces": "Leipzig"}, pfad, zeigen=False
        ))
    assert "different entries" not in str(fehler.value)
    assert pfad.read_text(encoding="utf-8") == "## Facts\n- Wohnt in Leipzig.\n"
    assert asyncio.run(memory.ausfuehren(
        {"text": "Wohnt in Dresden.", "kind": "fact", "replaces": "Wohnt in Leipzig."}, pfad, zeigen=False
    )) == "Replaced."
    assert pfad.read_text(encoding="utf-8") == "## Facts\n- Wohnt in Dresden.\n"


def test_ein_ersetzen_ohne_treffer_laesst_die_datei_stehen(tmp_path):
    pfad = tmp_path / "memory.md"
    pfad.write_text("## Facts\n- Wohnt in Leipzig.\n", encoding="utf-8")
    vorher = pfad.read_text(encoding="utf-8")
    with pytest.raises(memory.MemoryVerboten) as fehler:
        asyncio.run(memory.ausfuehren(
            {"text": "Wohnt in Dresden.", "kind": "fact", "replaces": "Berlin"}, pfad, zeigen=True
        ))
    assert "- Wohnt in Leipzig." in str(fehler.value)
    assert pfad.read_text(encoding="utf-8") == vorher


def test_ohne_ersetzt_wert_kommt_ein_neuer_eintrag_dazu(tmp_path):
    """The silent case: a plain save still appends as it always did."""
    pfad = tmp_path / "memory.md"
    pfad.write_text("## Facts\n- Wohnt in Leipzig.\n", encoding="utf-8")
    antwort = asyncio.run(memory.ausfuehren({"text": "Mag Tee.", "kind": "fact"}, pfad, zeigen=True))
    assert antwort == "Saved."
    assert pfad.read_text(encoding="utf-8") == "## Facts\n- Wohnt in Leipzig.\n- Mag Tee.\n"


def test_ein_ganzes_dokument_wird_abgewiesen(tmp_path):
    pfad = tmp_path / "memory.md"
    lang = "x" * (memory.MAX_LAENGE + 1)
    with pytest.raises(memory.MemoryVerboten):
        asyncio.run(memory.ausfuehren({"text": lang, "kind": "fact"}, pfad, zeigen=True))
    assert not pfad.exists()


def test_es_gibt_keinen_weg_die_datei_zu_leeren(tmp_path):
    """No parameter hands over whole content and none deletes. Clearing the
    memory is the user's move, in the settings window."""
    felder = set(memory.werkzeug_beschreibung().schema["properties"])
    assert felder == {"text", "kind", "replaces"}


# --- The way through the registry --------------------------------------------


def test_die_registry_bietet_es_an_und_fuehrt_es_aus(tmp_path):
    pfad = tmp_path / "memory.md"
    registry = WerkzeugRegistry([], memory_pfad=pfad)

    namen = [w["function"]["name"] for w in registry.als_openai_werkzeuge()]
    # `goal` and the clock depend on nothing and are therefore always in the
    # offering (app/tools/ziel_werkzeug.py, app/tools/uhr.py) — named here
    # because the list is exact.
    assert namen == ["goal", "get_current_time", memory.WERKZEUG_NAME]

    antwort = asyncio.run(
        registry.ausfuehren(memory.WERKZEUG_NAME, {"text": "Heißt Prüfstein.", "kind": "fact"})
    )
    assert antwort == "Saved."
    assert "- Heißt Prüfstein." in pfad.read_text(encoding="utf-8")
    # The listing only where the caller says the memory travels to its model.
    leer = {"text": "", "kind": "fact"}
    assert asyncio.run(registry.ausfuehren(memory.WERKZEUG_NAME, leer)) == memory.VERBORGEN
    gezeigt = asyncio.run(registry.ausfuehren(memory.WERKZEUG_NAME, leer, gedaechtnis_zeigen=True))
    assert "- Heißt Prüfstein." in gezeigt


def test_ohne_pfad_gibt_es_das_werkzeug_nicht(tmp_path):
    registry = WerkzeugRegistry([])
    namen = [w["function"]["name"] for w in registry.als_openai_werkzeuge()]
    assert memory.WERKZEUG_NAME not in namen
    with pytest.raises(WerkzeugVerboten):
        asyncio.run(registry.ausfuehren(memory.WERKZEUG_NAME, {"text": "x", "kind": "fact"}))


def test_abgeschaltet_wird_es_weder_angeboten_noch_ausgefuehrt(tmp_path):
    registry = WerkzeugRegistry([], memory_pfad=tmp_path / "memory.md")
    registry.abgeschaltet = {memory.WERKZEUG_NAME}
    namen = [w["function"]["name"] for w in registry.als_openai_werkzeuge()]
    assert memory.WERKZEUG_NAME not in namen
    with pytest.raises(WerkzeugVerboten):
        asyncio.run(registry.ausfuehren(memory.WERKZEUG_NAME, {"text": "x", "kind": "fact"}))


def test_die_registry_haelt_das_gedaechtnis_ebenfalls_frei(tmp_path):
    registry = WerkzeugRegistry([], memory_pfad=tmp_path / "memory.md")
    for argumente in ({"text": "x", "kind": "rule"}, {"text": "x", "kind": "fact"}):
        assert registry.braucht_bestaetigung(memory.WERKZEUG_NAME, argumente) is False
        assert registry.bestaetigungsgrund(memory.WERKZEUG_NAME, argumente) is None


# --- A note above the first heading is the person's own -----------------------


def test_a_note_above_the_first_heading_survives_a_save(tmp_path):
    path = tmp_path / "memory.md"
    path.write_text(
        "My own note, written by hand.\nSecond line.\n\n## Rules\n- Be brief.\n",
        encoding="utf-8",
    )
    asyncio.run(memory.ausfuehren({"text": "Lives in Berlin.", "kind": "fact"}, path, zeigen=True))
    assert path.read_text(encoding="utf-8").startswith(
        "My own note, written by hand.\nSecond line.\n\n## Rules\n- Be brief."
    )
    assert "- Lives in Berlin." in path.read_text(encoding="utf-8")


def test_a_file_without_a_note_comes_out_as_before(tmp_path):
    """The silence probe: a file with nothing above its headings comes out
    byte for byte as it did before the note was kept."""
    path = tmp_path / "memory.md"
    path.write_text("## Rules\n- Be brief.\n", encoding="utf-8")
    asyncio.run(memory.ausfuehren({"text": "Lives in Berlin.", "kind": "fact"}, path, zeigen=True))
    assert path.read_text(encoding="utf-8") == "## Rules\n- Be brief.\n\n## Facts\n- Lives in Berlin.\n"


def test_a_note_without_a_gap_stays_as_written(tmp_path):
    """The note is kept byte for byte, gap included — an entry already
    stored is still 'already known' and the file is not rewritten."""
    path = tmp_path / "memory.md"
    path.write_text("My note\n## Rules\n- Be brief.\n", encoding="utf-8")
    answer = asyncio.run(
        memory.ausfuehren({"text": "Be brief.", "kind": "rule"}, path, zeigen=True)
    )
    assert answer == "Already known — nothing changed."
    assert path.read_text(encoding="utf-8") == "My note\n## Rules\n- Be brief.\n"
