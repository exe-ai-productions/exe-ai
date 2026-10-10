"""What a finished background run leaves in the chat, and how it is drawn.

Both halves are checked in one file because neither is worth anything alone:
``app/hintergrundmeldung.py`` writes the message, ``frontend/src/lib/markdown.js``
draws it, and the promise they keep together is that command output arrives
as command output.

It broke exactly there. The raw output went into the message without a
fence, so the renderer read it as Markdown: the lines of a paragraph glued
together with a space, a row of dashes turned into a rule, a line beginning
with "- " into a list item, the indentation dropped. An `ls -la` reached the
window as one long sentence.

The renderer is not read here but RUN, in node, the way
``tests/test_chatscrollen.py`` runs App.svelte's scroll logic: what is
asserted is the HTML that actually comes out.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import hintergrundmeldung
from app.tools import hintergrund

WURZEL = Path(__file__).resolve().parent.parent
MARKDOWN = WURZEL / "frontend/src/lib/markdown.js"


def _meldung(befehl: str, ausgabe: str, code: int = 0) -> str:
    lauf = hintergrund.Lauf(nummer=7, chat_id="chat-1", befehl=befehl, hintergrund=True)
    lauf.code = code
    return hintergrundmeldung._text(lauf, ausgabe)


# --- The message that is stored --------------------------------------------


def test_die_ausgabe_steht_in_einem_zaun():
    """Line for line, indentation and all, and nothing read as Markdown."""
    ausgabe = "total 8\ndrwxr-xr-x  2 a  b   64 .\n  - not a list\n---"
    kopf, rest = _meldung("ls -la", ausgabe).split("\n\n", 1)
    assert kopf == "[background run #7 finished: ls -la]"
    assert rest == f"```console\n{ausgabe}\n```"


def test_der_zaun_waechst_ueber_backticks_in_der_ausgabe():
    """A grep for fences prints fences. With the shortest fence the output
    would close its own box halfway through, and everything after it would
    be read as prose again — so the fence is one mark longer than the
    longest run it has to survive."""
    ausgabe = 'waechter.py:380: if sauber.startswith("```"):'
    assert _meldung("grep -rn x app", ausgabe).endswith(
        f"````console\n{ausgabe}\n````"
    )


def test_der_zaun_wird_auch_nach_dem_kappen_geschlossen():
    """The cut lands where it lands — mid-line, mid-fence. An opening left
    without its closing partner would swallow everything drawn after it."""
    ausgabe = "y" * (hintergrundmeldung.MAX_ZEICHEN - 10) + "```py\nrest, then cut"
    meldung = _meldung("cat gross.md", ausgabe)
    assert "then cut" not in meldung, "nothing was cut, the case checks nothing"
    # The dangling ```py inside is three marks long, the fence around it four.
    assert meldung.endswith("\n````")
    assert meldung.count("````") == 2


def test_ein_lauf_ohne_ausgabe_bekommt_keinen_kasten():
    """An empty box says less than the line above it already does."""
    leer = "[background run #7 finished: touch leer]"
    assert _meldung("touch leer", "") == leer
    assert _meldung("touch leer", "\n  \n") == leer


def test_der_ausgang_steht_ueber_dem_kasten():
    """A failed run has to be readable as failed before one reads what it
    wrote, so the exit code stays in the line above and out of the box."""
    assert _meldung("false", "boom", code=2) == (
        "[background run #7 failed with exit code 2: false]\n\n```console\nboom\n```"
    )


# --- The message as the window draws it ------------------------------------

# The three modules markdown.js imports, replaced by the little this test
# asks of them: for a language highlight.js does not know, colouring is
# nothing but escaping; the copy button carries a text; and command output
# is not a document, so it never becomes a file box.
ERSATZ = """
const hervorheben = (code) => String(code)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const t = () => 'Copy';
const dateiart = () => null;
const dateiname = () => null;
"""


def _modul(ersatz: str = ERSATZ) -> str:
    """markdown.js with its imports stood in for and its export cut off, so
    node can run it as a plain script."""
    quelle = MARKDOWN.read_text(encoding="utf-8")
    quelle = re.sub(r"^import .*$", "", quelle, flags=re.M)
    return f"{ersatz}\n{quelle[: quelle.rindex('export {')]}"


def _node(skript: str) -> str:
    # The script goes in through standard input and both ways are read as
    # UTF-8. As an argument it is longer than a command line may be on
    # Windows, and the system's own code page there would garble every
    # letter outside ASCII on the way back.
    lauf = subprocess.run(["node", "-"], input=skript, capture_output=True, text=True, encoding="utf-8")
    assert lauf.returncode == 0, f"{lauf.stderr}\n{lauf.stdout}"
    return lauf.stdout.rstrip("\n")


def _gezeichnet(text: str) -> str:
    """The real rendern(), run against the real message."""
    return _node(f"{_modul()}\nconsole.log(rendern({json.dumps(text)}))")


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_die_gezeichnete_ausgabe_behaelt_ihre_zeilen():
    """The bug itself: one box, the lines intact, and no rule or list made
    out of a `---` or a `- ` that a command happened to print."""
    ausgabe = "total 8\ndrwxr-xr-x  2 a  b   64 .\n  - not a list\n---"
    html = _gezeichnet(_meldung("ls -la", ausgabe))
    assert html.count("<pre>") == 1
    # One row per line, each line intact inside its own row.
    for zeile in ausgabe.split("\n"):
        assert f'<span class="code-zeile"><span>{zeile}</span></span>' in html, html
    assert "<hr>" not in html
    assert "<li>" not in html


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_backticks_zerlegen_die_gezeichnete_meldung_nicht():
    """Backticks in the output AND in the command line above it. Both used
    to open a code block of their own and tear the message apart; the fence
    is longer than the one, and a fence only counts at the start of a line,
    which settles the other."""
    ausgabe = 'waechter.py:380: if sauber.startswith("```"):'
    html = _gezeichnet(_meldung("grep -rn '```' app", ausgabe))
    assert html.startswith("<p>[background run #7 finished: grep -rn '```' app]</p>")
    assert html.count("<pre>") == 1
    # Nothing left standing open: that class is for a block still being
    # written, and a stored message is not being written any more.
    assert "codeblock offen" not in html
    assert f"<code>{ausgabe}</code>" in html


def test_die_meldung_nennt_sich_werkzeugmeldung(client, chat_id):
    """The row a finished background run leaves is not something the model
    said, and it has to say so.

    Without it the row is an assistant turn with no cancel mark -- exactly
    the description a window used to hunt for when looking for the answer
    being written. It was adopted as that answer, emptied and refilled from
    the replayed stream; "send again" would have deleted it; and the reader
    saw the same output twice, in the tool card and again as text.
    """
    from app.hintergrundmeldung import anmelden
    from app.tools.hintergrund import FEHLER, Lauf, laeufe

    repositories = client.app.state.repositories
    anmelden(repositories)
    lauf = Lauf(
        nummer=7, chat_id=chat_id, befehl="brew install node",
        hintergrund=True, zustand=FEHLER, code=127,
    )

    laeufe.abschluss(lauf, "zsh:1: command not found: brew")

    zeile = repositories.messages.auflisten(chat_id=chat_id)[-1]
    assert zeile.art == "werkzeugmeldung"
    # It has no run of its own, so it claims no state. A row carrying one
    # would be back among the candidates for "which answer is live".
    assert zeile.zustand is None


def test_ein_beim_beenden_getoeteter_lauf_hinterlaesst_seine_meldung(client, chat_id):
    """The service goes down with a background command still running. Marking
    the run forgotten kept its late report out of a closed database -- and
    kept it out of the chat altogether: runs live in memory only, so after
    the next launch the chat held "started run #3" and nothing else, and the
    model took the run for pending. The report is written at the kill, while
    the database is open; the companion that wakes at the closed pipe a
    moment later writes nothing more."""
    from app.hintergrundmeldung import anmelden
    from app.tools.hintergrund import ABSCHLUSS_BEIM_BEENDEN, FEHLER, LAEUFT, laeufe

    class _Prozess:
        getoetet = False

        def kill(self):
            self.getoetet = True

    repositories = client.app.state.repositories
    anmelden(repositories)
    lauf = laeufe.anlegen(chat_id, "npm run build", hintergrund=True)
    lauf.prozess = _Prozess()
    assert lauf.zustand == LAEUFT

    assert laeufe.alle_toeten() == 1

    assert lauf.prozess is None
    assert lauf.zustand == FEHLER
    assert lauf.vergessen is True
    zeilen = repositories.messages.auflisten(chat_id=chat_id)
    assert [z.art for z in zeilen] == ["werkzeugmeldung"]
    eintrag = zeilen[-1].stats["werkzeuge"][0]
    assert eintrag["fehlgeschlagen"] is True
    assert eintrag["exit_code"] is None
    assert eintrag["ergebnis"] == ABSCHLUSS_BEIM_BEENDEN

    # The late companion: same calls a normal end makes, and nothing lands.
    laeufe.beenden(lauf, -9)
    laeufe.abschluss(lauf, "killed")
    assert len(repositories.messages.auflisten(chat_id=chat_id)) == 1


def test_die_meldung_traegt_laufnummer_und_exit_code(client, chat_id):
    """WHICH run failed, and with what.

    Both used to ride in the header line above the output ("[background run
    #3 failed with exit code 1: ...]"). That line stopped being drawn
    because it wrote the command a second time right above the card that
    already carries it -- and the two facts went with it. THAT something
    failed stayed visible; which run and which code did not, in the card,
    in the terminal bar, or anywhere else.

    So they belong in the entry, where the card can say them without
    repeating the command.
    """
    from app.hintergrundmeldung import anmelden
    from app.tools.hintergrund import FEHLER, Lauf, laeufe

    repositories = client.app.state.repositories
    anmelden(repositories)
    laeufe.abschluss(
        Lauf(
            nummer=3, chat_id=chat_id, befehl="npm test",
            hintergrund=True, zustand=FEHLER, code=1,
        ),
        "1 test failed",
    )

    eintrag = repositories.messages.auflisten(chat_id=chat_id)[-1].stats["werkzeuge"][0]
    assert eintrag["lauf_nummer"] == 3
    assert eintrag["exit_code"] == 1


def test_ein_geglueckter_lauf_meldet_seine_null(client, chat_id):
    """Zero is written down, and only the drawing leaves it out.

    A missing key and a zero are different things -- the first says nobody
    measured, the second says it went well -- and the difference is the same
    one `dauer_sekunden` is careful about next door. What the card does with
    it is the card's business.
    """
    from app.hintergrundmeldung import anmelden
    from app.tools.hintergrund import FERTIG, Lauf, laeufe

    repositories = client.app.state.repositories
    anmelden(repositories)
    laeufe.abschluss(
        Lauf(
            nummer=4, chat_id=chat_id, befehl="npm run build",
            hintergrund=True, zustand=FERTIG, code=0,
        ),
        "built in 2.31s",
    )

    eintrag = repositories.messages.auflisten(chat_id=chat_id)[-1].stats["werkzeuge"][0]
    assert eintrag["exit_code"] == 0
    assert eintrag["fehlgeschlagen"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_ein_zaun_im_zitat_bleibt_ein_codeblock():
    """CommonMark counts a fence inside a blockquote as a fence, and a model
    writing a callout writes one every time.

    Anchoring the opening fence at the start of a line — which is what stops
    a fence in the MIDDLE of a line from opening a block — took the quoted
    ones with it, and the reader got the raw backticks with the whole block
    glued into a single line. The quote marker also has to come off the
    code: keeping it would put "> " in front of every line in the box, and
    copying it would paste something that does not run.
    """
    gezeichnet = _gezeichnet(
        "> **Hinweis:** erst installieren:\n> ```bash\n> npm install\n> ```"
    )
    assert "<div class=\"codeblock umbricht" in gezeichnet, gezeichnet
    assert "npm install" in gezeichnet
    assert "&gt; npm install" not in gezeichnet, "the quote marker is still in the code"
    assert "```" not in gezeichnet, "raw fence characters in the text"


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_ein_zaun_mitten_in_der_zeile_hinterlaesst_keinen_leeren_kasten():
    """The opening fence is rightly not recognised — it is not at the start
    of a line. Its CLOSING half then is, and fell into the open-fence rule
    with nothing behind it: an empty grey box wearing the "still being
    written" style, under an answer that was finished.
    """
    gezeichnet = _gezeichnet("Ergebnis: ```js\nconst a = 1\n```")
    assert "codeblock offen" not in gezeichnet, gezeichnet
    assert "<code></code>" not in gezeichnet
    assert "const a = 1" in gezeichnet, "the code has vanished entirely"


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_der_offene_zaun_beim_streamen_bleibt_ein_offener_kasten():
    """The guard above must not cost the case it sits next to: an answer
    still being written genuinely has a fence with content and no close, and
    that one keeps its open box."""
    gezeichnet = _gezeichnet("Gleich kommt Code:\n```py\nprint(1)")
    assert "codeblock offen" in gezeichnet, gezeichnet
    assert "print(1)" in gezeichnet


# --- Where a fence ends ------------------------------------------------------
#
# The opening fence was anchored at the start of a line long ago; the CLOSING
# one was not, and it is the one that decides where the box stops. Everything
# below is that half: a fence closes on a fence LINE, and on nothing else.

# The same stand-ins, except that `dateiart` now tells the truth about one
# language: a ```md block IS a document. That is what makes rendern() leave a
# file marker exactly where dateienAus() has to find a file, which is the only
# way to check that the two still read the same fences.
ERSATZ_DOKUMENT = """
const hervorheben = (code) => String(code)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const t = () => 'Copy';
const dateiart = (sprache) => (sprache === 'md' ? { endung: 'md' } : null);
const dateiname = (sprache, nummer) => 'datei-' + nummer + '.md';
"""

DATEI_MARKE_PY = re.compile("\x01datei(\\d+)\x01")


def _dokument(text: str) -> tuple[str, list[dict]]:
    """What rendern() draws AND what dateienAus() counts, from one run —
    the two have to agree about every fence in the same text."""
    ersatz = ERSATZ_DOKUMENT
    roh = json.dumps(text)
    ausgabe = _node(
        f"{_modul(ersatz)}\n"
        f"console.log(JSON.stringify({{html: rendern({roh}), dateien: dateienAus({roh})}}))"
    )
    daten = json.loads(ausgabe)
    return daten["html"], daten["dateien"]


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_ein_zaun_endet_nur_an_einer_zaunzeile():
    """The defect: the closing backreference was not anchored, so the block
    ended at the first run of three marks ANYWHERE — mid-line included.

    A grep for fences prints fences, and one printed INSIDE a block closed it
    after `grep -n '`. What followed — the rest of that line, the next command
    and the real closing fence — fell out of the box and was read as prose.
    Only a writer that makes its fence longer than anything it carries was
    safe (hintergrundmeldung.py does); the three marks a model writes in an
    ordinary answer were not.
    """
    gezeichnet = _gezeichnet("```sh\ngrep -n '```' file.md\necho done\n```")
    assert gezeichnet.count("<pre>") == 1, gezeichnet
    for zeile in ("grep -n '```' file.md", "echo done"):
        assert f'<span class="code-zeile"><span>{zeile}</span></span>' in gezeichnet, gezeichnet
    # Nothing fell out of the box: no loose paragraph, no leftover marks.
    assert "<p>" not in gezeichnet, gezeichnet


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_ein_laengerer_schlusszaun_laesst_keine_marke_stehen():
    """A fence may close with MORE marks than it opened with — CommonMark
    allows it, and a writer padding its fence produces it. The backreference
    took only as many as it opened with, and the surplus stayed behind as a
    stray backtick sitting under the finished box."""
    gezeichnet = _gezeichnet("```js\nx\n````")
    assert "<code>x</code>" in gezeichnet, gezeichnet
    assert "`" not in gezeichnet, "a fence mark is still in the text"


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_ein_laengerer_zaun_haelt_die_kuerzeren_darin():
    """The point of a longer fence: it survives everything shorter inside it.
    An answer explaining Markdown writes exactly this, and the inner fences
    have to reach the reader as text — not close the outer block three lines
    early."""
    gezeichnet = _gezeichnet("````md\n```js\nlet a = 1\n```\n````")
    assert gezeichnet.count("<pre>") == 1, gezeichnet
    for zeile in ("```js", "let a = 1", "```"):
        assert f'<span class="code-zeile"><span>{zeile}</span></span>' in gezeichnet, gezeichnet


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_ein_offener_zaun_im_zitat_wird_beim_streamen_gerettet():
    """A callout is written from its first line like anything else, so
    between the chunk carrying "> ```bash" and the one carrying its closing
    fence the block is open.

    The rescue for open fences had no quote marker, so it did not recognise
    this one at all: the reader watched a blockquote with the raw backticks
    and every line of code glued into it, until the last chunk turned the
    whole thing into a box.
    """
    gezeichnet = _gezeichnet("> **Note:** run this:\n> ```bash\n> npm install")
    assert "codeblock offen" in gezeichnet, gezeichnet
    assert "npm install" in gezeichnet
    assert "&gt; npm install" not in gezeichnet, "the quote marker is still in the code"
    assert "```" not in gezeichnet, "raw fence characters in the text"


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_ein_halber_schlusszaun_beim_streamen_schliesst_nichts():
    """Mid-stream the text ends wherever the chunk ended — and a block whose
    content prints fences carries fence-shaped runs long before its own
    closing fence arrives. Such a run used to close the box, so a block still
    being written was drawn as finished and lost everything after it."""
    gezeichnet = _gezeichnet("```sh\ngrep -n '```")
    assert "codeblock offen" in gezeichnet, gezeichnet
    assert "<code>grep -n '```</code>" in gezeichnet


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_ein_verirrter_schlusszaun_im_zitat_bleibt_ein_leerer_kasten_erspart():
    """The guard next door must survive the quote marker joining the rescue:
    a closing fence with no opening of its own — reachable by the rescue —
    must not become an empty grey box under a finished answer."""
    gezeichnet = _gezeichnet("> Ergebnis: fertig\n> ```")
    assert "codeblock offen" not in gezeichnet, gezeichnet
    assert "<code></code>" not in gezeichnet


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_ein_zaun_mitten_in_der_zeile_ist_ein_codeblock():
    """Small models write "Here is the fix: ```python" and put the code on
    the next line. Code is drawn as code wherever its fence stands: closed,
    still streaming, and inside a quote — and the prose before the fence
    stays prose."""
    fertig = _gezeichnet("Here is the fix: ```python\nprint(1)\n```\nDone.")
    assert '<div class="codeblock umbricht' in fertig, fertig
    assert "print(1)" in fertig
    assert "Here is the fix:" in fertig
    assert "```" not in fertig, "raw fence characters in the text"

    offen = _gezeichnet("Here is the fix: ```python\nprint(1)")
    assert "codeblock offen" in offen, offen
    assert "print(1)" in offen

    zitiert = _gezeichnet("> Ergebnis: ```js\n> const a = 1\n> ```")
    assert '<div class="codeblock umbricht' in zitiert, zitiert
    assert "&gt; const" not in zitiert


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_ein_inline_span_mit_drei_zeichen_oeffnet_keinen_block():
    """What keeps the leniency above from swallowing prose: a fence in the
    middle of a line counts only when nothing but its info word and a line
    break follow it. "run ```js``` inline" is a span, not an opening — with
    or without a closing fence further down."""
    ohne = _gezeichnet("run ```js``` inline\nmore text")
    assert "codeblock" not in ohne, ohne
    mit = _gezeichnet("run ```js``` inline\n```\n")
    assert "codeblock offen" not in mit, mit


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this machine")
def test_rendern_und_dateienaus_lesen_dieselben_zaeune():
    """One pattern, two readers, and they must never disagree about where a
    block ends — a document counted differently is a card pointing at the
    wrong text, or at nothing.

    A Markdown document is the case that shows it: its own content is full of
    fences, and while the closing one was unanchored the file stopped at the
    first of them. Both halves stopped there, so the COUNT still matched and
    only the document was wrong — cut off, with its tail spilled into the
    prose beside the card.
    """
    text = "```md\n# Titel\n\nrun ```js``` inline\n```"
    gezeichnet, dateien = _dokument(text)

    assert len(DATEI_MARKE_PY.findall(gezeichnet)) == len(dateien) == 1, gezeichnet
    assert dateien[0]["inhalt"] == "# Titel\n\nrun ```js``` inline"
    # Nothing of the document was left lying outside its card.
    assert "inline" not in gezeichnet, gezeichnet
    assert "`" not in gezeichnet, gezeichnet
