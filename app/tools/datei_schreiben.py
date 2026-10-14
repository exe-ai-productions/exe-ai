"""The write tool — `write_file`.

Writing a file through the shell means a here-document or an `echo` with
quoting that survives the model, the shell and the file system. Small models
lose that fight often enough that the content arrives mangled. A tool that
takes the text as an argument cannot mangle it.

Overwriting is allowed. The share is the permission — the same rule the shell
works under, and a write tool that refuses to overwrite is a write tool
nobody can use twice.

One exception, and it is narrow: an ``exe.md`` at the top of a shared folder
(app/ordnerwissen.py). That file is the user's notes about the folder, the
model is expected to keep it current, and "write the exe.md" is the call that
turns what is in it into three fresh lines. Creating one is still this tool's
job; replacing one is edit_file's.

A path ending in ``.pdf`` gets a PDF rather than a text file with a
misleading name. ``read_file`` reads PDFs, and a model asked for a report
could name one and then hand back
something no reader opens. The layout is deliberately plain — two fonts, one
size, fixed margins: what this tool promises is the text, not a design.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from pathlib import Path
from typing import Any

from app import ordnerwissen
from app.tools import aenderungsblock, grenzen
from app.tools.mcp_client import MCPWerkzeug

SERVER_NAME = "shell"
WERKZEUG_NAME = "write_file"

# A4 at 72 dpi, the unit reportlab counts in. Margins, line height and font
# size are fixed on purpose: this tool promises the text, not a layout, and a
# number the model could pick would be a design decision nobody made.
SEITE = (595.27, 841.89)
RAND = 56.0
ZEILENHOEHE = 14.0
SCHRIFTGROESSE = 11.0

# Helvetica is Base-14/WinAnsi and stops at Latin-1 — Cyrillic, Greek, CJK
# and emoji all came out as boxes, with the tool still reporting success.
# Noto Sans covers Latin, Greek and Cyrillic; Noto Emoji is
# the black-and-white set, the only kind reportlab can draw (it paints
# outlines, never a colour glyph table). Both ship under app/daten, next to
# the thinking-stage catalogue, and carry their OFL license text in
# THIRD_PARTY_NOTICES.md.
SCHRIFT = "NotoSans"
SCHRIFT_EMOJI = "NotoEmoji"
_SCHRIFTORDNER = Path(__file__).resolve().parent.parent / "daten"
_SCHRIFTDATEI = _SCHRIFTORDNER / "NotoSans.ttf"
_SCHRIFTDATEI_EMOJI = _SCHRIFTORDNER / "NotoEmoji.ttf"

# Neither font has a glyph for a tab, and stringWidth has no notion of a tab
# stop, so it drew as a box. Four spaces is what most editors
# already show for one, and an indented block still reads as indented.
_TABULATOR_ALS_LEERZEICHEN = " " * 4

_schriftgesichter: dict[str, Any] | None = None

# Writing a PDF now runs off the event loop (see below), on a dedicated,
# single-worker pool rather than asyncio.to_thread's shared default
# executor. That keeps two PDF writes from ever running at once — the font
# cache above and reportlab's own font registry would otherwise race, and
# two writes to the same path could interleave — without a burst of PDF
# writes tying up the threads the rest of this server's own to_thread calls
# (cron logging, the memory-pill poll, ...) share. A waiting write queues on
# this pool; it does not block the event loop.
_pdf_ausfuehrer = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="pdf-schreiben"
)


def _schriften_laden() -> dict[str, Any]:
    """Registers the two shipped fonts with reportlab, once per process.

    A face's ``charToGlyph`` is the same table reportlab itself reads to
    place a glyph — checking it here means a character neither font can
    draw is caught before a page exists, not drawn as reportlab's own box.

    A font file that is missing or damaged raises reportlab's own
    ``TTFError`` — neither an ``ImportError`` nor an ``OSError``, so it
    would otherwise reach the model as a raw reportlab crash instead of
    this tool's usual English refusal.
    """
    global _schriftgesichter
    if _schriftgesichter is not None:
        return _schriftgesichter
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFError, TTFont

    try:
        text = TTFont(SCHRIFT, str(_SCHRIFTDATEI))
        emoji = TTFont(SCHRIFT_EMOJI, str(_SCHRIFTDATEI_EMOJI))
    except TTFError as fehler:
        raise grenzen.GrenzeVerletzt(
            f"PDF creation failed because a bundled font could not be loaded ({fehler}). Save "
            "the text with a different file extension."
        ) from fehler
    pdfmetrics.registerFont(text)
    pdfmetrics.registerFont(emoji)
    _schriftgesichter = {SCHRIFT: text.face, SCHRIFT_EMOJI: emoji.face}
    return _schriftgesichter


def _schrift_fuer_zeichen(zeichen: str, gesichter: dict[str, Any]) -> str | None:
    """Which of the two fonts draws this character, or ``None`` for neither."""
    code = ord(zeichen)
    if code in gesichter[SCHRIFT].charToGlyph:
        return SCHRIFT
    if code in gesichter[SCHRIFT_EMOJI].charToGlyph:
        return SCHRIFT_EMOJI
    return None


def _unbekannte_zeichen(text: str, gesichter: dict[str, Any]) -> set[str]:
    """Every character in ``text`` that neither shipped font can draw."""
    return {zeichen for zeichen in text if _schrift_fuer_zeichen(zeichen, gesichter) is None}


def _zeilen(inhalt: str) -> list[str]:
    """Splits on a newline the way this tool draws one — ``\\n`` or ``\\r\\n``
    or a bare ``\\r`` — and nothing else.

    ``str.splitlines()`` also breaks on form feed, vertical tab, NEL and the
    Unicode line/paragraph separators, which this tool never treats as a
    break anywhere else. Using it for the coverage scan but plain iteration
    for drawing let those characters slip past the scan uncounted while
    still vanishing from the page — silently, the exact failure the scan
    exists to prevent. One split, used for both.
    """
    return inhalt.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _schrift_laeufe(text: str, gesichter: dict[str, Any]) -> list[tuple[str, str]]:
    """Groups ``text`` into maximal runs of one font each.

    Both the width measurement and the drawing need this: a single
    ``stringWidth``/``drawString`` call takes one font name, so a line
    mixing Noto Sans text and a Noto Emoji character is measured and drawn
    run by run, not character by character. Grouped with ``groupby`` rather
    than appending one character at a time to a growing string, which turned
    a long single-font run (no break characters to wrap on) quadratic.
    """
    from itertools import groupby

    def schrift_von(zeichen: str) -> str:
        schrift = _schrift_fuer_zeichen(zeichen, gesichter)
        assert schrift is not None, "called after the coverage check in _pdf_schreiben"
        return schrift

    return [(schrift, "".join(gruppe)) for schrift, gruppe in groupby(text, key=schrift_von)]


def _laeufe_mit_breite(
    text: str, gesichter: dict[str, Any]
) -> list[tuple[str, str, float]]:
    """Each font run in ``text`` together with its own glyph width.

    Shared by the two callers that need a run's width — measuring a whole
    line and drawing one glyph run at a time — so the two stay in step:
    a line that fits by this measurement is drawn using the same widths.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    return [
        (schrift, stueck, stringWidth(stueck, schrift, SCHRIFTGROESSE))
        for schrift, stueck in _schrift_laeufe(text, gesichter)
    ]


def _text_breite(text: str, gesichter: dict[str, Any]) -> float:
    """Summed glyph width for a run that may mix both fonts."""
    return sum(breite for _, _, breite in _laeufe_mit_breite(text, gesichter))


def _seite_beginnen(blatt: Any) -> None:
    """Marks a fresh page as non-empty before anything else runs.

    reportlab drops a page with no drawing operation at all when the canvas
    is saved. For a built-in Base-14 font ``setFont`` alone is enough, but
    for an embedded TTF font it writes nothing to the content stream until a
    glyph is actually drawn — so a page holding only blank lines (or empty
    content) would otherwise save a PDF with no pages, a file no
    reader opens, while the tool reports success. An empty string still
    counts as a draw call.
    """
    blatt.setFont(SCHRIFT, SCHRIFTGROESSE)
    blatt.drawString(RAND, SEITE[1] - RAND, "")


def _zeile_zeichnen(blatt: Any, x: float, y: float, zeile: str, gesichter: dict[str, Any]) -> None:
    """Draws one already-wrapped line, switching font at every script boundary.

    ``drawString`` paints a whole call in the canvas's current font, so a
    line mixing text and emoji is grouped into runs of one font first, each
    run drawn on its own, the cursor moved on by exactly what it measured.
    """
    for schrift, stueck, breite in _laeufe_mit_breite(zeile, gesichter):
        blatt.setFont(schrift, SCHRIFTGROESSE)
        blatt.drawString(x, y, stueck)
        x += breite


def _pdf_schreiben(ziel: Path, inhalt: str) -> None:
    """Writes the text as a PDF: two plain fonts, fixed margins, A4 pages.

    Reportlab and the font registration are imported here rather than at
    module level so a machine without reportlab still serves every other
    write — the dependency is in requirements.txt, but an installation that
    skipped it should lose PDFs, not writing.

    Each character draws in Noto Sans or, failing that, Noto Emoji — the two
    fonts this tool ships. A character neither one has a glyph
    for stops the write before any page exists, with an English sentence
    naming it; Base-14 Helvetica used to draw a silent box instead. A tab
    becomes four spaces before anything else runs, so the wrap
    below counts it like any other character.

    Long lines are wrapped at the right margin instead of running off the
    page, because a line that leaves the paper is a line the reader loses.
    The wrap sums the width each character's own font reports, so it holds
    for wide characters and mixed scripts too. A word with no space in it is
    broken the way it names its own parts: at `/`, `-`, `.` and `_` first,
    and only a piece that is still too wide between its characters
    (`trennstuecke`, `packen`).
    """
    from reportlab.pdfgen import canvas

    gesichter = _schriften_laden()
    inhalt = inhalt.replace("\t", _TABULATOR_ALS_LEERZEICHEN)

    unbekannt = _unbekannte_zeichen("".join(_zeilen(inhalt)), gesichter)
    if unbekannt:
        zeichenliste = ", ".join(f"'{zeichen}'" for zeichen in sorted(unbekannt))
        raise grenzen.GrenzeVerletzt(
            f"'{ziel}' was not written: neither bundled font (Noto Sans, Noto Emoji) contains "
            f"glyphs for {zeichenliste}, so these characters cannot be included in a PDF. Save "
            "the content with a different file extension."
        )

    blatt = canvas.Canvas(str(ziel), pagesize=SEITE)
    _seite_beginnen(blatt)
    breite = SEITE[0] - 2 * RAND
    y = SEITE[1] - RAND

    def passt(text: str) -> bool:
        return _text_breite(text, gesichter) <= breite

    def zeichenweise(wort: str) -> list[str]:
        """Breaks a single word that is wider than the page.

        A URL, a long path or a run of base64 holds no space to break at.
        Drawn as one piece it would run past the right margin, where no
        reader shows it — so it is cut between characters instead. A single
        character wider than the page still gets its own piece; that is the
        end of what a fixed font size can do.
        """
        stuecke: list[str] = []
        laufend = ""
        for zeichen in wort:
            if laufend and not passt(laufend + zeichen):
                stuecke.append(laufend)
                laufend = zeichen
                continue
            laufend += zeichen
        stuecke.append(laufend)
        return stuecke

    def trennstuecke(wort: str) -> list[str]:
        """A word too wide for a line, cut after the marks that carry meaning.

        A URL, a path or a file name is read in its parts: `https://…/a-very-
        long-name.html` says where it breaks by itself. Cutting it between
        characters instead splits it into syllables nobody asked for — `…/add
        ress-t` / `hat-has-no-space-in-it` — and the reader has to put the
        address back together from letter groups.

        Each piece keeps its mark, so the whole word is still the same string
        when the pieces are read in order: `/`, `-`, `.` and `_` are the four
        the house's own addresses and file names are built from — `_` for
        the file names this house writes with underscores between their
        parts. A piece that is still too wide is the caller's
        business (`zeichenweise`).
        """
        stuecke: list[str] = []
        laufend = ""
        for zeichen in wort:
            laufend += zeichen
            if zeichen in "/-._":
                stuecke.append(laufend)
                laufend = ""
        if laufend:
            stuecke.append(laufend)
        return stuecke

    def packen(atome: list[str], stuecke: list[str]) -> str:
        """Packs pieces into whole lines, appending to ``stuecke``.

        Returns what is left standing at the end, for the caller to carry on
        with. A piece too wide on its own goes through `zeichenweise` — that
        is the last resort, after the marks have had their chance.
        """
        laufend = ""
        for atom in atome:
            versuch = laufend + atom if laufend else atom
            if passt(versuch):
                laufend = versuch
                continue
            if passt(atom):
                # The piece fits on a line of its own, so the mark in front
                # of it is the better break — the line being written ends
                # there.
                if laufend:
                    stuecke.append(laufend)
                laufend = atom
                continue
            # Not even alone: it has no mark left to break at, so its
            # characters fill the REST of the line being written before the
            # next one starts. Flushing first would throw the rest of that
            # line away — measured at up to a third more lines on a path of
            # one long marker-free run.
            unterteile = zeichenweise(laufend + atom)
            stuecke.extend(unterteile[:-1])
            laufend = unterteile[-1]
        return laufend

    def umbrechen(zeile: str) -> list[str]:
        if passt(zeile):
            return [zeile]
        stuecke: list[str] = []
        laufend = ""
        for wort in zeile.split(" "):
            versuch = f"{laufend} {wort}" if laufend else wort
            if passt(versuch):
                laufend = versuch
                continue
            if laufend:
                stuecke.append(laufend)
                laufend = ""
            if passt(wort):
                laufend = wort
                continue
            laufend = packen(trennstuecke(wort), stuecke)
        stuecke.append(laufend)
        return stuecke

    # An empty text still gets a page: a PDF with no pages is a file no
    # reader opens, and the tool reported success. _zeilen("") is [""],
    # so an empty document already draws the one blank line it needs.
    for rohzeile in _zeilen(inhalt):
        for zeile in umbrechen(rohzeile):
            if y < RAND:
                blatt.showPage()
                _seite_beginnen(blatt)
                y = SEITE[1] - RAND
            _zeile_zeichnen(blatt, RAND, y, zeile, gesichter)
            y -= ZEILENHOEHE
    blatt.save()


def _pdf_schreiben_serialisiert(ziel: Path, inhalt: str) -> bool:
    """Runs on `_pdf_ausfuehrer`'s one worker thread; answers whether `ziel`
    existed a moment before the write.

    The existence check and the write happen together, on the pool's single
    thread: two overlapping writes to the same path can otherwise both see
    "not there yet" and both report themselves as having created it, one
    quietly overwriting what the other just wrote.
    """
    gab_es_schon = ziel.exists()
    _pdf_schreiben(ziel, inhalt)
    return gab_es_schon


def werkzeug_beschreibung() -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Writes text to a file, creating it and any missing parent folders. "
            "An existing file is replaced as a whole, so read it first if the "
            "old content matters.\n"
            "Works inside the shared folders — relative paths resolve against "
            "the first one, or against a private working folder when none is "
            "shared.\n"
            "To change a part of a file, use edit_file if you have it, instead "
            "of writing the whole thing back.\n"
            "A path ending in .pdf produces a PDF holding this text, on A4 "
            "pages in two plain fonts. Latin, Greek and Cyrillic text plus "
            "black-and-white emoji draw; a script neither covers (e.g. CJK, "
            "Arabic) is refused instead of turning into boxes — write that "
            "content under a different extension. Use .pdf when the reader "
            "expects a PDF. "
            "A PDF can only be written whole: edit_file cannot change one, so "
            "write it again with the corrected text. Any other extension "
            "writes the text as it is.\n"
            "An existing exe.md at the top of a shared folder is the one file "
            "this refuses to replace — if you have edit_file, add to that one "
            "with it."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": 'File to write, e.g. "notes/todo.md".',
                },
                "content": {
                    "type": "string",
                    "description": "The complete text the file should contain after writing.",
                },
            },
            "required": ["path", "content"],
        },
        server=SERVER_NAME,
    )


def aussenpfad(argumente: dict[str, Any], ordner: list[str]) -> str | None:
    return grenzen.aussenpfad(argumente, ordner)


def braucht_bestaetigung(argumente: dict[str, Any], ordner: list[str]) -> bool:
    return aussenpfad(argumente, ordner) is not None


async def ausfuehren(
    argumente: dict[str, Any], ordner: list[str], data_dir: Path | str | None = None
) -> str:
    roh = str(argumente.get("path") or "").strip()
    if not roh:
        raise grenzen.GrenzeVerletzt("No path provided.")
    inhalt = argumente.get("content")
    if inhalt is None:
        raise grenzen.GrenzeVerletzt("No content provided.")
    inhalt = str(inhalt)

    ziel = grenzen.ziel(roh, ordner, data_dir)
    if ziel.is_dir():
        raise grenzen.GrenzeVerletzt(f"'{ziel}' is a folder, not a file.")

    # The one file this tool will not replace. An exe.md is what the user
    # wrote down about the folder, it is kept up to date by the model, and
    # "write the exe.md" is exactly the call that turns two hundred lines
    # into three — the realistic way that file is destroyed, far more so
    # than an `rm`. Refused as an ordinary tool result with a reason, the
    # same shape the shell uses for a refused background run, and the
    # refusal names the tool that CAN do the job. Creating one is still
    # this tool's work: the check only fires on a file that is there.
    if ziel.exists() and ordnerwissen.ist_notiz(ziel, ordner):
        raise grenzen.GrenzeVerletzt(
            f"'{ziel}' already exists and was not overwritten, because replacing the entire "
            "file would discard its contents. If edit_file is available, use it to add "
            "content or change a passage."
        )

    gab_es_schon = ziel.exists()
    ist_pdf = ziel.suffix.lower() == ".pdf"
    # Read before the overwrite below destroys it — the one chance to see
    # what the file said a moment ago. A file that cannot be read as text
    # (binary, or some other encoding) is not diffed; it is still overwritten.
    # A PDF is never diffed, so it is not read either: pulling a large one
    # into memory for a block that is thrown away again costs for nothing.
    voriger_inhalt = None
    if gab_es_schon and not ist_pdf:
        try:
            voriger_inhalt = ziel.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            voriger_inhalt = None
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        if ist_pdf:
            # Reportlab lays out and draws synchronously; run it off the
            # event loop so a slow PDF does not stall every other request
            # this server is answering at the same time. Read back from the
            # pool's own check, taken together with the write (see above) —
            # the one above was too early to still be accurate once this
            # write had to wait its turn behind another one.
            schleife = asyncio.get_running_loop()
            gab_es_schon = await schleife.run_in_executor(
                _pdf_ausfuehrer, _pdf_schreiben_serialisiert, ziel, inhalt
            )
        else:
            # The bytes as the model gave them, on every system: without
            # ``newline=""`` Windows turns every \n into \r\n, and the file
            # read back no longer equals what was written.
            ziel.write_text(inhalt, encoding="utf-8", newline="")
    except ImportError as fehler:
        # Only the PDF branch imports anything, so this is its error alone.
        # reportlab is in requirements.txt; an installation that skipped it —
        # or whose reportlab cannot load its own dependencies — says so, with
        # the import error named, instead of writing text under a .pdf name.
        raise grenzen.GrenzeVerletzt(
            f"'{ziel}' was not written because this installation cannot create PDFs ({fehler}). "
            "Save the text with a different file extension."
        ) from fehler
    except OSError as fehler:
        raise grenzen.GrenzeVerletzt(f"'{ziel}' could not be written ({fehler}).") from fehler

    zeilen = len(inhalt.splitlines())
    was = "Overwrote" if gab_es_schon else "Created"
    antwort = f"{was} {ziel} — {zeilen} lines, {len(inhalt):,} characters."
    if ist_pdf:
        antwort += " Saved as a PDF."
    if voriger_inhalt is not None:
        block = aenderungsblock.bauen(voriger_inhalt, inhalt)
        if block:
            antwort += "\n\n" + block
    return antwort
