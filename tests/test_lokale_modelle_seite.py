"""The local models page: the head with the server sign and the wired memory
bar, the quick picker as a table above whatever is chosen, and the model's
parameters in two columns with the reset as a sign. Read off the source, the
way the other interface tests do.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEILE = ROOT / "frontend" / "src" / "teile"


def _source(name: str) -> str:
    return (TEILE / name).read_text(encoding="utf-8")


def _markup(name: str) -> str:
    return _source(name).split("<style>", 1)[0]


def _style(name: str) -> str:
    return _source(name).split("<style>", 1)[1]


def _catalogue(language: str) -> dict[str, dict[str, str]]:
    path = ROOT / "app" / "locales" / f"{language}.json"
    data: dict[str, dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
    return data


# --- The head ------------------------------------------------------------------


def test_the_head_wears_the_server_sign_and_no_word_mark():
    markup = _markup("ModelleLokal.svelte")
    head = markup.split("{#snippet kopf()}", 1)[1].split("{/snippet}", 1)[0]
    # The overview wears the bars, the server pages their own signs.
    assert 'zeichen="ranking_bars"' in head and "zeichen={serverPage.zeichen}" in head
    assert "<h2" in head
    # The page's own name, not the short word of the window row.
    assert "t('einstellungen.lokale_modelle')" in head
    assert "Schriftzug" not in markup
    assert "<svg" not in head


def test_the_title_is_the_page_title_size_and_the_count_a_quiet_pill_beside_it():
    style = _style("ModelleLokal.svelte")
    assert "font-size: var(--schrift-seitentitel)" in style.split("\n  .titel {", 1)[1].split("}", 1)[0]
    markup = _markup("ModelleLokal.svelte")
    head = markup.split("{#snippet kopf()}", 1)[1].split("{/snippet}", 1)[0]
    # The count is a pill in the title's row, not a line under it.
    assert "\n  .zaehler {" not in style and 'class="zaehler"' not in head
    assert '<Standpille farbe="count">' in head


def test_the_head_shows_the_wired_memory_of_the_machine_asked_on_the_runner_beat():
    markup = _markup("ModelleLokal.svelte")
    assert "<MemoryBar" in markup
    assert "wired={speicher?.wired_gb" in markup
    assert "api.speicherBlick()" in markup
    # Asked in the same beat as the runner, not in a loop of its own.
    beat = markup.split("let active = true", 1)[1].split("holen()", 1)[0]
    assert "api.runnerAuskunft()" in beat
    assert "api.speicherBlick()" in beat


def test_the_port_keeps_its_line_with_a_dash_and_no_estimate_stands_beside_it():
    markup = _markup("ModelleLokal.svelte")
    assert "auskunft?.port ?? '-') : '-'" in markup
    # No second memory figure next to the wired bar: neither the sum nor its word.
    assert "planGesamt" not in markup and "vram_erwartet" not in markup
    for window in ("Modellserver", "Agentserver"):
        assert "serverPlan" not in _source(f"{window}.svelte"), window
    assert "serverPlan" not in (ROOT / "frontend" / "src" / "lib" / "zustand.svelte.js").read_text(encoding="utf-8")
    for language in ("de", "en"):
        assert "vram_erwartet" not in _catalogue(language)["modell"], language


def test_the_memory_bar_names_wired_memory_and_never_guesses_a_figure():
    markup = _markup("MemoryBar.svelte")
    assert "chip_bolt" in markup
    assert "modell.wired_label" in markup
    assert "modell.wired_von" in markup
    assert "formatNumber(wired, 1, texte.sprache)" in markup
    # No wired figure on a platform that cannot say: a dash in its place, the
    # total still named, and a track that announces nothing.
    assert "wired: known ?" in markup
    assert "aria-hidden={known ? null : 'true'}" in markup


# --- The quick picker as a table ---------------------------------------------------


def test_the_quick_picker_is_not_in_the_sidebar_any_more():
    markup = _markup("ModelleLokal.svelte")
    sidebar = markup.split("{#snippet liste()}", 1)[1].split("{/snippet}", 1)[0]
    assert "schnellwahl_titel" not in sidebar
    # The list of the settings stands there, the same one every page carries.
    assert "<SettingsNav" in sidebar
    assert "Menuezeile" not in sidebar and "SERVERLISTE" not in markup


def test_the_table_stands_above_whatever_is_chosen():
    markup = _markup("ModelleLokal.svelte")
    content = markup.split("{#snippet inhalt()}", 1)[1]
    assert content.index("<QuickPickTable") < content.index("{#if modell}")


def test_the_table_has_the_five_columns_in_order():
    markup = _markup("QuickPickTable.svelte")
    head = markup.split('class="row head"', 1)[1].split("{#if !rows.length}", 1)[0]
    keys = [
        "modell.spalte_modell",
        "modell.spalte_server",
        "modell.kontext",
        "modell.spalte_framework",
        "modell.schnellwahl_titel",
    ]
    positions = [head.index(key) for key in keys]
    assert positions == sorted(positions)


def test_a_row_chooses_on_click_and_its_switch_never_does():
    markup = _markup("QuickPickTable.svelte")
    assert "onclick={() => onchoose?.(r.id)}" in markup
    # The name button adds no handler of its own: its click is the row's.
    button = markup.split('<button class="name"', 1)[1].split(">", 1)[0]
    assert "onclick" not in button
    switch = markup.split('class="switch"', 1)[1].split("</span>", 1)[0]
    assert "e.stopPropagation()" in switch
    assert "onswitch?.(r.id, an)" in markup


def test_the_agent_servers_own_file_is_a_row_without_a_switch():
    markup = _markup("ModelleLokal.svelte")
    assert "switchable: m.anbieter !== SLOT_ENDPUNKT" in markup
    assert "[...modelle, ...agentFiles]" in markup
    # The chat's choice still holds none of the agent server's models.
    assert "lokale().filter((m) => m.anbieter !== SLOT_ENDPUNKT)" in markup
    table = _markup("QuickPickTable.svelte")
    assert "{#if r.switchable}" in table


def test_the_table_says_nothing_but_a_dash_while_it_is_empty():
    markup = _markup("QuickPickTable.svelte")
    assert '<p class="empty" title={emptyText}>-</p>' in markup
    # Outside the table's own element, so the table holds rows and nothing else.
    table = markup.split('role="table"', 1)[1].split('<p class="empty"', 1)[0]
    assert "</div>\n    {#if !rows.length}" in markup
    assert "empty" not in table


def test_the_logo_stands_bare_and_a_missing_one_is_a_letter_not_a_guess():
    markup = _markup("QuickPickTable.svelte")
    assert "modellMarke(r.name, r.maker)" in markup
    # The mark itself is the shared piece the picture server's lists use too.
    assert "<MakerMark {mark} name={r.name} />" in markup
    assert "slice(0, 1).toUpperCase()" in _markup("MakerMark.svelte")
    style = _style("MakerMark.svelte")
    logo = style.split("\n  .logo {", 1)[1].split("}", 1)[0]
    assert "background" not in logo
    assert "box-shadow" not in logo


def test_the_context_follows_the_language_in_its_decimal_sign():
    tokens = (ROOT / "frontend" / "src" / "lib" / "tokenzahl.js").read_text(encoding="utf-8")
    assert "sprache = 'en'" in tokens
    assert "kurz(r.context, texte.sprache)" in _markup("QuickPickTable.svelte")


# --- The parameters ---------------------------------------------------------------


def test_the_parameter_section_wears_the_two_sliders_sign():
    markup = _markup("Parametertafel.svelte")
    assert 'zeichen="settings_two"' in markup


def test_the_reset_is_a_sign_button_with_the_word_as_its_title():
    markup = _markup("Parametertafel.svelte")
    assert "stillknopf" not in markup
    button = markup.split('class="signbutton"', 1)[1].split("</button>", 1)[0]
    assert 'zeichen="refresh"' in button
    assert "aria-label={t('parameter.zuruecksetzen')}" in button
    assert "title={t('parameter.zuruecksetzen')}" in button
    # It stands at the right end of the section's head (the drawing's 34 px
    # button), not in a row of buttons under the card.
    head = markup.split("{#snippet rechts()}", 1)[1].split("{/snippet}", 1)[0]
    assert 'class="signbutton"' in head
    assert "Knopfreihe" not in markup
    style = _style("Parametertafel.svelte")
    assert "width: 34px" in style.split("\n  .signbutton {", 1)[1].split("}", 1)[0]
    assert "width: 44px" in style.split("html[data-phone]) .signbutton {", 1)[1].split("}", 1)[0]


def test_the_knobs_stand_in_two_cards_by_one_rule_and_one_under_the_other_when_narrow():
    markup = _markup("Parametertafel.svelte")
    # The head keeps the section; its content stands without a card of its own.
    head = re.search(r"<Serverabschnitt\s[^>]*titel=\{sectionTitle\}[^>]*>", markup)
    assert head and re.search(r"\bbare\b", head.group(0))
    assert '<div class="param-cards">' in markup
    assert "{@render card(sampling)}" in markup and "{@render card(lengths)}" in markup
    assert markup.index("{@render card(sampling)}") < markup.index("{@render card(lengths)}")
    # The rule is written once, as two lists of names; a card without a row is not drawn.
    assert "const SAMPLING_ORDER = ['temperature', 'top_p', 'top_k', 'min_p', 'typical_p', 'seed']" in markup
    assert "'max_tokens', 'reasoning_budget', 'repeat_penalty', 'repeat_last_n'" in markup
    assert "'presence_penalty', 'frequency_penalty'" in markup
    assert "{#if list.length}" in markup
    style = _style("Parametertafel.svelte")
    cards = style.split("\n  .param-cards {", 1)[1].split("}", 1)[0]
    assert "repeat(2, minmax(0, 1fr))" in cards and "gap: 24px" in cards and "align-items: start" in cards
    narrow = style.split("@container params (max-width: 560px)", 1)[1]
    assert "grid-template-columns: minmax(0, 1fr)" in narrow
    # No grid on the card itself any more, and no fixed width from the drawing.
    assert ".parameter :global(.karte)" not in style
    assert "514px" not in style


def test_a_section_can_show_its_content_without_a_card_of_its_own():
    section = _source("Serverabschnitt.svelte")
    assert "bare = false" in section
    assert '<div class="bare">' in section and '<div class="karte">' in section


def test_the_page_fills_the_area_when_a_model_is_shown():
    markup = _markup("ModelleLokal.svelte")
    assert "fuellen={Boolean(modell)}" in markup
    assert "<Fenstertafel grow>" in markup
    assert "gewicht={1}" in _markup("Parametertafel.svelte")
    assert "class:grow" in _markup("Fenstertafel.svelte")


# --- The texts ------------------------------------------------------------------------


def test_the_new_texts_stand_in_both_languages_with_the_figures_named():
    for language in ("de", "en"):
        modell = _catalogue(language)["modell"]
        for key in ("wired_label", "wired_von", "spalte_modell", "spalte_server", "spalte_framework"):
            assert modell[key], (language, key)
        assert "{wired}" in modell["wired_von"]
        assert "{total}" in modell["wired_von"]


# --- Local models and the server pages ----------------------------------------------


def test_a_server_page_shows_its_sign_and_name_and_its_window_alone():
    markup = _markup("ModelleLokal.svelte")
    head = markup.split("{#snippet kopf()}", 1)[1].split("{/snippet}", 1)[0]
    assert "zeichen={serverPage.zeichen}" in head and "t(serverPage.titel)" in head
    # The count belongs to the table, so only to "Local models".
    assert "{#if !reise}" in head and "aktiv_zahl" in head
    # The head keeps the memory bar and the facts on the local models and the server pages; the overview carries its own bar.
    assert "<MemoryBar" in head and "{#if !overview}" in head
    content = markup.split("{#snippet inhalt()}", 1)[1]
    server, local = content.split("{:else}\n        <QuickPickTable", 1)
    assert "{:else if serverPage}" in server
    for window in ("Agentserver", "Einbettungsserver", "Sprachserver", "Bereinigungsserver", "Bildserver", "Modellserver"):
        assert f"<{window} bind:head={{serverHead}} />" in server, window
    assert "QuickPickTable" not in server
    # "Local models" has the table and a model's parameters, and no server window.
    assert "<Parametertafel" in local
    for window in ("Agentserver", "Einbettungsserver", "Sprachserver", "Bereinigungsserver", "Bildserver", "Modellserver"):
        assert f"<{window} " not in local, window


SERVER_PAGES = {
    "Modellserver": "server",
    "Agentserver": "agent",
    "Einbettungsserver": "einbettung",
    "Sprachserver": "sprache",
    "Bereinigungsserver": "bereinigung",
    "Bildserver": "bild",
}


def test_the_head_of_a_server_page_draws_the_button_the_line_and_the_port_of_that_server():
    markup = _markup("ModelleLokal.svelte")
    head = markup.split("{#snippet kopf()}", 1)[1].split("{/snippet}", 1)[0]
    # The one button of the server, flush right in the head, from what the page hands up.
    assert "<Startknopf" in head and "head.tat" in head
    assert "head?.line" in head and 'class="kurzzeile"' in head
    # What a page left behind is never taken for the next one's.
    assert "serverHead?.page === gezeigt" in markup
    # The port of the shown server, not the model server's, on every server page.
    assert "serverPage ? (head?.port ?? '-')" in head


def test_every_server_page_hands_up_its_own_button_line_and_port_and_draws_none_itself():
    for window, name in SERVER_PAGES.items():
        source = _source(f"{window}.svelte")
        assert "let { head = $bindable(null) } = $props()" in source, window
        assert f"serverHead('{name}', (value) => (head = value)" in source, window
        # The button stands in the page head and nowhere else of the page.
        assert "<Startknopf" not in source and "kopfrechts" not in source, window
        assert "standtext" not in source and "standfarbe" not in source, window


def test_the_page_names_match_the_entries_of_the_settings_list():
    import re

    entries = (ROOT / "frontend" / "src" / "lib" / "einstellungsliste.js").read_text(encoding="utf-8")
    listed = re.findall(r"\{ name: '([a-z]+)', titel: '[a-z_.]+', zeichen: '[a-z_]+' \}", entries.split("export const SERVER", 1)[1].split("]", 1)[0])
    assert sorted(listed) == sorted(SERVER_PAGES.values())


def test_the_helper_takes_the_entry_back_when_the_page_goes():
    helper = (ROOT / "frontend" / "src" / "lib" / "serverHead.svelte.js").read_text(encoding="utf-8")
    assert "set({ page, ...read() })" in helper
    assert "$effect(() => () => set(null))" in helper


def test_the_window_of_a_server_has_no_head_of_its_own():
    tafel = _source("Servertafel.svelte")
    assert "Fensterkopf" not in tafel and "standtext" not in tafel
    for window in SERVER_PAGES:
        call = _markup(f"{window}.svelte").split("<Servertafel", 1)[1].split(">", 1)[0]
        for gone in ("titel=", "unter=", "standfarbe=", "standtext="):
            assert gone not in call, (window, gone)
        # The sign of the model card's head is the one thing a page may hand
        # over, and only the picture server does: its models are pictures.
        sign = re.search(r'\bzeichen="([^"]*)"', call)
        assert (sign.group(1) if sign else None) == ("bild" if window == "Bildserver" else None), window
    # The parameter card of a local model keeps its own head.
    assert "<Fensterkopf" in _markup("ModelleLokal.svelte")


def test_the_short_line_has_no_port_and_no_running_word():
    for window in ("Modellserver", "Agentserver"):
        line = _source(f"{window}.svelte").split("const laufzeile", 1)[1].split("return teile.join", 1)[0]
        assert "laeuft_port" not in line, window
        assert "kontext_kurz" in line and "mtp_label" in line and "im_speicher" in line, window
    # Only the model server names its stopped state; it says so in the same line.
    assert "line: erststart || !answered ? '' : laufzeile || t('modell.nichts_laeuft')" in _source("Modellserver.svelte")


def test_the_words_of_the_old_sentences_are_gone_from_both_catalogues():
    for language in ("de", "en"):
        catalogue = _catalogue(language)
        assert "laeuft" not in catalogue["einbettungsserver"] and "aus" not in catalogue["einbettungsserver"]
        assert "laeuft" not in catalogue["sprachserver"]
        # Still read by the phone and the tools.
        assert catalogue["modell"]["laeuft_port"]
        assert catalogue["status"]["aktiv"] and catalogue["status"]["inaktiv"]


def test_the_start_button_is_one_size_with_a_dot_in_both_states():
    markup = _markup("Startknopf.svelte")
    assert "farbe={punkt === 'gruen' ? 'gruen' : 'still'}" in markup and "groesse={10}" in markup
    button = _style("Startknopf.svelte").split(".startknopf {", 1)[1].split("}", 1)[0]
    assert "width: 86px" in button and "height: 34px" in button and "border-radius: 9px" in button


def test_the_page_opens_on_local_models_and_a_wish_names_what_to_show():
    markup = _markup("ModelleLokal.svelte")
    assert "const LOCAL = 'lokal'" in markup and "let gezeigt = $state(LOCAL)" in markup


def test_the_other_pages_keep_their_own_list_and_the_settings_still_ask_before_leaving():
    """Silence: the settings, the local models, the provider page, the server
    pages and the catalogue carry the settings list, and the settings window
    still switches its own pages through the guard that asks about an unsaved
    edit. The catalogue reads none of the settings figures."""
    assert "SettingsNav" in _source("Katalog.svelte")
    assert "settingsState" not in _source("Katalog.svelte")
    # The provider page puts the shared list in its sidebar and reads none of its figures.
    assert "settingsState" not in _source("ModelleCloud.svelte")
    prompt = _source("SystemPrompt.svelte")
    assert "function navZiel(key)" in prompt
    assert "chooseRow(zeile, { page: navZiel," in prompt
