"""The doc folder's window: one way in, the two choices of its list, and
who brought a file.

``lib/docFolderFilters.svelte.js`` holds which project the start page stands
on and whose files it shows — a memory for as long as the window is open.
The module uses runes, so it is compiled with the Svelte compiler and the
calls go in the way the buttons make them; the asks of ``lib/api.js`` are
run in Node against a counting ``fetch``. What needs a browser — the drag,
the rendered wall — is pinned as the source lines it is, as the house does
for markup.

What the service answers to an origin and a project is its own matter
(tests/test_docfolder.py).
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
FILTER = FRONTEND / "src/lib/docFolderFilters.svelte.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (FRONTEND / "node_modules").is_dir(),
    reason="no Node or no frontend dependencies on this machine",
)


def _run(driver: str, *extra: Path) -> dict:
    """Run a driver in Node from the frontend folder and hand back what it
    reported."""
    script = FRONTEND / f"docfolder-{os.getpid()}.check.mjs"
    script.write_text(driver, encoding="utf-8")
    try:
        run = subprocess.run(["node", script.name], cwd=FRONTEND, capture_output=True, text=True, encoding="utf-8", timeout=60)
    finally:
        script.unlink(missing_ok=True)
        for path in extra:
            path.unlink(missing_ok=True)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(run.stdout.split("---BERICHT---", 1)[1].strip())


def _source(name: str = "DocFolder.svelte") -> str:
    return (FRONTEND / "src/teile" / name).read_text(encoding="utf-8")


def _body(source: str, head: str) -> str:
    """A function of the component, from its head to its closing brace,
    without its comments."""
    return re.sub(r"/\*.*?\*/", "", source.split(head, 1)[1].split("\n  }\n", 1)[0], flags=re.S)


# --- The two choices ---------------------------------------------------------


def test_the_filter_module_holds_the_project_and_the_origin():
    module = FRONTEND / f"docfolder-{os.getpid()}.filter.mjs"
    report = _run(
        f"""
import {{ compileModule }} from 'svelte/compiler'
import {{ readFileSync, writeFileSync }} from 'fs'
writeFileSync({module.name!r}, compileModule(readFileSync({str(FILTER)!r}, 'utf-8'),
  {{ filename: 'filter.svelte.js', generate: 'client' }}).js.code)
const m = await import('./{module.name}')
const f = m.docFolderFilters
const steps = [[f.project, f.origin]]
f.project = 'p1'; f.origin = 'cronjob'; steps.push([f.project, f.origin])
f.project = ''; f.origin = ''; steps.push([f.project, f.origin])
console.log('---BERICHT---' + JSON.stringify({{
  steps,
  gone: ['ANSICHTEN', 'HERKUNFT_JE_ANSICHT', 'ansichtWaehlen'].filter((n) => n in m),
  fields: Object.keys(f).sort(),
  origins: Object.entries(m.ORIGINS),
}}))
process.exit(0)
""",
        module,
    )
    # It starts on every project and everyone's files; a choice stands, and
    # dropping it again leaves the start page as it began.
    assert report["steps"] == [["", ""], ["p1", "cronjob"], ["", ""]]
    assert report["gone"] == []
    assert report["fields"] == ["origin", "project"]
    # The three origins in the order of the list, each with the key of its
    # word written out.
    assert report["origins"] == [
        ["user", "docfolder.origin_user"],
        ["agent", "docfolder.origin_agent"],
        ["cronjob", "docfolder.origin_cronjob"],
    ]


def test_every_origin_has_its_word_in_both_languages():
    for language, words in (("de", ["Nutzer", "Agent", "Cronjob"]), ("en", ["User", "Agent", "Cron job"])):
        catalogue = json.loads((WURZEL / f"app/locales/{language}.json").read_text(encoding="utf-8"))
        folder = catalogue["docfolder"]
        assert [folder["origin_user"], folder["origin_agent"], folder["origin_cronjob"]] == words
        # The dock is called the same wherever its files are named.
        assert catalogue["werkzeuge"]["quelle_dock"] == "Dock"


def test_the_ask_carries_origin_and_project_together():
    """The window narrows nothing itself: both choices travel with the ask
    and the service answers their intersection. Schweigeprobe: no choice,
    no parameter — and in a chat only the chat is named."""
    report = _run(
        """
const asked = []
globalThis.fetch = async (address, options) => {
  asked.push([options?.method ?? 'GET', address, options?.headers?.['Content-Type'] ?? null])
  return new Response('[]', { status: 200 })
}
const { api } = await import('./src/lib/api.js')
await api.docFolder({ project: 'p1', origin: 'cronjob' })
await api.docFolder({ origin: 'user' })
await api.docFolder({ project: '', origin: '' })
await api.docFolder({ chat: 'c1' })
await api.docFolderAdd(new File(['a'], 'my plan.txt', { type: 'text/plain' }))
await api.docFolderAdd(new File(['a'], 'raw.bin'), 'c1')
console.log('---BERICHT---' + JSON.stringify({ asked, old: Object.keys(api).filter((n) => /^dock[A-Z]/.test(n)) }))
process.exit(0)
"""
    )
    assert report["asked"] == [
        ["GET", "/api/v1/doc-folder?project=p1&origin=cronjob", None],
        ["GET", "/api/v1/doc-folder?origin=user", None],
        ["GET", "/api/v1/doc-folder", None],
        ["GET", "/api/v1/doc-folder?chat=c1", None],
        # One route takes a file in: onto the dock, or with the chat named
        # into that chat's own folder.
        ["POST", "/api/v1/agentendock?name=my%20plan.txt", "text/plain"],
        ["POST", "/api/v1/agentendock?name=raw.bin&chat=c1", "application/octet-stream"],
    ]
    # The four calls of the second dock are gone.
    assert report["old"] == []


def test_the_chooser_stands_only_on_the_start_page():
    """Schweigeprobe: the chooser is gated on the open chat and stands there
    exactly once; in a chat neither choice is sent, so nothing narrows a
    wall whose choices cannot be seen."""
    source = _source()
    assert source.count("{#if !chat}") == 1
    assert source.count('class="projekt"') == 1
    assert source.index("{#if !chat}") < source.index('class="projekt"')
    assert "ANSICHTEN" not in source and "ansichtWaehlen" not in source
    assert re.search(
        r"api\.docFolder\(\s*chat\s*\?\s*\{\s*chat\s*\}\s*:\s*\{\s*project,\s*origin\s*\}\s*\)", source
    )
    # A changed origin asks again, as a changed project does.
    effect = source.split("$effect(() => {\n    void project", 1)[1].split("})", 1)[0]
    assert "void origin" in effect and "void chat" in effect


def test_the_list_names_the_origins_a_line_and_the_projects():
    source = _source()
    listed = source[source.index('<div class="projektliste" role="listbox">') :]
    listed = listed[: listed.index("</div>")]
    order = [
        listed.index("{#each originEntries as entry (entry.wert)}"),
        listed.index('<span class="divider" role="separator"></span>'),
        listed.index("{#each projectEntries as entry (entry.wert)}"),
    ]
    assert order == sorted(order)
    assert "onclick={() => originPick(entry.wert)}" in listed
    # The same origin chosen again shows everyone's files; an origin the
    # list does not know is no filter.
    assert "filters.origin = filters.origin === value ? '' : value" in _body(source, "function originPick(value) {")
    assert "Object.hasOwn(ORIGINS, filters.origin) ? filters.origin : ''" in source


def test_each_origin_wears_its_mark():
    """An agent's file wears the agent mark, a cron job's the stopwatch.
    Schweigeprobe: the person's own file has no branch and so no plaque."""
    source = _source()
    marks = source[source.index("{#if file.origin === 'agent'}") :]
    marks = marks[: marks.index("{/if}")]
    agent, cronjob = marks.split("{:else if file.origin === 'cronjob'}")
    assert "<Agentenmarke groesse={18} />" in agent and "Hauszeichen" not in agent
    assert '<Hauszeichen zeichen="stopwatch" groesse={18} />' in cronjob and "Agentenmarke" not in cronjob
    assert marks.count('class="plakette"') == 2
    assert "{:else}" not in marks
    assert source.count('class="plakette"') == 2
    assert "{:else if zeichen === 'stopwatch'}" in _source("Hauszeichen.svelte")


def _declarations(selector: str) -> str:
    """The declarations of the one rule with exactly this selector, without
    the comments standing in it."""
    style = _source().split("<style>", 1)[1]
    bodies = re.findall(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", style, flags=re.S))
    assert len(bodies) == 1, selector
    return bodies[0]


def test_the_mark_stands_bare_at_the_lower_left():
    """The sign of who brought a file has no ground and no edge of its own.
    It stands inside the document at the lower left, in the box and on the
    line of the cross opposite, and it takes no pointer, so a click on it
    opens the file like a click anywhere on the tile. The silence check:
    the cross keeps its glass."""
    mark = _declarations(".plakette")
    assert "left: 5px;" in mark and "bottom: 38px;" in mark
    assert "width: 20px;" in mark and "height: 20px;" in mark
    for gone in ("background", "box-shadow", "border", "padding", "top:", "right:"):
        assert gone not in mark, gone
    assert "color: var(--text);" in mark and "pointer-events: none;" in mark
    cross = _declarations(".weg")
    assert "right: 5px;" in cross and "bottom: 38px;" in cross
    assert "background: var(--glass-dropdown);" in cross


def test_the_wall_does_not_fade_at_its_top():
    """The first row stands in full strength under the heading: the wall
    carries no mask. It still scrolls."""
    wall = _declarations(".rollen")
    assert "mask" not in wall and "--auslauf" not in wall
    assert "overflow-y: auto;" in wall


# --- One way in --------------------------------------------------------------


def test_the_second_dock_is_gone_from_the_window():
    """No module, no call and no address of the old dock is left anywhere in
    the window's sources. Schweigeprobe: the one dock's address still is."""
    assert not (FRONTEND / "src/lib/dock.svelte.js").exists()
    sources = {
        path: path.read_text(encoding="utf-8", errors="replace")
        for path in (FRONTEND / "src").rglob("*")
        if path.is_file() and path.suffix in {".js", ".svelte", ".ts"}
    }
    for word in ("notizen/dock", "notizen\\/dock", "dock.svelte", "dockLaden", "dockVoll", "dockDateienAblegen", "dockAblegen", "dockEntfernen", "dockAlle", "dockPlaetzeAnzahl"):
        # As a name of its own: the one dock's `agentendockEntfernen` ends
        # in one of these words and is no trace of the old dock.
        trace = re.compile(rf"(?<![A-Za-z]){re.escape(word)}")
        assert [path.name for path, text in sources.items() if trace.search(text)] == [], word
    assert any("/agentendock" in text for text in sources.values())


def test_a_folder_address_is_one_of_the_two_routes():
    """What the input bar takes as a file of the folder: a file of the dock
    or a document of a chat. Schweigeprobe: the old dock's address and the
    listing beside the files are none."""
    bar = _source("Eingabeleiste.svelte")
    pattern = re.search(r"const FOLDER_FILE =\s*/(.+)/\n", bar)
    assert pattern, "FOLDER_FILE not found"
    folder_file = re.compile(pattern.group(1))
    assert folder_file.match("/agentendock/3f2a-1")
    assert folder_file.match("/documents/3f2a-1/file")
    assert not folder_file.match("/notizen/dock/3f2a-1")
    assert not folder_file.match("/agentendock/alle")


def test_dropped_and_picked_files_take_the_same_way():
    """Both hand their files to `add`, which puts them in one after the
    other — the open chat named, so a file of a chat lies in that chat's
    folder — tells of a refused file and goes on, and asks for the wall
    once at the end."""
    source = _source()
    add = _body(source, "async function add(list) {")
    loop = add[add.index("for (const file of list) {") : add.index("await load()")]
    assert "await api.docFolderAdd(file, into)" in loop
    # Where they go is read once, before the first file is on its way.
    assert add.index("const into = chat") < add.index("for (const file of list) {")
    assert "melde(error.message, 'fehler')" in loop and "return" not in add
    assert add.count("await load()") == 1
    assert "await add(chosenFiles)" in _body(source, "async function picked(event) {")
    assert "await add([...(event.dataTransfer?.files ?? [])])" in _body(source, "async function dropped(event) {")
    # Removing knows one route too.
    remove = _body(source, "async function remove(file) {")
    assert "await api.agentendockEntfernen(file.id)" in remove and "source ===" not in remove


def test_in_a_chat_the_folder_button_opens_that_chats_folder():
    """The row stands for the dock by name; in a chat the files are put
    into the chat's own folder, so the folder button shows that one.
    Schweigeprobe: without the callback the row opens its named location."""
    source = _source()
    assert "onopen={chat ? openChatFolder : null}" in source
    assert "return api.ordnerOeffnen(chat, null)" in _body(source, "function openChatFolder() {")
    row = _source("Speicherortzeile.svelte")
    opened = _body(row, "async function oeffnen() {")
    assert "if (onopen) await onopen()" in opened
    assert "else await api.speicherortOeffnen(name)" in opened
    assert "onopen = null" in row


# --- The folder as a drop target ---------------------------------------------
# Dragging needs a browser; these read the component's source.


def test_files_dropped_on_the_folder_do_not_reach_the_chat():
    """The input bar attaches every drop that reaches the window to the
    chat; the folder's drop stops there, on every path, before anything is
    put into the folder."""
    code = _body(_source(), "async function dropped(event) {")
    stop = code.find("event.stopPropagation()")
    assert stop >= 0, "the drop is not stopped"
    before = code[:stop]
    # Nothing before the stop may skip it: no condition, no early return,
    # no block still open around it.
    assert not re.search(r"\b(if|return)\b|\?|&&|\|\|", before), before
    assert before.count("{") == before.count("}")
    assert code.index("await add(") > stop


def test_a_drop_beside_the_folder_still_reaches_the_chat():
    """Silence check: the window-wide drop of the input bar is still there,
    so a file dropped beside the folder is attached as before."""
    window = re.search(r"<svelte:window(.*?)/>", _source("Eingabeleiste.svelte"), re.S)
    assert window and "ondrop={fallenlassen}" in window.group(1)


def test_moving_onto_an_own_tile_keeps_the_highlight():
    """A leave onto one of the folder's own cards is not a leave: the folder
    counts the elements the drag stands in, and only the count falling to
    nought ends the highlight. Where the drag went is not asked — a browser
    that names no element on a leave must not make the folder flicker."""
    source = _source()
    folder = re.search(r'<div\s+class="modul"(.*?)>\s*<!--.*?-->\s*<div class="ordnerzeile"', source, re.S)
    assert folder, "folder element not found"
    assert "ondragenter={dragEntered}" in folder.group(1)
    assert "ondragleave={dragLeft}" in folder.group(1)
    assert "dragDepth += 1" in _body(source, "function dragEntered() {")
    left = _body(source, "function dragLeft() {")
    assert "dragDepth = Math.max(0, dragDepth - 1)" in left
    assert "if (!dragDepth) dropTarget = false" in left
    assert "relatedTarget" not in source
    # Let go, the count starts over: the next drag finds a dark folder.
    drop = _body(source, "async function dropped(event) {")
    assert "dragDepth = 0" in drop and "dropTarget = false" in drop


def test_the_folder_lights_up_only_for_a_drag_it_takes():
    """Files — the dock has no count of places any more. Text and the
    folder's own tiles are let go here without anything happening, so they
    leave it dark."""
    source = _source()
    assert _body(source, "function takes(event) {").strip() == (
        "return Boolean(event.dataTransfer?.types?.includes('Files'))"
    )
    assert "ondragover={(e) => { e.preventDefault(); dropTarget = takes(e) }}" in source
    # A tile of the folder is dragged with a kind of its own and no file.
    assert "'application/x-exe-docfolder'" in _body(source, "function dragStart(event, file) {")
    assert "dropTarget = true" not in source


# --- The head and the tiles --------------------------------------------------


def test_eine_zeile_mit_auswahl_und_drei_knoepfen_ohne_etikett_pfad_und_zahl():
    """The head is one row: the project chooser with the house arrow, then
    open, move and add for the folder — no label, no path, no count — and
    under it the heading over the files."""
    quelle = (FRONTEND / "src/teile/DocFolder.svelte").read_text(encoding="utf-8")
    zeile = quelle[quelle.index('<div class="ordnerzeile">') : quelle.index('<div class="abschnitt">')]
    assert 'class="projektknopf"' in zeile
    assert 'zeichen="pfeil_unten"' in zeile
    assert "<Speicherortzeile" in zeile
    assert "showPath={false}" in zeile
    assert "onadd=" in zeile
    assert "etikett=" not in quelle
    # No count anywhere in the head or over the wall.
    assert "files.length}" not in quelle.replace("{#if files.length}", "")
    assert "{t('docfolder.dateien')}</div>" in quelle

    reihe = (FRONTEND / "src/teile/Speicherortzeile.svelte").read_text(encoding="utf-8")
    assert '{#if showPath}<span class="pfad"' in reihe
    assert "showPath = true" in reihe


def test_der_dateianfang_liest_nur_die_verlangten_bytes():
    """fileStart() asks for the range, stops reading once it has enough even
    where the server sends everything, and leaves a character the cut went
    through out of the text. Schweigeprobe: an empty file (the server answers
    a range on it with 416) is '' and a failed answer is null — the tile then shows the page sign, not an empty paper."""
    kennung = os.getpid()
    treiber = FRONTEND / f"anfang-{kennung}.pruefung.mjs"
    treiber.write_text(
        """
let gelesen = 0, abgebrochen = false, bereich = null
const text = 'abc' + 'ä'.repeat(4000)
const voll = new TextEncoder().encode(text)
globalThis.fetch = async (adresse, optionen) => {
  if (adresse === 'leer') return new Response('', { status: 416 })
  if (adresse === 'fehlt') return new Response('nein', { status: 404 })
  bereich = optionen?.headers?.Range ?? null
  let stelle = 0
  const strom = new ReadableStream({
    pull(steuer) {
      if (stelle >= voll.length) return steuer.close()
      const stueck = voll.subarray(stelle, stelle + 64)
      stelle += stueck.length
      gelesen += stueck.length
      steuer.enqueue(stueck)
    },
    cancel() { abgebrochen = true },
  }, { highWaterMark: 0 })
  return new Response(strom)
}
const { fileStart } = await import('./src/lib/fileStart.js')
const anfang = await fileStart('a', 'datei', 10)
const leer = await fileStart('b', 'leer', 10)
const fehlt = await fileStart('c', 'fehlt', 10)
console.log('---BERICHT---' + JSON.stringify({ anfang, bereich, gelesen, abgebrochen, leer, fehlt }))
process.exit(0)
""",
        encoding="utf-8",
    )
    try:
        lauf = subprocess.run(["node", treiber.name], cwd=FRONTEND, capture_output=True, text=True, encoding="utf-8", timeout=60)
    finally:
        treiber.unlink(missing_ok=True)
    assert lauf.returncode == 0, (lauf.stdout + lauf.stderr)[-3000:]
    bericht = json.loads(lauf.stdout.split("---BERICHT---", 1)[1].strip())
    # Ten bytes are 'abc' and three and a half 'ä': the half is left out.
    assert bericht["anfang"] == "abcäää"
    assert bericht["bereich"] == "bytes=0-9"
    assert bericht["abgebrochen"] is True
    assert bericht["gelesen"] < 400
    assert bericht["leer"] == ""
    assert bericht["fehlt"] is None


# --- What a tool wrote below the chat's folder -------------------------------


def test_the_cross_stands_on_a_dock_file_only():
    """A chat's document carries no cross, and neither does a file a tool
    wrote below the chat's folder: the cross takes a file off the dock, the
    one place removing has a route for. Silence probe: a dock file keeps
    it, and removing still knows that one route."""
    source = _source()
    condition = source.split('class="weg"', 1)[0].rsplit("{#if ", 1)[1].split("}", 1)[0]
    assert condition == "file.source === 'agent'"
    assert "await api.agentendockEntfernen(file.id)" in _body(source, "async function remove(file) {")


def test_the_wall_is_asked_again_while_the_open_chats_answer_runs():
    """A tool of the chat's own answer writes into the chat's folder, and no
    announcement says so: the wall asks every few seconds while that answer
    runs, as it does while a job runs, and once more when it is over.
    Silence probe: without a run it asks nothing on a clock."""
    source = _source()
    assert "const answering = $derived(Boolean(laufVon(chat)))" in source
    assert "answering || zustand.auftraege.some(" in source
    clock = source.split("const clock = setInterval(", 1)[0].rsplit("$effect(() => {", 1)[1]
    assert "if (!running) return" in clock
    # Only where the answer ended in the chat still open: a chat left in
    # mid-answer asks through its own change, and a second, quiet ask
    # beside it could leave the wall on the chat that was left.
    assert "const now = answering ? chat : ''" in source
    assert "if (answeredIn && answeredIn === chat && !now) untrack(() => load(true))" in source
