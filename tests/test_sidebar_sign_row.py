"""The sign row at the foot of the sidebar, open and folded.

`frontend/src/teile/Seitenleiste.svelte` draws the same six signs at the foot
of the open sidebar and of the folded bar of signs — the speech bubble (the
chat list) first. A click on the bubble shows the chat list; while the list
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
    found = re.search(r"\{#snippet fensterknoepfe\(mitChats = false\)\}(.*?)\{/snippet\}", SOURCE, re.S)
    assert found, "the snippet of the window signs is gone"
    return found.group(1)


def _rule() -> str:
    """`sidebarOpen`, `chatsAn` and `chatsZeigen`, exactly as the component has them."""
    found = re.search(
        r"(  function sidebarOpen\(\) \{.*?\n  function chatsZeigen\(\) \{.*?\n  \}\n)", SOURCE, re.S
    )
    assert found, "the chat sign's rule was not found"
    return found.group(1)


def test_the_open_and_the_folded_bar_wear_the_same_six_signs():
    snippet = _snippet()
    # Six signs with the bubble: the chats, the three windows of the list
    # FENSTER (one button in an `each`), settings and the studio.
    assert snippet.count('class="zk"') == 4
    assert "{#each FENSTER as" in snippet
    assert len(re.findall(r"\['(?:lokal|cloud|katalog)', '", SOURCE)) == 3
    assert "{#if mitChats}" in snippet
    assert snippet.index("{#if mitChats}") < snippet.index("{#each FENSTER as")
    # The bubble is the first of the row and carries the house's own hint.
    assert 'title={t(\'jobs.bereich_chats\')}' in snippet
    # Both rows ask for it: the folded bar (before it came without) ...
    bar = SOURCE.split('<nav class="zeichenleiste"', 1)[1].split("</nav>", 1)[0]
    assert "{@render fensterknoepfe(true)}" in bar
    assert "{@render fensterknoepfe()}" not in bar
    # ... and the open sidebar.
    foot = SOURCE.split('<div class="fensterzeile">', 1)[1].split("</div>", 1)[0]
    assert "{@render fensterknoepfe(true)}" in foot


def test_the_top_of_the_folded_bar_keeps_its_four_signs():
    """Silence probe: the bubble comes below; above stand the way back in,
    new chat, new project and the search — and nothing else."""
    bar = SOURCE.split('<nav class="zeichenleiste"', 1)[1].split("</nav>", 1)[0]
    top = bar.split('<span class="frei"></span>', 1)[0]
    assert top.count("<button") == 4
    for handler in ("seitenleisteSchalten()", "neuerChatAusDerListe", "newProject", "sucheZeigen"):
        assert handler in top


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
