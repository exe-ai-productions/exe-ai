"""The memory tool: what it writes, and what it refuses.

The interesting half is what it CANNOT do. A tool that can hand over whole
file contents can also wipe the memory in one call, so a delete names ONE
entry by a part of its text and refuses a part that points at several; and
the memory has one size, so a write that would take it past the line is
refused, with the entries in the answer.
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
    assert "2 entries contain 'Mag'." in str(fehler.value)
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
        {"text": "Mag Tee.", "kind": "fact", "replaces": "- "}, pfad
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
    with pytest.raises(memory.MemoryVerboten) as fehler:
        asyncio.run(memory.ausfuehren({"text": "  ", "kind": "fact"}, pfad))
    assert "nothing was changed" in str(fehler.value)
    assert not pfad.exists()


def test_an_empty_text_is_an_error_and_not_a_listing(tmp_path):
    """The way through an empty text used to hand the entries over; the
    entries stand in the system prompt, so the way is gone and the call fails
    with a sentence that says what to pass instead."""
    pfad = tmp_path / "memory.md"
    pfad.write_text("## Rules\n- Kurz antworten.\n\n## Facts\n- Wohnt in Leipzig.\n", encoding="utf-8")
    vorher = pfad.read_text(encoding="utf-8")
    for argumente in (
        {"text": "", "kind": "fact"},
        {"text": "", "kind": "fact", "replaces": "Leipzig"},
    ):
        with pytest.raises(memory.MemoryVerboten) as fehler:
            asyncio.run(memory.ausfuehren(argumente, pfad))
        assert "Kurz antworten" not in str(fehler.value)
        assert "'remove'" in str(fehler.value)
    assert pfad.read_text(encoding="utf-8") == vorher


def test_ein_ersetzen_ohne_treffer_laesst_die_datei_stehen(tmp_path):
    pfad = tmp_path / "memory.md"
    pfad.write_text("## Facts\n- Wohnt in Leipzig.\n", encoding="utf-8")
    vorher = pfad.read_text(encoding="utf-8")
    with pytest.raises(memory.MemoryVerboten) as fehler:
        asyncio.run(memory.ausfuehren(
            {"text": "Wohnt in Dresden.", "kind": "fact", "replaces": "Berlin"}, pfad
        ))
    assert "- Wohnt in Leipzig." in str(fehler.value)
    assert pfad.read_text(encoding="utf-8") == vorher


def test_ohne_ersetzt_wert_kommt_ein_neuer_eintrag_dazu(tmp_path):
    """The silent case: a plain save still appends as it always did."""
    pfad = tmp_path / "memory.md"
    pfad.write_text("## Facts\n- Wohnt in Leipzig.\n", encoding="utf-8")
    antwort = asyncio.run(memory.ausfuehren({"text": "Mag Tee.", "kind": "fact"}, pfad))
    assert antwort == "Saved."
    assert pfad.read_text(encoding="utf-8") == "## Facts\n- Wohnt in Leipzig.\n- Mag Tee.\n"


def test_ein_ganzes_dokument_wird_abgewiesen(tmp_path):
    pfad = tmp_path / "memory.md"
    lang = "x" * (memory.MAX_LAENGE + 1)
    with pytest.raises(memory.MemoryVerboten):
        asyncio.run(memory.ausfuehren({"text": lang, "kind": "fact"}, pfad))
    assert not pfad.exists()


def test_the_tool_takes_a_text_a_kind_and_two_parts_of_an_entry():
    """No parameter hands over whole content: a delete names one entry by a
    part of its text. Clearing the memory in one go is the user's move, in
    the settings window."""
    felder = set(memory.werkzeug_beschreibung().schema["properties"])
    assert felder == {"text", "kind", "replaces", "remove"}
    assert memory.werkzeug_beschreibung().schema["required"] == []


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
        registry.ausfuehren(
            memory.WERKZEUG_NAME, {"text": "Heißt Prüfstein.", "kind": "fact"},
            gedaechtnis_zeigen=True,
        )
    )
    assert antwort == "Saved."
    assert "- Heißt Prüfstein." in pfad.read_text(encoding="utf-8")
    geloescht = asyncio.run(
        registry.ausfuehren(
            memory.WERKZEUG_NAME, {"remove": "Prüfstein"}, gedaechtnis_zeigen=True
        )
    )
    assert geloescht == "Removed."
    assert "Prüfstein" not in pfad.read_text(encoding="utf-8")


def test_where_the_memory_does_not_travel_the_tool_is_neither_offered_nor_run(tmp_path):
    pfad = tmp_path / "memory.md"
    pfad.write_text("## Facts\n- Wohnt in Leipzig.\n", encoding="utf-8")
    registry = WerkzeugRegistry([], memory_pfad=pfad)

    namen = [w["function"]["name"] for w in registry.als_openai_werkzeuge(memory_shown=False)]
    assert memory.WERKZEUG_NAME not in namen

    # A run that calls it all the same is refused, whatever the call says, and
    # neither a save nor a replacement nor a listing happens.
    for argumente in (
        {"text": "Mag Tee.", "kind": "fact"},
        {"text": "Wohnt in Dresden.", "kind": "fact", "replaces": "Leipzig"},
        {"remove": "Leipzig"},
    ):
        with pytest.raises(WerkzeugVerboten) as fehler:
            asyncio.run(registry.ausfuehren(memory.WERKZEUG_NAME, argumente))
        assert "Leipzig" not in str(fehler.value)
    assert pfad.read_text(encoding="utf-8") == "## Facts\n- Wohnt in Leipzig.\n"


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


# --- Deleting -------------------------------------------------------------------


def _file(tmp_path, content: str):
    pfad = tmp_path / "memory.md"
    pfad.write_text(content, encoding="utf-8")
    return pfad


def test_a_delete_takes_out_exactly_the_entry_a_part_of_its_text_points_at(tmp_path):
    pfad = _file(
        tmp_path, "## Rules\n- Kurz antworten.\n\n## Facts\n- Wohnt in Leipzig.\n- Mag Tee.\n"
    )
    antwort = asyncio.run(memory.ausfuehren({"remove": "leipzig"}, pfad))
    assert antwort == "Removed."
    assert pfad.read_text(encoding="utf-8") == "## Rules\n- Kurz antworten.\n\n## Facts\n- Mag Tee.\n"


def test_a_delete_finds_the_entry_under_either_heading(tmp_path):
    pfad = _file(tmp_path, "## Rules\n- Kurz antworten.\n\n## Facts\n- Mag Tee.\n")
    asyncio.run(memory.ausfuehren({"remove": "Kurz"}, pfad))
    assert pfad.read_text(encoding="utf-8") == "## Facts\n- Mag Tee.\n"


def test_a_delete_that_points_at_none_or_at_several_changes_nothing_and_names_the_entries(tmp_path):
    pfad = _file(tmp_path, "## Facts\n- Wohnt in Leipzig.\n- Mag Tee in Leipzig.\n")
    vorher = pfad.read_text(encoding="utf-8")
    for teil, grund in (("Berlin", "No entry contains"), ("Leipzig", "2 entries contain")):
        with pytest.raises(memory.MemoryVerboten) as fehler:
            asyncio.run(memory.ausfuehren({"remove": teil}, pfad))
        assert grund in str(fehler.value)
        assert "- Wohnt in Leipzig." in str(fehler.value)
        assert "'remove'" in str(fehler.value)
        assert pfad.read_text(encoding="utf-8") == vorher


def test_a_part_every_entry_contains_cannot_wipe_the_memory(tmp_path):
    pfad = _file(tmp_path, "## Facts\n- Eins e.\n- Zwei e.\n- Drei e.\n")
    vorher = pfad.read_text(encoding="utf-8")
    with pytest.raises(memory.MemoryVerboten):
        asyncio.run(memory.ausfuehren({"remove": "e"}, pfad))
    assert pfad.read_text(encoding="utf-8") == vorher


def test_a_delete_takes_no_text(tmp_path):
    pfad = _file(tmp_path, "## Facts\n- Mag Tee.\n")
    vorher = pfad.read_text(encoding="utf-8")
    with pytest.raises(memory.MemoryVerboten) as fehler:
        asyncio.run(memory.ausfuehren({"remove": "Tee", "text": "Mag Kaffee.", "kind": "fact"}, pfad))
    assert "takes no 'text'" in str(fehler.value)
    assert pfad.read_text(encoding="utf-8") == vorher


def test_a_delete_keeps_what_the_person_wrote_into_the_file(tmp_path):
    inhalt = "Meine Notiz.\n\n## Facts\n- Mag Tee.\n- Wohnt in Leipzig.\n\n## Mein Abschnitt\nbleibt\n"
    pfad = _file(tmp_path, inhalt)
    asyncio.run(memory.ausfuehren({"remove": "Tee"}, pfad))
    neu = pfad.read_text(encoding="utf-8")
    assert neu.startswith("Meine Notiz.\n\n## Facts\n- Wohnt in Leipzig.")
    assert "## Mein Abschnitt\nbleibt" in neu
    assert "Tee" not in neu


def test_silence_a_save_with_text_goes_on_as_before_and_the_blank_remove_is_none(tmp_path):
    pfad = _file(tmp_path, "## Facts\n- Mag Tee.\n")
    assert asyncio.run(memory.ausfuehren({"text": "Mag Kaffee.", "kind": "fact", "remove": ""}, pfad)) == "Saved."
    assert pfad.read_text(encoding="utf-8") == "## Facts\n- Mag Tee.\n- Mag Kaffee.\n"


# --- The size of the memory ------------------------------------------------------


def _full(tmp_path, *, extra: str = "", room: int = 0):
    """A memory holding ``MAX_TOTAL`` characters of entries, ``room`` of them
    left free: seven entries of 500 characters and one that fills the rest, a
    line break between each of them."""
    entries = [chr(ord("a") + i) * 500 for i in range(7)]
    entries.append("z" * (memory.MAX_TOTAL - len("\n".join(entries)) - 1 - room))
    pfad = _file(tmp_path, extra + "## Facts\n" + "\n".join(f"- {e}" for e in entries) + "\n")
    return pfad, entries


def test_the_memory_holds_exactly_its_size_and_not_one_character_more(tmp_path):
    # Two characters free: an entry of one character and its line break fit.
    pfad, entries = _full(tmp_path, room=2)
    regeln, fakten = memory._zeilen_teilen(pfad.read_text(encoding="utf-8"))
    assert memory._total_size(regeln, fakten) == memory.MAX_TOTAL - 2
    assert asyncio.run(memory.ausfuehren({"text": "x", "kind": "fact"}, pfad)) == "Saved."
    regeln, fakten = memory._zeilen_teilen(pfad.read_text(encoding="utf-8"))
    assert memory._total_size(regeln, fakten) == memory.MAX_TOTAL
    # The line is reached; another character is one too many.
    vorher = pfad.read_text(encoding="utf-8")
    with pytest.raises(memory.MemoryFull):
        asyncio.run(memory.ausfuehren({"text": "y", "kind": "fact"}, pfad))
    assert pfad.read_text(encoding="utf-8") == vorher


def test_a_save_past_the_size_is_refused_with_the_entries_and_a_way_out(tmp_path):
    pfad, entries = _full(tmp_path)
    vorher = pfad.read_text(encoding="utf-8")
    with pytest.raises(memory.MemoryVerboten) as fehler:
        asyncio.run(memory.ausfuehren({"text": "Noch etwas, das nicht mehr hineinpasst.", "kind": "rule"}, pfad))
    text = str(fehler.value)
    assert "Nothing was saved" in text
    assert "'replaces'" in text and "'remove'" in text
    assert entries[0] in text and entries[-1] in text
    assert pfad.read_text(encoding="utf-8") == vorher


def test_a_replacement_that_grows_the_memory_past_the_size_is_refused(tmp_path):
    pfad, entries = _full(tmp_path)
    vorher = pfad.read_text(encoding="utf-8")
    with pytest.raises(memory.MemoryFull):
        asyncio.run(memory.ausfuehren(
            {"text": "q" * 560, "kind": "fact", "replaces": "a" * 20}, pfad
        ))
    assert pfad.read_text(encoding="utf-8") == vorher


def test_a_replacement_that_shrinks_a_full_memory_goes_through(tmp_path):
    pfad, entries = _full(tmp_path)
    antwort = asyncio.run(memory.ausfuehren(
        {"text": "Kurz.", "kind": "fact", "replaces": "a" * 20}, pfad
    ))
    assert antwort == "Replaced."
    assert "Kurz." in pfad.read_text(encoding="utf-8")


def test_a_delete_frees_the_room_a_refused_save_needed(tmp_path):
    pfad, entries = _full(tmp_path)
    with pytest.raises(memory.MemoryFull):
        asyncio.run(memory.ausfuehren({"text": "q" * 400, "kind": "fact"}, pfad))
    asyncio.run(memory.ausfuehren({"remove": "a" * 20}, pfad))
    assert asyncio.run(memory.ausfuehren({"text": "q" * 400, "kind": "fact"}, pfad)) == "Saved."


def test_a_memory_filled_past_the_line_by_hand_can_still_be_shortened_but_not_grown(tmp_path):
    pfad = _file(tmp_path, "## Facts\n" + "\n".join(f"- {c * 590}" for c in "abcdefg") + "\n")
    regeln, fakten = memory._zeilen_teilen(pfad.read_text(encoding="utf-8"))
    assert memory._total_size(regeln, fakten) > memory.MAX_TOTAL
    with pytest.raises(memory.MemoryFull):
        asyncio.run(memory.ausfuehren({"text": "x", "kind": "fact"}, pfad))
    assert asyncio.run(memory.ausfuehren({"remove": "a" * 20}, pfad)) == "Removed."


def test_only_the_entries_count_and_not_the_text_of_the_person_above_the_first_heading(tmp_path):
    pfad, entries = _full(tmp_path, extra="Eine lange Notiz. " * 200 + "\n\n", room=5)
    assert asyncio.run(memory.ausfuehren({"text": "x", "kind": "fact"}, pfad)) == "Saved."


def test_silence_an_entry_that_is_already_there_is_known_even_in_a_full_memory(tmp_path):
    pfad, entries = _full(tmp_path)
    assert asyncio.run(memory.ausfuehren({"text": entries[0], "kind": "fact"}, pfad)) == (
        "Already known; nothing changed."
    )


def test_the_description_names_the_size_and_the_three_things_the_tool_does():
    text = memory.werkzeug_beschreibung().beschreibung
    assert f"{memory.MAX_TOTAL:,}" in text
    assert "'remove'" in text and "'replaces'" in text
    assert "Nothing is asked" in text
    assert "cannot delete" not in text and "lists the entries you have stored" not in text


# --- A note above the first heading is the person's own -----------------------


def test_a_note_above_the_first_heading_survives_a_save(tmp_path):
    path = tmp_path / "memory.md"
    path.write_text(
        "My own note, written by hand.\nSecond line.\n\n## Rules\n- Be brief.\n",
        encoding="utf-8",
    )
    asyncio.run(memory.ausfuehren({"text": "Lives in Berlin.", "kind": "fact"}, path))
    assert path.read_text(encoding="utf-8").startswith(
        "My own note, written by hand.\nSecond line.\n\n## Rules\n- Be brief."
    )
    assert "- Lives in Berlin." in path.read_text(encoding="utf-8")


def test_a_file_without_a_note_comes_out_as_before(tmp_path):
    """The silence probe: a file with nothing above its headings comes out
    byte for byte as it did before the note was kept."""
    path = tmp_path / "memory.md"
    path.write_text("## Rules\n- Be brief.\n", encoding="utf-8")
    asyncio.run(memory.ausfuehren({"text": "Lives in Berlin.", "kind": "fact"}, path))
    assert path.read_text(encoding="utf-8") == "## Rules\n- Be brief.\n\n## Facts\n- Lives in Berlin.\n"


def test_a_note_without_a_gap_stays_as_written(tmp_path):
    """The note is kept byte for byte, gap included — an entry already
    stored is still 'already known' and the file is not rewritten."""
    path = tmp_path / "memory.md"
    path.write_text("My note\n## Rules\n- Be brief.\n", encoding="utf-8")
    answer = asyncio.run(
        memory.ausfuehren({"text": "Be brief.", "kind": "rule"}, path)
    )
    assert answer == "Already known; nothing changed."
    assert path.read_text(encoding="utf-8") == "My note\n## Rules\n- Be brief.\n"


# --- A heading of the person's own, with its lines, stays where it stands ----

NOTES = "## Notizen\nErste Zeile.\nZweite Zeile.\n"


def test_a_foreign_heading_and_its_lines_stay_where_they_are():
    alt = f"## Rules\n- Be brief.\n\n{NOTES}\n## Facts\n- Lives in Berlin.\n"
    neu = memory.eintragen(alt, "Likes tea.", memory.FAKTUM)
    assert neu == f"## Rules\n- Be brief.\n\n{NOTES}\n## Facts\n- Lives in Berlin.\n- Likes tea."
    assert "- ## Notizen" not in neu


def test_a_foreign_heading_under_the_facts_ends_that_list(tmp_path):
    path = tmp_path / "memory.md"
    path.write_text(f"## Facts\n- Lives in Berlin.\n\n{NOTES}", encoding="utf-8")
    asyncio.run(memory.ausfuehren({"text": "Likes tea.", "kind": "fact"}, path))
    assert path.read_text(encoding="utf-8") == (
        f"## Facts\n- Lives in Berlin.\n- Likes tea.\n\n{NOTES}"
    )


def test_a_foreign_heading_at_the_end_of_the_file_stays_there():
    alt = "## Rules\n- Be brief.\n\n# Notizen\nOnly a line.\n"
    neu = memory.eintragen(alt, "Be kind.", memory.REGEL)
    assert neu == "## Rules\n- Be brief.\n- Be kind.\n\n# Notizen\nOnly a line."


def test_the_lines_of_a_foreign_heading_are_no_entries():
    alt = f"## Facts\n- Lives in Berlin.\n\n{NOTES}"
    listing = memory.auflisten(alt)
    assert listing == "## Facts\n- Lives in Berlin."
    assert "Zeile" not in listing and "Notizen" not in listing


def test_an_own_heading_below_a_foreign_one_owns_its_lines_again():
    alt = f"## Rules\n- Be brief.\n\n{NOTES}\n## Facts\n- Lives in Berlin.\n"
    regeln, fakten = memory._zeilen_teilen(alt)
    assert (regeln, fakten) == (["Be brief."], ["Lives in Berlin."])


def test_a_new_list_gets_its_heading_beside_a_foreign_one():
    alt = f"## Facts\n- Lives in Berlin.\n\n{NOTES}"
    neu = memory.eintragen(alt, "Be brief.", memory.REGEL)
    assert neu == f"## Rules\n- Be brief.\n\n## Facts\n- Lives in Berlin.\n\n{NOTES.rstrip()}"


def test_a_hashtag_without_a_blank_is_still_an_entry():
    alt = "## Facts\n- Lives in Berlin.\n#hashtag\n"
    regeln, fakten = memory._zeilen_teilen(alt)
    assert fakten == ["Lives in Berlin.", "#hashtag"]
    assert "#hashtag" in memory.eintragen(alt, "Likes tea.", memory.FAKTUM)


def test_a_heading_of_up_to_three_blanks_of_indent_counts_and_four_do_not():
    three = "## Facts\n- Lives in Berlin.\n   ### Mine\nHand-written.\n"
    four = "## Facts\n- Lives in Berlin.\n    ### Mine\n"
    assert memory._zeilen_teilen(three)[1] == ["Lives in Berlin."]
    assert memory._zeilen_teilen(four)[1] == ["Lives in Berlin.", "### Mine"]
