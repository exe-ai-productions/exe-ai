"""The model, agent and cleaning server pages: a maker's mark (or the first
letter) in front of every file in a choice field, sizes and speed written with
the decimal sign of the language, the first-start steps drawn with the house's
wordmark in three strengths, and the "Parameter" head with its own sign.

What the browser draws is measured in ``test_server_pages_logos_chrome.py``;
these tests hold what the sources say, so a later change to one part cannot
quietly undo another.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
TEILE = SRC / "teile"

MODEL_SERVER = (TEILE / "Modellserver.svelte").read_text(encoding="utf-8")
AGENT_SERVER = (TEILE / "Agentserver.svelte").read_text(encoding="utf-8")
CLEANING_SERVER = (TEILE / "Bereinigungsserver.svelte").read_text(encoding="utf-8")
EMBEDDING_SERVER = (TEILE / "Einbettungsserver.svelte").read_text(encoding="utf-8")
SPEECH_SERVER = (TEILE / "Sprachserver.svelte").read_text(encoding="utf-8")
FIELD = (TEILE / "Auswahlfeld.svelte").read_text(encoding="utf-8")
ENTRY_FILE = SRC / "lib" / "modelEntry.js"
# A missing helper makes the assertions below fail, not the import of this file.
ENTRY = ENTRY_FILE.read_text(encoding="utf-8") if ENTRY_FILE.exists() else ""

SERVER_PAGES = pytest.mark.parametrize(
    "source", [MODEL_SERVER, AGENT_SERVER], ids=["Modellserver", "Agentserver"]
)


def _list(source: str, name: str) -> str:
    """The body of ``const <name> = $derived([ ... ])``."""
    body = source.split(f"const {name} = $derived([", 1)[1]
    return body.split("\n  ])", 1)[0]


def _markup(source: str) -> str:
    return source.split("<style>", 1)[0]


def _style(source: str) -> str:
    return source.split("<style>", 1)[1]


# --- The field draws a letter where an entry has no mark -----------------------------


def test_the_field_draws_the_letter_only_where_an_entry_has_no_logo():
    markup = _markup(FIELD)
    assert "{:else if aktuell?.letter}" in markup
    assert "{:else if eintrag.letter}" in markup
    # One drawing of the mark in the field and one in the list, as before.
    assert markup.count("{@html aktuell.logo.html}") == 1
    assert markup.count("{@html eintrag.logo.html}") == 1
    # The letter sits behind the logo test, never beside it.
    assert markup.index("{@html aktuell.logo.html}") < markup.index("{:else if aktuell?.letter}")
    assert markup.index("{@html eintrag.logo.html}") < markup.index("{:else if eintrag.letter}")


def test_the_letter_is_a_20_px_box_in_the_still_text_colour():
    letter = _style(FIELD).split(".letter {", 1)[1].split("}", 1)[0]
    assert "width: 20px" in letter and "height: 20px" in letter
    assert "color: var(--text-still)" in letter
    assert "font: 700 13px var(--schrift)" in letter


# --- What an entry carries ------------------------------------------------------------


def test_an_entry_mark_is_the_logo_of_the_file_else_its_first_letter():
    assert "return logo ? { logo } : { letter: Array.from(name)[0].toUpperCase() }" in ENTRY
    # A choice that names no file is given neither.
    assert "if (!name) return {}" in ENTRY


def test_an_id_mark_follows_the_model_after_the_first_colon():
    assert "colon >= 0 && colon < text.length - 1 ? text.slice(colon + 1) : text" in ENTRY


def test_an_entry_size_is_the_catalogue_way_with_the_decimal_sign_of_the_language():
    assert "t('modell.gb', { zahl: formatGb(gb, texte.sprache) })" in ENTRY


@SERVER_PAGES
def test_every_file_entry_carries_its_mark_and_the_choice_that_names_no_file_none(source: str):
    drafter = _list(source, "drafterauswahl")
    vision = _list(source, "visionauswahl")
    model = _list(source, "modellauswahl")
    # The foreign module, the candidates, the projectors and the model files.
    assert drafter.count("...entryMark(") == 2
    assert vision.count("...entryMark(") == 1
    assert "...entryMark(m.name)" in model
    # The empty choices stand as they were.
    assert "{ wert: '', text: t('modell.drafter_keiner') }" in drafter
    assert "{ wert: '', text: t('modell.vision_keiner') }" in vision
    # No size is written with the point any more.
    assert not re.search(r"groesse_gb\}\s*GB", source)
    assert "entrySize(m.groesse_gb)" in source


def test_the_model_server_empty_choice_has_no_mark():
    first = _list(MODEL_SERVER, "modellauswahl").strip().splitlines()[0]
    assert first.strip() == "{ wert: '', text: t('modell.modell_keiner') },"


def test_the_agent_server_main_model_and_recognition_entries():
    model = _list(AGENT_SERVER, "modellauswahl")
    first = model.strip().splitlines()[0]
    # "Main model" is the state with no choice of its own: no mark, first place.
    assert first.strip() == "{ wert: HAUPTMODELL_WAHL, text: t('modell.agentenmodell_hauptmodell') },"
    assert "wert: `slot:${m.name}`" in model
    # The ids of the recognition carry the mark of their model (after the first colon).
    assert "{ wert: `kennung:${m.id}`, text: m.id, ...idMark(m.id) }" in model
    assert "!== HAUPTMODELL_WAHL" in model


# --- Speed, and the first-start steps ------------------------------------------------


def test_the_model_server_writes_the_speed_with_the_decimal_sign_of_the_language():
    assert "formatNumber(tempo / 1e6, 1, texte.sprache) + ' MB/s'" in MODEL_SERVER
    assert "toFixed(1)" not in MODEL_SERVER


def test_the_first_start_steps_wear_the_wordmark_in_three_strengths_and_no_digit():
    steps = _markup(MODEL_SERVER).split('<div class="reisekarten">', 1)[1]
    steps = steps.split('<div class="reisekarte">', 1)[1]
    marks = re.findall(r'<div class="nr nr-(\d)" aria-hidden="true"><Wortmarke mitText=\{false\} /></div>', steps)
    assert marks == ["1", "2", "3"]
    # No number and no tick in a circle.
    assert "✓" not in steps
    assert not re.search(r'<div class="nr">', steps)
    # The step that is done keeps its pill.
    assert "{t('modell.reise_da')}" in steps


def test_the_wordmark_steps_are_32_by_25_6_with_the_opacities_0_4_0_7_and_1():
    style = _style(MODEL_SERVER)
    box = style.split(".reisekarte .nr {", 1)[1].split("}", 1)[0]
    assert "width: 32px" in box and "height: 25.6px" in box
    # No circle and no border any more.
    assert "border" not in box and "border-radius" not in box
    for number, opacity in (("1", "0.4"), ("2", "0.7"), ("3", "1")):
        rule = style.split(f".nr-{number} {{", 1)[1].split("}", 1)[0]
        assert f"opacity: {opacity}" in rule
    assert ".reisekarte.fertig" not in style and ".reisekarte.dran" not in style


# --- The cleaning server --------------------------------------------------------------


def test_the_cleaning_server_parameter_head_carries_its_sign():
    assert (
        """<Serverabschnitt zeichen="settings_two" titel={t('sprachserver.gruppe_parameter')}>"""
        in CLEANING_SERVER
    )


def test_the_cleaning_server_writes_sizes_with_the_decimal_sign_and_keeps_the_empty_entry():
    model = _list(CLEANING_SERVER, "modellauswahl")
    assert "entrySize(m.groesse_gb)" in model
    assert not re.search(r"groesse_gb\}\s*GB", CLEANING_SERVER)
    assert "t('bereinigungsserver.leer')" in model
    # The empty entry names no file: it is the first of the list and has no mark.
    first = model.strip().splitlines()[0]
    assert "entryMark" not in first
    # Every file entry carries the mark of its file.
    assert "...entryMark(m.name)" in model


@pytest.mark.parametrize(
    "source,name",
    [(CLEANING_SERVER, "modellauswahl"), (EMBEDDING_SERVER, "auswahl"), (SPEECH_SERVER, "modellauswahl")],
    ids=["Bereinigungsserver", "Einbettungsserver", "Sprachserver"],
)
def test_the_three_other_server_pages_write_every_file_with_its_mark_and_the_size_with_the_decimal_sign(
    source: str, name: str
):
    # The list ends at its own closing: `])` of an array that starts with an entry, `)` of a map.
    entries = re.split(r"\n  \]?\)", source.split(f"const {name} = $derived(", 1)[1], maxsplit=1)[0]
    assert len(entries) < 1500, "the slice must be the one list, not the rest of the page"
    assert "...entryMark(m.name)" in entries
    assert "text: `${m.name} · ${entrySize(m.groesse_gb)}`" in entries
    assert "import { entryMark, entrySize } from '../lib/modelEntry.js'" in source
    assert not re.search(r"groesse_gb\}\s*GB", source)


def test_the_speech_server_choices_that_name_no_file_stay_without_a_mark():
    voices = _list(SPEECH_SERVER, "stimmeauswahl")
    assert voices.strip().splitlines()[0].strip() == "{ wert: '', text: '-' },"
    assert "...modellauswahl" in voices
    for name in ("stimmprobeauswahl", "stimmsprachauswahl", "sprachauswahl"):
        assert "entryMark" not in _list(SPEECH_SERVER, name), name
