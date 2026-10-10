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
