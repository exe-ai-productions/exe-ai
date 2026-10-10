"""A PDF as text, page by page.

Two readers need the same reading and only one of them had it: the upload
route pulled a PDF's text apart in place (``app/api/v1/dokumente.py``), and
the read tool could not read a PDF at all — it handed the model the raw bytes
of one as replacement characters, without an error.

The page boundaries are why this lives in one module rather than in two.
Joining the pages into one text throws them away for good, and a model that
is to name "page 12" as its source needs them kept. So the pages are handed
back as a list and the joining is a second, named step: whoever wants the
whole text asks for it, whoever wants one page asks for that.

pypdf is a pure-Python reader and is already a dependency — nothing leaves
the machine, and no image is rendered: a page without a text layer comes back
empty, which is the honest answer for a scan.
"""

from __future__ import annotations

import hashlib
import io
import logging

log = logging.getLogger(__name__)

# What a PDF file starts with. Checked so a file whose name says ".pdf" and
# whose content says otherwise is read as the text it is, instead of failing
# in the extractor.
KENNUNG = b"%PDF"

ENDUNG = ".pdf"


class PdfUnlesbar(Exception):
    """The bytes are not a PDF this machine can read — the message says why."""


# The file read last, kept as (digest, pages) so a walk through one document
# takes it apart ONCE. Measured on a 300-page file: taking it apart costs
# 87 ms, so `page 1` through `page 300` cost 26 seconds of pure re-reading,
# all of it behind a tool call the user waits on. The digest costs 0.11 ms
# against that.
#
# ONE entry, and the entry is the whole answer to "how many": the case this
# exists for is a model walking the pages of one document, so the file being
# read now is the only one worth keeping. Anything larger would be a number
# nobody measured.
_ZULETZT: tuple[str, tuple[str, ...]] | None = None


def ist_pdf(daten: bytes) -> bool:
    """Whether these bytes open with a PDF header."""
    return daten.startswith(KENNUNG)


def seiten(daten: bytes, *, merken: bool = True) -> list[str]:
    """The text of every page, in order.

    One entry per page, empty where a page carries no text layer at all. The
    list's length is the page count, so nobody has to open the file twice.

    **One bad page does not lose the document.** Only a file that cannot be
    opened at all is refused; a page whose extraction throws comes back empty,
    exactly like one without a text layer. Refusing all of it would take 499
    readable pages away over the five hundredth — and page-wise access to a
    document too large to travel is what this module exists for.

    The same bytes twice in a row are taken apart once — see ``_ZULETZT``.
    The caller gets a list of its own each time, so nothing it does to the
    result reaches the next reader.

    ``merken=False`` for a reader that will not come back: the upload route
    reads a document exactly once and stores its text itself, so pinning
    that text in memory for the rest of the process buys nothing.
    """
    global _ZULETZT

    kennung = hashlib.sha256(daten).hexdigest()
    # Read ONCE into a local: three separate reads of the global would let
    # another thread swap the entry between the check and the use, and the
    # caller would get another document's pages under a matching digest.
    zuletzt = _ZULETZT
    if zuletzt is not None and zuletzt[0] == kennung:
        return list(zuletzt[1])

    texte = _zerlegen(daten)
    if merken:
        _ZULETZT = (kennung, tuple(texte))
    return texte


def _zerlegen(daten: bytes) -> list[str]:
    """The reading itself, without the memory of the last one."""
    from pypdf import PdfReader

    try:
        leser = PdfReader(io.BytesIO(daten))
        seitenliste = list(leser.pages)
    except Exception as fehler:  # pypdf raises various things, per file
        raise PdfUnlesbar(str(fehler)) from fehler

    texte: list[str] = []
    for seite in seitenliste:
        try:
            texte.append(seite.extract_text() or "")
        except Exception:  # noqa: BLE001 - one page must not cost the rest
            log.warning("A page of a PDF could not be read", exc_info=True)
            texte.append("")
    return texte


def volltext(seitentexte: list[str]) -> str:
    """The pages as one text — the shape a request carries.

    Each page opens with `[page N]`, the same marker syntax the read-file
    tool writes (`app/tools/datei_lesen.py`) — a model asked to name its
    source needs to see where page N begins, which an upload without the
    marks could never show. The two are not byte-identical:
    this join keeps the blank line between pages the upload route has
    always used, where the tool's own join uses a single line break.
    """
    return "\n\n".join(
        f"[page {nummer}]\n{seite}" for nummer, seite in enumerate(seitentexte, start=1)
    )
