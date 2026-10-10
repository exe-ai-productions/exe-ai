"""The tool column beside the chat, run rather than read.

``lib/arbeitsleiste.svelte.js`` keeps whether the column is open and which
tool it shows — one at a time. A click on a sign shows that tool and opens a
folded column on it; the sign of the tool already showing does nothing; the
head's button and ⌘J fold the column and keep the tool. The module is
compiled with the Svelte compiler (it uses runes), its imports are bent to
stand-ins, and the calls go in the way the buttons make them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
LEISTE = FRONTEND / "src/lib/arbeitsleiste.svelte.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

STUBS = """
export const gespeichert = []
export const VORGABE_LAYOUT = { leiste_offen: false, leiste_modul: 'terminal', leiste_breite: 312 }
export const layoutSpeichern = (wert) => gespeichert.push(wert)
export const t = (schluessel) => schluessel
export const frage = async () => true
"""

TREIBER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
let code = compileModule(readFileSync(%(leiste)r, 'utf-8'), { filename: 'arbeitsleiste.svelte.js', generate: 'client' }).js.code
code = code
  .replace(/from '\\.\\/anzeige\\.js'/g, "from './%(stubs)s'")
  .replace(/from '\\.\\/texte\\.svelte\\.js'/g, "from './%(stubs)s'")
  .replace(/from '\\.\\/zustand\\.svelte\\.js'/g, "from './%(stubs)s'")
writeFileSync('%(leiste_mjs)s', code)
const m = await import('./%(leiste_mjs)s')
const { leiste } = m
const stand = () => ({ offen: leiste.offen, modul: leiste.modul })
const bericht = await (async () => {
%(szenario)s
})()
console.log('---BERICHT---' + JSON.stringify(bericht))
process.exit(0)
"""


def _namensatz() -> dict[str, str]:
    """One set of file names per RUN, not per test file.

    The drivers have to stand beside `node_modules` — one of them compiles a
    Svelte module and imports `svelte/compiler` — so they cannot move to a
    temporary folder the way tests/test_anzeigefunde.py's driver did. Fixed
    names cost twice in the shared tree: two test runs overwrite each other's
    driver, and a killed run leaves one lying. The process id makes the names
    unique; `.gitignore` keeps them out of the history either way.
    """
    kennung = str(os.getpid())
    return {
        "stubs": f"reiter-{kennung}.stubs.mjs",
        "pruefung": f"reiter-{kennung}.pruefung.mjs",
        "leiste_mjs": f"reiter-{kennung}.leiste.mjs",
    }


def _fahren(szenario: str) -> dict:
    namen = _namensatz()
    dateien = {
        FRONTEND / namen["stubs"]: STUBS,
        FRONTEND / namen["pruefung"]: TREIBER % {
            "leiste": str(LEISTE),
            "szenario": szenario,
            "stubs": namen["stubs"],
            "leiste_mjs": namen["leiste_mjs"],
        },
    }
    for pfad, inhalt in dateien.items():
        pfad.write_text(inhalt, encoding="utf-8")
    try:
        lauf = subprocess.run(
            ["node", namen["pruefung"]],
            cwd=FRONTEND, capture_output=True, text=True, timeout=120,
        )
    finally:
        for pfad in list(dateien) + [FRONTEND / namen["leiste_mjs"]]:
            pfad.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    marke = "---BERICHT---"
    assert marke in lauf.stdout, lauf.stdout[-3000:]
    return json.loads(lauf.stdout.split(marke, 1)[1].strip())


def test_a_click_shows_the_tool_and_the_shown_tools_sign_stays_quiet():
    bericht = _fahren("""
    const schritte = []
    await m.modulWaehlen('terminal'); schritte.push(stand())
    await m.modulWaehlen('bilder'); schritte.push(stand())
    await m.modulWaehlen('bilder'); schritte.push(stand())
    return schritte
""")
    assert bericht == [
        {"offen": True, "modul": "terminal"},
        {"offen": True, "modul": "bilder"},
        # The sign of the tool showing does nothing: folding is the head's
        # button. Before, this click closed the tool.
        {"offen": True, "modul": "bilder"},
    ]


def test_folding_keeps_the_tool():
    """The head's button and ⌘J fold the column and bring it back on the
    tool it showed; a sign of the folded bar opens it on that sign's tool."""
    bericht = _fahren("""
    await m.modulWaehlen('vorschau')
    await m.schliessen()
    const zu = stand()
    m.oeffnen()
    const auf = stand()
    await m.schalten()
    const weg = stand()
    await m.schalten()
    const zurueck = stand()
    await m.schliessen()
    await m.modulWaehlen('agenten')
    return { zu, auf, weg, zurueck, zeichen: stand() }
""")
    assert bericht["zu"] == {"offen": False, "modul": "vorschau"}
    assert bericht["auf"] == {"offen": True, "modul": "vorschau"}
    assert bericht["weg"] == {"offen": False, "modul": "vorschau"}
    assert bericht["zurueck"] == {"offen": True, "modul": "vorschau"}
    assert bericht["zeichen"] == {"offen": True, "modul": "agenten"}


def test_an_offer_shows_its_tool():
    bericht = _fahren("""
    await m.modulWaehlen('terminal')
    m.anbieten('vorschau')
    return { stand: stand(), hatReiter: 'reiter' in m.leiste }
""")
    assert bericht["stand"] == {"offen": True, "modul": "vorschau"}
    # Silence probe: there are no tabs any more, one tool shows at a time.
    assert bericht["hatReiter"] is False


def test_das_cli_ist_kein_werkzeug_mehr():
    """Schweigeprobe: the CLI's button is gone, a click on it does nothing,
    and a layout remembered on it opens the terminal."""
    bericht = _fahren("""
    await m.modulWaehlen('cli')
    const klick = stand()
    m.leisteAnwenden({ leiste_offen: true, leiste_modul: 'cli', leiste_breite: 300 })
    return { klick, geladen: stand(), liste: m.MODULE }
""")
    assert bericht["klick"] == {"offen": False, "modul": "terminal"}
    assert bericht["geladen"] == {"offen": True, "modul": "terminal"}
    assert "cli" not in bericht["liste"]


def test_a_tool_folded_by_hand_does_not_push_back_in():
    """Folded by hand on a tool, the column does not open itself again when
    that tool has something new; another tool's news does open it."""
    bericht = _fahren("""
    await m.modulWaehlen('terminal')
    await m.schliessen()
    m.anbieten('terminal')
    const geschlossen = stand()
    m.anbieten('vorschau')
    return { geschlossen, offen: stand() }
""")
    assert bericht["geschlossen"] == {"offen": False, "modul": "terminal"}
    assert bericht["offen"] == {"offen": True, "modul": "vorschau"}


def test_der_doc_ordner_ist_ein_werkzeug_neben_den_bildern():
    """The doc folder stands as a tool of its own now: a layout remembered on
    the notes — its place before — opens it, and a click on it does too."""
    bericht = _fahren("""
    m.leisteAnwenden({ leiste_offen: true, leiste_modul: 'notiz', leiste_breite: 300 })
    const geladen = stand()
    await m.modulWaehlen('bilder')
    await m.modulWaehlen('docfolder')
    return { geladen, danach: stand(), liste: m.MODULE }
""")
    assert bericht["geladen"] == {"offen": True, "modul": "docfolder"}
    assert bericht["danach"] == {"offen": True, "modul": "docfolder"}
    assert "docfolder" in bericht["liste"]
    # Silence probe: the notes are gone as a tool. Put `notiz` back into
    # MODULE and every assertion above stays true while the column grows a
    # "Notizen" sign pointing at a branch that no longer exists.
    assert "notiz" not in bericht["liste"]


def test_agenten_und_zeitplaene_sind_zwei_werkzeuge():
    """The agents and the schedules are two tools, each with its own sign:
    a layout remembered on the schedules opens the schedules' tool, and a
    click on the agents' sign shows the agents."""
    bericht = _fahren("""
    m.leisteAnwenden({ leiste_offen: true, leiste_modul: 'cronjobs', leiste_breite: 300 })
    const geladen = stand()
    await m.modulWaehlen('agenten')
    return { geladen, danach: stand(), liste: m.MODULE }
""")
    assert bericht["geladen"] == {"offen": True, "modul": "cronjobs"}
    assert bericht["danach"] == {"offen": True, "modul": "agenten"}
    # Silence probe: with `cronjobs` out of MODULE again, a remembered
    # layout falls back to the terminal and the first assertion fails.
    assert "cronjobs" in bericht["liste"]


SIGNS = FRONTEND / "src/teile/ToolSigns.svelte"


def test_die_sechs_knoepfe_tragen_je_ihre_eigene_farbe():
    """Six signs stand in the column's row: browser, agents, schedules,
    terminal, pictures, doc folder. The agents and the schedules no longer
    share a sign, so no sign wears "the more urgent of two": each shows
    exactly its own ampel's colour."""
    quelle = SIGNS.read_text(encoding="utf-8")
    liste = re.search(r"export const ORDER = \[(.*?)\]", quelle, re.S).group(1)
    namen = re.findall(r"'(\w+)'", liste)
    assert namen == ["vorschau", "agenten", "cronjobs", "terminal", "bilder", "docfolder"]
    # Silence probe: the old rule that mixed the two colours is gone.
    assert "dringender" not in quelle
    assert "if (name === 'agenten' || name === 'cronjobs') return eigeneFarbe(name)" in quelle
