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
MASKE = QUELLE / "teile" / "MCPMaske.svelte"
HAUSZEICHEN = QUELLE / "teile" / "Hauszeichen.svelte"
SYSTEM_PROMPT = QUELLE / "teile" / "SystemPrompt.svelte"


# --- Every not-yet-connected tile opens the sheet, not the small menu -----


def test_jede_nicht_verbundene_kachel_oeffnet_das_blatt():
    quelle = VERBINDUNGEN.read_text(encoding="utf-8")
    funktion = quelle.split("function brauchtVerbindung", 1)[1].split("\n  }", 1)[0]
    assert "'frei'" in funktion and "'getrennt'" in funktion


def test_eine_kachel_ohne_schluessel_oeffnet_das_menue_mit_verbinden():
    """A tile whose key is missing keeps its menu, so it can still be
    switched off and removed; the menu's connect line opens the sheet."""
    quelle = VERBINDUNGEN.read_text(encoding="utf-8")
    funktion = quelle.split("function brauchtVerbindung", 1)[1].split("\n  }", 1)[0]
    assert "'schluessel_fehlt'" not in funktion
    zweig = quelle.split("{#if stand === 'schluessel_fehlt'}", 1)[1].split("{/if}", 1)[0]
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


def test_die_vier_ueberschriften_tragen_tafelkopf_und_ihr_zeichen():
    quelle = MASKE.read_text(encoding="utf-8")
    for zeichen, text in [
        ("wolke", "mcp.url"),
        ("schluessel", "mcp.api_key"),
        ("person", "mcp.anmeldung"),
        ("werkzeug", "mcp.tools_titel"),
    ]:
        treffer = re.search(
            r'class="tafelkopf[^"]*"><Hauszeichen zeichen="%s"[^>]*/>\{t\(\'%s\'\)\}' % (zeichen, text),
            quelle,
        )
        assert treffer, f"{zeichen}/{text} not found in tafelkopf form"


def test_die_maske_definiert_die_hausform_mit_haarlinie():
    quelle = MASKE.read_text(encoding="utf-8")
    block = quelle.split(".tafelkopf {", 1)[1].split(".feldblock .tafelkopf, .zeile", 1)[1]
    assert "border-top: 1px solid var(--linie)" in block


# --- The two new drawn signs are wired at their sites ----------------------


def test_plus_und_plug_sind_im_hauskatalog():
    quelle = HAUSZEICHEN.read_text(encoding="utf-8")
    assert "zeichen === 'plus'" in quelle
    assert "zeichen === 'plug'" in quelle
    sichtfelder = quelle.split("const SICHTFELDER", 1)[1].split("\n", 1)[0]
    assert "plug: '0 0 64 64'" in sichtfelder


def test_das_fenster_zeigt_plus_fuer_neu_und_plug_fuer_eine_kachel():
    quelle = VERBINDUNGEN.read_text(encoding="utf-8")
    symbol = quelle.split("{#snippet symbol()}", 1)[1].split("{/snippet}", 1)[0]
    assert "mcpModus === 'neu' ? 'plus' : 'plug'" in symbol


def test_die_leiste_zeigt_den_stecker_fuer_mcp_server():
    quelle = SYSTEM_PROMPT.read_text(encoding="utf-8")
    assert "tools: { zeichen: 'plug'" in quelle


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
    assert "entfernen={mcpKachel?.eintrag ? () => entfernen(mcpKachel.eintrag) : null}" in seite
    funktion = seite.split("async function entfernen(eintrag)", 1)[1].split("\n  }", 1)[0]
    assert funktion.index("frage(t('verbindungen.entfernen_frage'") < funktion.index("api.serverEntfernen")
    assert "mcpOffen = false" in funktion.split("api.serverEntfernen", 1)[1]


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
    assert "eintraege.find((e) => gehoertZurKachel(k, e))" in seite
    assert "!KATALOG.some((k) => gehoertZurKachel(k, e))" in seite
    assert "nachName" not in seite
    assert "const schluesselVon = (k) => `${k.katalog ? 'katalog' : 'eigen'}:${nameVon(k)}`" in seite
    assert "{#each cards as k (schluesselVon(k))}" in seite
    assert "menue?.name" not in seite and "kachelVon(menue.name)" not in seite
    assert "const kachelVon = (schluessel) =>" in seite
    assert "istKatalogName(k) ? serverTitel(nameVon(k)) : nameVon(k)" in seite


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
    assert "api.serverSchreiben(serverName, grundfelder(), { neu: erstesSchreiben() })" in anmelden
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
