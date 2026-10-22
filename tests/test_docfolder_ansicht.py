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
    for language, words in (("de", ["Nutzer", "Agent", "Cronjob"]), ("en", ["User", "Agent", "Cronjob"])):
        catalogue = json.loads((WURZEL / f"app/locales/{language}.json").read_text(encoding="utf-8"))
        folder = catalogue["docfolder"]
        assert [folder["origin_user"], folder["origin_agent"], folder["origin_cronjob"]] == words
        # The folder is called the same wherever its files are named.
        assert catalogue["werkzeuge"]["quelle_dock"] == {"de": "Doc-Ordner", "en": "Doc folder"}[language]


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


def _folder_file_matches(addresses: list[str]) -> list[bool]:
    """The window's own expression, run by node on the addresses."""
    bar = _source("Eingabeleiste.svelte")
    pattern = re.search(r"const FOLDER_FILE =\s*/(.+)/\n", bar)
    assert pattern, "FOLDER_FILE not found"
    script = (
        f"const r = new RegExp({json.dumps(pattern.group(1))});"
        f"console.log(JSON.stringify({json.dumps(addresses)}.map((a) => r.test(a))))"
    )
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_a_folder_address_is_one_of_the_three_routes():
    """What the input bar takes as a file of the folder: a file of the dock,
    a document of a chat or a loose file of a chat's folder, at any depth.
    Schweigeprobe: the old dock's address, the listing beside the files and
    every address that climbs out of the chat's folder are none."""
    taken = [
        "/agentendock/3f2a-1",
        "/documents/3f2a-1/file",
        "/chat-files/3f2a-1/bericht.md",
        "/chat-files/3f2a-1/unter/ordner/tabelle.csv",
        "/chat-files/3f2a-1/Mein%20Bericht%20%C3%BC.md",
        "/chat-files/3f2a-1/...",
        # A backslash in a name is written %5C by the service: a legit name.
        "/chat-files/3f2a-1/a%5Cb.md",
        "/chat-files/3f2a-1/50%252Fprozent.md",
    ]
    refused = [
        "/notizen/dock/3f2a-1",
        "/agentendock/alle",
        "/chat-files/3f2a-1/../geheim",
        "/chat-files/3f2a-1/%2e%2e/geheim",
        "/chat-files/3f2a-1/.%2E/geheim",
        "/chat-files/3f2a-1/a/./b",
        "/chat-files/3f2a-1/a%2F..%2Fb",
        "/chat-files/3f2a-1/x/a%2fb.md",
        "/chat-files/3f2a-1/",
        "/chat-files//x",
        "/chat-files/3f2a-1/a?b=1",
        "/chat-files/3f2a-1/a#b",
        "//fremd.example/chat-files/1/a",
        "https://fremd.example/chat-files/1/a",
    ]
    got = _folder_file_matches(taken + refused)
    assert got[: len(taken)] == [True] * len(taken)
    assert got[len(taken) :] == [False] * len(refused)


def test_dropped_files_take_the_one_way_in():
    """A drop hands its files to `add`, which puts them in one after the
    other — the open chat named, so a file of a chat lies in that chat's
    folder — tells of a refused file and goes on, and asks for the wall
    once at the end. There is no second way in: the row has no button for
    picking files."""
    source = _source()
    add = _body(source, "async function add(list) {")
    loop = add[add.index("for (const file of list) {") : add.index("await load()")]
    assert "await api.docFolderAdd(file, into)" in loop
    # Where they go is read once, before the first file is on its way.
    assert add.index("const into = chat") < add.index("for (const file of list) {")
    assert "melde(error.message, 'fehler')" in loop and "return" not in add
    assert add.count("await load()") == 1
    assert "async function picked(" not in source and "filePicker" not in source
    assert 'type="file"' not in source
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


def test_the_doc_folder_wears_the_galleries_folder_row_without_a_plus():
    """The defect: the gallery's folder row said its name and path and had
    open and change; the doc folder's showed the buttons alone and a plus,
    with a heading over the files. Both are the one row now — name, path,
    open, change — and the doc folder has no plus and no heading; on the
    start page the project chooser stands under the row."""
    quelle = (FRONTEND / "src/teile/DocFolder.svelte").read_text(encoding="utf-8")
    zeile = quelle[quelle.index('<div class="ordnerzeile">') : quelle.index('<div class="rollen">')]
    assert "<Speicherortzeile" in zeile
    assert "etikett={t('docfolder.ordner')}" in zeile
    # In a chat the row never shows the dock's path, not even while the
    # chat's own is still on its way.
    assert "pathText={chat ? (chatPlace ?? '') : null}" in zeile
    assert "onadd" not in quelle and "showPath" not in quelle
    assert "dateien_hinzufuegen" not in quelle and "docfolder.dateien" not in quelle
    # The chooser stands in its own row, on the start page only.
    chooser = zeile[zeile.index('<div class="chooser-row">') :]
    assert 'class="projektknopf"' in chooser and 'zeichen="pfeil_unten"' in chooser
    assert zeile.index("{#if !chat}") < zeile.index('<div class="chooser-row">')
    assert '<div class="abschnitt">' not in quelle
    # No count anywhere in the head or over the wall.
    assert "files.length}" not in quelle.replace("{:else if files.length}", "")

    reihe = (FRONTEND / "src/teile/Speicherortzeile.svelte").read_text(encoding="utf-8")
    assert '<span class="pfad" title={shownPath}><span>{shownPath}</span></span>' in reihe
    # The path is cut at its front: the box reads right to left and the path
    # itself, in the inner span, left to right. `plaintext` on the box would
    # take the direction away again and cut it at the end.
    box = reihe.split("  .pfad {", 1)[1].split("\n  }", 1)[0]
    assert "direction: rtl;" in box and "unicode-bidi" not in box
    inner = reihe.split("  .pfad span {", 1)[1].split("\n  }", 1)[0]
    assert "direction: ltr;" in inner and "unicode-bidi: bidi-override;" in inner
    assert "const shownPath = $derived(displayPath(pathText ?? pfad))" in reihe
    assert "onadd" not in reihe and "showPath" not in reihe


def test_the_gallery_row_is_unchanged_and_takes_no_files():
    """Silence probe: the gallery names its folder and shows the path as it
    did, and gives its row no way to hand files in."""
    galerie = (FRONTEND / "src/teile/ModulBilder.svelte").read_text(encoding="utf-8")
    assert "<Speicherortzeile name=\"images\" etikett={t('bilder.bildordner')} onaendern={laden} />" in galerie
    assert "pathText" not in galerie


def test_the_folder_name_is_one_text_in_both_languages():
    for sprache, wort in (("de", "Dateiordner"), ("en", "File folder")):
        katalog = json.loads((WURZEL / "app" / "locales" / f"{sprache}.json").read_text(encoding="utf-8"))
        assert katalog["docfolder"]["ordner"] == wort, sprache
        # The heading and the plus are gone with their texts.
        assert "dateien" not in katalog["docfolder"], sprache
        assert "dateien_hinzufuegen" not in katalog["speicherorte"], sprache


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
    clock = source.split("return pollWithoutOverlap(() => load(true), 3000)", 1)[0].rsplit("$effect(() => {", 1)[1]
    assert "if (!running) return" in clock
    # Only where the answer ended in the chat still open: a chat left in
    # mid-answer asks through its own change, and a second, quiet ask
    # beside it could leave the wall on the chat that was left.
    assert "const now = answering ? chat : ''" in source
    assert "if (answeredIn && answeredIn === chat && !now) untrack(() => load(true))" in source


# --- A PDF opens in the reader's frame ---------------------------------------


def _opened(files: list[dict]) -> list[list]:
    """What ``open`` hands to the reader for each file: the component's own
    text of ``isPicture``, ``isPdf`` and ``open`` run in Node, with the
    reader's two doors recorded instead of drawn."""
    source = _source()
    lifted = "\n".join(
        f"function {head}{{{_body(source, f'function {head}{{')}\n}}"
        for head in ("isPicture(file) ", "isPdf(file) ", "open(file) ")
    )
    driver = f"""
const calls = []
const api = {{ docFolderAddress: (path) => '/file/' + path }}
const originLine = () => 'origin'
const folderOf = (file) => (file.source === 'agent' ? 'agent_dock' : '')
const endingOf = (file) => (file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '')
const isText = (file) => ['md', 'txt'].includes(endingOf(file))
const previewOf = () => ''
const bigPreview = async () => ''
const CARD_PREVIEW = {{}}
const t = (key) => key
const bildZeigen = (adresse, more) => calls.push(['picture', adresse, more.name])
const showPage = (page) => calls.push(['page', page.adresse, page.framed === true, Boolean(page.loadText)])
{lifted}
for (const file of {json.dumps(files)}) open(file)
console.log('---BERICHT---')
console.log(JSON.stringify(calls))
"""
    return _run(driver)


def test_a_pdf_of_the_wall_opens_in_the_frame_like_the_card_in_a_chat():
    """A document of the chat and a file on the dock both reach the reader
    with their address and ``framed``: its pages one under the other, not
    the shell's small picture of the first page. Silence probes: a picture
    still opens in the picture reader, a text file as text, and a PDF with
    no address to fetch from is not framed."""
    chat_pdf = {"name": "plan.pdf", "type": "application/pdf", "path": "p1", "source": "document"}
    dock_pdf = {"name": "scan.pdf", "type": "application/pdf", "path": "p2", "source": "agent"}
    picture = {"name": "dog.jpg", "type": "image/jpeg", "path": "p3", "source": "document"}
    note = {"name": "notes.md", "type": "text/markdown", "path": "p4", "source": "document"}
    page = {"name": "sheet.xlsx", "type": "application/vnd.ms-excel", "path": "p5", "source": "document"}
    no_address = {"name": "lost.pdf", "type": "application/pdf", "path": "", "source": "document"}

    calls = _opened([chat_pdf, dock_pdf, picture, note, page, no_address])

    assert calls == [
        ["page", "/file/p1", True, False],
        ["page", "/file/p2", True, False],
        ["picture", "/file/p3", "dog.jpg"],
        ["page", "/file/p4", False, True],
        ["page", "/file/p5", False, False],
        ["page", "", False, False],
    ]


# --- The picture of a page is no picture to save -----------------------------


def test_the_shells_picture_of_a_page_takes_no_pointer_and_a_picture_tile_keeps_its_image():
    """A right click on the face of a PDF's tile landed on an image and the
    menu offered "save image" — what is saved is a picture of page one, not
    the file. The face takes no pointer, so the click lands on the tile.
    Silence probe: the tile of a real picture keeps its image as it was."""
    markup = _source().split("</script>", 1)[1].split("<style>", 1)[0]
    images = re.findall(r"<img [^>]*>", markup)
    face = [tag for tag in images if "previewOf(file, CARD_PREVIEW)" in tag]
    picture = [tag for tag in images if "api.docFolderAddress(file.path)" in tag]

    assert len(face) == 1 and 'class="shell"' in face[0]
    assert len(picture) == 1 and "class=" not in picture[0]
    assert "pointer-events: none;" in _declarations(".shell")
