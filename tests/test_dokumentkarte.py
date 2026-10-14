"""A document in the chat: one card from its first line, and the rail beside it.

Three things broke here, and they are checked together because they are one
path — the fence a model opens, the card that stands for it, the tab that
shows it.

While a document was being written, the answer showed its raw source in an
open code box, which collapsed into a card on the last three backticks. The
card was as wide as its bubble and looked different for a file handed in.
And the rail beside the chat stayed empty until the fence closed, showed
Markdown as its source, and wore a frame, a footer and a second row of
buttons.

The modules that can run are RUN, in node, the way
``tests/test_hintergrundmeldung.py`` runs the renderer: the real catalogue
(``lib/dateiarten.js``) under the real ``lib/markdown.js``, and the real tab
store with its two reactive imports stood in for. What only exists as a
component is read.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from tests.test_hintergrundmeldung import _modul, _node

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend/src"
CATALOGUE = SOURCE / "lib/dateiarten.js"
TABS = SOURCE / "lib/vorschautabs.svelte.js"
CARD = SOURCE / "teile/Dateikarte.svelte"
RAIL = SOURCE / "teile/ModulVorschau.svelte"
COLUMN = SOURCE / "teile/Arbeitsleiste.svelte"
MESSAGE = SOURCE / "teile/Nachricht.svelte"
APP = SOURCE / "App.svelte"
SHEET = SOURCE / "stil/global.css"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")

FILE_MARK = re.compile("\x01datei(\\d+)\x01")


def _catalogue() -> str:
    """lib/dateiarten.js as a plain script: it imports nothing, so cutting
    the word `export` is all it takes."""
    return re.sub(r"^export ", "", CATALOGUE.read_text(encoding="utf-8"), flags=re.M)


# The renderer over the REAL catalogue. Only colouring and the copy button's
# text are stood in for — neither decides what is a file.
STAND_IN = f"""
const hervorheben = (code) => String(code)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const t = () => 'Copy';
{_catalogue()}
"""


def _run(expression: str):
    """One expression over the renderer and the catalogue, back as data."""
    return json.loads(_node(f"{_modul(STAND_IN)}\nconsole.log(JSON.stringify({expression}))"))


def _tabs(script: str):
    """The real tab store, run. `$state` is a plain object outside a
    component, and the two modules it imports are a list of what was offered
    and the chat on screen."""
    store = re.sub(r"^import .*$", "", TABS.read_text(encoding="utf-8"), flags=re.M)
    store = store.replace("$state(", "(")
    store = re.sub(r"^export ", "", store, flags=re.M)
    preamble = "const offered = []; const anbieten = (what) => offered.push(what);\n"
    preamble += "const zustand = { aktiverChat: 'chat-1' };\n"
    return json.loads(_node(f"{preamble}{store}\n{script}"))


def _rule(path: Path, selector: str) -> str:
    """The body of one rule in a component's stylesheet."""
    sheet = path.read_text(encoding="utf-8").split("<style>", 1)[1]
    found = re.search(rf"^\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", sheet, flags=re.M)
    assert found, f"no rule for {selector} in {path.name}"
    return found.group(1)


def _markup(path: Path) -> str:
    """What a component draws: neither its script nor its stylesheet."""
    return path.read_text(encoding="utf-8").split("</script>", 1)[1].split("<style>", 1)[0]


# --- The fence that is still open -------------------------------------------


@needs_node
@pytest.mark.parametrize("language", ["markdown", "md"])
def test_a_document_being_written_is_a_card_from_its_first_line(language):
    """The defect: an open fence was always a code box, so forty lines of a
    document ran through the answer as source and then folded into a card."""
    text = f"Here it is:\n\n```{language}\n# Fruit\n\n- apple\n- pear"
    drawn = _run(f"rendern({json.dumps(text)})")

    assert len(FILE_MARK.findall(drawn)) == 1, drawn
    assert "codeblock" not in drawn, drawn
    # Nothing of the document shows in the answer itself.
    assert "Fruit" not in drawn and "apple" not in drawn, drawn


@needs_node
def test_code_being_written_keeps_its_open_box():
    """The case next door, which must not change: code is no document, and
    while it is written its source is what one wants to watch."""
    text = "Here it is:\n\n```python\nprint('apple')"
    drawn = _run(f"rendern({json.dumps(text)})")

    assert "codeblock offen" in drawn, drawn
    assert not FILE_MARK.findall(drawn), drawn


@needs_node
def test_code_being_written_is_no_open_file():
    text = "Here it is:\n\n```python\nprint('apple')"
    assert _run(f"openFile({json.dumps(text)})") is None


@needs_node
@pytest.mark.parametrize("text", ["Data:\n\n```json", "Notes:\n\n```md"])
def test_a_language_still_being_written_is_no_document_yet(text):
    """A fence arrives letter by letter, and "```json" is also the beginning
    of "```jsonc". Taken for a document one piece too early, it put a card
    into the answer and an empty tab into the rail for a file that never
    came. The language counts once something stands behind it."""
    assert _run(f"openFile({json.dumps(text)})") is None
    assert not FILE_MARK.findall(_run(f"rendern({json.dumps(text)})"))
    assert _run(f"dateienZahl({json.dumps(text)})") == 0

    assert _run(f"openFile({json.dumps(text + chr(10))})")["inhalt"] == ""
    assert len(FILE_MARK.findall(_run(f"rendern({json.dumps(text + chr(10))})"))) == 1


@needs_node
def test_a_longer_language_is_code_and_not_the_document_it_begins_with():
    text = "Data:\n\n```jsonc\n{ // a comment\n"
    assert _run(f"openFile({json.dumps(text)})") is None
    assert "codeblock offen" in _run(f"rendern({json.dumps(text)})")


@needs_node
def test_the_open_file_is_the_text_written_so_far():
    text = "Here it is:\n\n```md\n# Fruit\n\n- apple"
    assert _run(f"openFile({json.dumps(text)})") == {
        "name": "md-1.md",
        "art": "md",
        "inhalt": "# Fruit\n\n- apple",
        "open": True,
    }


@needs_node
def test_a_closed_fence_is_no_open_file():
    """`open` has to end with the fence: the stream reads `dateienAus` to
    tell that a file is finished, and a file reported by both would be
    opened twice."""
    text = "```md\n# Fruit\n```\n\nDone."
    assert _run(f"openFile({json.dumps(text)})") is None
    assert [d["name"] for d in _run(f"dateienAus({json.dumps(text)})")] == ["md-1.md"]


@needs_node
def test_the_card_keeps_its_name_when_the_fence_closes():
    """One card, before and after: the open file already carries the number
    it will have once it is closed — also behind a file that came before it,
    and also in a later section of the message (the offset)."""
    before = "```md\n# One\n```\n\n"
    growing = before + "```md\n# Two"
    closed = growing + "\n```"

    assert _run(f"openFile({json.dumps(growing)})")["name"] == "md-2.md"
    assert _run(f"dateienAus({json.dumps(closed)})")[1]["name"] == "md-2.md"
    assert _run(f"openFile({json.dumps(growing)}, 3)")["name"] == "md-5.md"
    assert _run(f"dateienAus({json.dumps(closed)}, 3)")[1]["name"] == "md-5.md"


@needs_node
def test_the_pieces_of_an_answer_carry_the_open_file_last():
    """What the message view draws: the marker the renderer left and the
    file behind it have to be the same one, the finished file first."""
    text = "```md\n# One\n```\n\nand\n\n```md\n# Two"
    pieces = _run(f"dateiTeileRoh({json.dumps(text)})")
    files = [p["wert"] for p in pieces if p["art"] == "datei"]

    assert [f["name"] for f in files] == ["md-1.md", "md-2.md"]
    assert "open" not in files[0]
    assert files[1]["open"] is True and files[1]["inhalt"] == "# Two"


@needs_node
def test_the_open_file_has_taken_its_number():
    """The count the next section starts from. Without the open file in it,
    a document in the following section was handed the same name."""
    assert _run(f"dateienZahl({json.dumps('```md' + chr(10) + '# One')})") == 1
    assert _run(f"dateienZahl({json.dumps('no file here')})") == 0


@needs_node
def test_two_files_in_a_row_leave_only_blank_text_between_them():
    """What lets the message view stand them side by side: the piece of text
    between two fences is empty, so it ends no row."""
    text = "```md\n# One\n```\n\n```md\n# Two\n```"
    pieces = _run(f"dateiTeileRoh({json.dumps(text)})")

    assert [p["art"] for p in pieces] == ["html", "datei", "html", "datei", "html"]
    assert pieces[2]["wert"].strip() == ""


# --- The catalogue ----------------------------------------------------------


@needs_node
def test_markdown_is_drawn_and_the_others_stay_what_they_were():
    """Markdown was shown as its source in the rail. A table stays a table,
    a page stays drawn, data stays text."""
    shown = _run(
        "Object.fromEntries(['md','markdown','html','svg','csv','tsv','json','python']"
        ".map((s) => [s, dateiart(s)?.zeigen ?? null]))"
    )
    assert shown == {
        "md": "gerendert",
        "markdown": "gerendert",
        "html": "gerendert",
        "svg": "gerendert",
        "csv": "tabelle",
        "tsv": "tabelle",
        "json": "text",
        "python": None,
    }


@needs_node
def test_the_size_of_a_growing_file_moves():
    """Whole kilobytes stand still for seconds; the line that says a file is
    being written counts in tenths, in the way the window's language writes
    a number. A finished file keeps the short form."""
    text = "x" * 1229
    assert _run(f"growingSize({json.dumps(text)}, 'de')") == "1,2 KB"
    assert _run(f"growingSize({json.dumps(text)}, 'en')") == "1.2 KB"
    assert _run("growingSize('x'.repeat(900), 'de')") == "900 B"
    assert _run(f"dateigroesse({json.dumps(text)})") == "1 KB"


@needs_node
def test_the_facts_of_a_file_being_written():
    file = json.dumps({"art": "md", "inhalt": "x" * 1229})
    assert _run(f"writingFacts({file}, 'wird geschrieben', 'de')") == "MD · wird geschrieben · 1,2 KB"
    assert _run(f"writingFacts({file}, 'being written', 'en')") == "MD · being written · 1.2 KB"
    assert _run(f"dateiFakten({file})") == "MD · 1 KB"


@pytest.mark.parametrize(
    ("language", "word", "view"),
    [("de", "wird geschrieben", "Ansicht"), ("en", "being written", "View")],
)
def test_both_languages_say_that_a_file_is_being_written(language, word, view):
    texts = json.loads((ROOT / f"app/locales/{language}.json").read_text(encoding="utf-8"))
    assert texts["datei"]["wird_geschrieben"] == word
    assert texts["datei"]["gerendert"] == view
    # The rail's one way to keep a file is the download.
    assert set(texts["datei"]) == {"quelltext", "gerendert", "herunterladen", "wird_geschrieben"}


# --- The tab beside the chat -------------------------------------------------


@needs_node
def test_a_growing_file_is_carried_into_its_tab():
    state = _tabs(
        """
        tabOeffnen('chat-1', { name: 'md-1.md', art: 'md', inhalt: '# One' })
        const first = tabs.proChat['chat-1']
        followTab('chat-1', { name: 'md-1.md', art: 'md', inhalt: '# One' })
        const untouched = tabs.proChat['chat-1'] === first
        followTab('chat-1', { name: 'md-1.md', art: 'md', inhalt: '# One\\n\\nmore' })
        console.log(JSON.stringify({ list: tabs.proChat['chat-1'], untouched, offered }))
        """
    )
    assert state["list"] == [
        {"id": "md:md-1.md", "name": "md-1.md", "art": "md", "inhalt": "# One\n\nmore", "pfad": ""}
    ]
    # The same content writes nothing — a caller inside an effect would
    # otherwise be its own trigger.
    assert state["untouched"] is True
    # Following never opens the rail a second time.
    assert state["offered"] == ["vorschau"]


@needs_node
def test_a_closed_tab_stays_closed_while_its_file_grows():
    """The reader closed the tab while the document was still being written.
    Every further piece, the last one included, must leave it closed."""
    state = _tabs(
        """
        tabOeffnen('chat-1', { name: 'md-1.md', art: 'md', inhalt: '# One' })
        tabSchliessen('chat-1', 'md:md-1.md')
        followTab('chat-1', { name: 'md-1.md', art: 'md', inhalt: '# One\\n\\nmore' })
        console.log(JSON.stringify({ list: tabs.proChat['chat-1'], closed: tabs.zu['chat-1'] }))
        """
    )
    assert state["list"] == []
    assert state["closed"] == {"md:md-1.md": True}


@needs_node
def test_following_opens_no_tab_of_its_own():
    state = _tabs(
        """
        followTab('chat-1', { name: 'md-1.md', art: 'md', inhalt: '# One' })
        console.log(JSON.stringify({ list: tabsVon('chat-1'), offered }))
        """
    )
    assert state == {"list": [], "offered": []}


WRITER = """
const sights = []
const carry = tabWriter('chat-1', () => { sights.push('first'); return true })
"""


@needs_node
def test_the_writer_opens_a_tab_once_and_then_follows_it():
    """One answer, one file, three pieces and the closing fence: the tab is
    opened at the first sight and only followed from then on."""
    state = _tabs(
        WRITER
        + """
        carry({ name: 'md-1.md', art: 'md', inhalt: '# One', open: true })
        carry({ name: 'md-1.md', art: 'md', inhalt: '# One\\nmore', open: true })
        carry({ name: 'md-1.md', art: 'md', inhalt: '# One\\nmore\\nend' })
        console.log(JSON.stringify({ list: tabsVon('chat-1'), sights, offered }))
        """
    )
    assert [(t["name"], t["inhalt"]) for t in state["list"]] == [("md-1.md", "# One\nmore\nend")]
    assert state["sights"] == ["first"]
    assert state["offered"] == ["vorschau"]


@needs_node
def test_the_writer_leaves_a_tab_closed_that_the_reader_closed():
    """Closed while the file was being written: the pieces that follow, the
    one with the closing fence included, must not bring it back."""
    state = _tabs(
        WRITER
        + """
        carry({ name: 'md-1.md', art: 'md', inhalt: '# One', open: true })
        tabSchliessen('chat-1', 'md:md-1.md')
        carry({ name: 'md-1.md', art: 'md', inhalt: '# One\\nmore', open: true })
        carry({ name: 'md-1.md', art: 'md', inhalt: '# One\\nmore\\nend' })
        console.log(JSON.stringify({ list: tabsVon('chat-1'), sights }))
        """
    )
    assert state == {"list": [], "sights": ["first"]}


@needs_node
def test_the_writer_tells_files_apart_by_name():
    """The defect a count had: an open fence that turns out to be something
    else leaves a number behind, and the next file was then only followed —
    into a tab it never got. By name, every file has its own first sight."""
    state = _tabs(
        WRITER
        + """
        carry({ name: 'md-1.md', art: 'md', inhalt: '# One', open: true })
        carry({ name: 'html-1.html', art: 'html', inhalt: '<p>', open: true })
        carry({ name: 'html-1.html', art: 'html', inhalt: '<p>two</p>' })
        console.log(JSON.stringify({ list: tabsVon('chat-1'), sights }))
        """
    )
    assert [(t["name"], t["inhalt"]) for t in state["list"]] == [("md-1.md", "# One"), ("html-1.html", "<p>two</p>")]
    assert state["sights"] == ["first", "first"]


@needs_node
def test_a_new_answer_brings_a_closed_tab_back():
    """Closed means closed until the file is written AGAIN: the writer of the
    next answer has not seen the file yet, so it opens it."""
    state = _tabs(
        """
        tabWriter('chat-1')({ name: 'md-1.md', art: 'md', inhalt: '# One' })
        tabSchliessen('chat-1', 'md:md-1.md')
        tabWriter('chat-1')({ name: 'md-1.md', art: 'md', inhalt: '# Again' })
        console.log(JSON.stringify(tabsVon('chat-1').map((t) => t.inhalt)))
        """
    )
    assert state == ["# Again"]


@needs_node
def test_a_fence_is_unsettled_until_more_text_comes():
    """"```" closes the document above it; "```bash" — the same marks, one
    piece later — opens a block inside it, and the document is open again.
    Whoever follows the answer has to look once more after such an end, also
    when the piece that settles it carries no fence mark at all."""
    document = "```markdown\n# Title\n"
    assert _run(f"endsInFence({json.dumps(document + '```')})") is True
    assert _run(f"endsInFence({json.dumps(document + '> ```ba')})") is True
    # The case it exists for: closed for one piece, open again with the next.
    assert _run(f"openFile({json.dumps(document + '```')})") is None
    assert _run(f"openFile({json.dumps(document + '```bash' + chr(10) + 'npm i')})")["inhalt"] == (
        "# Title\n```bash\nnpm i"
    )
    # Settled ends and plain prose need no second look.
    assert _run(f"endsInFence({json.dumps(document + '```' + chr(10))})") is False
    assert _run(f"endsInFence({json.dumps(document + 'three marks ``` in a sentence')})") is False
    assert _run("endsInFence('')") is False


@needs_node
def test_a_fence_behind_prose_is_unsettled_too():
    """A model opens a document after a few words as well, and the marks and
    the language often arrive in two pieces: the second one has no fence mark
    in it, and is the one that makes the document."""
    marks = "Here it is: ```"
    assert _run(f"endsInFence({json.dumps(marks)})") is True
    assert _run(f"endsInFence({json.dumps(marks + 'markdown')})") is True
    assert _run(f"openFile({json.dumps(marks + 'markdown')})") is None
    assert _run(f"openFile({json.dumps(marks + 'markdown' + chr(10) + '# Title')})")["inhalt"] == "# Title"


def test_the_stream_hands_every_file_to_the_writer():
    """The wiring in the stream: the closed files and the one still open all
    go through the one writer of this answer."""
    app = APP.read_text(encoding="utf-8")
    assert "dateienAus, dateienDavor, dateienVorherJeNachricht, endsInFence, openFile," in app
    assert "const carryFile = tabWriter(zielChat, () => {" in app
    assert "for (const file of dateienAus(platzhalter.content, dateienVorher)) carryFile(file)" in app
    # A fence left unsettled is looked at again with the next piece.
    assert "const fenceMoved = ereignis.text.includes('`') || fenceUnsettled" in app
    assert "fenceUnsettled = endsInFence(platzhalter.content)" in app
    assert "const unfinished = openFile(platzhalter.content, dateienVorher)" in app
    assert "if (unfinished) carryFile(unfinished)" in app
    # No second way into the rail beside it.
    assert "tabOeffnen(" not in app and "followTab(" not in app


# --- The card ----------------------------------------------------------------


def test_the_card_has_one_size_and_the_small_shadow():
    rule = _rule(CARD, ".dateikarte")
    for line in (
        "width: 300px;",
        "max-width: 100%;",
        "height: 56px;",
        "border: 1px solid var(--linie);",
        "border-radius: 9px;",
        "background: var(--bg-erhoben);",
        "box-shadow: var(--karten-schatten);",
    ):
        assert line in rule, f"{line!r} is missing:\n{rule}"


def test_the_card_tells_its_state_with_the_dot_and_nothing_else():
    markup = _markup(CARD)
    # Blue while written, green when there; and it breathes only where the
    # chat's dots are allowed to move, like every running dot beside it.
    assert (
        "<Leuchtpunkt farbe={writing ? 'blau' : 'gruen'} groesse={9} "
        "atmet={writing && punktPulsiert('chat')} />"
    ) in markup
    # One click target: the card. Saving is done in the reader and the rail.
    assert "<button" not in markup, markup
    assert markup.count("onclick=") == 1, markup
    assert "<svg" not in markup, markup


def test_an_answer_draws_its_files_as_a_row_of_cards():
    message = MESSAGE.read_text(encoding="utf-8")
    assert "{#each cardRows(dateiTeile(teil.text, versaetze[i])) as stueck, j (j)}" in message
    assert "writing={isWriting(file)}" in message
    # Blue only while the answer runs: a message cut short ends in the same
    # open fence, and its file is simply as far as it got.
    assert "const isWriting = (file) => Boolean(file.open && laeuft)" in message
    assert "flex-wrap: wrap;" in _rule(MESSAGE, ".file-row")
    # A file handed in wears the same card, at the same size.
    assert "flex-wrap: wrap;" in _rule(MESSAGE, ".dok-reihe")
    assert "flex: 1" not in _rule(MESSAGE, ".dok-zeile :global(.dateikarte)")
    # ... and may shrink with a narrow bubble instead of running out of it.
    assert "max-width: 100%;" in _rule(MESSAGE, ".dok-zeile")


# --- The shadow --------------------------------------------------------------


def test_the_card_shadow_is_one_value_for_every_look():
    sheet = SHEET.read_text(encoding="utf-8")
    assert sheet.count("--karten-schatten:") == 1
    base = sheet.split(":root", 1)[1].split("}", 1)[0]
    assert "--karten-schatten: 0 2px 6px -2px rgba(0, 0, 0, 0.25);" in base


def test_only_the_file_card_wears_the_card_shadow():
    """The silence probe: a tile, a menu card, a model card are not cards
    standing in the chat, and none of them picks the value up."""
    carriers = sorted(
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*")
        if path.suffix in {".svelte", ".css", ".js"} and "var(--karten-schatten)" in path.read_text(encoding="utf-8")
    )
    assert carriers == ["teile/Dateikarte.svelte"]


# --- The rail ----------------------------------------------------------------


def test_the_rail_is_tabs_an_address_line_and_the_page():
    rail = RAIL.read_text(encoding="utf-8")
    markup = _markup(RAIL)
    sheet = rail.split("<style>", 1)[1]

    for sign in ("kreuz", "neu_laden", "dokument_zeilen", "download"):
        assert f'<Hauszeichen zeichen="{sign}"' in markup, sign
    # In the rail itself the name stands once beside the tabs: in the
    # address line, and only where the file has no path to show there.
    assert (
        '<span class="adresse-name" title={offen?.pfad || null}><span>{offen?.pfad || offen?.name}</span></span>'
        in markup
    )
    assert markup.count("offen?.name}") == 1

    # No footer, no fading edge, no frame around the page.
    assert 'class="fuss"' not in markup and ".fuss" not in sheet
    assert "rollfade" not in rail
    assert "border: 2px" not in sheet
    assert "border: none;" in _rule(RAIL, ".seite")
    assert "padding: 4px 12px 12px;" in _rule(RAIL, ".buehne")
    # One way to keep the file. Printing and filing into a folder are gone.
    assert "print" not in rail.lower() and "drucken" not in rail
    assert "erzeugnisAblegen" not in rail
    assert "erzeugnisAblegen" not in (SOURCE / "lib/api.js").read_text(encoding="utf-8")


def test_the_head_of_the_column_does_not_name_the_file_again():
    """The name stood three times: in the head of the column, on the tab and
    in the address line. The head says which tool it is and nothing of the
    file — and no detail beside the name for any tool, the terminal's
    number of runs included: sign, name, fold button."""
    column = COLUMN.read_text(encoding="utf-8")
    assert "aktiverTab" not in column and "vorschautabs" not in column
    assert "leiste.modul === 'vorschau'" not in column.split("const MODULE", 1)[0]
    assert "const detail = " not in column and "{detail}" not in column
    assert "terminal.laeufe.length" not in column and "t('terminal.laeufe'" not in column
    head = column.split('<div class="kopf">', 1)[1].split("<!-- Folds the column", 1)[0]
    assert '<span class="modulname">{titel}</span>' in head
    assert head.count('<span class="spacer"></span>') == 3
    # The text is gone from both catalogues: nothing reads it any more.
    for language in ("de", "en"):
        catalogue = json.loads((ROOT / "app" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
        assert "laeufe" not in catalogue["terminal"], language


def test_the_rail_draws_markdown_and_can_show_its_source():
    rail = RAIL.read_text(encoding="utf-8")
    assert "{:else if isMarkdown && !quelltextZeigen}" in rail
    assert "{#each dateiTeile(offen.inhalt) as stueck, i (i)}" in rail
    # The switch exists only where there are two views to switch between.
    assert "const hasTwoViews = $derived(kannZeichnen || kannTabelle || isMarkdown)" in rail
    assert "{#if hasTwoViews}" in rail
    assert "aria-pressed={quelltextZeigen}" in rail
    # What the browser draws stays sealed.
    assert 'sandbox="allow-scripts"' in rail and "mitSchutzregel(offen.inhalt)" in rail


# --- A document with a block inside it ---------------------------------------

FENCE = "`" * 3
INNER_DOC = (
    f"{FENCE}markdown\n# A\n{FENCE}python\nprint(1)\n{FENCE}\nMore\n"
)


@needs_node
def test_a_document_that_holds_a_block_is_open_until_its_own_closing_fence():
    """The inner block's closing fence closes the inner block only: the
    document is still open, carries the block and the text behind it, and
    its card is the only thing the answer shows."""
    opened = _run(f"openFile({json.dumps(INNER_DOC)})")
    assert opened is not None and opened["open"] is True
    assert opened["inhalt"] == f"# A\n{FENCE}python\nprint(1)\n{FENCE}\nMore"
    assert _run(f"dateienAus({json.dumps(INNER_DOC)})") == []
    html = _run(f"rendern({json.dumps(INNER_DOC)})")
    assert FILE_MARK.findall(html) == ["0"]
    # Nothing of the source runs on into the answer as text.
    assert "More" not in html and "print" not in html


@needs_node
def test_a_document_that_holds_a_block_is_finished_at_its_own_closing_fence():
    closed = INNER_DOC + FENCE
    (file,) = _run(f"dateienAus({json.dumps(closed)})")
    assert file["name"] == "markdown-1.md"
    assert file["inhalt"] == f"# A\n{FENCE}python\nprint(1)\n{FENCE}\nMore"
    assert _run(f"openFile({json.dumps(closed)})") is None
    html = _run(f"rendern({json.dumps(closed)})")
    assert FILE_MARK.findall(html) == ["0"]
    assert "More" not in html and "print" not in html


@needs_node
def test_text_after_a_finished_document_with_a_block_stays_text():
    text = INNER_DOC + FENCE + "\n\nAfter the file."
    (file,) = _run(f"dateienAus({json.dumps(text)})")
    assert file["inhalt"].endswith("More")
    html = _run(f"rendern({json.dumps(text)})")
    assert "After the file." in html


@needs_node
def test_a_document_with_two_blocks_keeps_both():
    text = (
        f"{FENCE}markdown\n{FENCE}js\na\n{FENCE}\nmid\n{FENCE}python\nb\n{FENCE}\n{FENCE}"
    )
    (file,) = _run(f"dateienAus({json.dumps(text)})")
    assert file["inhalt"].count(FENCE) == 4 and "mid" in file["inhalt"]


@needs_node
def test_the_fences_that_close_at_the_first_bare_fence_still_do():
    """Silence: a code block keeps CommonMark's rule, a document without a
    block inside closes at the first bare fence, a longer fence survives the
    shorter ones inside it, and a block in a quote is read as before."""
    # A code block holding a fence with a language: closes at the first bare one.
    code = f"{FENCE}python\nx\n{FENCE}js\ny\n{FENCE}\nafter"
    html = _run(f"rendern({json.dumps(code)})")
    assert html.count("<pre>") == 1 and "after" in html
    # A document without a block inside it.
    doc = f"{FENCE}markdown\n# A\n{FENCE}\ntext"
    (file,) = _run(f"dateienAus({json.dumps(doc)})")
    assert file["inhalt"] == "# A"
    # A longer document fence holds ``` examples whole, as before.
    longer = f"````markdown\n{FENCE}python\nx\n{FENCE}\n````"
    (file,) = _run(f"dateienAus({json.dumps(longer)})")
    assert file["inhalt"] == f"{FENCE}python\nx\n{FENCE}"
    # A document in a quote, with no block inside it.
    quoted = f"> {FENCE}markdown\n> # A\n> {FENCE}"
    (file,) = _run(f"dateienAus({json.dumps(quoted)})")
    assert file["inhalt"] == "# A"


@needs_node
def test_a_document_in_a_quote_holds_its_block_too():
    quoted = f"> {FENCE}markdown\n> # A\n> {FENCE}python\n> x\n> {FENCE}\n> {FENCE}"
    (file,) = _run(f"dateienAus({json.dumps(quoted)})")
    assert file["inhalt"] == f"# A\n{FENCE}python\nx\n{FENCE}"


@needs_node
def test_the_unsettled_end_still_looks_once_more():
    """`test_a_fence_is_unsettled_until_more_text_comes` stays what it is:
    the end of a document that holds a block is a bare fence that may close
    the block or the document."""
    assert _run(f"endsInFence({json.dumps(INNER_DOC + FENCE)})") is True


# --- File names run across the chat ------------------------------------------


@needs_node
def test_two_answers_of_one_chat_do_not_hand_out_the_same_name():
    """The second answer's first document goes on from the first's count —
    as it is written (the stream's offset) and as it is drawn after a
    reload (the message's offset) — and the two have two tabs."""
    answer = f"{FENCE}markdown\n# One\n{FENCE}"
    second = f"{FENCE}markdown\n# Two\n{FENCE}"
    result = _run(
        f"""(() => {{
          const chat = [
            {{ id: 'u1', role: 'user', content: 'a' }},
            {{ id: 'a1', role: 'assistant', content: {json.dumps(answer)} }},
            {{ id: 'u2', role: 'user', content: 'b' }},
            {{ id: 'a2', role: 'assistant', content: {json.dumps(second)} }},
          ]
          const karte = dateienVorherJeNachricht(chat)
          return {{
            offsets: ['u1', 'a1', 'u2', 'a2'].map((id) => karte.get(id)),
            davor: dateienDavor(chat, 'a2'),
            stream: dateienAus({json.dumps(second)}, dateienDavor(chat, 'a2')).map((f) => f.name),
            loaded: dateiTeile({json.dumps(second)}, karte.get('a2'))
              .filter((p) => p.art === 'datei').map((p) => p.wert.name),
            first: dateienAus({json.dumps(answer)}, karte.get('a1')).map((f) => f.name),
          }}
        }})()"""
    )
    assert result["offsets"] == [0, 0, 1, 1]
    assert result["davor"] == 1
    assert result["first"] == ["markdown-1.md"]
    assert result["stream"] == ["markdown-2.md"]
    assert result["loaded"] == ["markdown-2.md"]


@needs_node
def test_names_that_differ_take_two_tabs():
    state = _tabs(
        """
        tabWriter('chat-1')({ name: 'markdown-1.md', art: 'md', inhalt: '# One' })
        tabWriter('chat-1')({ name: 'markdown-2.md', art: 'md', inhalt: '# Two' })
        console.log(JSON.stringify(tabsVon('chat-1').map((t) => t.name)))
        """
    )
    assert state == ["markdown-1.md", "markdown-2.md"]


@needs_node
def test_counting_across_a_chat_leaves_the_rest_as_it_was():
    """Silence: two documents of one answer count as before, and rows that
    carry no document move nothing — a report of a finished background
    command and the person's own rows take no number."""
    two = f"{FENCE}markdown\n# A\n{FENCE}\n\n{FENCE}markdown\n# B\n{FENCE}"
    result = _run(
        f"""(() => {{
          const chat = [
            {{ id: 'u1', role: 'user', content: {json.dumps(two)} }},
            {{ id: 'r1', role: 'assistant', art: 'werkzeugmeldung', content: {json.dumps(two)} }},
            {{ id: 'a1', role: 'assistant', content: 'no document here' }},
            {{ id: 'a2', role: 'assistant', content: {json.dumps(two)} }},
            {{ id: 'a3', role: 'assistant', content: {json.dumps(two)} }},
          ]
          const karte = dateienVorherJeNachricht(chat)
          return {{
            offsets: chat.map((n) => karte.get(n.id)),
            names: dateienAus({json.dumps(two)}).map((f) => f.name),
          }}
        }})()"""
    )
    assert result["offsets"] == [0, 0, 0, 0, 2]
    assert result["names"] == ["markdown-1.md", "markdown-2.md"]
