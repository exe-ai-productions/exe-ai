"""A send that ends before the request leaves, and a queued message the
service refuses, give back the words AND what was attached to them.

Three stretches of the window, each lifted out of its component by its real
text and run in node with everything around it stubbed:

* `senden` (frontend/src/App.svelte) — which early ends give back, that a
  send which arrives gives nothing back, and that the entries a queued
  message kept stand in the bar's keeping while it is sent and are let go of
  when it is over;
* `keep` and `zurueckgeben` (frontend/src/teile/Eingabeleiste.svelte) — what
  was kept comes back into the bar.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.test_hausregeln import _node, _stueck as _piece
from tests.fensterquelle import BAR_SOURCE, WINDOW_SOURCE

ROOT = Path(__file__).resolve().parent.parent
APP = WINDOW_SOURCE
BAR = BAR_SOURCE

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _senden_script(cases: str) -> str:
    senden = _piece(APP, r"\n  async function senden\(.*?\n  \}\n", "senden")
    return f"""
const make = (over = {{}}) => {{
  const log = {{
    giveBack: [], melde: [], answered: 0, benutzerfrage: [], kept: [], released: [],
    heldDuringAnswer: false,
  }}
  const zustand = {{
    benutzerfrage: {{}}, aktiverChat: 'A', modellId: 'm', sendet: {{}},
    nachrichten: [], nachrichtenChatId: 'A', ...(over.zustand ?? {{}}),
  }}
  const env = {{
    chosenModelOff: () => Boolean(over.modelOff),
    api: {{ bildHochladen: async (file) => {{
      if (over.uploadFails) throw new Error('upload refused')
      return {{ bild: 'stored-' + file }}
    }} }},
    openNewChat: async () => {{ if (over.chatFails) throw new Error('no chat') }},
  }}
  const eingabe = {{
    zurueckgeben: (...args) => log.giveBack.push(args),
    keep: (id, kept) => {{ log.kept.push([id, kept]); return () => log.released.push(id) }},
  }}
  const melde = (...args) => log.melde.push(args)
  const t = (key) => key
  const chatNameFrom = (text) => String(text).slice(0, 20)
  const nachrichtenAnzeige = () => []
  const aktuellerChat = () => null
  const chatsLaden = async () => {{}}
  const nachrichtenSetzen = () => {{}}
  const runter = () => {{}}
  const nameUpload = () => {{}}
  const antwortHolen = async () => {{
    log.answered += 1
    log.heldDuringAnswer = log.kept.length > 0 && log.released.length === 0
  }}
  const benutzerfrageBeantworten = async (words) => {{ log.benutzerfrage.push(words) }}
  const haltendenWertSetzen = async () => true
  const {{ chosenModelOff, api, openNewChat }} = env
  {senden}
  return {{ senden, log, zustand }}
}}
const results = {{}}
{cases}
console.log(JSON.stringify(results))
"""


@needs_node
def test_a_send_that_ends_early_gives_back_words_and_attachments():
    results = _node(_senden_script("""
{
  const m = make({ zustand: { modellId: '' } })
  await m.senden('hello', ['p.png'], [{ id: 'd1' }], null, null, false, 'k1')
  results.noModel = { back: m.log.giveBack, melde: m.log.melde.length, answered: m.log.answered }
}
{
  const m = make({ modelOff: true })
  await m.senden('hello', [], [], null, null, false, 'k2')
  results.modelOff = { back: m.log.giveBack, melde: m.log.melde.length, answered: m.log.answered }
}
{
  const m = make({ uploadFails: true })
  await m.senden('hello', ['p.png'], [], null, null, false, 'k3')
  results.uploadFails = {
    back: m.log.giveBack, melde: m.log.melde.length, answered: m.log.answered,
    marked: Object.keys(m.zustand.sendet),
  }
}
{
  const m = make({ chatFails: true, zustand: { aktiverChat: null } })
  let error = null
  try { await m.senden('hello', [], [], null, null, false, 'k4') } catch (e) { error = e.message }
  results.chatFails = { back: m.log.giveBack, error, answered: m.log.answered }
}
"""))
    # Words and attachments go back under the send's id, to the chat they
    # were written for, exactly once; nothing went to the service.
    assert results["noModel"] == {"back": [["hello", "A", "k1"]], "melde": 1, "answered": 0}
    assert results["modelOff"] == {"back": [["hello", "A", "k2"]], "melde": 0, "answered": 0}
    assert results["uploadFails"] == {
        "back": [["hello", "A", "k3"]], "melde": 1, "answered": 0, "marked": [],
    }
    assert results["chatFails"] == {
        "back": [["hello", None, "k4"]], "error": "no chat", "answered": 0,
    }


@needs_node
def test_a_send_that_arrives_gives_nothing_back():
    results = _node(_senden_script("""
{
  // Silence probe: the request leaves, the bar is not told to take anything.
  const m = make()
  await m.senden('hello', ['p.png'], [{ id: 'd1' }], null, null, false, 'k1')
  results.arrives = { back: m.log.giveBack, answered: m.log.answered }
}
{
  // A send with no id of its own has nothing of the bar's to give back.
  const m = make({ zustand: { modellId: '' } })
  await m.senden('hello', [], [], null, null, false, null)
  results.noId = { back: m.log.giveBack, melde: m.log.melde.length }
}
{
  // Words that answer a standing question are the answer, not a send.
  const m = make({ zustand: { benutzerfrage: { A: { id: 'q' } }, modellId: '' } })
  await m.senden('yes', [], [], null, null, false, 'k5')
  results.answer = { back: m.log.giveBack, answers: m.log.benutzerfrage, answered: m.log.answered }
}
"""))
    assert results["arrives"] == {"back": [], "answered": 1}
    assert results["noId"] == {"back": [], "melde": 1}
    assert results["answer"] == {"back": [], "answers": ["yes"], "answered": 0}


@needs_node
def test_a_queue_entry_is_kept_under_its_sends_id_and_let_go_of_after():
    results = _node(_senden_script("""
const kept = { bilder: [{ datei: 'p.png' }], dokumente: [{ id: 'd1' }] }
{
  // The send arrives: the entries stood in the keeping under the send's id
  // while it ran, and are let go of when it is over; nothing is given back.
  const m = make({ keep: true })
  await m.senden('hello', ['p.png'], [{ id: 'd1' }], null, null, false, null, kept)
  results.arrives = {
    kept: m.log.kept, released: m.log.released, back: m.log.giveBack, answered: m.log.answered,
    heldDuring: m.log.heldDuringAnswer,
  }
}
{
  // The send ends before the request: the entries and the words go back
  // under the very id they were kept under; the bar's keeping consumed them.
  const m = make({ keep: true, zustand: { modellId: '' } })
  await m.senden('hello', ['p.png'], [], null, null, false, null, kept)
  results.endsEarly = { kept: m.log.kept, back: m.log.giveBack, answered: m.log.answered }
}
{
  // Silence probe: a queued message that kept nothing keeps nothing and a
  // send of the bar's own (an id, no entries) is not kept a second time.
  const m = make({ keep: true })
  await m.senden('hello', [], [], null, null, false, 'own1')
  results.nothingKept = { kept: m.log.kept, back: m.log.giveBack }
}
"""))
    kept_id = results["arrives"]["kept"][0][0]
    assert len(kept_id) >= 5
    assert results["arrives"]["kept"] == [[kept_id, {
        "bilder": [{"datei": "p.png"}], "dokumente": [{"id": "d1"}],
    }]]
    assert results["arrives"]["heldDuring"] is True
    assert results["arrives"]["released"] == [kept_id]
    assert results["arrives"]["back"] == [] and results["arrives"]["answered"] == 1
    early = results["endsEarly"]
    assert early["answered"] == 0
    assert early["back"] == [["hello", "A", early["kept"][0][0]]]
    assert results["nothingKept"] == {"kept": [], "back": []}


def _bar_script(case: str) -> str:
    keep = _piece(BAR, r"\n  (?:export )?function keep\(messageId, kept\) \{.*?\n  \}\n", "keep")
    give_back = _piece(
        BAR,
        r"\n  (?:export )?function zurueckgeben\(inhalt, chat = entwurfChat, messageId = null\) \{.*?\n  \}\n",
        "zurueckgeben",
    )
    return f"""
const URL = {{ createObjectURL: (file) => 'blob:' + file.name, revokeObjectURL: () => {{}} }}
const LEERER_ENTWURF = {{ text: '', anhaenge: [], dokumentAnhaenge: [] }}
const file = (name) => ({{ name, type: 'image/png' }})
let text = ''
let anhaenge = []
let dokumentAnhaenge = []
const zurueckbehalten = new Map()
const entwuerfe = new Map()
let entwurfChat = 'A'
{keep}
{give_back}
const state = () => ({{
  text, pictures: anhaenge.map((a) => a.datei.name), documents: dokumentAnhaenge.map((d) => d.id),
  drafts: [...entwuerfe].map(([k, v]) => [k, v.text, v.anhaenge.map((a) => a.datei.name), v.dokumentAnhaenge.map((d) => d.id)]),
  kept: [...zurueckbehalten.keys()],
}})
{case}
console.log(JSON.stringify(state()))
"""


KEPT = (
    "{ bilder: [{ datei: file('red.png') }, { datei: file('blue.png') }], "
    "dokumente: [{ id: 'doc-1', datei: file('plan.pdf'), dokument: { id: 'stored-1' } }] }"
)


@needs_node
def test_what_a_queue_entry_kept_comes_back_with_its_words():
    got = _node(_bar_script(f"keep('q1', {KEPT})\nzurueckgeben('queued words', 'A', 'q1')"))
    assert got["text"] == "queued words"
    assert got["pictures"] == ["red.png", "blue.png"]
    assert got["documents"] == ["doc-1"]
    assert got["kept"] == [], "they came back and are not kept a second time"


@needs_node
def test_a_queue_entry_that_came_back_in_another_chat_goes_to_that_chats_draft():
    got = _node(_bar_script(f"keep('q1', {KEPT})\nzurueckgeben('words', 'B', 'q1')"))
    assert got["text"] == ""
    assert got["pictures"] == [] and got["documents"] == []
    assert got["drafts"] == [["B", "words", ["red.png", "blue.png"], ["doc-1"]]]


@needs_node
def test_letting_go_of_a_kept_send_leaves_nothing_behind():
    # The send arrived: nothing came back, and the keeper is emptied.
    got = _node(_bar_script(f"const release = keep('q1', {KEPT})\nrelease()"))
    assert got["kept"] == []
    assert got["pictures"] == [] and got["documents"] == [] and got["text"] == ""


def test_the_queue_carries_the_entries_and_both_ways_out_pass_them_on():
    app = APP.read_text(encoding="utf-8")
    bar = BAR.read_text(encoding="utf-8")
    # The entry the bar lines up carries what it took out of the bar.
    assert "einreihen(chatBeimStart, { ...auftrag, kept })" in bar
    # Only the queue's own move hands the entries to `senden`, and nothing
    # else sends an entry.
    call = (
        "senden(\n      eintrag.inhalt, eintrag.bilder, eintrag.dokumente, eintrag.denken, "
        "eintrag.skill,\n      false, null, eintrag.kept, eintrag,\n    )"
    )
    assert app.count(call) == 1
    # The bar's own send keeps its entries the same way.
    assert "const release = keep(messageId, kept)" in bar
