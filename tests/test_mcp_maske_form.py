"""Source-text checks for the MCP sheet unification: every not-yet-connected
tile routed through one sheet, its headings in the house form, the two new
drawn signs wired at their sites.

Behavioural testing of a full Svelte component's instance script is not
practical here (the codebase's own compileModule technique reaches only
`.svelte.js` modules and `<script module>` blocks — see test_docfolder_ansicht.py
and test_verbessern_cloud.py — and MCPMaske.svelte's new logic lives in
its instance `<script>`, which needs `$props()`/`$state()`). This is the
codebase's established substitute for a behavioural test where none is
practical, the same standing source-text checks have elsewhere
(test_hausregeln.py's TAFELKOPF_FORM).
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "frontend" / "src"
VERBINDUNGEN = QUELLE / "teile" / "Verbindungen.svelte"
CARDS = QUELLE / "lib" / "mcpCards.js"
MASKE = QUELLE / "teile" / "MCPMaske.svelte"
HAUSZEICHEN = QUELLE / "teile" / "Hauszeichen.svelte"
SYSTEM_PROMPT = QUELLE / "teile" / "SystemPrompt.svelte"


# --- Every not-yet-connected tile opens the sheet, not the small menu -----


def test_every_tile_and_every_disconnected_card_opens_the_sheet():
    """A tile without an entry and a card whose sign-in is gone each carry the
    grey button into the sheet, not the small menu."""
    source = VERBINDUNGEN.read_text(encoding="utf-8")
    tile = source.split("{#snippet tile(k)}", 1)[1].split("{/snippet}", 1)[0]
    assert "onclick={() => maskeOeffnen(k)}" in tile and "t('verbindungen.verbinden')" in tile
    card = source.split("{#snippet card(k)}", 1)[1].split("{/snippet}", 1)[0]
    lost = card.split("{#if stand === 'getrennt'}", 1)[1].split("{:else}", 1)[0]
    assert "onclick={() => maskeOeffnen(k)}" in lost and "t('verbindungen.verbinden')" in lost
    assert "brauchtVerbindung" not in source


def test_a_card_without_a_key_keeps_its_menu_and_the_menu_opens_the_sheet():
    """A card whose key is missing keeps its menu, so it can still be
    switched off and removed; the menu's connect line opens the sheet."""
    source = VERBINDUNGEN.read_text(encoding="utf-8")
    card = source.split("{#snippet card(k)}", 1)[1].split("{/snippet}", 1)[0]
    menu_branch = card.split("{:else}", 1)[1]
    assert "oeffnen(k, e)" in menu_branch and "aria-haspopup=\"menu\"" in menu_branch
    zweig = source.split("{#if stand === 'schluessel_fehlt'}", 1)[1].split("{/if}", 1)[0]
    # `k` follows the open menu: closing it first would hand the sheet nothing.
    assert "maskeOeffnen(k); schliessen()" in zweig


def test_das_kleine_menue_hat_keinen_verbinden_zweig_mehr():
    """The connect branch used to gate on the tile's own state
    (`stand === 'frei' || stand === 'getrennt'`) before showing a "Connect"
    button — `oeffnen()` never lets that branch run any more, so its
    markup would be dead if it were still there."""
    quelle = VERBINDUNGEN.read_text(encoding="utf-8")
    assert "stand === 'frei' || stand === 'getrennt'" not in quelle
    assert "function verbinden(kachel)" not in quelle


# --- The four field/section headings carry the house form -----------------


def test_the_mask_labels_carry_no_sign_and_no_rule():
    """Field labels are small quiet lines, section headings half bold: both
    without a drawn sign (the sign stands once, on the empty tool field)."""
    source = MASKE.read_text(encoding="utf-8")
    markup = source.split("</script>", 1)[1].split("<style>", 1)[0]
    assert "tafelkopf" not in source
    assert markup.count("<Hauszeichen") == 1
    for key in ("mcp.url", "mcp.api_key", "mcp.anmeldung", "mcp.eigene_app", "mcp.tools_titel"):
        assert re.search(r'class="(label|heading)">\{t\(\'%s\'\)\}' % re.escape(key), markup), key


def test_the_mask_defines_label_and_heading_without_a_rule():
    source = MASKE.read_text(encoding="utf-8")
    label = source.split("\n  .label {", 1)[1].split("}", 1)[0]
    heading = source.split("\n  .heading {", 1)[1].split("}", 1)[0]
    assert "font-size: 12px" in label and "color: var(--text-leise)" in label
    assert "margin-bottom: 6px" in label
    assert "font-weight: 600" in heading
    assert "border" not in label and "border" not in heading
    assert "height: 34px" in source.split("\n  .eingabe {", 1)[1].split("}", 1)[0]


# --- The two new drawn signs are wired at their sites ----------------------


def test_plus_und_plug_sind_im_hauskatalog():
    quelle = HAUSZEICHEN.read_text(encoding="utf-8")
    assert "zeichen === 'plus'" in quelle
    assert "zeichen === 'plug'" in quelle
    sichtfelder = quelle.split("const SICHTFELDER", 1)[1].split("\n", 1)[0]
    assert "plug: '0 0 64 64'" in sichtfelder


def test_the_window_has_no_title_sign_and_the_empty_tool_field_shows_the_plug():
    page = VERBINDUNGEN.read_text(encoding="utf-8")
    assert "{#snippet symbol()}" not in page
    assert "<Hauszeichen" not in page
    mask = MASKE.read_text(encoding="utf-8")
    assert '<Hauszeichen zeichen="plug" groesse={76} strich={3} />' in mask


def test_die_leiste_zeigt_den_stecker_fuer_mcp_server():
    # The list of the settings names the sign of the MCP row.
    quelle = (SYSTEM_PROMPT.parent.parent / "lib" / "einstellungsliste.js").read_text(encoding="utf-8")
    assert "{ id: 'tools', zeichen: 'plug'" in quelle


def test_every_tile_on_file_can_be_removed():
    """A catalogue tile without a key is on file too and has to be
    removable: nothing right before the remove button asks about the
    catalogue."""
    source = VERBINDUNGEN.read_text(encoding="utf-8")
    marker = "t('verbindungen.entfernen')"
    assert marker in source
    # The button's own tag included (a guard can sit on it as an attribute),
    # comments taken out of the whole file first so a window never starts
    # inside one.
    code = re.sub(r"<!--.*?-->", "", source.split(marker, 1)[0], flags=re.S)
    before_label = code[-500:].lower()
    assert "katalog" not in before_label and "catalog" not in before_label


def test_a_card_without_an_address_asks_for_the_shipped_entry():
    """The sheet of a server the program starts itself — not on file, no
    address — names it as shipped when it writes; a typed server never
    does. The call carries the switch to the service."""
    source = MASKE.read_text(encoding="utf-8")
    assert "const shippedServer = !istNeu && !kachel.eintrag && !quelle.url && !quelle.command" in source
    assert "shipped: shippedServer" in source
    api = (QUELLE / "lib" / "api.js").read_text(encoding="utf-8")
    assert "params.set('shipped', 'true')" in api


def test_the_sheet_of_a_server_on_file_carries_the_removal_of_the_page():
    """An entry whose sign-in was abandoned opens the sheet, so the sheet
    needs the way out the small menu has: the page's own removal, which asks
    first, and the sheet closes after it."""
    maske = MASKE.read_text(encoding="utf-8")
    knopfzeile = maske.split('<div class="knopfzeile">', 1)[1].split("</div>", 1)[0]
    zweig = knopfzeile.split("{#if !istNeu && kachel.eintrag && entfernen}", 1)[1].split("{/if}", 1)[0]
    assert "t('verbindungen.entfernen')" in zweig and "onclick={() => entfernen()}" in zweig
    assert "entfernen = null" in maske
    seite = VERBINDUNGEN.read_text(encoding="utf-8")
    assert "entfernen={mcpKachel?.eintrag ? () => entfernen(mcpKachel.eintrag, titelVon(mcpKachel)) : null}" in seite
    funktion = seite.split("async function entfernen(eintrag, serverTitle)", 1)[1].split("\n  }", 1)[0]
    assert funktion.index("frage(t('verbindungen.entfernen_frage'") < funktion.index("api.serverEntfernen")
    assert "mcpOffen = false" in funktion.split("api.serverEntfernen", 1)[1]


def test_the_button_row_stands_under_both_columns_never_inside_one():
    """Three buttons of 137 px do not fit into a column of 333 px: the row
    stands under the two columns, and the error line keeps the left one."""
    maske = MASKE.read_text(encoding="utf-8")
    markup = maske.split("</script>", 1)[1].split("<style>", 1)[0]
    assert markup.count('<div class="knopfzeile">') == 1
    row = markup.index('<div class="knopfzeile">')
    assert row > markup.index('<div class="trenner">') and row > markup.index("t('mcp.tools_titel')")
    assert markup.index("fehlertext") < markup.index('<div class="trenner">')


def test_the_buttons_of_the_row_are_equally_wide_and_equally_high_and_no_label_breaks():
    maske = MASKE.read_text(encoding="utf-8")
    rule = maske.split("\n  .knopfzeile {", 1)[1].split("}", 1)[0]
    for part in ("display: grid", "grid-auto-flow: column", "grid-auto-columns: minmax(0, 1fr)",
                 "width: max-content", "max-width: 100%", "align-self: flex-end"):
        assert part in rule
    assert "flex-shrink" not in rule and "display: flex" not in rule
    # From the narrowest window the program opens on, no label breaks.
    wide = maske.split("@media (min-width: 720px) {", 1)[1].split("\n  }", 1)[0]
    assert ".knopfzeile .button { white-space: nowrap; }" in wide
    # The rule is the mask's own: the house button stays as it is.
    css = (QUELLE / "stil" / "global.css").read_text(encoding="utf-8")
    assert "knopfzeile" not in css


def test_the_menu_and_the_sheet_hand_the_title_of_the_card_to_both_questions():
    seite = VERBINDUNGEN.read_text(encoding="utf-8")
    assert "vergessen(k.eintrag, titelVon(k))" in seite
    assert "entfernen(k.eintrag, titelVon(k))" in seite
    assert "entfernen(mcpKachel.eintrag, titelVon(mcpKachel))" in seite


def test_silence_a_new_address_and_a_card_never_set_up_get_no_removal():
    """`modus: 'neu'` has no entry, a catalogue card never set up has none
    either: the page hands down nothing, and the sheet shows nothing."""
    maske = MASKE.read_text(encoding="utf-8")
    assert "{#if !istNeu && kachel.eintrag && entfernen}" in maske
    assert maske.count("t('verbindungen.entfernen')") == 1
    seite = VERBINDUNGEN.read_text(encoding="utf-8")
    assert seite.count("t('verbindungen.entfernen')") == 1  # the small menu keeps its own


def test_the_page_keeps_two_cards_of_one_name_apart():
    """A server of one's own under a shipped name stands beside the shipped
    card: the list, the open menu and the card's own state are keyed by the
    kind and the name, never by the name alone; the shipped title and logo
    stay with the shipped server."""
    seite = VERBINDUNGEN.read_text(encoding="utf-8")
    karten = CARDS.read_text(encoding="utf-8")
    assert "entries.find((e) => gehoertZurKachel(k, e))" in karten
    assert "!KATALOG.some((k) => gehoertZurKachel(k, e))" in karten
    assert "nachName" not in seite and "nachName" not in karten
    assert "const schluesselVon = (k) => `${k.katalog ? 'katalog' : 'eigen'}:${nameVon(k)}`" in karten
    assert "{#each setUp as k (schluesselVon(k))}" in seite
    assert "{#each notSetUp as k (schluesselVon(k))}" in seite
    assert "menue?.name" not in seite and "kachelVon(menue.name)" not in seite
    assert "const kachelVon = (schluessel) =>" in seite
    assert "istKatalogName(k) ? serverTitel(nameVon(k)) : nameVon(k)" in karten


def test_the_first_write_of_a_card_without_an_entry_goes_as_a_new_one():
    """Merged into a server of one's own of the same name, the card would
    overwrite it: the first write is a new entry, and the service names the
    taken id with its own sentence. A second try of the same sheet is not."""
    maske = MASKE.read_text(encoding="utf-8")
    assert "const ohneEintrag = !istNeu && !kachel.eintrag" in maske
    assert "const erstesSchreiben = () => ohneEintrag && !eintragGeschrieben" in maske
    schreiben = maske.split("async function anlegenUndVerbinden", 1)[1].split("\n  }", 1)[0]
    assert "neu: (istNeu && serverName !== gespeicherterName) || erstesSchreiben()" in schreiben
    assert schreiben.index("api.serverSchreiben") < schreiben.index("eintragGeschrieben = true")
    anmelden = maske.split("async function browserAnmelden", 1)[1].split("\n  }", 1)[0]
    assert "serverName, { ...grundfelder(), ...signInFields() }, { neu: erstesSchreiben() }," in anmelden
    # Only after the write, so a refused first write is a first write again.
    assert anmelden.index("erstesSchreiben()") < anmelden.index("eintragGeschrieben = true")


def test_a_card_that_names_its_address_variable_asks_for_the_address():
    """SearXNG: the sheet shows the field of its own instance's address with
    the existing label, empty and without a placeholder; connecting waits for
    text in it; the entry is written from the tile (program and address in
    its environment), never taken from the shipped list."""
    maske = MASKE.read_text(encoding="utf-8")
    assert "const fragtAdresse = !istNeu && !kachel.eintrag && !!quelle.address_env" in maske
    feld = maske.split("{#if fragtAdresse}", 1)[1].split("{/if}", 1)[0]
    assert "t('modell.eigener_adresse')" in feld and "bind:value={eigeneAdresse}" in feld
    assert "placeholder" not in feld
    assert ": fragtAdresse ? eigeneAdresse.trim().length > 0" in maske
    assert "adresse: eigeneAdresse.trim()," in maske
    assert "!quelle.command" in maske  # not the shipped way


def test_a_tile_with_its_own_program_writes_the_program_and_the_address_into_the_entry():
    quelle = (QUELLE / "lib" / "mcpWerkzeuge.js").read_text(encoding="utf-8")
    funktion = quelle.split("export function grundfelder", 1)[1].split("\n}", 1)[0]
    # Only where no entry is on file: an entry that is there keeps its own.
    assert "if (quelle.command && !eintrag) {" in funktion and "felder.type = 'stdio'" in funktion
    assert "if (quelle.address_env && adresse) felder.env = { [quelle.address_env]: adresse }" in funktion


# --- One sheet with every way (the sign-in order) -------------------------


def _netzblock() -> str:
    """The part of the sheet that stands for every server reached over the
    network: own app and API key."""
    maske = MASKE.read_text(encoding="utf-8")
    return maske.split("{#if showWays}", 1)[1].split("{#if verbunden}", 1)[0]


def test_the_sections_are_the_same_for_every_kind_of_card_and_for_a_new_address():
    """Notion (oauth), Gmail (oauth_kennung), GitHub (schluessel) and a
    typed address stand on the same block, which asks nothing about the kind
    the server reports — only the way on top does."""
    block = _netzblock()
    assert "verlangt" not in block and "anmeldung" not in block
    order = [
        block.index(f"t('{key}')")
        for key in (
            "mcp.eigene_app", "verbindungen.kennung", "verbindungen.geheimnis",
            "mcp.rueckleitung", "mcp.eigene_rueckleitung", "mcp.api_key", "mcp.kopfzeile",
        )
    ]
    assert order == sorted(order)
    maske = MASKE.read_text(encoding="utf-8")
    assert "const overNetwork = istNeu || !!quelle.url" in maske


def test_the_way_the_server_reports_stands_above_the_two_that_are_always_there():
    maske = MASKE.read_text(encoding="utf-8")
    assert maske.index("{#if browserWay && !verbunden}") < maske.index("{#if showWays}")
    weg = maske.split("{#if browserWay && !verbunden}", 1)[1].split("{/if}", 1)[0]
    assert "t('mcp.im_browser_anmelden')" in weg and "onclick={browserAnmelden}" in weg
    assert "const browserWay = $derived(verlangt === 'anmeldung' || verlangt === 'oauth_kennung')" in maske


def test_a_server_that_runs_here_as_a_program_shows_neither_section():
    """SearXNG and Exe Web Search have nothing to sign in to."""
    maske = MASKE.read_text(encoding="utf-8")
    assert "const overNetwork = istNeu || !!quelle.url" in maske
    assert "const showWays = $derived(overNetwork && !verbunden)" in maske
    assert "{#if showWays}" in maske


def test_the_return_address_comes_from_the_service_and_can_be_copied():
    maske = MASKE.read_text(encoding="utf-8")
    api = (QUELLE / "lib" / "api.js").read_text(encoding="utf-8")
    assert "oauthRedirect: () => ruf('/tools/oauth/redirect')" in api
    assert "api.oauthRedirect()" in maske
    feld = _netzblock().split("t('mcp.rueckleitung')", 1)[1].split("</div>\n          </div>", 1)[0]
    assert "readonly" in feld and "value={shownRedirect}" in feld
    assert "onclick={copyRedirect}" in feld and "t('nachricht.kopieren')" in feld
    assert "const shownRedirect = $derived(ownRedirect.trim() || defaultRedirect)" in maske
    assert "navigator.clipboard.writeText(shownRedirect)" in maske


def test_an_own_https_address_goes_with_the_sign_in_and_is_read_back():
    maske = MASKE.read_text(encoding="utf-8")
    anmelden = maske.split("async function browserAnmelden", 1)[1].split("\n  }", 1)[0]
    assert "if (ownRedirect.trim()) daten.redirect_uri = ownRedirect.trim()" in anmelden
    assert anmelden.index("daten.redirect_uri") < anmelden.index("api.oauthStart(daten)")
    assert "liste.find((e) => e.server === quelle.name)?.redirect_uri" in maske
    feld = _netzblock().split("t('mcp.eigene_rueckleitung')", 1)[1].split("</label>", 1)[0]
    assert "bind:value={ownRedirect}" in feld and "placeholder" not in feld


def test_a_key_is_written_as_a_header_and_the_other_ways_are_cleared():
    maske = MASKE.read_text(encoding="utf-8")
    assert "return { ...headerFields(umgebungsname, headerName, keyHeaders), api_key: apiKey.trim() }" in maske
    assert "const umgebungsname = quelle?.api_key_env || usedVariable || apiKeyUmgebungsname(serverName)" in maske
    # A typed address with a key is connected without asking the server first.
    verbinden = maske.split("async function verbinden", 1)[1].split("\n  }", 1)[0]
    assert verbinden.index("hasKey") < verbinden.index("verlangt === undefined")
    assert "api_key_env = " not in maske.replace("quelle?.api_key_env", "")
    modul = (QUELLE / "lib" / "mcpWerkzeuge.js").read_text(encoding="utf-8")
    assert "return { headers, api_key_env: null, auth: null }" in modul


def test_silence_the_time_limit_the_tool_list_and_the_removal_stay_as_they_were():
    maske = MASKE.read_text(encoding="utf-8")
    assert "t('mcp.zeitgrenze')" in maske and "bind:value={timeLimit}" in maske
    assert "{#each werkzeuge as werkzeug (werkzeug.name)}" in maske
    assert "{#if !istNeu && kachel.eintrag && entfernen}" in maske
    assert "timeout: timeLimitFromField(timeLimit)" in maske


def test_the_card_of_a_key_server_asks_the_service_not_the_name_of_a_variable():
    """With the key in a header there is no `api_key_env` to look at: the
    list answers whether every variable a header names is set."""
    seite = CARDS.read_text(encoding="utf-8")
    assert "if (eintrag.schluessel_gesetzt === false) return 'schluessel_fehlt'" in seite
    assert "eintrag.schluessel_gesetzt == null" in seite


def test_the_sign_in_through_the_browser_replaces_a_key_the_entry_had():
    maske = MASKE.read_text(encoding="utf-8")
    assert "auth: 'oauth', api_key_env: null, headers: headersWithoutKey(kachel?.eintrag?.headers)," in maske
    assert maske.count("...signInFields()") == 2  # a typed address and a tile


def test_connect_waits_for_a_valid_header_name_and_for_an_address_of_a_new_server():
    maske = MASKE.read_text(encoding="utf-8")
    assert "const headerNameValid = $derived(/^[A-Za-z0-9!#$%&'*+.^_`|~-]+$/.test(headerName.trim()))" in maske
    assert "hasKey ? headerNameValid && (!istNeu || adresse.trim().length > 0)" in maske


def test_the_copy_button_copies_nothing_it_does_not_have():
    maske = MASKE.read_text(encoding="utf-8")
    funktion = maske.split("async function copyRedirect", 1)[1].split("\n  }", 1)[0]
    assert "if (!shownRedirect) return" in funktion
    assert "if (!document.execCommand('copy')) return" in funktion
    assert funktion.index("return") < funktion.index("copied = true")
    assert "data-copied={copied} disabled={!shownRedirect} onclick={copyRedirect}" in maske


def test_a_late_answer_does_not_overwrite_what_the_person_typed():
    maske = MASKE.read_text(encoding="utf-8")
    assert "if (own && !ownRedirect) ownRedirect = own" in maske


def test_a_header_that_holds_a_key_makes_the_sheet_ask_for_the_key():
    """An entry whose key stands in a header and is not set shows red on the
    page; its sheet asks for the key like one with `api_key_env`."""
    maske = MASKE.read_text(encoding="utf-8")
    assert "(quelle.api_key_env || keyVariableOf(quelle.headers)) ? 'schluessel' : null" in maske
    assert "const usedVariable = keyVariableOf(keyHeaders)" in maske
