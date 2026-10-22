"""The cloud providers page as the abnahme drawing has it: the head with the
button for a new provider, the providers as a table, under it two equal
columns (the chosen provider's card with the parameters of one model, and its
catalogue), a pop-up that adds a provider, and one state for a cloud model —
its tick.

What the browser draws is measured against the proof service; these tests hold
what the sources say, so a later change to one part cannot quietly undo
another.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
LOCALES = ROOT / "app" / "locales"


def _source(name: str) -> str:
    return (SRC / "teile" / name).read_text(encoding="utf-8")


def _markup(name: str) -> str:
    return _source(name).split("<style>", 1)[0]


def _style(name: str) -> str:
    return _source(name).split("<style>", 1)[1]


def _catalogue(language: str) -> dict:
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))


# --- The page ----------------------------------------------------------------------


def test_the_head_carries_the_cloud_sign_the_title_and_the_button_for_a_new_provider():
    markup = _markup("ModelleCloud.svelte")
    head = markup.split("{#snippet kopf()}", 1)[1].split("{/snippet}", 1)[0]
    assert 'name="cloud"' in head and "modell.cloud_titel" in head
    assert 'class="new-button"' in head
    assert "modell.anbieter_hinzufuegen" in head
    assert "maskOpen = true" in head


def test_the_providers_stand_in_a_table_over_two_equal_columns():
    markup = _markup("ModelleCloud.svelte")
    assert "<ProviderTable" in markup
    assert "<Serverreihe>" in markup
    # The table comes first, the columns after it.
    assert markup.index("<ProviderTable") < markup.index("<Serverreihe>")
    assert "{@render card(haus)}" in markup and "{@render catalogCard(haus)}" in markup


def test_no_column_stands_empty_where_a_provider_has_no_catalogue():
    markup = _markup("ModelleCloud.svelte")
    # The two columns only where there is a catalogue to put in the second.
    assert re.search(r"\{#if katalog\.length\}\s*<Serverreihe>", markup)
    assert 'class="single-column"' in markup


def test_the_old_blocks_of_the_page_are_gone():
    markup = _markup("ModelleCloud.svelte")
    for gone in ("Fensterkopf", "Fenstertafel", "Knopfreihe", "loeschknopf"):
        assert gone not in markup, gone
    # The model page and the provider page are one page now.
    assert "gewaehltesModell" not in markup
    assert "HINZU" not in markup
    # The quiet dot is allowed for the provider that does not answer, and for
    # nothing else on the page.
    assert re.findall(r"<Leuchtpunkt\b[^>]*>", markup) and all(
        'farbe="still"' in dot for dot in re.findall(r"<Leuchtpunkt\b[^>]*>", markup)
    )


def test_the_sidebar_carries_the_settings_list_and_the_providers_stand_in_their_own_column():
    markup = _markup("ModelleCloud.svelte")
    listing = markup.split("{#snippet liste()}", 1)[1].split("{#snippet kopf()}", 1)[0]
    assert '<SettingsNav current="cloud" />' in listing
    assert "Menuezeile" not in listing and "listenzeile" not in listing
    column = markup.split("{#snippet providers()}", 1)[1].split("{#snippet rightSide()}", 1)[0]
    assert "<Menuezeile" in column
    assert "gezeigtArt = 'haus'" in column and "gezeigtArt = 'modell'" in column
    # The way to a new provider stands at the foot of the column and opens the same pop-up.
    assert "maskOpen = true" in column
    # The column and the content stand in one grid, the column 300 px wide, over each other where it is narrow.
    style = _style("ModelleCloud.svelte")
    assert re.search(r"\.two-columns \{[^}]*grid-template-columns: 300px minmax\(0, 1fr\)", style)
    assert re.search(r"@media \(max-width: 900px\) \{\s*\.two-columns \{ grid-template-columns: minmax\(0, 1fr\)", style)
    assert "{@render providers()}" in markup.split("{#snippet inhalt()}", 1)[1]


def test_a_provider_that_does_not_answer_has_no_model_row_of_its_own():
    markup = _markup("ModelleCloud.svelte")
    column = markup.split("{#snippet providers()}", 1)[1].split("{#snippet rightSide()}", 1)[0]
    assert re.search(r"\{#if haus\.erreichbar\}\s*\{#each haus\.modelle as m", column)
    right = markup.split("{#snippet rightSide()}", 1)[1].split("{#if offen}", 1)[0]
    assert "haus.erreichbar && haus.modelle.length" in right


def test_the_card_has_the_signs_that_explain_and_the_default_under_the_context_name():
    markup = _markup("ModelleCloud.svelte")
    card = markup.split("{#snippet card(haus)}", 1)[1].split("{/snippet}", 1)[0]
    for key in ("modell.vision_erklaerung", "modell.werkzeuge_erklaerung", "modell.denken_erklaerung"):
        assert f'title={{t(\'{key}\')}}' in card, key
    # The info sign is the title's carrier, and the zeitgrenze has none.
    assert card.count('zeichen="info"') == 3
    assert "modell.kontext_gefunden" in card and 'class="subline"' in card
    assert "modell.kontext_titel" in card


def test_the_default_context_reads_standard_and_default():
    assert _catalogue("de")["modell"]["kontext_gefunden"] == "Standard: {zahl}"
    assert _catalogue("en")["modell"]["kontext_gefunden"] == "Default: {zahl}"


def test_the_parameter_block_names_its_model():
    markup = _markup("ModelleCloud.svelte")
    assert "<Parametertafel modell={paramsModel} withName />" in markup
    panel = _markup("Parametertafel.svelte")
    assert "withName" in panel and "t('parameter.titel')} · ${modell.name}" in panel


def test_the_catalogue_has_its_count_the_tick_at_the_end_and_a_sign_for_the_parameters():
    markup = _markup("ModelleCloud.svelte")
    card = markup.split("{#snippet catalogCard(haus)}", 1)[1].split("{/snippet}", 1)[0]
    # The head is the card's first row, not a head above the card.
    assert "count={catalogCount}" not in card and "titel={t('liste.katalog')}" not in card
    assert card.index('class="zeile duenn catalog-head"') < card.index("<Ankreuzliste")
    assert "{catalogCount}" in card
    assert "tickEnd" in card and "isOpen=" in card
    assert 'zeichen="settings_two"' in card


def test_a_single_model_without_a_catalogue_shows_its_row_over_the_open_block():
    markup = _markup("ModelleCloud.svelte")
    alone = markup.split('class="single-column"', 1)[1].split("</div>", 1)[0]
    # The card, then the model's row, then the parameters — the block is open.
    assert alone.index("{@render card(haus)}") < alone.index("{@render singleModels(haus)}")
    assert alone.index("{@render singleModels(haus)}") < alone.index("{@render paramsBlock()}")
    row = markup.split("{#snippet singleModels(haus)}", 1)[1].split("{/snippet}", 1)[0]
    assert "schalten(m.id, !istAn(m.id))" in row
    # The tick away is not a deletion of the provider.
    assert "anbieterEntfernen" not in row


def test_removing_a_provider_asks_with_a_red_confirm_button():
    source = _source("ModelleCloud.svelte")
    asking = source.split("async function anbieterEntfernen", 1)[1].split("try {", 1)[0]
    assert "danger: true" in asking


def test_a_new_provider_is_added_in_a_pop_up_without_a_sign_in_its_title():
    markup = _markup("ModelleCloud.svelte")
    window = markup.split("<Fenster ", 1)[1].split("</Fenster>", 1)[0]
    assert 'art="provider"' in window and "bind:offen={maskOpen}" in window
    assert "symbol" not in window
    assert "<Anbietermaske" in window


def test_only_the_provider_mask_is_594_wide_and_the_other_pop_ups_keep_their_width():
    window = _source("Fenster.svelte")
    widths = window.split("const BREITE = {", 1)[1].split("}", 1)[0]
    assert "provider: '594px'" in widths
    # The question keeps 460 and the sheet of a server's tools keeps 740.
    assert "frage: '460px'" in widths and "mcp: '740px'" in widths


def test_the_name_of_a_row_gives_way_only_where_the_row_asks_for_it():
    row = _source("Menuezeile.svelte")
    assert "nameGivesWay = false" in row
    assert re.search(r"\.name-gives-way \.titel \{\s*flex: 0 1 auto;\s*min-width: 0;", row)
    column = _markup("ModelleCloud.svelte").split("{#snippet providers()}", 1)[1].split("{#snippet rightSide()}", 1)[0]
    assert "nameGivesWay" in column
    # No other list asks for it.
    for other in ("Einstellungsliste.svelte", "Katalog.svelte", "SettingsNav.svelte"):
        assert "nameGivesWay" not in _source(other), other


def test_the_texts_of_a_state_are_drawn_in_the_text_forms_of_the_colours():
    table = _style("ProviderTable.svelte")
    assert ".key.missing { color: var(--rot-text); }" in table
    assert ".state.reachable { color: var(--gruen-text); }" in table
    page = _style("ModelleCloud.svelte")
    assert ".state-word.reachable { color: var(--gruen-text); }" in page
    assert ".count.missing { color: var(--rot-text); }" in page
    # The quiet lines under a name read in the quiet ink of the card, not the figure ink.
    subline = page.split(".subline {", 1)[1].split("}", 1)[0]
    assert "color: var(--text-leise);" in subline, subline
    # The drawn layer carries an opacity of 0.6 on top of the quiet ink.
    assert "opacity: 0.6;" in subline, subline
    # The base colours stay for dots and the tick, which are drawings and not text.
    assert "color: var(--gruen);" in page.split(".haken {", 1)[1].split("}", 1)[0]


# --- The table -----------------------------------------------------------------------


def test_the_table_has_five_columns_and_a_bin_that_never_chooses_the_row():
    markup = _markup("ProviderTable.svelte")
    assert markup.count('role="columnheader"') == 5
    for key in ("modell.column_provider", "modell.schluessel", "modell.feld_modell", "modell.column_status"):
        assert f"t('{key}')" in markup, key
    bin_button = markup.split('class="binbutton"', 1)[1].split("</button>", 1)[0]
    assert "e.stopPropagation()" in bin_button
    assert 'zeichen="trash"' in bin_button
    assert "title={t('modell.anbieter_entfernen')}" in bin_button


def test_the_table_draws_the_logo_bare_and_the_state_as_a_word():
    style = _style("ProviderTable.svelte")
    logo = style.split("\n  .logo {", 1)[1].split("}", 1)[0]
    assert "background" not in logo and "box-shadow" not in logo
    markup = _markup("ProviderTable.svelte")
    assert "Standpille" not in markup
    assert 'zeichen="server"' in markup


def test_the_words_of_the_cells_are_made_by_the_page():
    markup = _markup("ModelleCloud.svelte")
    cells = markup.split("const tableRows", 1)[1].split("const catalogCount", 1)[0]
    assert "t('modell.schluessel_gesetzt')" in cells
    assert "t('modell.schluessel_fehlt')" in cells
    assert "t('modell.von_zahl')" in cells
    # The variable's name is the tooltip of the key cell, never a value.
    assert "haus.schluessel_env" in cells and "t('modell.schluessel_hinweis')" in cells
    # A provider that does not answer has a dash where its models would be.
    assert ": '-'" in cells


def test_the_two_new_column_heads_stand_in_both_languages():
    for language in ("de", "en"):
        modell = _catalogue(language)["modell"]
        assert modell["column_provider"], language
        assert modell["column_status"], language
    assert _catalogue("de")["modell"]["column_provider"] == "Anbieter"
    assert _catalogue("de")["modell"]["column_status"] == "Zustand"


# --- The catalogue list and the field -------------------------------------------------


def test_the_search_field_of_a_list_has_no_placeholder():
    markup = _markup("Ankreuzliste.svelte")
    search = markup.split('<div class="suche">', 1)[1].split("</div>", 1)[0]
    assert "placeholder" not in search
    assert "aria-label={t('app.suchen')}" in search


def test_the_ticking_list_keeps_its_box_look_and_adds_the_end_look():
    markup = _markup("Ankreuzliste.svelte")
    assert "tickEnd = false" in markup and "rowAction = null" in markup
    box = markup.split("{:else}", 1)[1].split("{/if}", 1)[0]
    assert 'class="kreuz"' in box
    ending = markup.split("{#if tickEnd}", 1)[1].split("{:else}", 1)[0]
    # Not a button inside a button: the row is a row, its action the button.
    assert 'role="button"' in ending and "<button" not in ending.split("{@render rowAction", 1)[0]
    assert "e.stopPropagation()" in ending
    assert "e.key === 'Enter' || e.key === ' '" in ending


def test_the_end_look_of_the_list_draws_rows_of_the_card_and_leaves_the_basic_look_alone():
    markup = _markup("Ankreuzliste.svelte")
    # The three parts take the end look from the same switch; the foot button is the card's own.
    assert markup.count("class:end-look={tickEnd}") == 3
    assert "class={tickEnd ? 'feldknopf' : 'textknopf'}" in markup
    style = _style("Ankreuzliste.svelte")
    # Every rule of the end look hangs on its own classes, so the tools list keeps its box look.
    for selector in (".suchzeile.end-look", ".listenkarte.end-look", ".fuss.end-look", ".zeile.end"):
        assert selector in style, selector
    assert "padding: 9px 0;" in style.split("\n  .zeile {", 1)[1].split("}", 1)[0]
    assert "margin-top: 10px;" in style.split("\n  .fuss {", 1)[1].split("}", 1)[0]
    cloud = _style("ModelleCloud.svelte")
    assert re.search(r"\.right \.katalog\.zeile\.stapel \{\s*padding: 0;\s*gap: 0;", cloud)


def test_the_selection_field_draws_a_logo_in_the_field_and_in_the_list():
    markup = _markup("Auswahlfeld.svelte")
    assert markup.count("{@html aktuell.logo.html}") == 1
    assert markup.count("{@html eintrag.logo.html}") == 1


def test_the_mask_is_a_pop_up_form_with_a_selection_field_over_labelled_fields():
    markup = _markup("Anbietermaske.svelte")
    assert "<Auswahlfeld" in markup and "LOGOS.exe" in markup
    for gone in ("Fensterkopf", "Fenstertafel", "Knopfreihe", "Serverabschnitt"):
        assert gone not in markup, gone
    # Words at the foot, the main button blocked until the form is ready.
    assert "t('modell.abbrechen')" in markup and "t('modell.verbinden')" in markup
    assert "disabled={!bereit || arbeitet}" in markup


def test_a_section_without_a_title_has_no_head_and_the_count_stands_behind_the_title():
    markup = _markup("Serverabschnitt.svelte")
    assert "{:else if zeichen || titel || rechts}" in markup
    assert "count = ''" in markup and 'class="count-figure"' in markup
