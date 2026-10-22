"""The work bar on the phone: which tabs it has, which one a name stands for,
the colour of the terminal tab and the dot on a tool's row of the chat list.

The decisions live in an import-free module (`work.js`), so they run here
exactly as they ship. The rest checks the shape of the files: the bar
carries no terminal client, it does not write the desktop's saved layout,
and the rows of the chat list are wired to the bar and to the dot.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
PHONE = FRONTEND / "src" / "phone"
LOCALES = ROOT / "app" / "locales"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _run(body: str) -> dict:
    driver = FRONTEND / f"phone_work.{os.getpid()}.check.mjs"
    driver.write_text(
        "import * as work from './src/phone/work.js'\n" + textwrap.dedent(body),
        encoding="utf-8",
    )
    try:
        done = subprocess.run(
            ["node", driver.name], cwd=FRONTEND, capture_output=True, text=True, timeout=60
        )
    finally:
        driver.unlink(missing_ok=True)
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


# ——— the tabs ———


@needs_node
def test_the_bar_has_six_tabs_and_no_terminal_client():
    out = _run("console.log(JSON.stringify(work.TABS.map((tab) => tab.name)))")
    assert out == ["terminal", "vorschau", "bilder", "docfolder", "agenten", "cronjobs"]
    assert "cli" not in out


@needs_node
def test_a_name_that_is_a_tab_stays_and_any_other_falls_to_the_first():
    out = _run(
        """
        console.log(JSON.stringify([
          work.pickTab('cronjobs'), work.pickTab('cli'), work.pickTab(undefined), work.pickTab(''),
        ]))
        """
    )
    assert out == ["cronjobs", "terminal", "terminal", "terminal"]


# ——— the colour of the terminal tab ———


@needs_node
def test_a_running_command_is_blue_even_when_the_last_call_was_refused():
    out = _run(
        """
        console.log(JSON.stringify([
          work.terminalColour({ running: true, lastRefused: true }),
          work.terminalColour({ running: true }),
        ]))
        """
    )
    assert out == ["blau", "blau"]


@needs_node
def test_a_refused_call_or_a_failed_run_is_red_until_the_next_call():
    out = _run(
        """
        console.log(JSON.stringify([
          work.terminalColour({ lastRefused: true }),
          work.terminalColour({ lastRun: 'rot' }),
        ]))
        """
    )
    assert out == ["rot", "rot"]


@needs_node
def test_a_quiet_terminal_wears_no_colour():
    """The silent case: nothing running, nothing refused, and a run that ended
    well or was stopped by hand are no news on a phone."""
    out = _run(
        """
        console.log(JSON.stringify([
          work.terminalColour(), work.terminalColour({}),
          work.terminalColour({ lastRun: 'gruen' }), work.terminalColour({ lastRun: 'still' }),
        ]))
        """
    )
    assert out == [None, None, None, None]


# ——— the colours ———


@needs_node
def test_the_colours_of_the_house_pass_and_the_grey_of_a_quiet_ampel_does_not():
    out = _run(
        """
        console.log(JSON.stringify(
          ['rot', 'gelb', 'blau', 'gruen', 'still', 'leer', undefined].map(work.tabColour)))
        """
    )
    assert out == ["rot", "gelb", "blau", "gruen", None, None, None]


# ——— the files ———


def _read(name: str) -> str:
    return (PHONE / name).read_text(encoding="utf-8")


def test_the_bar_keeps_its_own_tab_and_never_writes_the_desktop_layout():
    for name in ("WorkBar.svelte", "workbar.svelte.js", "workState.svelte.js"):
        assert "arbeitsleiste.svelte.js" not in _read(name), name
    assert "$state" in _read("workbar.svelte.js")


def test_the_bar_shows_each_tool_of_the_tab_row_and_not_the_terminal_client():
    bar = _read("WorkBar.svelte")
    for module in ("ModulTerminal", "ModulVorschau", "ModulBilder", "DocFolder", "ModulAgenten", "ModulCronjobs"):
        assert f"<{module}" in bar, module
    assert "ModulCli" not in bar


def test_the_chat_list_opens_the_bar_at_a_tool_and_wears_the_dot():
    drawer = _read("Drawer.svelte")
    assert "workOpen(name)" in drawer
    assert "workBusyByTab()" in drawer
    assert "{#each TABS as tab (tab.name)}" in drawer
    phone = _read("Phone.svelte")
    assert "<WorkBar />" in phone
    # the head has neither the button nor the dot any more
    head = _read("Header.svelte")
    assert "workOpen" not in head and "workBusy" not in head


def test_the_phone_follows_the_open_chat_with_the_terminal_runs():
    """Without this the terminal tab and the dot on the button never see a run:
    the runs belong to the chat the stream is connected to."""
    phone = _read("Phone.svelte")
    assert "followTerminal(zustand.aktiverChat)" in phone
    assert "verbinden as followTerminal" in phone


def test_picking_a_chat_or_a_page_closes_the_bar():
    phone = _read("Phone.svelte")
    effect = phone[phone.index("Picking another chat"):]
    effect = effect[: effect.index("})") + 2]
    assert "zustand.aktiverChat" in effect and "void page" in effect and "untrack(workClose)" in effect


def test_the_dot_asks_only_the_facts_that_can_make_it_blue():
    """The chat list reads the dots while the chat streams: the list of tool
    calls stays out of it (it can only make a tab red)."""
    state = _read("workState.svelte.js")
    busy = state[state.index("export const workBusyByTab"):]
    assert "historie" not in busy and "toolStates" not in busy


def test_looking_at_the_terminal_marks_its_runs_as_seen():
    assert "terminalGesehen()" in _read("WorkBar.svelte")


def test_the_bar_reads_the_same_ampels_as_the_desktops_row_of_signs():
    state = _read("workState.svelte.js")
    for name in ("terminal.laeufe", "agentenampel", "cronjobampel", "laufampel"):
        assert name in state, name


def test_every_text_the_bar_uses_exists_in_both_catalogs():
    used = set(re.findall(r"t\('([a-z_]+\.[a-z_]+)'\)", _read("WorkBar.svelte") + _read("Drawer.svelte")))
    used |= {"terminal.titel", "vorschau.titel", "bilder.titel", "docfolder.title", "agenten.titel", "cronjobs.titel"}
    for lang in ("en", "de"):
        catalog = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        for key in used:
            group, name = key.split(".")
            assert name in catalog.get(group, {}), (lang, key)
