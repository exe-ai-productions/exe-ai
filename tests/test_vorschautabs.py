"""The tabs of the preview rail, run rather than read.

``lib/vorschautabs.svelte.js`` keeps which files a chat produced. A tab can
be filed before anyone knows where the file lies on disk (the streaming
answer carries the file's text, not its place); a card in the transcript that
shows the same file later does know the place. The module is compiled with
the Svelte compiler (it uses runes), its imports are bent to stand-ins, and
the calls go in the way the answer and the cards make them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
TABS = FRONTEND / "src/lib/vorschautabs.svelte.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

STUBS = """
export const anbieten = () => {}
export const zustand = { aktiverChat: 'c1' }
"""

DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
let code = compileModule(readFileSync(%(tabs)r, 'utf-8'), { filename: 'vorschautabs.svelte.js', generate: 'client' }).js.code
code = code
  .replace(/from '\\.\\/arbeitsleiste\\.svelte\\.js'/g, "from './%(stubs)s'")
  .replace(/from '\\.\\/zustand\\.svelte\\.js'/g, "from './%(stubs)s'")
writeFileSync('%(tabs_mjs)s', code)
const m = await import('./%(tabs_mjs)s')
const entries = (chat = 'c1') => JSON.parse(JSON.stringify(m.tabsVon(chat)))
const report = await (async () => {
%(scenario)s
})()
console.log('---BERICHT---' + JSON.stringify(report))
process.exit(0)
"""


def _run_driver(scenario: str) -> dict:
    """One name set per run (the drivers stand beside ``node_modules``, as in
    tests/test_werkzeugreiter.py): the process id keeps two runs apart."""
    pid_tag = str(os.getpid())
    stubs = f"tabs-{pid_tag}.stubs.mjs"
    check = f"tabs-{pid_tag}.check.mjs"
    tabs_mjs = f"tabs-{pid_tag}.tabs.mjs"
    files = {
        FRONTEND / stubs: STUBS,
        FRONTEND / check: DRIVER % {
            "tabs": str(TABS),
            "scenario": scenario,
            "stubs": stubs,
            "tabs_mjs": tabs_mjs,
        },
    }
    for file_path, text in files.items():
        file_path.write_text(text, encoding="utf-8")
    try:
        run = subprocess.run(
            ["node", check], cwd=FRONTEND, capture_output=True, text=True, timeout=120,
        )
    finally:
        for file_path in [*files, FRONTEND / tabs_mjs]:
            file_path.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    marker = "---BERICHT---"
    assert marker in run.stdout, run.stdout[-3000:]
    return json.loads(run.stdout.split(marker, 1)[1].strip())


def test_a_card_gives_a_tab_without_a_path_its_path():
    report = _run_driver("""
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>' })
    m.tabOeffnen('c1', { name: 'b.html', art: 'html', inhalt: '<p>b</p>', pfad: '/w/b.html' })
    m.tabEinsortieren('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>', pfad: '/w/a.html' })
    return { entries: entries(), active: m.aktiverTab('c1').id }
""")

    assert report["entries"] == [
        {"id": "html:a.html", "name": "a.html", "art": "html", "inhalt": "<p>a</p>", "pfad": "/w/a.html"},
        {"id": "html:b.html", "name": "b.html", "art": "html", "inhalt": "<p>b</p>", "pfad": "/w/b.html"},
    ]
    # The card shows, it does not choose: the tab in front stays in front.
    assert report["active"] == "html:b.html"


def test_the_writing_answer_gives_a_tab_without_a_path_its_path_at_the_same_content():
    report = _run_driver("""
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>' })
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>', pfad: '/w/a.html' })
    return { entries: entries() }
""")

    assert [e["pfad"] for e in report["entries"]] == ["/w/a.html"]
    assert report["entries"][0]["inhalt"] == "<p>a</p>"


def test_silence_a_path_that_stands_is_not_replaced_by_a_card():
    report = _run_driver("""
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>', pfad: '/w/a.html' })
    m.tabEinsortieren('c1', { name: 'a.html', art: 'html', inhalt: '<p>x</p>', pfad: '/other/a.html' })
    return { entries: entries() }
""")

    assert [(e["pfad"], e["inhalt"]) for e in report["entries"]] == [("/w/a.html", "<p>a</p>")]


def test_silence_nothing_is_written_when_there_is_nothing_to_fill():
    """The card calls from an effect: a write that changes nothing would
    trigger that effect again. The list stays the very same object."""
    report = _run_driver("""
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>', pfad: '/w/a.html' })
    m.tabOeffnen('c1', { name: 'b.html', art: 'html', inhalt: '<p>b</p>' })
    const before = m.tabs.proChat.c1
    m.tabEinsortieren('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>', pfad: '/w/a.html' })
    m.tabEinsortieren('c1', { name: 'b.html', art: 'html', inhalt: '<p>b</p>' })
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>', pfad: '/w/a.html' })
    return { same: before === m.tabs.proChat.c1 }
""")

    assert report["same"] is True


def test_silence_a_closed_tab_does_not_come_back_through_a_card():
    report = _run_driver("""
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>' })
    m.tabSchliessen('c1', 'html:a.html')
    m.tabEinsortieren('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>', pfad: '/w/a.html' })
    return { entries: entries() }
""")

    assert report["entries"] == []


def test_silence_a_card_without_a_path_changes_nothing_in_a_tab_without_one():
    report = _run_driver("""
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>' })
    const before = m.tabs.proChat.c1
    m.tabEinsortieren('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>' })
    return { same: before === m.tabs.proChat.c1, entries: entries() }
""")

    assert report["same"] is True
    assert [e["pfad"] for e in report["entries"]] == [""]


# --- a tab whose file is gone ------------------------------------------------


def test_a_tab_is_taken_out_by_its_address_without_a_closed_mark():
    report = _run_driver("""
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>' })
    m.tabEinsortieren('c1', { name: 'b.pdf', art: 'pdf', inhalt: '', adresse: '/doc/b/file', fakten: '2 p' })
    m.tabRemoveByAddress('c1', '/doc/b/file')
    const gone = entries()
    const closed = JSON.parse(JSON.stringify(m.tabs.zu))
    m.tabEinsortieren('c1', { name: 'b.pdf', art: 'pdf', inhalt: '', adresse: '/doc/b/file', fakten: '2 p' })
    return { gone, closed, back: entries().map((e) => e.id) }
""")

    assert [e["id"] for e in report["gone"]] == ["html:a.html"]
    assert report["closed"] == {}
    # Not closed by hand: the file shown again files its tab again.
    assert report["back"] == ["html:a.html", "pdf:b.pdf"]


def test_the_chosen_tab_taken_out_hands_the_choice_to_the_last_remaining_one():
    report = _run_driver("""
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>' })
    m.tabOeffnen('c1', { name: 'b.html', art: 'html', inhalt: '<p>b</p>' })
    m.tabEinsortieren('c1', { name: 'c.pdf', art: 'pdf', inhalt: '', adresse: '/doc/c/file', fakten: '' })
    m.tabWaehlen('c1', 'pdf:c.pdf')
    m.tabRemoveByAddress('c1', '/doc/c/file')
    return { active: m.aktiverTab('c1').id }
""")

    assert report["active"] == "html:b.html"


def test_the_only_tab_taken_out_leaves_the_rail_as_without_a_tab():
    report = _run_driver("""
    m.tabEinsortieren('c1', { name: 'c.pdf', art: 'pdf', inhalt: '', adresse: '/doc/c/file', fakten: '' })
    m.tabRemoveByAddress('c1', '/doc/c/file')
    return { entries: entries(), active: m.aktiverTab('c1') }
""")

    assert report["entries"] == []
    assert report["active"] is None


def test_silence_closing_by_hand_still_marks_the_tab_closed():
    report = _run_driver("""
    m.tabEinsortieren('c1', { name: 'c.pdf', art: 'pdf', inhalt: '', adresse: '/doc/c/file', fakten: '' })
    m.tabSchliessen('c1', 'pdf:c.pdf')
    return { closed: JSON.parse(JSON.stringify(m.tabs.zu)) }
""")

    assert report["closed"] == {"c1": {"pdf:c.pdf": True}}


def test_silence_an_address_no_tab_carries_writes_nothing_and_a_text_tab_stays():
    report = _run_driver("""
    m.tabOeffnen('c1', { name: 'a.html', art: 'html', inhalt: '<p>a</p>' })
    m.tabEinsortieren('c1', { name: 'c.pdf', art: 'pdf', inhalt: '', adresse: '/doc/c/file', fakten: '' })
    const before = m.tabs.proChat.c1
    m.tabRemoveByAddress('c1', '/doc/other/file')
    m.tabRemoveByAddress('c1', '')
    m.tabRemoveByAddress('c2', '/doc/c/file')
    return { same: before === m.tabs.proChat.c1, ids: entries().map((e) => e.id) }
""")

    assert report["same"] is True
    assert report["ids"] == ["html:a.html", "pdf:c.pdf"]


def test_the_message_removes_the_tab_only_after_the_attachment_went():
    """Source guard of ``Nachricht.svelte``: a failed removal at the service
    leaves the tab, so the tab is taken out after the awaited call."""
    source = (FRONTEND / "src/teile/Nachricht.svelte").read_text(encoding="utf-8")
    body = source.split("async function dokumentAnhangWeg(karte) {", 1)[1].split("\n  }\n", 1)[0]

    assert body.index("await api.anhangEntfernen(") < body.index("tabRemoveByAddress(chatId, ")
    assert "fileAddressOf(karte)" in body
