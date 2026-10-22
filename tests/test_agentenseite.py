"""The agents page of the settings: the description under a name in the list,
the pen and the bin as signs, the tools with their marks, the mask in two
columns, its foot as three signs, and the colour and folder controls that
carry no word. Read off the source, the way the other interface tests do.
"""

from __future__ import annotations

import json
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


# --- The list and the head ---------------------------------------------------


def test_a_row_of_the_list_carries_what_the_agent_is_for_under_its_name():
    markup = _markup("SettingsAgents.svelte")
    row = markup.split("{#each dateien as eintrag (eintrag.name)}", 1)[1].split("{/each}", 1)[0]
    assert "purposeOf(eintrag.name)" in row
    assert 'class="unter" title={purposeOf(eintrag.name)}' in row
    # Without a description the row stays one line: the second line stands under a condition.
    assert "{#if purposeOf(eintrag.name)}" in row
    # One lookup table, built once per list, not a search per row and render.
    assert "new Map(agenten.map((a) => [a.name, a.description ?? '']))" in _source("SettingsAgents.svelte")


def test_the_head_has_a_pen_and_a_red_bin_and_no_word_button_and_no_hand_drawn_branch():
    markup = _markup("SettingsAgents.svelte")
    head = markup.split('<div class="knoepfe">', 1)[1].split("{#if datei.kaputt}", 1)[0]
    assert '<Hauszeichen zeichen="stift"' in head and '<Hauszeichen zeichen="trash"' in head
    assert "aria-label={t('agenten.bearbeiten')} title={t('agenten.bearbeiten')}" in head
    assert "aria-label={t('agenten.loeschen')} title={t('agenten.loeschen')}" in head
    assert 'class="signbutton danger"' in head and 'class="knopf' not in head
    # The branch of the subagents row and head comes from the house catalogue.
    assert "<svg" not in markup
    assert markup.count('<Hauszeichen zeichen="branch"') == 2
    style = _style("SettingsAgents.svelte")
    assert "color: var(--rot-text)" in style.split(".signbutton.danger {", 1)[1].split("}", 1)[0]


def test_every_tool_pill_wears_its_mark_and_a_servers_tool_wears_the_servers_logo():
    markup = _markup("SettingsAgents.svelte")
    pill = markup.split('<Standpille farbe="werkzeug">', 1)[1].split("</Standpille>", 1)[0]
    assert '<span class="wzzeichen">' in pill and "<Werkzeugzeichen name={werkzeug}" in pill
    assert "logo={info && !info.builtin ? serverLogo(info.server) : null}" in pill
    # The server comes from the tools list, not from the name, whose odd characters are turned to underscores.
    assert "toolInfo.get(werkzeug)" in pill and "api.werkzeuge()" in _source("SettingsAgents.svelte")
    # Both states of the tools stay: "all" and "none".
    assert "agenten.alle_werkzeuge" in markup and "agenten.keine_werkzeuge" in markup


def test_the_row_of_the_menu_reads_how_many_are_created_in_both_languages():
    assert _catalogue("de")["agenten"]["created_count"] == "{n} angelegt"
    assert _catalogue("en")["agenten"]["created_count"] == "{n} created"
    # The figure lives with the other figures of the list; the settings write the count in as it changes.
    figures = (TEILE.parent / "lib" / "settingsState.svelte.js").read_text(encoding="utf-8")
    assert "t('agenten.created_count', { n: settingsState.agents })" in figures
    assert "settingsState.agents = dateien.length" in _source("SystemPrompt.svelte")


# --- The mask ------------------------------------------------------------------


def test_the_mask_stands_in_two_columns_that_fall_to_one_under_860_px_and_on_the_phone():
    markup = _markup("Agentenmaske.svelte")
    left, right = markup.split('<div class="spalte">')[1:3]
    # Left: name, description, instruction. Right: tools, colour, folders, limits.
    for key in ("agenten.name", "agenten.purpose", "agenten.anweisung"):
        assert key in left and key not in right.split('class="grenzenkopf"', 1)[0]
    for key in ("werkzeuge.titel", "agenten.alle_werkzeuge", "agenten.farbe", "agenten.ordner", "agenten.grenzen"):
        assert key in right, key
    style = _style("Agentenmaske.svelte")
    grid = style.split("  .spalten {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)" in grid
    assert "@media (max-width: 860px)" in style
    assert ":global(html[data-phone]) .spalten { grid-template-columns: minmax(0, 1fr); grid-template-rows: 1fr auto; }" in style
    # The mask is also measured by its own width: a window of 900 px gives it far less than 860.
    assert "container: maske / inline-size" in style and "@container maske (max-width: 640px)" in style


def test_the_page_uses_the_whole_area_the_instruction_grows_down_to_the_foot():
    mask = _style("Agentenmaske.svelte")
    assert "flex: 1 1 auto" in mask.split("  .maske {", 1)[1].split("}", 1)[0]
    prompt = mask.split("  .feld.prompt {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 auto" in prompt and "min-height: 320px" in prompt and "\n    height: 320px" not in prompt
    assert "stacked grow" in _markup("Agentenmaske.svelte")
    page = _style("SettingsAgents.svelte")
    grid = page.split("  .zweispaltig {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 auto" in grid and "grid-template-rows: minmax(0, 1fr)" in grid
    # The list and the chosen agent scroll inside themselves, like the tools list.
    for rule in ("\n  .liste {", "\n  .einzel {"):
        assert "overflow-y: auto" in page.split(rule, 1)[1].split("}", 1)[0], rule
    assert "flex: 1 1 auto" in page.split("\n  .kasten-text {", 1)[1].split("}", 1)[0]
    # In the narrow layout (the page's own width) and on the phone the instruction is a box of its own height again.
    narrow = page.split("@container agents-page (max-width: 640px) {", 1)[1].split("\n  }\n", 1)[0]
    assert "height: 320px" in narrow.split(".kasten-text {", 1)[1].split("}", 1)[0]
    phone = page.split(":global(html[data-phone]) .kasten-text {", 1)[1].split("}", 1)[0]
    assert "flex: none" in phone and "height: 320px" in phone
    # The signs are a fingertip tall on the phone, in the head and in the foot of the mask.
    for sheet in (page, _style("Agentenmaske.svelte")):
        sign = sheet.split(":global(html[data-phone]) .signbutton {", 1)[1].split("}", 1)[0]
        assert "width: 44px" in sign and "height: 44px" in sign
    # The frame gives the list the page's height and the short foot of the schedules.
    prompt = _source("SystemPrompt.svelte")
    assert "const agentList = $derived(istAgent && !maske && !agentBearbeiten)" in prompt
    assert "festeHoehe={istWerkzeuge || istCronjobs || agentList || istDatei} fillsFoot={istCronjobs || agentList}" in prompt


def test_the_tools_have_their_heading_and_every_row_of_the_list_its_mark():
    markup = _markup("Agentenmaske.svelte")
    assert '<div class="heading">{t(\'werkzeuge.titel\')}</div>' in markup
    row = markup.split('<label class="wz">', 1)[1].split("</label>", 1)[0]
    assert '<span class="wzzeichen">' in row
    assert "<Werkzeugzeichen name={werkzeug.name} server={werkzeug.server} eingebaut={werkzeug.builtin}" in row
    assert "logo={werkzeug.builtin ? null : serverLogo(werkzeug.server)}" in row
    # The cap of 20 with the soft edge and the empty state stay.
    source = _source("Agentenmaske.svelte")
    assert "const LISTE_OFFEN_BIS = 20" in source and "use:rollfade" in source
    assert "agenten.keine_werkzeuge" in markup


def test_the_foot_of_the_mask_is_three_signs_with_their_word_as_tooltip_and_label():
    markup = _markup("Agentenmaske.svelte")
    foot = markup.split('<div class="fuss">', 1)[1]
    for word, sign in (("app.abbrechen", "kreuz"), ("agenten.zuruecksetzen", "refresh"), ("app.sichern", "save")):
        assert f"aria-label={{t('{word}')}}" in foot and f"title={{t('{word}')}}" in foot
        assert f'<Hauszeichen zeichen="{sign}"' in foot
    # The cross keeps the red edge of "this throws away"; the reset only stands where a state is.
    assert 'class="signbutton verwirft"' in foot
    reset = foot.split("{#if stand}", 1)[1].split("{/if}", 1)[0]
    assert 'zeichen="refresh"' in reset and 'zeichen="kreuz"' not in reset and 'zeichen="save"' not in reset
    # The save keeps its conditions, and no tick and no word button is left.
    assert "disabled={sichert || laedt || !neuName.trim() || !neuPrompt.trim()}" in foot
    assert 'class="haken"' not in markup and 'class="knopf' not in markup
    style = _style("Agentenmaske.svelte")
    assert "color: var(--rot-text)" in style.split(".signbutton.verwirft {", 1)[1].split("}", 1)[0]


def test_the_limits_stand_folded_with_their_count_and_the_arrow_comes_from_the_house():
    source = _source("Agentenmaske.svelte")
    assert "const GRENZEN_ANZAHL = 6" in source and "let grenzenOffen = $state(false)" in source
    markup = _markup("Agentenmaske.svelte")
    head = markup.split('<button class="grenzenkopf"', 1)[1].split("</button>", 1)[0]
    assert "aria-expanded={grenzenOffen}" in head
    assert '<Hauszeichen zeichen="chevron_right"' in head
    assert "prefers-reduced-motion: reduce" in source
    # The two limits that may not be left out keep their fields.
    assert "bind:wert={maxRunden} min={1}" in markup and "bind:wert={maxMinuten} min={1}" in markup


def test_the_question_about_deleting_an_agent_is_red_on_the_desktop_and_on_the_phone():
    desktop = _source("SystemPrompt.svelte")
    body = desktop.split("async function agentLoeschen(name = agentName) {", 1)[1].split("\n  }\n", 1)[0]
    assert "frage(t('agenten.loeschen_frage', { name }), { danger: true, okSchluessel: 'agenten.delete_button' })" in body
    phone = (ROOT / "frontend" / "src" / "phone" / "settings" / "Agents.svelte").read_text(encoding="utf-8")
    remove = phone.split("async function remove(name) {", 1)[1].split("\n  }\n", 1)[0]
    assert "frage(t('agenten.loeschen_frage', { name }), { danger: true, okSchluessel: 'agenten.delete_button' })" in remove


# --- Colour and folders --------------------------------------------------------


def test_the_colour_is_taken_away_with_a_bin_whose_tooltip_says_what_goes():
    markup = _markup("Agentenfarbwahl.svelte")
    away = markup.split('<button class="weg"', 1)[1].split("</button>", 1)[0]
    assert '<Hauszeichen zeichen="trash"' in away
    assert "aria-label={t('agenten.farbe_entfernen')} title={t('agenten.farbe_entfernen')}" in away
    assert _catalogue("de")["agenten"]["farbe_entfernen"] == "Farbe löschen"
    assert _catalogue("en")["agenten"]["farbe_entfernen"] == "Remove color"
    # Code and bin stand only where a colour is set.
    assert markup.index("{#if farbe}") < markup.index('class="code"') < markup.index('class="weg"')


def test_a_folder_pill_has_a_bin_and_the_folder_button_is_the_sign_alone():
    markup = _markup("Startordnerpillen.svelte")
    pill = markup.split('<div class="pille">', 1)[1].split("{/each}", 1)[0]
    assert '<Hauszeichen zeichen="trash"' in pill and "✕" not in markup
    assert "aria-label={t('arbeitsordner.loesen')} title={t('arbeitsordner.loesen')}" in pill
    assert 'title={displayPath(pfad)}' in pill
    button = markup.split('<button\n      class="mehr"', 1)[1].split("</button>", 1)[0]
    assert '<Hauszeichen zeichen="ordner"' in button and "mehrwort" not in button
    assert "title={t('arbeitsordner.hinzufuegen')}" in button
    assert "aria-label={t('arbeitsordner.hinzufuegen')}" in button
    # The typed path for a machine without a dialog stays, with its keys held in the field.
    assert 'class="pfadfeld"' in markup and "ereignis.stopPropagation()" in markup


# --- The delete question's word and the warning under the tools ---------------------


def test_the_red_button_of_the_delete_question_says_delete_in_both_languages():
    # The call itself is read in the test of the red question above.
    assert _catalogue("de")["agenten"]["delete_button"] == "Löschen"
    assert _catalogue("en")["agenten"]["delete_button"] == "Delete"


def test_the_warning_stands_when_the_command_tool_and_a_web_tool_are_both_allowed():
    markup = _markup("Agentenmaske.svelte")
    assert "import { artFuer } from '../lib/werkzeugarten.js'" in markup
    derived = markup.split("const allowed = $derived(", 1)[1].split("</script>", 1)[0]
    # All tools, or the picked ones: the switch decides what the list holds.
    assert "alleWerkzeuge\n      ? werkzeuge\n      : gewaehlteWerkzeuge.map((name) => ({" in derived
    assert "artFuer(w.name, w.server) === 'terminal'" in derived
    assert "artFuer(w.name, w.server) === 'web'" in derived
    block = markup.split("{#if commandWebWarning}", 1)[1].split("{/if}", 1)[0]
    assert "t('agenten.command_web_warning')" in block
    # It stands under the list of tools, above the colour.
    assert markup.index("{#if commandWebWarning}") < markup.index("t('agenten.farbe')")
    assert markup.index("{#each werkzeuge as werkzeug") < markup.index("{#if commandWebWarning}")


def test_the_warning_is_the_quiet_yellow_form_and_reads_the_same_in_both_languages_of_the_decision():
    style = _style("Agentenmaske.svelte")
    rule = style.split("\n  .tool-warning {", 1)[1].split("}", 1)[0]
    assert "var(--gelb-text)" in rule
    assert "color-mix(in srgb, var(--gelb) 8%, var(--bg))" in rule
    assert _catalogue("en")["agenten"]["command_web_warning"] == "Warning: run_command can run any command"
    assert _catalogue("de")["agenten"]["command_web_warning"] == "Warnung: run_command kann jeden Befehl ausführen"
