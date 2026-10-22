"""The sign row at the foot of the sidebar, open and folded.

`frontend/src/teile/Seitenleiste.svelte` draws the same five signs at the foot
of the open sidebar and of the folded bar of signs — the speech bubble (the
chat list) first, the settings last. A click on the bubble shows the chat list; while the list
already stands there it folds the sidebar like the sidebar's own button, and
on the folded bar it unfolds the sidebar with the list.

The component itself is a view; the click's rule is lifted out of the source
and run in node with the window's state stubbed, the way
tests/test_seitenleiste_schmales_fenster.py runs `seitenleisteSchalten`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "frontend/src/teile/Seitenleiste.svelte").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _snippet() -> str:
    found = re.search(r"\{#snippet fusszeichen\(\)\}(.*?)\{/snippet\}", SOURCE, re.S)
    assert found, "the snippet of the signs of the foot is gone"
    return found.group(1)


def _rule() -> str:
    """`sidebarOpen`, `chatsAn` and `chatsZeigen`, exactly as the component has them."""
    found = re.search(
        r"(  function sidebarOpen\(\) \{.*?\n  function chatsZeigen\(\) \{.*?\n  \}\n)", SOURCE, re.S
    )
    assert found, "the chat sign's rule was not found"
    return found.group(1)


def test_the_open_and_the_folded_bar_wear_the_same_five_signs():
    snippet = _snippet()
    # Five signs, in this order: the chats, a new chat, a new project, the
    # pictures, the settings. The three menus of the models are rows of the
    # settings list now, no signs here.
    assert snippet.count("<button") == 5
    handlers = ["chatsZeigen", "neuerChatAusDerListe", "newProject", "studioSchalten", "einstellungenOeffnen"]
    positions = [snippet.index("onclick={" + handler) for handler in handlers]
    assert positions == sorted(positions)
    assert "FENSTER" not in SOURCE
    assert "menueFensterOeffnen('lokal')" not in SOURCE
    # The bubble is first and carries the house's own hint; the settings are
    # last and wear the gear.
    assert 'title={t(\'jobs.bereich_chats\')}' in snippet
    assert 'zeichen="gear"' in snippet.rsplit("<button", 1)[1]
    # Both rows ask for it: the folded bar ...
    bar = SOURCE.split('<nav class="zeichenleiste"', 1)[1].split("</nav>", 1)[0]
    assert "{@render fusszeichen()}" in bar
    # ... and the open sidebar.
    foot = SOURCE.split('<div class="fensterzeile">', 1)[1].split("</div>", 1)[0]
    assert "{@render fusszeichen()}" in foot


def test_the_gear_stands_lit_for_every_menu_of_the_settings():
    """The settings, the local models, the cloud providers and the catalogue
    are one place; the gear stands for all four."""
    found = re.search(r"const einstellungenOffen = \(\) =>\s*\[(.*?)\]\.some", SOURCE, re.S)
    assert found
    assert re.findall(r"'(\w+)'", found.group(1)) == ["prompt", "lokal", "cloud", "katalog"]
    assert "class:aktiv={einstellungenOffen()}" in _snippet()


def test_the_top_of_the_folded_bar_keeps_its_two_signs():
    """Silence probe: the five signs come below; above stand the way back in
    and the search — and nothing else."""
    bar = SOURCE.split('<nav class="zeichenleiste"', 1)[1].split("</nav>", 1)[0]
    top = bar.split('<span class="frei"></span>', 1)[0]
    assert top.count("<button") == 2
    for handler in ("seitenleisteSchalten()", "sucheZeigen"):
        assert handler in top


def test_the_chat_list_has_no_buttons_for_a_new_chat_or_project_over_it():
    """They stand at the foot only; the search carries the key of the chat search."""
    head = SOURCE.split('<div class="suchfeld">', 1)[1].split("{/if}", 1)[0]
    assert "neuerChatAusDerListe" not in head and "newProject" not in head
    assert "<kbd" in head and "sucheTaste" in head


HOUSE_SIGNS = (ROOT / "frontend/src/teile/Hauszeichen.svelte").read_text(encoding="utf-8")
# The cog: its path and its circle, on the 24 grid.
COG_PATH = (
    "M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 "
    "2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 "
    "2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051"
    "a2.34 2.34 0 0 0 3.319-1.915"
)


def _branch(name: str) -> str:
    """The drawing of one sign in the house signs, from its branch to the next one."""
    found = re.search(r"\{:else if zeichen === '" + name + r"'[^}]*\}(.*?)\{:else if zeichen ===", HOUSE_SIGNS, re.S)
    assert found, f"the branch of {name} is gone"
    return found.group(1)


def test_the_settings_sign_is_the_cog():
    """The sun of the old catalogue drawing is gone: the gear is a cog on the
    24 grid, drawn with the house's plain stroke, and no 64 grid is asked
    for any more."""
    gear = _branch("gear")
    assert f'<path d="{COG_PATH}" />' in gear
    assert '<circle cx="12" cy="12" r="3" />' in gear
    assert "M32 11 V17" not in gear and "r=\"9\"" not in gear
    assert "gear:" not in HOUSE_SIGNS.split("const SICHTFELDER", 1)[1].split("\n", 1)[0]
    assert "gear.svg" not in HOUSE_SIGNS
    # The button is the same as before: the gear at 24 px, last in the row.
    last = _snippet().rsplit("<button", 1)[1]
    assert 'zeichen="gear"' in last and "groesse={24}" in last


def test_the_notices_name_the_cog():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    lucide = notices.split("## Lucide", 1)[1].split("```", 1)[0]
    assert "`gear` (`settings`)" in lucide


def test_the_new_project_sign_is_the_folder_with_a_plus():
    """One folder in the house: `folder_plus` takes the branch of `ordner`
    and adds the plus; every other place keeps the plain folder."""
    button = re.search(r"<button[^>]*onclick=\{newProject\}.*?</button>", _snippet(), re.S)
    assert button
    assert 'zeichen="folder_plus"' in button.group(0) and "groesse={26}" in button.group(0)
    assert 'zeichen="ordner"' not in button.group(0)
    shared = re.search(
        r"\{:else if zeichen === 'ordner' \|\| zeichen === 'folder_plus'\}(.*?)\{:else if zeichen ===", HOUSE_SIGNS, re.S
    )
    assert shared, "the folder and the folder with a plus share one branch"
    drawing = shared.group(1)
    assert 'd="M3.75 18 V6 H9.75 L11.63 8.25 H18 V11.25"' in drawing
    assert 'd="M3.75 18 H16.5 L20.25 11.25 H7.5 Z"' in drawing
    plus = drawing.split("{#if zeichen === 'folder_plus'}", 1)[1]
    assert '<path d="M21 2.5v4M19 4.5h4" stroke-width="1.8" />' in plus
    # The folder itself is drawn once in the house (the colour test counts on it).
    assert HOUSE_SIGNS.count("M3.75 18 V6 H9.75") == 1


def test_the_other_signs_of_the_row_are_the_ones_they_were():
    snippet = _snippet()
    assert 'name="chats"' in snippet and 'zeichen="plus"' in snippet and 'name="studio"' in snippet
    # Five signs in all: two window signs and three house signs (the plus, the folder, the gear).
    assert snippet.count("<Hauszeichen") == 3 and snippet.count("<Fensterzeichen") == 2


def _run(state: dict, call: str = "chatsZeigen();") -> dict:
    script = f"""
const state = {json.dumps(state)};
const zustand = state.zustand;
const studio = state.studio;
const calls = [];
const istSeitenleisteSchmal = () => state.schmal;
const eineSeiteOffen = () => state.seiteOffen;
// What a menu page and the studio put away is back when they close.
const seitenSchliessen = () => {{ calls.push('seitenSchliessen'); state.seiteOffen = false; }};
const studioSchliessen = () => {{ calls.push('studioSchliessen'); studio.offen = false; }};
const blattWechseln = (blatt) => {{ calls.push('blatt:' + blatt); zustand.seitenblatt = blatt; }};
const seitenleisteSchalten = () => {{
  calls.push('schalten');
  if (state.schmal) zustand.seitenleisteOffen = !zustand.seitenleisteOffen;
  else zustand.seitenleisteEingeklappt = !zustand.seitenleisteEingeklappt;
}};
{_rule()}
const vorher = chatsAn();
{call}
console.log(JSON.stringify({{ vorher, nachher: chatsAn(), calls, zustand, studio, seiteOffen: state.seiteOffen }}));
"""
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr + run.stdout
    return json.loads(run.stdout)


def _stand(**over) -> dict:
    base = {
        "schmal": False,
        "seiteOffen": False,
        "zustand": {"seitenleisteEingeklappt": False, "seitenleisteOffen": False, "seitenblatt": "chats"},
        "studio": {"offen": False},
    }
    for key, value in over.items():
        if isinstance(value, dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


@needs_node
def test_a_second_click_on_the_bubble_folds_the_open_sidebar():
    report = _run(_stand())
    assert report["vorher"] is True
    assert report["calls"] == ["schalten"]
    assert report["zustand"]["seitenleisteEingeklappt"] is True
    assert report["nachher"] is False


@needs_node
def test_the_bubble_on_the_folded_bar_unfolds_the_sidebar_with_the_chat_list():
    report = _run(_stand(zustand={"seitenleisteEingeklappt": True, "seitenblatt": "agenten"}))
    # The list is not what shows while the bar is folded: the sign is not lit.
    assert report["vorher"] is False
    assert report["calls"][-1] == "schalten"
    assert "blatt:chats" in report["calls"]
    assert report["zustand"]["seitenleisteEingeklappt"] is False
    assert report["zustand"]["seitenblatt"] == "chats"
    assert report["nachher"] is True


@needs_node
def test_the_bubble_shows_the_chat_list_over_a_menu_page_and_over_the_studio():
    """Silence probe: with a menu page or the studio standing, the bubble is
    the way back to the list, as before — it does not fold the sidebar."""
    over_menu = _run(_stand(seiteOffen=True))
    assert over_menu["vorher"] is False
    assert over_menu["calls"] == ["seitenSchliessen", "studioSchliessen", "blatt:chats"]
    assert over_menu["zustand"]["seitenleisteEingeklappt"] is False
    assert over_menu["nachher"] is True
    over_studio = _run(_stand(studio={"offen": True}))
    assert over_studio["vorher"] is False
    assert "schalten" not in over_studio["calls"]
    assert over_studio["studio"]["offen"] is False
    assert over_studio["nachher"] is True


@needs_node
def test_the_bubble_on_a_drawer_window_opens_and_closes_the_drawer():
    closed = _run(_stand(schmal=True))
    assert closed["vorher"] is False
    assert closed["zustand"]["seitenleisteOffen"] is True
    assert closed["zustand"]["seitenleisteEingeklappt"] is False, "the desktop state stays"
    opened = _run(_stand(schmal=True, zustand={"seitenleisteOffen": True}))
    assert opened["vorher"] is True
    assert opened["zustand"]["seitenleisteOffen"] is False
