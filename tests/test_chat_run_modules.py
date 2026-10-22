"""The run of the chat and the bar's draft live in modules of their own
(`frontend/src/lib/chatlauf.svelte.js`, `frontend/src/lib/eingabe.svelte.js`),
shared by the desktop window and the phone page. What a page owes them is its
view: handed over with `ansicht()`, taken away again when the page goes.

The hand-over is run in node (the real method, lifted out of each module);
the wiring in the two components is guarded by their text.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "frontend/src/lib"
RUN = (LIB / "chatlauf.svelte.js").read_text(encoding="utf-8")
STORE = (LIB / "eingabe.svelte.js").read_text(encoding="utf-8")
WINDOW = (ROOT / "frontend/src/App.svelte").read_text(encoding="utf-8")
BAR = (ROOT / "frontend/src/teile/Eingabeleiste.svelte").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no Node on this machine")


def _method(source: str) -> str:
    found = re.search(r"\n    ansicht\(hand\) \{.*?\n    \},\n", source, re.S)
    assert found, "ansicht() not found"
    return found.group(0).strip().removesuffix(",").replace("ansicht(hand)", "function ansicht(hand)", 1)


def _run(declarations: str, source: str, steps: str) -> dict:
    script = f"""
{declarations}
{_method(source)}
{steps}
"""
    run = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True)
    assert run.returncode == 0, f"{run.stderr}\n{run.stdout}"
    return json.loads(run.stdout.strip().splitlines()[-1])


RUN_DECLARATIONS = "let view = null, runter = () => 'none', eingabe = null"
STORE_DECLARATIONS = (
    "let view = null, feld = null, fokus = () => 'none', questionHidden = () => false,"
    " mitlesenBeenden = () => {}, zwischenWeg = () => {}, ansichtBereich = () => null"
)


@needs_node
def test_the_run_takes_a_view_and_gives_it_back_when_the_page_goes():
    got = _run(
        RUN_DECLARATIONS,
        RUN,
        """
const a = { runter: () => 'a', eingabe: { name: 'a' } }
const away = ansicht(a)
const during = [runter(), eingabe?.name]
away()
console.log(JSON.stringify({ during, after: [runter(), eingabe] }))
""",
    )
    assert got == {"during": ["a", "a"], "after": [None, None]}


@needs_node
def test_a_newer_view_is_not_taken_away_by_the_older_one():
    """Silence probe: the page that was swapped in stays served when the
    page it replaced lets go afterwards."""
    got = _run(
        RUN_DECLARATIONS,
        RUN,
        """
const awayA = ansicht({ runter: () => 'a' })
const awayB = ansicht({ runter: () => 'b' })
awayA()
const afterOld = runter()
awayB()
console.log(JSON.stringify({ afterOld, afterNew: runter() ?? null }))
""",
    )
    assert got == {"afterOld": "b", "afterNew": None}


@needs_node
def test_the_draft_store_takes_a_view_and_gives_it_back_when_the_page_goes():
    got = _run(
        STORE_DECLARATIONS,
        STORE,
        """
const field = { name: 'field' }
const a = { feld: field, fokus: () => 'focused', questionHidden: () => true, bereich: () => 'range' }
const away = ansicht(a)
const during = [feld?.name, fokus(), questionHidden(), ansichtBereich()]
away()
console.log(JSON.stringify({ during, after: [feld, fokus(), questionHidden(), ansichtBereich()] }))
""",
    )
    assert got == {"during": ["field", "focused", True, "range"], "after": [None, None, False, None]}


@needs_node
def test_the_draft_store_keeps_the_newer_view_too():
    got = _run(
        STORE_DECLARATIONS,
        STORE,
        """
const awayA = ansicht({ feld: { name: 'a' } })
ansicht({ feld: { name: 'b' } })
awayA()
console.log(JSON.stringify({ feld: feld?.name }))
""",
    )
    assert got == {"feld": "b"}


def test_the_window_hands_its_view_over_before_its_other_effects_run():
    """`$effect.pre`: the effect that reattaches to a running answer is
    declared before the place of the view in the script, and it must find the
    scroll function and the bar already there."""
    assert "$effect.pre(() => chatRun.ansicht({ runter, eingabe }))" in WINDOW
    assert "chatRun.ansicht(" not in WINDOW.replace("$effect.pre(() => chatRun.ansicht(", "")


def test_the_bar_hands_its_view_over_and_follows_the_chat_through_the_store():
    assert re.search(
        r"\$effect\(\(\) =>\s+chatEingabe\.ansicht\(\{\s+feld,\s+fokus,\s+questionHidden,\s+mitlesenBeenden,\s+zwischenWeg,\s+bereich: \(\) => diktatBereich,",
        BAR,
    ), "the bar no longer hands its field, focus and mirror hooks to the store"
    assert "$effect(() => chatEingabe.neuladeParken())" in BAR
    assert "$effect(() => chatEingabe.chatWechseln(zustand.aktiverChat))" in BAR
    assert "$effect(() => chatEingabe.denkenLaden())" in BAR
    assert "bind:value={chatEingabe.text}" in BAR


def test_the_window_calls_the_bar_through_thin_wrappers_of_the_store():
    for name in ("keep", "zurueckgeben", "takeBack", "transcribing", "cancelTranscription"):
        assert re.search(rf"export function {name}\(.*?\) \{{\n\s+(?:return )?chatEingabe\.{name}\(", BAR), name


def test_both_modules_are_singletons_the_pages_share():
    assert "export const chatRun = createChatRun()" in RUN
    assert "export const chatEingabe = createEingabe()" in STORE
    assert "from './lib/chatlauf.svelte.js'" in WINDOW
    assert "from '../lib/eingabe.svelte.js'" in BAR


def test_the_window_gets_what_its_list_shows_of_the_run_from_the_shared_module():
    """The waiting mark, the clocks and the picture tiles are set up in
    `lib/chatansicht.svelte.js`, called while the page is made; the window
    keeps none of their rules."""
    view = (LIB / "chatansicht.svelte.js").read_text(encoding="utf-8")
    assert "export function useChatAnsicht()" in view
    assert "const ansicht = useChatAnsicht()" in WINDOW
    for rule in ("const laufMarke = $derived.by(", "function bildKacheln(", "function teilausfall("):
        assert rule in view and rule not in WINDOW, rule


def test_the_bar_gets_its_question_card_from_the_shared_module():
    """What waits on the person — which question stands in the card, what
    "later" pushed aside, the ways to answer — is kept in
    `lib/fragekarte.svelte.js`, called while the page is made; the bar gives
    it the way back to its field."""
    card = (LIB / "fragekarte.svelte.js").read_text(encoding="utf-8")
    assert "export function useFragekarte(" in card
    assert "const fragen = useFragekarte({ fokus: () => feld?.focus() })" in BAR
    for rule in ("function answerTool(", "function later(", "standingWith("):
        assert rule in card and rule not in BAR, rule
