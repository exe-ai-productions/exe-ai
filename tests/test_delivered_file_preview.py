"""A file the model hands into the chat reaches the preview at once.

``lib/deliveredFile.js`` knows what kind a delivered file's card carries and
files the file as a tab of the preview from the handler of the event that
brought it. The modules are run, not read: the tab list is compiled with the
Svelte compiler (it uses runes), the rail and the clock of the chat are
stand-ins, and the calls go in the way the chat's event handler makes them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LIB = FRONTEND / "src/lib"
NACHRICHT = FRONTEND / "src/teile/Nachricht.svelte"
CHATLAUF = LIB / "chatlauf.svelte.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)

# The rail: what the chat's handler asks of it, and what it was asked.
STUBS = """
export const calls = []
export const leiste = { nichtAufdraengen: '' }
export const anbieten = (name) => { if (leiste.nichtAufdraengen !== name) calls.push(name) }
export const zustand = { aktiverChat: 'c1' }
export const t = (key, values) => values ? key + ':' + values.zahl : key
"""

DRIVER = """
import { compileModule } from 'svelte/compiler'
import { readFileSync, writeFileSync } from 'fs'
const bend = (code) => code
  .replace(/from '\\.\\/arbeitsleiste\\.svelte\\.js'/g, "from './%(stubs)s'")
  .replace(/from '\\.\\/zustand\\.svelte\\.js'/g, "from './%(stubs)s'")
  .replace(/from '\\.\\/texte\\.svelte\\.js'/g, "from './%(stubs)s'")
  .replace(/from '\\.\\/vorschautabs\\.svelte\\.js'/g, "from './%(tabs_mjs)s'")
writeFileSync('%(tabs_mjs)s', bend(compileModule(readFileSync(%(tabs)r, 'utf-8'), { filename: 'vorschautabs.svelte.js', generate: 'client' }).js.code))
writeFileSync('%(file_mjs)s', bend(readFileSync(%(file)r, 'utf-8')))
writeFileSync('%(arten_mjs)s', readFileSync(%(arten)r, 'utf-8'))
writeFileSync('%(media_mjs)s', readFileSync(%(media)r, 'utf-8'))
const tabs = await import('./%(tabs_mjs)s')
const stubs = await import('./%(stubs)s')
const delivered = await import('./%(file_mjs)s')
const entries = (chat = 'c1') => JSON.parse(JSON.stringify(tabs.tabsVon(chat)))
const reads = []
const deps = (over = {}) => ({
  mayOpen: () => stubs.zustand.aktiverChat === 'c1',
  readText: async (d) => { reads.push(d.id); return d.text ?? ('text of ' + d.name) },
  addressOf: (d) => '/documents/' + d.id + '/file',
  ...over,
})
const report = await (async () => {
%(scenario)s
})()
console.log('---BERICHT---' + JSON.stringify(report))
process.exit(0)
"""


def _run_driver(scenario: str) -> dict:
    """One name set per run, standing beside ``node_modules`` as in
    tests/test_vorschautabs.py: the process id keeps two runs apart."""
    tag = str(os.getpid())
    names = {
        "stubs": f"delivered-{tag}.stubs.mjs",
        "tabs_mjs": f"delivered-{tag}.tabs.mjs",
        "file_mjs": f"delivered-{tag}.file.mjs",
    }
    # deliveredFile.js reads these two by their own names.
    arten, media = "dateiarten.js", "media.js"
    check = f"delivered-{tag}.check.mjs"
    files = {
        FRONTEND / names["stubs"]: STUBS,
        FRONTEND / check: DRIVER % {
            **names,
            "tabs": str(LIB / "vorschautabs.svelte.js"),
            "file": str(LIB / "deliveredFile.js"),
            "arten": str(LIB / arten),
            "media": str(LIB / media),
            "arten_mjs": arten,
            "media_mjs": media,
            "scenario": scenario,
        },
    }
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    try:
        run = subprocess.run(["node", check], cwd=FRONTEND, capture_output=True, text=True, encoding="utf-8", timeout=120)
    finally:
        for path in [*files, FRONTEND / names["tabs_mjs"], FRONTEND / names["file_mjs"], FRONTEND / arten, FRONTEND / media]:
            path.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    marker = "---BERICHT---"
    assert marker in run.stdout, run.stdout[-3000:]
    return json.loads(run.stdout.split(marker, 1)[1].strip())


HTML = "{ id: 'd1', name: 'page.html', typ: 'html', pfad: '/w/page.html' }"


@needs_node
def test_a_card_gets_the_kind_of_its_ending_and_htm_is_html():
    report = _run_driver("""
    const kinds = ['html', 'HTM', 'csv', 'json', 'svg', 'md', 'markdown', 'yml', 'xml', 'zip', '', undefined]
    return kinds.map((k) => [String(k), delivered.deliveredLanguage(k)])
""")

    assert dict((k, v) for k, v in report) == {
        "html": "html", "HTM": "html", "csv": "csv", "json": "json", "svg": "svg",
        "md": "md", "markdown": "md", "yml": "yml", "xml": "xml", "zip": "", "": "", "undefined": "",
    }


@needs_node
def test_a_delivered_html_file_is_filed_and_the_preview_comes_forward():
    report = _run_driver(f"""
    await delivered.openDeliveredFiles('c1', [{HTML}], deps())
    return {{ entries: entries(), active: tabs.aktiverTab('c1').id, offered: stubs.calls, reads }}
""")

    assert report["entries"] == [
        {"id": "html:page.html", "name": "page.html", "art": "html", "inhalt": "text of page.html", "pfad": "/w/page.html"},
    ]
    assert report["active"] == "html:page.html"
    assert report["offered"] == ["vorschau"]


@needs_node
def test_a_pdf_gets_its_tab_with_an_address_and_comes_forward():
    report = _run_driver("""
    const pdf = { id: 'p1', name: 'paper.pdf', typ: 'pdf', size_bytes: 12288, seiten: 3, pfad: '/w/paper.pdf' }
    await delivered.openDeliveredFiles('c1', [pdf], deps())
    return { entries: entries(), offered: stubs.calls, reads }
""")

    assert report["entries"] == [{
        "id": "pdf:paper.pdf", "name": "paper.pdf", "art": "pdf", "inhalt": "", "pfad": "/w/paper.pdf",
        "adresse": "/documents/p1/file", "fakten": "PDF · 12 KB · nachricht.dokument_seiten:3",
    }]
    assert report["offered"] == ["vorschau"]
    assert report["reads"] == [], "a PDF is drawn from the file, its text is never fetched"


@needs_node
def test_with_the_column_folded_on_the_preview_the_tab_is_only_filed():
    report = _run_driver(f"""
    stubs.leiste.nichtAufdraengen = 'vorschau'
    await delivered.openDeliveredFiles('c1', [{HTML}], deps())
    return {{ entries: entries(), offered: stubs.calls }}
""")

    assert [e["id"] for e in report["entries"]] == ["html:page.html"]
    assert report["offered"] == []


@needs_node
def test_where_the_preview_may_not_open_the_tab_is_only_filed():
    """Silence probe, a chat that is not on screen and an answer picked up
    again after a reload: the tab is filed in its own chat, the preview of
    the chat on screen stays where it is — and the answer is asked after the
    text came back, not before."""
    report = _run_driver(f"""
    stubs.zustand.aktiverChat = 'c2'
    await delivered.openDeliveredFiles('c1', [{HTML}], deps())
    const late = {{ id: 'd2', name: 'later.html', typ: 'html' }}
    stubs.zustand.aktiverChat = 'c1'
    await delivered.openDeliveredFiles('c1', [late], deps({{ readText: async (d) => {{ stubs.zustand.aktiverChat = 'c2'; return 'x' }} }}))
    return {{ entries: entries(), other: entries('c2'), offered: stubs.calls }}
""")

    assert [e["id"] for e in report["entries"]] == ["html:page.html", "html:later.html"]
    assert report["other"] == []
    assert report["offered"] == []


@needs_node
def test_a_picture_a_file_of_no_known_kind_and_an_unreadable_text_are_left_alone():
    report = _run_driver("""
    await delivered.openDeliveredFiles('c1', [
      { id: 'i1', name: 'drawing.png', typ: 'png' },
      { id: 'z1', name: 'bundle.zip', typ: 'zip' },
      { id: 'b1', name: 'binary.csv', typ: 'csv', text: null },
      { name: 'no-id.html', typ: 'html' },
    ], deps({ readText: async (d) => (d.text === null ? null : 'x') }))
    return { entries: entries(), offered: stubs.calls }
""")

    assert report["entries"] == []
    assert report["offered"] == []


@needs_node
def test_code_and_text_are_filed_with_their_text_and_what_is_drawn_or_played_with_its_address():
    report = _run_driver("""
    const files = [
      { id: 'c1', name: 'is_prime.py', typ: 'py' },
      { id: 't1', name: 'notes.txt', typ: 'txt' },
      { id: 'g1', name: 'anim.gif', typ: 'gif', size_bytes: 3072 },
      { id: 'v1', name: 'clip.mp4', typ: 'mp4', size_bytes: 921600 },
      { id: 'a1', name: 'tone.mp3', typ: 'mp3', size_bytes: 40960 },
      { id: 'w1', name: 'plan.docx', typ: 'docx', size_bytes: 18432 },
      { id: 's1', name: 'sales.xlsx', typ: 'xlsx', size_bytes: 22528 },
      { id: 'd1', name: 'deck.pptx', typ: 'pptx', size_bytes: 122880 },
      { id: 'o1', name: 'old.doc', typ: 'doc', size_bytes: 5120 },
      { id: 'p1', name: 'drawing.png', typ: 'png' },
    ]
    await delivered.openDeliveredFiles('c1', files, deps())
    return { entries: entries(), reads, offered: stubs.calls }
""")

    by_name = {e["name"]: e for e in report["entries"]}
    assert list(by_name) == [
        "is_prime.py", "notes.txt", "anim.gif", "clip.mp4", "tone.mp3", "plan.docx", "sales.xlsx", "deck.pptx",
    ], "a PNG stays a tile and an old binary Office file gets no tab"
    assert (by_name["is_prime.py"]["art"], by_name["is_prime.py"]["inhalt"]) == ("py", "text of is_prime.py")
    assert by_name["notes.txt"]["art"] == "txt"
    for name, art, address, facts in (
        ("anim.gif", "gif", "/documents/g1/file", "GIF · 3 KB"),
        ("clip.mp4", "mp4", "/documents/v1/file", "MP4 · 900 KB"),
        ("tone.mp3", "mp3", "/documents/a1/file", "MP3 · 40 KB"),
        ("plan.docx", "docx", "/documents/w1/file", "DOCX · 18 KB"),
        ("sales.xlsx", "xlsx", "/documents/s1/file", "XLSX · 22 KB"),
        ("deck.pptx", "pptx", "/documents/d1/file", "PPTX · 120 KB"),
    ):
        assert (by_name[name]["art"], by_name[name]["adresse"], by_name[name]["fakten"]) == (art, address, facts)
        assert by_name[name]["inhalt"] == ""
    assert report["reads"] == ["c1", "t1"], "only a text is fetched"
    assert report["offered"], "the preview comes forward"


@needs_node
def test_a_failed_read_does_not_stop_the_files_after_it():
    report = _run_driver("""
    await delivered.openDeliveredFiles('c1', [
      { id: 'a', name: 'a.json', typ: 'json' },
      { id: 'b', name: 'b.json', typ: 'json' },
    ], deps({ readText: async (d) => { if (d.id === 'a') throw new Error('gone'); return '{}' } }))
    return { ids: entries().map((e) => e.id) }
""")

    assert report["ids"] == ["json:b.json"]


@needs_node
def test_a_markdown_document_is_filed_as_before_and_a_rewrite_replaces_it():
    report = _run_driver("""
    const note = { id: 'n1', name: 'note.md', typ: 'md' }
    await delivered.openDeliveredFiles('c1', [note], deps({ readText: async () => '# one' }))
    await delivered.openDeliveredFiles('c1', [note], deps({ readText: async () => '# two' }))
    return { entries: entries() }
""")

    assert [(e["art"], e["inhalt"]) for e in report["entries"]] == [("md", "# two")]


def test_the_cards_pass_their_kind_on_and_the_chat_files_in_its_event_handler():
    """The two places of the message and the handler of the event: nothing
    reads a delivered file's kind from a hard-wired list any more, and the
    filing is not left to an effect."""
    nachricht = NACHRICHT.read_text(encoding="utf-8")
    assert "['md', 'markdown'].includes(karte.typ)" not in nachricht
    assert nachricht.count("sprache={deliveredLanguage(karte.typ)}") == 2
    assert "dateizeichen(deliveredLanguage(karte.typ))" in nachricht
    chat = CHATLAUF.read_text(encoding="utf-8")
    handler = re.search(r"if \(Array\.isArray\(ereignis\.dokumente\)\) \{(.*?)\n          \}", chat, re.S)
    assert handler and "openDeliveredFiles(zielChat, ereignis.dokumente" in handler.group(1)
    # An answer picked up again after a reload replays its whole run: the
    # files of it are filed and the preview is not brought forward.
    assert "mayOpen: () => !wiederanhang && zielChat === zustand.aktiverChat" in handler.group(1)
    assert "$effect" not in (LIB / "deliveredFile.js").read_text(encoding="utf-8")
