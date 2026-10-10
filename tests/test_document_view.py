"""A document opened from the chat: the sheet over the window, the PDF in the
browser's own viewer, and the card in an answer.

The page that opens over the window filled the window's height whatever it
held, and showed Markdown as its source. A PDF could only be read as the
text taken out of it; nobody saw its pages. And a file a tool handed into
the chat hung on the answer in the service but had no card in the bubble.

What can run is RUN, in node: the tab store, the catalogue of file kinds,
and the few lines that decide which card gets a file's address. The file
route is asked through the service. What only exists as a component is read.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tests.conftest import pdf_mit_seiten
from tests.test_dokumentkarte import _catalogue, _markup, _rule, _tabs
from tests.test_hintergrundmeldung import _node

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend/src"
API = SOURCE / "lib/api.js"
READER_STORE = SOURCE / "lib/bildschau.svelte.js"
READER = SOURCE / "teile/Bildschau.svelte"
CARD = SOURCE / "teile/Dateikarte.svelte"
RAIL = SOURCE / "teile/ModulVorschau.svelte"
FRAME = SOURCE / "teile/PdfFrame.svelte"
MESSAGE = SOURCE / "teile/Nachricht.svelte"
APP = SOURCE / "App.svelte"
SHELL = ROOT / "fenster-electron/main.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")


def _script(path: Path) -> str:
    """A component's script, without its markup and its stylesheet."""
    return path.read_text(encoding="utf-8").split("</script>", 1)[0]


def _upload(client, name: str, data: bytes) -> dict:
    chat = client.post("/api/v1/chats", json={"title": "Papers"}).json()
    answer = client.post(f"/api/v1/documents?chat_id={chat['id']}&name={name}", content=data)
    assert answer.status_code == 201, answer.text
    return answer.json()["dokument"]


# --- The file route ---------------------------------------------------------


def test_the_file_route_says_show_for_a_pdf_and_keeps_its_name(client):
    """A frame stays empty for a file the service tells the browser to save.
    A PDF is told to be shown, and still carries the name it is saved under."""
    meta = _upload(client, "offer.pdf", pdf_mit_seiten(["One page"]))
    answer = client.get(f"/api/v1/documents/{meta['id']}/file")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("application/pdf")
    assert answer.headers["content-disposition"] == 'inline; filename="offer.pdf"'
    assert answer.content.startswith(b"%PDF-")


@pytest.mark.parametrize("name", ["notes.md", "notes.txt", "page.html", "table.csv"])
def test_every_other_type_is_still_saved_and_never_shown(client, name):
    """The silence check: only the one type the window frames is shown in
    place. A text document — a page of markup among them — keeps being
    handed out as a file to save."""
    meta = _upload(client, name, b"<h1>Just text</h1>")
    answer = client.get(f"/api/v1/documents/{meta['id']}/file")
    assert answer.status_code == 200
    assert answer.headers["content-disposition"] == f'attachment; filename="{name}"'
    assert not answer.headers["content-type"].startswith("text/html")


# --- The address of the file ------------------------------------------------


@needs_node
def test_the_address_of_a_documents_file_is_its_file_route_with_the_key():
    """One helper names the address, for the frame and for the link that
    saves: neither can send a header, so the key travels in the address."""
    source = API.read_text(encoding="utf-8")
    found = re.search(r"^  (documentFileAddress: .+),$", source, flags=re.M)
    assert found, "api.js names no address for a document's file"
    script = (
        "const BASIS = '/api/v1'; const mitSchluessel = (url) => 'keyed:' + url;\n"
        f"const api = {{ {found.group(1)} }};\n"
        "console.log(JSON.stringify([api.documentFileAddress('x'), api.documentFileAddress('a/b c')]))"
    )
    assert json.loads(_node(script)) == [
        "keyed:/api/v1/documents/x/file",
        "keyed:/api/v1/documents/a%2Fb%20c/file",
    ]


@needs_node
def test_the_message_decides_per_card_what_is_framed_and_what_has_an_address():
    """Only a PDF is framed. An attachment that is text keeps being read as
    the text taken out of it, so it gets no address; a file handed into the
    chat always gets its own, because its text and its save are the file."""
    source = _script(MESSAGE)
    lines = re.search(r"^  const isPdf = .+\n  const fileAddressOf = .+$", source, flags=re.M)
    assert lines, "the message no longer decides which card is framed"
    script = (
        "const api = { documentFileAddress: (id) => `/file/${id}` };\n"
        f"{lines.group(0)}\n"
        "const cards = [{id: '1', typ: 'pdf'}, {id: '2', typ: 'PDF'}, {id: '3', typ: 'md'}, {typ: 'pdf'}, {id: '5'}];\n"
        "console.log(JSON.stringify([cards.map(isPdf), cards.map(fileAddressOf)]))"
    )
    assert json.loads(_node(script)) == [
        [True, True, False, True, False],
        ["/file/1", "/file/2", "/file/3", None, "/file/5"],
    ]
    own, answer = _markup(MESSAGE).split("\n{:else}\n", 1)
    own_card = own.split("{#each dokumentKarten as karte", 1)[1].split("/>", 1)[0]
    assert "fileAddress={isPdf(karte) ? fileAddressOf(karte) : null}" in own_card
    assert "framed={isPdf(karte)}" in own_card
    assert "chatId={isPdf(karte) ? chatId : null}" in own_card, "a text attachment files itself into the rail"
    assert "ladeInhalt={karte.id ? () => dokumentLesen(karte) : null}" in own_card
    answer_card = answer.split("{#each dokumentKarten as karte", 1)[1].split("/>", 1)[0]
    assert "fileAddress={fileAddressOf(karte)}" in answer_card and "framed={isPdf(karte)}" in answer_card


@needs_node
def test_a_file_handed_into_the_chat_is_read_from_the_file_itself():
    """The defect behind an empty sheet: the row of a delivered file holds no
    extracted text, so its card reads the file. What reads as UTF-8 comes
    back as text, whatever type its name was given — a picture's bytes come
    back as nothing, and the reader shows its page sign. An attachment keeps
    the text taken out of it. Each is fetched once."""
    helper = re.search(r"^  documentFileText: async \(id\) => \{\n(?:.*\n)*?  \},$", API.read_text(encoding="utf-8"), flags=re.M)
    assert helper, "api.js no longer reads a document's file as text"
    reading = re.search(
        r"^  const dokumentSpeicher = new Map\(\)\n(?:.*\n)*?  \}\n", _script(MESSAGE), flags=re.M
    )
    assert reading, "the message no longer fetches a document's text"
    script = (
        "const asked = [];\n"
        "const png = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0xff, 0xd8]);\n"
        "const rufRoh = async (path) => { asked.push(path); const id = path.split('/')[2];\n"
        "  const bytes = id === 'shot' ? png : new TextEncoder().encode(`file of ${id} — äöü`);\n"
        "  return { arrayBuffer: async () => bytes.buffer } };\n"
        f"const fromFile = {{ {helper.group(0).strip().rstrip(',')} }};\n"
        "const api = { ...fromFile, dokumentLesen: async (id) => { asked.push(`text:${id}`); return {text: `taken out of ${id}`} } };\n"
        f"{reading.group(0)}\n"
        "(async () => { const read = [];\n"
        "  for (const id of ['note', 'yaml', 'shot', 'note']) read.push(await dokumentLesen({id}, true));\n"
        "  read.push(await dokumentLesen({id: 'own'}));\n"
        "  console.log(JSON.stringify([read, asked])) })()"
    )
    read, asked = json.loads(_node(script))
    assert read == ["file of note — äöü", "file of yaml — äöü", None, "file of note — äöü", "taken out of own"]
    assert asked == ["/documents/note/file", "/documents/yaml/file", "/documents/shot/file", "text:own"]


def _function(source: str, name: str) -> str:
    """One function of a component's script, as it stands."""
    found = re.search(rf"^  function {name}\(\w*\) \{{\n(?:.*\n)*?  \}}\n", source, flags=re.M)
    assert found, f"no function {name}"
    return found.group(0)


def _card_lines(language: str, cards: str) -> list:
    """The message's own line builders, run over the real catalogue."""
    texts = json.loads((ROOT / f"app/locales/{language}.json").read_text(encoding="utf-8"))["nachricht"]
    source = _script(MESSAGE)
    script = (
        f"const texts = {json.dumps(texts)};\n"
        "const t = (key, values = {}) => texts[key.split('.')[1]].replace('{zahl}', values.zahl);\n"
        + "".join(_function(source, name) for name in ("pageCount", "fileFacts", "faktenZeile", "getragen"))
        + f"console.log(JSON.stringify({cards}.map((card) => "
        "[faktenZeile(card), fileFacts(card), getragen(card)?.hinweis ?? null])))"
    )
    return json.loads(_node(script))


@needs_node
def test_the_line_of_an_uploaded_file_is_kind_size_and_pages():
    """As drawn: "PDF · 1 KB · 1 Seite" — kind, then size, then pages, one
    page in the singular. That the whole document reached the model is the
    ordinary case and stands under the pointer, not in the line; the tab of
    the file gets the same three facts."""
    one, many, plain = _card_lines(
        "de",
        "[{typ: 'pdf', kb: 1, seiten: 1, getragen: 'ganz'}, {typ: 'pdf', kb: 140, seiten: 3, getragen: 'ganz'},"
        " {typ: 'md', kb: 1}]",
    )
    assert one[:2] == ["PDF · 1 KB · 1 Seite", "PDF · 1 KB · 1 Seite"]
    assert one[2] == "Vollständig im Kontext\nDas ganze Dokument liegt im Kontextfenster des Modells."
    assert many[:2] == ["PDF · 140 KB · 3 Seiten", "PDF · 140 KB · 3 Seiten"]
    assert plain == ["MD · 1 KB", "MD · 1 KB", None]
    assert _card_lines("en", "[{typ: 'pdf', kb: 1, seiten: 1}, {typ: 'pdf', kb: 9, seiten: 2}]") == [
        ["PDF · 1 KB · 1 page", "PDF · 1 KB · 1 page", None],
        ["PDF · 9 KB · 2 pages", "PDF · 9 KB · 2 pages", None],
    ]


@needs_node
def test_a_document_that_did_not_reach_the_model_says_so_in_its_line():
    """The silence check for the line: the card is the one place that says a
    document was too large, so that word stays where it is read without a
    pointer — and it is no fact of the file, so the tab does not carry it."""
    for carried in ("kein_platz", "abgelehnt"):
        line, facts, hint = _card_lines("de", f"[{{typ: 'pdf', kb: 2400, seiten: 300, getragen: '{carried}'}}]")[0]
        assert line == "PDF · 2400 KB · 300 Seiten · Dokument zu groß", carried
        assert facts == "PDF · 2400 KB · 300 Seiten" and hint is None, carried


@needs_node
def test_a_tab_holds_where_its_file_lies_and_keeps_it_while_the_file_grows():
    """A tab opened for a file carries the file's path; what is written on
    into it keeps the path. A card that files a tab hands the path over as
    well. Without one the field is empty — the silence check."""
    tabs = _tabs(
        "tabOeffnen('chat-1', {name: 'notes.md', art: 'md', inhalt: '# A', pfad: '/work/notes.md'});"
        "followTab('chat-1', {name: 'notes.md', art: 'md', inhalt: '# A\\nmore'});"
        "tabOeffnen('chat-1', {name: 'page.html', art: 'html', inhalt: '<p>x</p>'});"
        "tabEinsortieren('chat-1', {name: 'tips.md', art: 'md', inhalt: '# T', pfad: '/work/tips.md'});"
        "tabEinsortieren('chat-1', {name: 'offer.pdf', art: 'pdf', inhalt: '', pfad: '/work/offer.pdf',"
        " adresse: '/file/1', fakten: 'PDF · 1 KB'});"
        "console.log(JSON.stringify(tabsVon('chat-1').map((tab) => [tab.name, tab.pfad, tab.inhalt.length])))"
    )
    assert tabs == [
        ["notes.md", "/work/notes.md", 8],
        ["page.html", "", 8],
        ["tips.md", "/work/tips.md", 3],
        ["offer.pdf", "/work/offer.pdf", 0],
    ]
    card = _script(CARD)
    assert "tabEinsortieren(chatId, { name, art: sprache, inhalt: text, pfad: filePath })" in card
    framed = card.split("function fileFramed() {", 1)[1].split("\n  }\n", 1)[0]
    assert "pfad: filePath, adresse: fileAddress, fakten: fileFacts," in framed
    own, answer = _markup(MESSAGE).split("\n{:else}\n", 1)
    for branch in (own, answer):
        card_markup = branch.split("{#each dokumentKarten as karte", 1)[1].split("/>", 1)[0]
        assert "filePath={karte.pfad || ''}" in card_markup


def test_the_field_of_the_rail_shows_the_path_or_else_the_name():
    """The name stands in the tab already; the field says where the file
    lies, cut at its end where it does not fit and whole under the pointer.
    A file with no place on disk shows its name, and no empty tooltip."""
    row = _markup(RAIL).split('<div class="adresse">', 1)[1].split("</div>", 1)[0]
    assert '<span class="adresse-name" title={offen?.pfad || null}>{offen?.pfad || offen?.name}</span>' in row
    assert '<span class="fakten">{fakten}</span>' in row, "kind and size left the field"
    field = _rule(RAIL, ".adresse-name")
    for declaration in ("white-space: nowrap;", "overflow: hidden;", "text-overflow: ellipsis;", "min-width: 0;"):
        assert declaration in field, f"the path is not cut at its end: {declaration}"


# --- The card ---------------------------------------------------------------


def test_a_framed_card_opens_the_file_in_a_frame_and_holds_no_text():
    """The card's click hands the reader the address, marked as framed, and
    files the tab with the address — before the branch that loads a text,
    and without touching it."""
    source = _script(CARD)
    opening = source.split("function oeffnen() {", 1)[1].split("\n  }\n", 1)[0]
    framed, text = opening.split("showPage({\n", 1)
    assert "if (framed && fileAddress) {" in framed
    assert "showPage({ name, adresse: fileAddress, framed: true })" in framed
    assert "fileFramed()" in framed and "return" in framed
    # Nothing of the framed way asks for the text, and the text way is whole.
    assert "inhaltHolen" not in framed and "loadText" not in framed
    assert "loadText: async () => {" in text
    # A card that stands for a stored file saves that file; one that only
    # holds a text saves the text.
    assert "adresse: fileAddress || ''," in text
    assert "download: fileAddress ? null : () => herunterladenText()," in text
    filing = source.split("function fileFramed() {", 1)[1].split("\n  }\n", 1)[0]
    assert "if (!chatId || chatId !== zustand.aktiverChat) return" in filing
    assert "name, art: 'pdf', inhalt: ''," in filing
    assert "adresse: fileAddress, fakten: fileFacts," in filing


@needs_node
def test_a_framed_tab_carries_its_address_and_a_text_tab_none():
    """The tab of a PDF holds where the file is fetched from and its line of
    facts; a written file's tab is exactly what it was."""
    tabs = _tabs(
        "tabEinsortieren('chat-1', {name: 'offer.pdf', art: 'pdf', inhalt: '',"
        " adresse: '/file/1', fakten: 'PDF · 140 KB'});"
        "tabEinsortieren('chat-1', {name: 'notes.md', art: 'md', inhalt: '# Notes'});"
        "tabEinsortieren('chat-1', {name: 'offer.pdf', art: 'pdf', inhalt: '', adresse: '/file/2', fakten: ''});"
        "console.log(JSON.stringify(tabsVon('chat-1')))"
    )
    assert [tab["name"] for tab in tabs] == ["offer.pdf", "notes.md"], "the same file was filed twice"
    assert tabs[0]["adresse"] == "/file/1" and tabs[0]["fakten"] == "PDF · 140 KB"
    assert sorted(tabs[1]) == ["art", "id", "inhalt", "name", "pfad"]


# --- The rail beside the chat -----------------------------------------------


@needs_node
def test_the_rail_shows_a_framed_tab_in_a_frame_without_a_source_switch():
    """A tab with an address is drawn by the browser's viewer: the frame of a
    PDF on the address, first on the stage. That frame is not sandboxed — a
    sandboxed frame may not load the viewer. A PDF is no kind of the
    catalogue, so it has no second view and the source switch is not drawn."""
    script = _script(RAIL)
    assert "const isFramed = $derived(Boolean(offen?.adresse))" in script
    stage = _markup(RAIL).split('<div class="buehne">', 1)[1]
    first = stage.split("{:else", 1)[0]
    assert "{#if isFramed}" in first, "the frame is not the first thing the stage decides"
    assert "<PdfFrame address={offen.adresse} title={offen.name} />" in first, "a framed tab has no frame"
    frame = re.search(r"<iframe[^>]*>", _markup(FRAME))
    assert frame and "sandbox" not in frame.group(0)
    # The sandbox of the frame that draws the model's own page is untouched.
    assert 'sandbox="allow-scripts"' in stage.split("{:else", 1)[1]
    assert "{#if hasTwoViews}" in _markup(RAIL)
    assert "isFramed" not in script.split("const hasTwoViews = $derived(", 1)[1].split(")", 1)[0]
    assert json.loads(_node(f"{_catalogue()}\nconsole.log(JSON.stringify(dateiart('pdf')))")) is None


@needs_node
def test_saving_a_framed_tab_saves_the_file_itself():
    """Not the text: the file's address, under the file's name — through the
    one link every save in the window clicks, the reader's included."""
    saving = _script(RAIL).split("function herunterladen() {", 1)[1].split("\n  }\n", 1)[0]
    framed, text = saving.split("dateiHerunterladen(", 1)
    assert "if (isFramed) {" in framed
    assert "return" in framed.split("saveFromAddress(offen.name, offen.adresse)", 1)[1]
    assert text.startswith("offen.name, offen.inhalt, eintrag?.typ)")
    assert "saveFromAddress(bildschau.name, bildschau.adresse)" in _script(READER)
    for component in (RAIL, READER):
        assert "createElement('a')" not in _script(component), f"{component.name} builds a save link of its own"
    script = (
        "const clicked = [];\n"
        "const document = { createElement: () => ({ click() { clicked.push([this.href, this.download]) } }) };\n"
        "class Blob {}; const URL = { createObjectURL: () => 'blob:1', revokeObjectURL: () => {} };\n"
        f"{_catalogue()}\n"
        "saveFromAddress('offer.pdf', '/file/1'); dateiHerunterladen('notes.md', '# Notes', 'text/markdown');\n"
        "console.log(JSON.stringify(clicked))"
    )
    assert json.loads(_node(script)) == [["/file/1", "offer.pdf"], ["blob:1", "notes.md"]]


# --- The viewer inside the frame --------------------------------------------

# No bar of the viewer's own, no strip of small pages, the page fitted to the width.
VIEWER_SWITCHES = "#toolbar=0&navpanes=0&view=FitH"


@needs_node
def test_the_frame_of_a_pdf_asks_the_viewer_for_no_bar_and_the_width():
    """The viewer draws a bar of its own over the pages unless the address of
    the frame says otherwise. The rail and the reader show a PDF through one
    frame, and that frame points at the file's address with the three
    switches behind the hash — and at nothing while it has no address. The
    expression is the component's own, run."""
    found = re.search(r"const frameAddress = \$derived\(\s*(.+?),?\s*\)$", _script(FRAME), flags=re.M | re.S)
    assert found, "the frame names no address for the viewer"
    values = [
        json.loads(_node(f"const address = {given}; console.log(JSON.stringify({found.group(1)}))"))
        for given in ("'/file/1?schluessel=k'", "''", "undefined")
    ]
    assert values == [f"/file/1?schluessel=k{VIEWER_SWITCHES}", "", ""]
    frames = re.findall(r"<iframe[^>]*>", _markup(FRAME))
    assert len(frames) == 1 and "src={frameAddress}" in frames[0], frames
    assert "<PdfFrame address={offen.adresse} title={offen.name} />" in _markup(RAIL)
    assert "<PdfFrame address={bildschau.adresse} title={bildschau.name} />" in _markup(READER)
    for component in (RAIL, READER):
        assert "import PdfFrame from './PdfFrame.svelte'" in _script(component), component.name


def test_only_the_frame_carries_the_switches():
    """Silence probe. The address every save goes by stays plain — the helper
    in api.js, the rail's save and the reader's — the switches stand once,
    in the frame, and the frame that draws the model's own page has no
    address at all: it keeps its `srcdoc` and its sandbox."""
    assert "toolbar" not in API.read_text(encoding="utf-8")
    for component in (RAIL, READER):
        assert "toolbar" not in component.read_text(encoding="utf-8"), component.name
    assert FRAME.read_text(encoding="utf-8").count(VIEWER_SWITCHES) == 1
    assert "saveFromAddress(offen.name, offen.adresse)" in _script(RAIL)
    assert "saveFromAddress(bildschau.name, bildschau.adresse)" in _script(READER)
    frames = re.findall(r"<iframe[^>]*>", _markup(RAIL))
    assert len(frames) == 1, "the rail draws the model's page in one frame of its own"
    assert "srcdoc={mitSchutzregel(offen.inhalt)}" in frames[0] and 'sandbox="allow-scripts"' in frames[0]
    assert " src=" not in frames[0] and "viewer" not in frames[0]


def test_the_sheet_of_a_pdf_keeps_the_corners_of_what_holds_it():
    """The viewer lays a dark rim around the sheet it draws, and the rounding
    of the page cut that rim instead of the sheet. The frame overhangs what
    holds it by a share of the width — the same on both sides, less above —
    and one layer cuts it at the holder's own rounding. Both holders are
    positioned and carry the house's radius."""
    cut = _rule(FRAME, ".cut")
    for line in (
        "position: absolute;", "inset: 0;", "overflow: hidden;", "border-radius: inherit;",
        "container-type: inline-size;",
    ):
        assert line in cut, line
    frame = _rule(FRAME, "iframe")
    # Measured: the rim of a sheet of A4 fitted to the width, beside it and above it.
    for line in (
        "position: absolute;", "left: -0.63cqw;", "width: calc(100% + 1.26cqw);",
        "top: -0.45cqw;", "height: calc(100% + 0.45cqw);", "border: none;",
    ):
        assert line in frame, line
    assert '<div class="cut">' in _markup(FRAME)
    assert '<div class="seite rahmen viewer">' in _markup(RAIL)
    for path, selector, page in ((RAIL, ".viewer", ".seite"), (READER, ".page.framed", ".page")):
        assert "position: relative;" in _rule(path, selector), path.name
        assert "border-radius: 9px;" in _rule(path, page), path.name


# --- The sheet over the window ----------------------------------------------


def test_the_reader_draws_a_framed_page_in_a_frame_and_markdown_rendered():
    """The reader takes `framed` only together with an address, and forgets
    it when it closes. A framed page is a frame on the sheet; Markdown goes
    through the renderer the rail uses; a source file keeps its numbered
    lines and everything else stays prose."""
    store = READER_STORE.read_text(encoding="utf-8")
    assert "framed: Boolean(file.framed && file.adresse)," in store
    assert store.count("framed: false,") == 2, "the reader's state and its reset name `framed` once each"
    markup = _markup(READER)
    assert '{:else if bildschau.framed}' in markup
    framed = markup.split("{:else if bildschau.framed}", 1)[1].split("{:else}", 1)[0]
    assert '<div class="page framed">' in framed
    assert "<PdfFrame address={bildschau.adresse} title={bildschau.name} />" in framed
    order = [
        markup.index("{:else if text != null && isSource}"),
        markup.index("{:else if text != null && isMarkdown}"),
        markup.index("{:else if text != null}"),
    ]
    assert order == sorted(order)
    rendered = markup[order[1] : order[2]]
    assert "{#each dateiTeile(text) as piece" in rendered and "{@html piece.wert}" in rendered
    script = _script(READER)
    assert "const MARKDOWN = new Set(['md', 'markdown'])" in script
    assert "const isSource = $derived(Boolean(dateiart(bildschau.language)) && !isMarkdown)" in script


def test_the_sheet_has_the_shape_of_a_sheet_of_paper():
    """210 to 297, in a tall window and in a flat one: the height is what the
    width of 760 asks for or what the window leaves, whichever is less, and
    the width follows from it. The sheet no longer stretches to the window,
    and its text still scrolls in it."""
    sheet = _rule(READER, ".page")
    assert "aspect-ratio: 210 / 297;" in sheet
    assert "height: min(var(--room), calc(min(760px, 100vw - 48px) * 297 / 210));" in sheet
    assert "--room: calc(100vh - 64px - 24px - 12px - 18px);" in sheet
    assert "flex: none;" in sheet and "flex: 1;" not in sheet
    assert not re.search(r"^\s*width:", sheet, flags=re.M), "a fixed width beside the ratio bends the sheet"
    assert "overflow-y: auto;" in sheet and "border-radius: 9px;" in sheet
    framed = _rule(READER, ".page.framed")
    assert "padding: 0;" in framed and "border: none;" in framed


# --- The card in an answer --------------------------------------------------


def test_an_answer_draws_the_card_of_every_document_it_carries():
    """The defect: only the user's own message drew document cards. The
    answer draws the same card, in the row that wraps, for what the message
    carries — and nothing where it carries none."""
    markup = _markup(MESSAGE)
    own, answer = markup.split("\n{:else}\n", 1)
    loop = "{#each dokumentKarten as karte (karte.id || karte.name)}"
    assert own.count(loop) == 1 and answer.count(loop) == 1
    before, after = answer.split(loop, 1)
    assert before.rstrip().endswith('<div class="file-row">')
    assert "{#if dokumentKarten.length}" in before[before.rindex("{#if") :], "the row is drawn for no document"
    card = after.split("/>", 1)[0]
    assert "<Dateikarte" in card and "zeichenHtml={DOK_ZEICHEN}" in card
    assert "fakten={faktenZeile(karte)}" in card and "fileFacts={fileFacts(karte)}" in card
    assert "{chatId}" in card, "a file of the answer does not reach the rail"
    assert "ladeInhalt={karte.id ? () => dokumentLesen(karte, true) : null}" in card
    # One list for both branches: the message's documents, the list before the single one.
    assert "nachricht.dokumente?.length ? nachricht.dokumente : dokument ? [dokument] : []," in _script(MESSAGE)


@needs_node
def test_a_running_answer_takes_its_documents_from_the_tool_result():
    """The card stands in the bubble without the chat being fetched again:
    the event carries the answer's documents, and the page stores them in the
    shape a stored answer has — one as `dokument`, several as `dokumente`.
    An event without documents leaves what the answer holds alone."""
    source = APP.read_text(encoding="utf-8")
    found = re.search(r"if \(Array\.isArray\(ereignis\.dokumente\)\) \{\n(?:.*\n){2}\s*\}", source)
    assert found, "the page no longer reads the documents of a tool result"
    script = (
        "const take = (ereignis, platzhalter) => {\n"
        f"{found.group(0)}\n"
        "return platzhalter }\n"
        "const a = {id: 'a'}, b = {id: 'b'};\n"
        "console.log(JSON.stringify(["
        "take({dokumente: [a]}, {}), take({dokumente: [a, b]}, {dokument: a}),"
        "take({}, {dokument: a}), take({dokumente: []}, {dokument: a})]))"
    )
    assert json.loads(_node(script)) == [
        {"dokument": {"id": "a"}, "dokumente": None},
        {"dokument": None, "dokumente": [{"id": "a"}, {"id": "b"}]},
        {"dokument": {"id": "a"}},
        {"dokument": None, "dokumente": None},
    ]


# --- The shell --------------------------------------------------------------


def test_the_main_window_of_the_shell_loads_the_viewer_and_no_other_window_does():
    """The viewer that draws a PDF is a built-in plugin, off unless a window
    asks for it. The main window asks; nothing else about its preferences
    changes, and no second window gets the switch."""
    source = SHELL.read_text(encoding="utf-8")
    window = source.split("fenster = new BrowserWindow({", 1)[1].split("fenster.loadFile(", 1)[0]
    preferences = window.split("webPreferences: {", 1)[1]
    preferences = re.sub(r"/\*.*?\*/", "", preferences, flags=re.S)
    settings = [line.strip() for line in preferences.split("},", 1)[0].splitlines() if line.strip()]
    assert settings == [
        "contextIsolation: true,",
        "nodeIntegration: false,",
        "preload: path.join(__dirname, 'preload.js'),",
        "plugins: true,",
    ]
    assert len(re.findall(r"^\s*plugins:", source, flags=re.M)) == 1
