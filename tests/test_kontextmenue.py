"""The right-click menu's list of entries, run for real.

This is JavaScript and the suite is Python, so node runs it — the same detour
tests/test_adressregel.py takes, and for the same reason: the rule lived in
fenster-electron/main.js, which requires electron and therefore cannot run
outside a packaged window, and one of its branches could be missing without a
test going red.

See fenster-electron/kontextmenue.js.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
MODUL = WURZEL / "fenster-electron" / "kontextmenue.js"

node_da = pytest.mark.skipif(shutil.which("node") is None, reason="no Node")

SKRIPT = """
const k = require(%(modul)s)
const rollen = (liste) => liste.filter((e) => e.art === 'rolle').map((e) => e.role)
const leer = { x: 10, y: 10, isEditable: false, selectionText: '', mediaType: 'none' }
console.log(JSON.stringify({
  leere_flaeche: k.baue(leer, {}),
  leere_flaeche_rollen: rollen(k.baue(leer, {})),
  textauswahl: k.baue({ ...leer, selectionText: '  ein Satz  ' }, { canCopy: true, canSelectAll: true }),
  feld: k.baue({ ...leer, isEditable: true, dictionarySuggestions: ['Haus'] }, { canCopy: true }),
  bild: k.baue({ ...leer, mediaType: 'image', srcURL: 'http://x/b.png' }, {}),
  link: k.baue({ ...leer, linkURL: 'http://x/seite' }, {}),
  link_ohne_schluessel: k.baue(
    { ...leer, linkURL: 'http://x/b.png?schluessel=geheim' }, {},
    { linkLabel: 'Copy Link Address — not available', linkAdresse: 'http://x/b.png' },
  ),
  vorlesen_auswahl: k.baue(
    { ...leer, selectionText: '  ein Satz  ' }, { canCopy: true }, { vorlesenLabel: 'Vorlesen' },
  ),
  vorlesen_feld: k.baue(
    { ...leer, isEditable: true, selectionText: 'im Feld' }, { canCopy: true }, { vorlesenLabel: 'Read aloud' },
  ),
  vorlesen_ohne_auswahl: k.baue(leer, {}, { vorlesenLabel: 'Vorlesen' }),
  vorlesen_ohne_wort: k.baue({ ...leer, selectionText: 'ein Satz' }, { canCopy: true }),
  bild_und_link: k.baue(
    { ...leer, mediaType: 'image', srcURL: 'http://x/b.png', linkURL: 'http://x/seite' }, {},
  ),
}))
""" % {"modul": json.dumps(str(MODUL))}


def _lauf() -> dict:
    ergebnis = subprocess.run(
        ["node", "-e", SKRIPT], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert ergebnis.returncode == 0, (ergebnis.stdout + ergebnis.stderr)[-2000:]
    return json.loads(ergebnis.stdout.strip().splitlines()[-1])


@node_da
def test_ein_rechtsklick_ohne_auswahl_bietet_alles_auswaehlen():
    """A right click next to marked text clears the
    selection (Chromium's own rule) and the menu then had nothing to offer —
    so no menu opened at all. The one entry that makes sense without a
    selection is the one that makes one, and it has to WORK: an `enabled:
    false` on it would be the same nothing with a label on it."""
    bericht = _lauf()
    assert bericht["leere_flaeche_rollen"] == ["selectAll"], bericht["leere_flaeche"]
    (eintrag,) = bericht["leere_flaeche"]
    assert "enabled" not in eintrag, "the entry is grey instead of executable"


@node_da
def test_die_schweigeproben_bleiben_bei_ihren_eintraegen():
    """Every other case keeps what it had — and none of them gets a SECOND
    selectAll beside the one it already carries."""
    bericht = _lauf()

    # A selection offers copy and everything; no third entry appears.
    assert bericht["textauswahl"] == [
        {"art": "rolle", "role": "copy", "enabled": True},
        {"art": "trenner"},
        {"art": "rolle", "role": "selectAll", "enabled": True},
    ], bericht["textauswahl"]

    # An editable field keeps its full list, spelling suggestion included.
    feld = bericht["feld"]
    assert feld[0] == {"art": "wort", "label": "Haus"}
    assert [e["role"] for e in feld if e.get("art") == "rolle"] == [
        "undo", "redo", "cut", "copy", "paste", "selectAll",
    ], feld
    assert sum(1 for e in feld if e.get("role") == "selectAll") == 1, (
        "the field got a second selectAll"
    )

    # A picture offers its two, and no selectAll beside them.
    assert [e["art"] for e in bericht["bild"]] == ["bild_speichern", "bild_kopieren"]

    # A link offers its one, with the label the caller decided.
    # Without an address from the caller there is nothing to copy — the
    # entry still says what it is (the caller always hands one in; main.js
    # reads it off the click).
    assert bericht["link"] == [
        {"art": "link", "label": "Copy Link Address"}
    ], bericht["link"]
    assert bericht["link_ohne_schluessel"][0]["label"] == (
        "Copy Link Address — not available"
    )
    assert bericht["link_ohne_schluessel"][0]["adresse"] == "http://x/b.png"

    # Picture AND link in one click: both, separated, still no selectAll.
    assert [e["art"] for e in bericht["bild_und_link"]] == [
        "bild_speichern", "bild_kopieren", "trenner", "link",
    ], bericht["bild_und_link"]


@node_da
def test_vorlesen_steht_nur_bei_markiertem_text():
    """Marked text, in the chat or in a field, gets "Read aloud" with the
    page's own word and the trimmed text; without a selection there is no
    such entry (the silence check), and neither in a window whose page never
    named it."""
    daten = _lauf()
    letzter = daten["vorlesen_auswahl"][-1]
    assert letzter == {"art": "vorlesen", "label": "Vorlesen", "text": "ein Satz"}
    assert daten["vorlesen_auswahl"][-2] == {"art": "trenner"}
    assert daten["vorlesen_feld"][-1] == {"art": "vorlesen", "label": "Read aloud", "text": "im Feld"}
    for fall in ("vorlesen_ohne_auswahl", "vorlesen_ohne_wort"):
        assert all(e["art"] != "vorlesen" for e in daten[fall]), fall
