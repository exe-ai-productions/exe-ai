"""Below 760 px the sidebar is a drawer, not a collapsible rail
(`frontend/src/lib/zustand.svelte.js`, `frontend/src/teile/Seitenleiste.svelte`).

`seitenleisteSchalten` is lifted out and run in node, the same way
tests/test_laufmarke.py runs `laufMarke`: the width branch was otherwise
pinned by nothing but the CSS media query, and the JS side never told the
two states apart.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "frontend/src/lib/zustand.svelte.js"
FRONTEND = WURZEL / "frontend/src"


def _abfrage() -> str:
    quelle = QUELLE.read_text()
    treffer = re.search(
        r"\n(?:export )?(const SEITENLEISTE_SCHMAL_ABFRAGE = '[^\n]+')\n", quelle
    )
    assert treffer, "SEITENLEISTE_SCHMAL_ABFRAGE not found"
    # Without `export`: the snippet runs as a plain `node -e` script.
    return treffer.group(1) + "\n"


def _istSchmal() -> str:
    quelle = QUELLE.read_text()
    treffer = re.search(
        r"\nexport function istSeitenleisteSchmal\(\) \{\n.*?\n\}\n", quelle, re.S
    )
    assert treffer, "istSeitenleisteSchmal not found"
    return treffer.group(0).strip() + "\n"


def _seitenleisteSchalten() -> str:
    quelle = QUELLE.read_text()
    treffer = re.search(
        r"\nexport function seitenleisteSchalten\(.*?\) \{\n.*?\n\}\n", quelle, re.S
    )
    assert treffer, "seitenleisteSchalten not found"
    return treffer.group(0).strip() + "\n"


def _resizeWaechter() -> str:
    # The handler is a named top-level function now, not an
    # inline arrow inside the `if` block — both belong in the snippet, in
    # the order the source itself has them.
    quelle = QUELLE.read_text()
    treffer = re.search(
        r"\nfunction seitenleisteSchmalGeaendert\(.*?\n\}\n"
        r"if \(typeof window !== 'undefined'\) \{\n.*?\n\}\n",
        quelle,
        re.S,
    )
    assert treffer, "the size guard was not found"
    return treffer.group(0).strip() + "\n"


def _resize_lauf(schmal: bool, seitenleisteOffen: bool, menueOffen: bool = False) -> bool:
    skript = f"""
let waechter = null;
const window = {{
  matchMedia: (abfrage) => ({{
    matches: {json.dumps(schmal)},
    addEventListener: (art, f) => {{ waechter = f; }},
  }}),
}};
const zustand = {{ seitenleisteOffen: {json.dumps(seitenleisteOffen)} }};
const eineSeiteOffen = () => {json.dumps(menueOffen)};
{_abfrage()}
{_resizeWaechter()}
waechter({{ matches: {json.dumps(schmal)} }});
console.log(JSON.stringify(zustand.seitenleisteOffen));
"""
    lauf = subprocess.run(["node", "-e", skript], capture_output=True, text=True)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout)


def _lauf(schmal: bool, ausgangszustand: dict, aufruf: str = "seitenleisteSchalten();") -> dict:
    skript = f"""
const window = {{
  matchMedia: (abfrage) => ({{ matches: {json.dumps(schmal)} }}),
}};
const zustand = {json.dumps(ausgangszustand)};
const gespeichert = [];
const layoutSpeichern = (werte) => gespeichert.push(werte);
// what a menu had put aside about the sidebar — a gesture on the rail
// itself clears it again (revealSidebar).
let sidebarBeforeMenu = null;
{_abfrage()}
{_istSchmal()}
{_seitenleisteSchalten()}
{aufruf}
console.log(JSON.stringify({{ zustand, gespeichert }}));
"""
    lauf = subprocess.run(["node", "-e", skript], capture_output=True, text=True)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_unter_760px_oeffnet_der_schalter_die_schublade():
    bericht = _lauf(
        True, {"seitenleisteOffen": False, "seitenleisteEingeklappt": True}
    )
    assert bericht["zustand"]["seitenleisteOffen"] is True
    assert bericht["zustand"]["seitenleisteEingeklappt"] is True, (
        "the narrow-window branch must not touch the rail state"
    )
    assert bericht["gespeichert"] == [], "the drawer remembers nothing"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_unter_760px_schliesst_der_schalter_die_offene_schublade():
    bericht = _lauf(
        True, {"seitenleisteOffen": True, "seitenleisteEingeklappt": True}
    )
    assert bericht["zustand"]["seitenleisteOffen"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ab_760px_bleibt_das_einklappen_wie_bisher():
    bericht = _lauf(
        False, {"seitenleisteOffen": False, "seitenleisteEingeklappt": False}
    )
    assert bericht["zustand"]["seitenleisteEingeklappt"] is True
    assert bericht["zustand"]["seitenleisteOffen"] is False
    assert bericht["gespeichert"] == [{"seitenleiste_zu": True}]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_verbreitertes_fenster_schliesst_die_stehende_schublade():
    assert _resize_lauf(schmal=False, seitenleisteOffen=True) is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_eine_offene_schublade_bleibt_offen_solange_das_fenster_schmal_bleibt():
    assert _resize_lauf(schmal=True, seitenleisteOffen=True) is True


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_eine_geschlossene_schublade_bleibt_von_der_groesse_unberuehrt():
    assert _resize_lauf(schmal=False, seitenleisteOffen=False) is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_narrowing_with_an_open_menu_leaves_the_drawer_closed():
    # The drawer lies over the main area on a narrow window; a menu's
    # content must stay in sight there, so crossing the breakpoint does not
    # open the drawer over it.
    assert _resize_lauf(schmal=True, seitenleisteOffen=False, menueOffen=True) is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_narrowing_without_an_open_menu_leaves_the_drawer_closed():
    # Silence check: no menu, nothing opens a drawer unasked.
    assert _resize_lauf(schmal=True, seitenleisteOffen=False, menueOffen=False) is False


# --- revealSidebar · a menu opening keeps its content in sight ------------


def _revealSidebar() -> str:
    quelle = QUELLE.read_text()
    treffer = re.search(
        r"\nexport function revealSidebar\(\) \{\n.*?\n\}\n", quelle, re.S
    )
    assert treffer, "revealSidebar not found"
    return treffer.group(0).strip() + "\n"


def _reveal_lauf(schmal: bool, ausgangszustand: dict) -> dict:
    skript = f"""
const window = {{
  matchMedia: (abfrage) => ({{ matches: {json.dumps(schmal)} }}),
}};
const zustand = {json.dumps(ausgangszustand)};
let sidebarBeforeMenu = null;
{_abfrage()}
{_istSchmal()}
{_revealSidebar()}
revealSidebar();
console.log(JSON.stringify({{ zustand, sidebarBeforeMenu }}));
"""
    lauf = subprocess.run(["node", "-e", skript], capture_output=True, text=True)
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return json.loads(lauf.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_menu_on_a_narrow_window_does_not_open_the_drawer_over_its_content():
    bericht = _reveal_lauf(
        True, {"seitenleisteOffen": False, "seitenleisteEingeklappt": True}
    )
    assert bericht["zustand"]["seitenleisteOffen"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_menu_opened_from_the_drawer_closes_it_and_remembers_it_was_open():
    bericht = _reveal_lauf(
        True, {"seitenleisteOffen": True, "seitenleisteEingeklappt": False}
    )
    assert bericht["zustand"]["seitenleisteOffen"] is False
    assert bericht["sidebarBeforeMenu"] == {
        "seitenleisteEingeklappt": False, "seitenleisteOffen": True,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_a_menu_on_a_wide_window_still_unfolds_the_sidebar():
    # Silence check: the wide window keeps its column beside the content.
    bericht = _reveal_lauf(
        False, {"seitenleisteOffen": False, "seitenleisteEingeklappt": True}
    )
    assert bericht["zustand"]["seitenleisteEingeklappt"] is False
    assert bericht["zustand"]["seitenleisteOffen"] is False


# --- seitenleisteSchalten(schmal) · the release judges by the gesture's own
# start, not by the width at the moment it lets go -------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_erzwungen_breiter_start_klappt_ein_trotz_inzwischen_schmalem_fenster():
    # fassen() captured schmal=False in the wide window; the window has since
    # gone narrow (window.matchMedia now reports true) — the gesture must
    # still take the wide branch, not the one a fresh call with no argument
    # would take today (that mismatch is the very bug this guards).
    bericht = _lauf(
        schmal=True,
        ausgangszustand={"seitenleisteOffen": False, "seitenleisteEingeklappt": False},
        aufruf="seitenleisteSchalten(false);",
    )
    assert bericht["zustand"]["seitenleisteEingeklappt"] is True
    assert bericht["zustand"]["seitenleisteOffen"] is False
    assert bericht["gespeichert"] == [{"seitenleiste_zu": True}]


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ein_erzwungen_schmaler_start_oeffnet_die_schublade_trotz_inzwischen_breitem_fenster():
    bericht = _lauf(
        schmal=False,
        ausgangszustand={"seitenleisteOffen": False, "seitenleisteEingeklappt": True},
        aufruf="seitenleisteSchalten(true);",
    )
    assert bericht["zustand"]["seitenleisteOffen"] is True
    assert bericht["zustand"]["seitenleisteEingeklappt"] is True
    assert bericht["gespeichert"] == [], "the drawer remembers nothing"


@pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")
def test_ohne_uebergabe_zaehlt_weiterhin_das_aktuelle_fenster():
    # Silence test: ⌘B and a plain click pass nothing in — both keep the old
    # behaviour, the window's width at the moment of the call.
    bericht = _lauf(
        schmal=True, ausgangszustand={"seitenleisteOffen": False, "seitenleisteEingeklappt": True}
    )
    assert bericht["zustand"]["seitenleisteOffen"] is True


# --- The matchMedia watcher is named and unregisters itself on HMR
# — not testable as behaviour, so checked in the source --------------------


def test_der_matchmedia_waechter_hat_einen_namen_und_meldet_sich_beim_neuladen_ab():
    quelle = QUELLE.read_text()
    assert "function seitenleisteSchmalGeaendert(" in quelle, (
        "the guard must be a named function, not an inline arrow"
    )
    treffer = re.search(
        r"addEventListener\?\.\(\s*'change',\s*seitenleisteSchmalGeaendert\s*\)", quelle
    )
    assert treffer, "the guard is not registered under its name"
    treffer = re.search(
        r"import\.meta\.hot\.dispose\(\(\) => \{\s*"
        r"seitenleisteSchmalAbfrage\?\.removeEventListener\?\.\(\s*"
        r"'change',\s*seitenleisteSchmalGeaendert\s*\)",
        quelle,
    )
    assert treffer, "no unregistering on HMR reload through import.meta.hot.dispose"


# --- One width for the narrow window: every rule that draws it --------------
#
# The icon bar, the drawer, the hidden seams, the tool sheet, the menu page
# beside the bar and the foot strip beside it are one state of the window.
# Each is drawn by its own rule; a rule left at another width would stand the
# window half in one layout and half in the other.

NARROW = "(width < 760px)"

# (file, the first selector inside the rule)
NARROW_WINDOW_RULES = [
    ("teile/Seitenleiste.svelte", ".zeichenleiste"),
    # The seams' handle, on both sides.
    ("teile/Seitengriff.svelte", ".zone"),
    ("teile/Arbeitsleiste.svelte", ".leiste"),
    ("teile/Seitenrahmen.svelte", ".seite"),
    ("App.svelte", ".fussstreifen"),
]

# Layouts of their own that have nothing to do with the sidebar: they keep
# their own width.
OWN_LAYOUT_RULES = [
    ("App.svelte", ".spur"),
    ("teile/Eingabeleiste.svelte", ".menueplatz"),
    ("teile/Menueseite.svelte", ".kopf"),
    ("teile/Fenster.svelte", ".popup.liste"),
    ("teile/ModelleLokal.svelte", ".aktionen"),
    ("teile/Werkzeuge.svelte", ".zwei"),
    ("teile/Modellserver.svelte", ".reisekarten"),
]


def _media_query(path: str, selector: str) -> str:
    """The media query of the rule whose first selector is `selector`."""
    source = (FRONTEND / path).read_text()
    found = re.findall(
        r"@media (\([^{]*\)) \{\s*(?:/\*.*?\*/\s*)*" + re.escape(selector) + r"[\s,{]",
        source,
        re.S,
    )
    assert len(found) == 1, f"{path}: {len(found)} rules start with {selector}"
    return found[0]


@pytest.mark.parametrize("path,selector", NARROW_WINDOW_RULES)
def test_every_narrow_window_rule_applies_below_760px(path, selector):
    assert _media_query(path, selector) == NARROW


def test_the_script_queries_apply_below_760px():
    assert _abfrage() == f"const SEITENLEISTE_SCHMAL_ABFRAGE = '{NARROW}'\n"
    # The tool surface reads the same state (a sheet over the chat) through
    # the same constant, not a spelling of its own.
    surface = (FRONTEND / "lib/flaeche.svelte.js").read_text()
    assert "import { SEITENLEISTE_SCHMAL_ABFRAGE } from './zustand.svelte.js'" in surface
    assert re.search(r"const BLATT = .*?matchMedia\(SEITENLEISTE_SCHMAL_ABFRAGE\)", surface)


@pytest.mark.parametrize("path,selector", OWN_LAYOUT_RULES)
def test_own_layouts_keep_their_720px(path, selector):
    # Silence check: only the narrow window moved, not every narrow rule.
    assert _media_query(path, selector) == "(max-width: 720px)"
