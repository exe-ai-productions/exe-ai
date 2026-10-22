"""The appearance page: the looks as a row of cards, always in sight.

The row is one group of radio buttons (arrow keys, Enter, Space), every look
of the choice has a picture, the own gradient's rows stand only while that
look is chosen, the bubble colour's reset only while a colour is set, and the
layout mode is the last row, a button with a sign and a tooltip but no word.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any

WURZEL = Path(__file__).resolve().parent.parent
TEILE = WURZEL / "frontend" / "src" / "teile"
LIB = WURZEL / "frontend" / "src" / "lib"


def _lesen(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8")


def _such(muster: str, text: str) -> re.Match[str]:
    treffer = re.search(muster, text)
    assert treffer, muster
    return treffer


def _seite() -> str:
    """The appearance page's markup in the settings window."""
    quelle = _lesen(TEILE / "SystemPrompt.svelte")
    anfang = quelle.index("{:else if istDarstellung}")
    ende = quelle.index("{:else if istSkills}")
    return quelle[anfang:ende]


def _node(code: str) -> Any:
    ergebnis = subprocess.run(
        ["node", "--input-type=module", "-e", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert ergebnis.returncode == 0, ergebnis.stderr
    return json.loads(ergebnis.stdout)


def test_the_page_shows_the_row_of_looks_and_no_dropdown():
    seite = _seite()
    assert "<Looktafel" in seite
    assert "bind:wert={modus}" in seite
    assert "MODI.map(" in seite
    assert "Klappwahl" not in seite
    assert "Klappwahl" not in _lesen(TEILE / "SystemPrompt.svelte")


def test_every_look_of_the_choice_has_a_picture():
    """Silence probe in both directions: a look without a picture would draw
    an empty card, a picture without a look is dead data."""
    modi = re.findall(
        r"\['([a-z]+)'",
        _such(r"const MODI = \[([\s\S]*?)\n  \]", _lesen(TEILE / "SystemPrompt.svelte")).group(1),
    )
    assert len(modi) == 8
    ergebnis = _node(
        f"""
        import {{ VORSCHAU, VORSCHAU_ZU_LOOK }} from '{LIB.as_uri()}/looksvorschau.js'
        const modi = {json.dumps(modi)}
        const ohne = modi.filter((m) => !['auto', 'eigen'].includes(m) && !VORSCHAU[VORSCHAU_ZU_LOOK[m]])
        const uebrig = Object.keys(VORSCHAU_ZU_LOOK).filter((m) => !modi.includes(m))
        console.log(JSON.stringify({{ ohne, uebrig }}))
        """
    )
    assert ergebnis == {"ohne": [], "uebrig": []}


def test_the_own_gradient_start_equals_the_sheet():
    """The card of the own gradient draws the gradient's start from the data
    module; the sheet carries the same numbers — held together here."""
    css = _lesen(WURZEL / "frontend" / "src" / "stil" / "global.css")
    block = _such(r":root\[data-modus='eigen'\] \{([\s\S]*?)\n\}", css).group(1)
    farben = [
        _such(rf"--rahmen-vorgabe-{n}: (#[0-9a-f]{{6}})", block).group(1) for n in range(1, 5)
    ]
    ton = int(_such(r"--rahmen-ton-vorgabe: (-?\d+)", block).group(1))
    winkel = int(_such(r"--rahmen-winkel-vorgabe: (\d+)deg", block).group(1))
    ergebnis = _node(
        f"""
        import {{ EIGEN_START }} from '{LIB.as_uri()}/looksvorschau.js'
        console.log(JSON.stringify(EIGEN_START))
        """
    )
    assert ergebnis["farben"] == farben
    assert ergebnis["ton"] == ton
    assert ergebnis["winkel"] == winkel


def test_the_own_gradient_picture_follows_the_choice_and_its_brightness():
    ergebnis = _node(
        f"""
        import {{ eigenVorschau }} from '{LIB.as_uri()}/looksvorschau.js'
        const gleich = (farbe) => farbe
        const start = eigenVorschau(undefined, gleich)
        const hell = eigenVorschau({{ farben: ['#ffffff', '#f0f0f0', '#e0e0e0', '#ffffff'], winkel: 90 }}, gleich)
        const dunkel = eigenVorschau({{ farben: ['#000000', '#101010', '#202020', '#000000'] }}, gleich)
        console.log(JSON.stringify({{ start, hell, dunkel }}))
        """
    )
    assert ergebnis["start"]["hell"] is False
    assert ergebnis["start"]["grund"].startswith("linear-gradient(0deg, #3b1280 0%")
    assert ergebnis["hell"]["hell"] is True
    assert ergebnis["hell"]["grund"].startswith("linear-gradient(90deg, #ffffff 0%")
    assert ergebnis["dunkel"]["hell"] is False


def test_the_row_is_a_radio_group_with_one_tab_stop_and_arrow_keys():
    quelle = _lesen(TEILE / "Looktafel.svelte")
    assert 'role="radiogroup"' in quelle
    assert 'role="radio"' in quelle
    assert "aria-checked={wert === look}" in quelle
    assert "tabindex={wert === look || (!bekannt && i === 0) ? 0 : -1}" in quelle
    # The check mark and the word "Active" stand only on the chosen card.
    assert _such(r"\{#if wert === look\}[\s\S]*?haken[\s\S]*?einstellungen\.aktiv", quelle)


def test_arrow_keys_move_the_choice_round_the_row():
    quelle = _lesen(TEILE / "Looktafel.svelte")
    funktion = _such(r"async function taste\(ereignis, stelle\) \{([\s\S]*?)\n  \}\n", quelle).group(1)
    ergebnis = _node(
        f"""
        const optionen = [['a'], ['b'], ['c']]
        let wert = 'a'
        const karten = [{{ focus() {{}} }}, {{ focus() {{}} }}, {{ focus() {{}} }}]
        const tick = async () => {{}}
        async function taste(ereignis, stelle) {{{funktion}}}
        const druck = (key) => ({{ key, preventDefault() {{ this.gestoppt = true }} }})
        const schritte = []
        for (const [key, stelle] of [['ArrowRight', 0], ['ArrowRight', 2], ['ArrowLeft', 0], ['ArrowDown', 1], ['ArrowUp', 1]]) {{
          await taste(druck(key), stelle)
          schritte.push(wert)
        }}
        const fremd = druck('x')
        await taste(fremd, 0)
        console.log(JSON.stringify({{ schritte, fremdGestoppt: Boolean(fremd.gestoppt), wert }}))
        """
    )
    # right: a→b, wraps c→a (from 2), left from 0 wraps to c, down b→c, up b→a.
    assert ergebnis["schritte"] == ["b", "a", "c", "c", "a"]
    assert ergebnis["fremdGestoppt"] is False


def test_a_card_keeps_its_size_when_chosen():
    """The chosen card's edge is an inset shadow, not a border: choosing a
    look must not move the cards beside it."""
    quelle = _lesen(TEILE / "Looktafel.svelte")
    karte = _such(r"\.karte \{([\s\S]*?)\n  \}", quelle).group(1)
    assert "border: none" in karte
    assert _such(r"\.karte\.aktiv \{[^}]*inset 0 0 0 1\.5px var\(--text\)", quelle)


def test_the_bubble_colour_reset_stands_only_with_a_colour_of_its_own():
    seite = _seite()
    assert re.search(
        r"\{#if zustand\.blasenfarbe\}\s*<button class=\"ruecksetzer\" onclick=\{\(\) => blasenfarbeSetzen\(''\)\}",
        seite,
    )


def test_the_gradient_rows_stand_only_while_the_own_gradient_is_chosen():
    seite = _seite()
    bedingung = seite.index("{#if rahmenSchema === EIGENER_VERLAUF}")
    ende = seite.index("{/if}", seite.index("einstellungen.winkel"))
    block = seite[bedingung:ende]
    for noetig in ("hintergrundfarbe", "einstellungen.farbton", "einstellungen.winkel"):
        assert noetig in block
    # And nowhere outside the condition.
    ausserhalb = seite[:bedingung] + seite[ende:]
    for fremd in ("hintergrundfarbe", "einstellungen.farbton", 'type="range"'):
        assert fremd not in ausserhalb


def test_the_code_colours_are_a_field_with_a_block_of_code_in_the_chosen_colours():
    seite = _seite()
    assert "<Auswahlfeld" in seite
    assert "CODE_PACKS.map(" in seite
    assert "gewaehlt={(neu) => codefarbenSetzen(neu)}" in seite
    # The block wears the highlighter's own classes, so the pack colours it; the row of the field has none.
    assert 'class="code-sample hljs"' in seite and "{#each CODE_SAMPLE as" in seite
    assert "codeprobe" not in seite and "CODE_PROBE" not in seite
    quelle = _lesen(TEILE / "SystemPrompt.svelte")
    for klasse in ("hljs-keyword", "hljs-string", "hljs-number", "hljs-comment", "hljs-title function_"):
        assert klasse in quelle


def test_the_layout_mode_is_the_last_row_a_sign_with_a_tooltip_and_no_word():
    seite = _seite()
    letzte = seite.rindex('<div class="einstellkachel">')
    zeile = seite[letzte:]
    assert "layoutModusOeffnen" in zeile
    assert 'zeichen="ecken"' in zeile
    assert "title={t('einstellungen.layout_modus')}" in zeile
    assert "aria-label={t('einstellungen.layout_modus')}" in zeile
    # The label stands once as the row's text; the button holds only the sign.
    knopf = _such(r"<button class=\"symbolknopf\"[\s\S]*?</button>", zeile).group(0)
    assert "{t(" not in re.sub(r"(title|aria-label)=\{t\([^)]*\)\}", "", knopf)
    # No other row follows it.
    assert zeile.count("einstellkachel") == 1


def test_the_active_mark_has_a_text_in_both_catalogues():
    for sprache in ("en", "de"):
        katalog = json.loads(_lesen(WURZEL / "app" / "locales" / f"{sprache}.json"))
        assert katalog["einstellungen"]["aktiv"]
