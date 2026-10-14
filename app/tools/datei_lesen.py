"""The read tool — `read_file`.

Reading a file through the shell works, but small models trip over the
quoting long before they trip over the task. A tool with a plain `path`
argument takes that whole class of mistake away, and it makes reading
switchable on its own: switch `write_file`, `edit_file` and `run_command` off
and what is left is an agent that can look but not touch.

Where it may read is decided in ``grenzen.py``, the same boundary the shell
works under.

**Three kinds of file, one tool.** Plain text is read as lines. A PDF is read
as pages — the extraction happens here, on the same reader the upload route
uses (``app/pdfseiten.py``), so a document too large to travel inside a
request can still be read a page or a stretch at a time; that is the whole
reason uploaded files are kept on disk at all. An image is handed to the model
AS an image, the way an attachment in the chat is (``app/werkzeugbild.py``) —
and where the model at the wheel cannot see, the tool says so instead of
pretending it read something.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app import pdfseiten
from app.tools import grenzen
from app.tools.mcp_client import MCPWerkzeug

SERVER_NAME = "shell"
WERKZEUG_NAME = "read_file"

# As much as the shell hands back, for the same reason: a long file would
# otherwise fill the whole context.
MAX_ZEICHEN = 20_000

# How much of the start decides whether this is text at all. A null byte in
# the first block means no line-based reading will make sense of it.
PROBE_BYTES = 4096


def werkzeug_beschreibung() -> MCPWerkzeug:
    return MCPWerkzeug(
        name=WERKZEUG_NAME,
        beschreibung=(
            "Reads a text file and returns its lines with a header saying which "
            "part of the file they are.\n"
            "Works inside the shared folders — relative paths resolve against "
            "the first one, or against a private working folder when none is "
            "shared.\n"
            "Read a long file in parts with offset and limit instead of asking "
            f"for everything: the answer is cut off at {MAX_ZEICHEN:,} characters.\n"
            "A PDF is read as text, page by page, and the header says which "
            "page a line belongs to. Ask for a single page with page, for a "
            "stretch with offset and limit — that is how to read a document "
            "too large to be included in full.\n"
            "An image is attached to the answer so you can look at it, as long "
            "as this model can see images; if it cannot, the tool says so.\n"
            "Other binary files are refused; if you have run_command, a "
            "suitable program can read them."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": 'File to read, e.g. "notes/todo.md".',
                },
                "offset": {
                    "type": "integer",
                    "description": "First line to return, counting from 1. Defaults to the "
                                   "start of the file.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of lines to return. Defaults to as many as will fit.",
                },
                "page": {
                    "type": "integer",
                    "description": (
                        "PDF only: a single page to return, counting from 1. If omitted, the "
                        "document is read using offset and limit."
                    ),
                },
            },
            "required": ["path"],
        },
        server=SERVER_NAME,
    )


def aussenpfad(argumente: dict[str, Any], ordner: list[str]) -> str | None:
    return grenzen.aussenpfad(argumente, ordner)


def braucht_bestaetigung(argumente: dict[str, Any], ordner: list[str]) -> bool:
    return aussenpfad(argumente, ordner) is not None


def _zahl(wert: Any) -> int | None:
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def _ausschnitt(
    text: str, argumente: dict[str, Any], kopfzusatz: str = "", seite: int | None = None
) -> str:
    """The requested lines of a text, with the header that says which they are.

    The one place the line window, the character cap and the continuation
    hint live — a PDF's pages are read through it too, so a cut says the same
    thing wherever it happens.

    ``seite`` is the page these lines were taken out of, when they were. It
    goes into the continuation hint: an offset alone means the whole document
    on the next call, which would answer with lines from its beginning as
    though they were the rest of this page.

    Header and hint are counted INTO the cap, the way the shell tool counts
    its exit note (``app/tools/shell.py``, ``_kuerzen``): added on top, the
    answer grew past the very ceiling it is cut to on its way out
    (``WERKZEUGERGEBNIS_GRENZE``, ``app/api/v1/generierung.py``), and the
    line that says how to read on was the first thing cut off. Both name the
    last line returned — the number being worked out right here — so the
    room is reserved for the largest number either of them could carry: the
    file's own line count.
    """
    zeilen = text.splitlines()
    gesamt = len(zeilen)
    ab = max(1, _zahl(argumente.get("offset")) or 1)
    anzahl = _zahl(argumente.get("limit"))
    if anzahl is not None and anzahl < 1:
        anzahl = None
    ausschnitt = zeilen[ab - 1 :] if anzahl is None else zeilen[ab - 1 : ab - 1 + anzahl]

    if not ausschnitt:
        return (
            f"lines {ab}–{ab} of {gesamt}{kopfzusatz}\n(no content: the file ends before this "
            "position)"
        )

    kopf_platz = len(f"lines {gesamt}–{gesamt} of {gesamt}{kopfzusatz}\n")
    hinweis_platz = len(
        f"\n… [cut off at {MAX_ZEICHEN:,} characters — continue with offset {gesamt}"
        + (f" and page {seite}" if seite is not None else "")
        + "]"
    )
    grenze = MAX_ZEICHEN - kopf_platz - hinweis_platz

    koerper = "\n".join(ausschnitt)
    bis = ab + len(ausschnitt) - 1
    if len(koerper) > grenze:
        # Cut on a line, not mid-word: the next call continues where this one
        # stopped, and that only works if the header tells the truth.
        gekuerzt: list[str] = []
        laenge = 0
        for zeile in ausschnitt:
            if laenge + len(zeile) + 1 > grenze and gekuerzt:
                break
            gekuerzt.append(zeile)
            laenge += len(zeile) + 1
        bis = ab + len(gekuerzt) - 1
        weiter = f"offset {bis + 1}" + (f" and page {seite}" if seite is not None else "")
        koerper = "\n".join(gekuerzt) + (
            f"\n… [truncated at {MAX_ZEICHEN:,} characters; continue with {weiter}]"
        )

    return f"lines {ab}–{bis} of {gesamt}{kopfzusatz}\n{koerper}"


def _mit_seitenmarken(seitentexte: list[str]) -> str:
    """The pages as one text, each one announced by its number.

    The marks are the point of reading a PDF at all rather than its bytes: a
    model that is to answer "on page 12" has to see where page 12 begins, and
    the plain join the request builder uses throws exactly that away.
    """
    return "\n".join(
        f"[page {nummer}]\n{seite}" for nummer, seite in enumerate(seitentexte, start=1)
    )


def _pdf_lesen(ziel, daten: bytes, argumente: dict[str, Any]) -> str:
    try:
        seitentexte = pdfseiten.seiten(daten)
    except pdfseiten.PdfUnlesbar as fehler:
        raise grenzen.GrenzeVerletzt(
            f"'{ziel}' is a PDF that cannot be read on this machine ({fehler}). Use "
            "run_command with a suitable program instead."
        ) from fehler
    anzahl = len(seitentexte)
    if not anzahl:
        raise grenzen.GrenzeVerletzt(f"'{ziel}' is a PDF with no pages.")

    seite = _zahl(argumente.get("page"))
    if seite is not None:
        if seite < 1 or seite > anzahl:
            raise grenzen.GrenzeVerletzt(
                f"'{ziel}' has {anzahl} pages; page {seite} does not exist."
            )
        text = seitentexte[seite - 1]
        if not text.strip():
            # A scan, or a page holding only pictures. Said out loud: a model
            # handed an empty result reads it as an empty page.
            return (
                f"page {seite} of {anzahl}\n(no text available: this page has no text layer)"
            )
        return _ausschnitt(
            text, argumente, kopfzusatz=f" on page {seite} of {anzahl}", seite=seite
        )

    if not any(seite.strip() for seite in seitentexte):
        # Asked of the page marks alone this would look like content: they
        # are written here, not in the file.
        return (
            f"{anzahl} pages\n(no text available: this PDF has no text layer)"
        )
    zusatz = f" of the PDF, {anzahl} pages, each marked [page N]"
    return _ausschnitt(_mit_seitenmarken(seitentexte), argumente, kopfzusatz=zusatz)


# What each kind of picture starts with. The name decides WHETHER a file is
# looked at as a picture; these bytes decide what it really is, so a JPEG
# called .png is announced as the JPEG it is instead of being declared wrong
# and refused by the provider. Same posture as the PDF branch below.
BILDKENNUNGEN: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def medientyp(daten: bytes) -> str | None:
    """What these bytes really are, or None for something that is no picture.

    Public: app/dokumentablage.py makes the same check on a file's first
    bytes, to say the same thing this tool would do with them — one place
    for "is this really a picture", not two that could drift apart.
    """
    for kennung, typ in BILDKENNUNGEN:
        if daten.startswith(kennung):
            return typ
    if daten[:4] == b"RIFF" and daten[8:12] == b"WEBP":
        return "image/webp"
    return None


# How many bytes a signature check ever needs from disk: the longest entry in
# BILDKENNUNGEN plus the WEBP check right above, which reaches to offset 12.
# A signature that needs more would be silently misread as "not a picture" —
# whoever adds one bumps this too.
KENNBYTES = 16


def medientyp_aus_pfad(pfad: str) -> str | None:
    """What a FILE on disk really is, or None — no picture, or unreadable.

    For a caller that only has a path, never the bytes themselves
    (app/dokumentablage.py): the same signature check as :func:`medientyp`,
    reading only the bytes a signature needs, never the file itself — a
    document kept on disk has no size ceiling of its own, and this runs on
    every history rebuild. A path that cannot be opened at all — gone, a
    stray null byte, no permission — is no picture either, the same fallback
    a genuinely missing file gets.
    """
    try:
        with open(pfad, "rb") as datei:
            kopf = datei.read(KENNBYTES)
    except (OSError, ValueError):
        return None
    return medientyp(kopf)


def _opens_like_pdf(target: Path) -> bool:
    """Whether the file on disk opens with a PDF header: its first bytes
    only, never the file. A file that cannot be opened is no PDF here — the
    text path below says why it cannot be read."""
    try:
        with target.open("rb") as handle:
            head = handle.read(len(pdfseiten.KENNUNG))
    except OSError:
        return False
    return pdfseiten.ist_pdf(head)


def _bild_bereiten(ziel: Path, data_dir) -> tuple[str, int]:
    """Reads the picture and builds what travels: its data URL, and how many
    bytes the file's own stripped kind has.

    Everything the model is to receive is made here — the read, the metadata
    coming off, the smaller copy from ``app/model_image.py`` (the same one
    place and the same thresholds as an uploaded picture: over 1920 pixels on
    the longest side or over 3 MB), the copy's own strip, the data URL — so
    the caller can run the whole of it in its own thread and the event loop
    is left before the first byte is read.

    The copy's folder lies under the data folder the run carries
    (``data_dir``, handed over from the registry); without one the running
    process's config answers. The file in the user's folder is never touched.
    """
    from app import model_image, speicherorte
    from app.bildmetadaten import metadaten_entfernen
    from app.config import get_config

    roh = ziel.read_bytes()
    # A photo carries EXIF: camera, time, place. Every other way a picture
    # reaches a model strips that first (app/api/v1/bilder.py), and the
    # promise in app/bildschutz.py is that the answer is the same wherever a
    # picture enters — so it is stripped here too. Always, not by the switch:
    # the switch decides what is kept in the picture folder, and this file is
    # the user's own, lying in their own folder. Only what TRAVELS is cleaned;
    # nothing on disk is touched. The sentence below counts these bytes.
    roh = metadaten_entfernen(roh)

    kopien = (
        speicherorte.bildkopien_verzeichnis_fuer(data_dir)
        if data_dir is not None
        else speicherorte.bildkopien_verzeichnis(get_config())
    )
    datei = model_image.kopie(ziel, kopien)

    gesendet = roh
    if datei != ziel:
        # The copy travels — stripped as well: the operating system's tool
        # carries metadata over into it (measured: the copy of a JPEG with
        # EXIF still held it). A copy that
        # vanished under us is extremely unlikely; the honest answer then is
        # the source's stripped bytes.
        try:
            gesendet = metadaten_entfernen(datei.read_bytes())
        except OSError:
            gesendet = roh
        # A copy that came out as no known picture is not sent under a
        # label it does not deserve: the source's stripped bytes go instead.
        if medientyp(gesendet) is None:
            gesendet = roh

    # The URL is written where the chat writes its own (`model_image.data_url`),
    # announced from the bytes that TRAVEL, never from a name. Bytes no known
    # kind starts with after the strip or the copy are said, not labelled.
    try:
        url = model_image.data_url(gesendet)
    except ValueError as error:
        raise grenzen.GrenzeVerletzt(
            f"'{ziel}' could not be prepared as an image ({error}). Nothing was read."
        ) from error
    return url, len(roh)


async def _bild_lesen(ziel, modellbild, data_dir=None) -> str:
    """Hands a REAL image to the model, or says why it cannot be handed over.

    Every real picture goes in, whatever its size: what the model
    receives is the smaller copy from ``app/model_image.py`` — the same one
    place and the same thresholds as an uploaded picture. The sentence counts
    the file's own bytes after the metadata came off, like the small path
    always did — not the copy's.

    A picture under both thresholds still travels byte-identical to before:
    ``kopie`` answers with the source itself then, and the source's bytes are
    what goes out.

    The whole byte work runs in its own thread (``_bild_bereiten``): reading,
    stripping and encoding a large picture must not stop the service
    meanwhile, and a picture too large for this machine ends as a tool
    refusal instead of tearing the answer down.
    """
    if modellbild is None:
        # Either the model at the wheel has no eyes, or this run has no way to
        # carry a picture. Both are the same answer for the model, and it has
        # to be an honest one: a picture it never saw must not come back as a
        # description it invented.
        return (
            f"'{ziel}' is an image, but this model does not support image input. Nothing was "
            "read. Explain this rather than describing the image."
        )

    import asyncio

    try:
        daten_url, eigen_bytes = await asyncio.to_thread(_bild_bereiten, ziel, data_dir)
    except OSError as fehler:
        raise grenzen.GrenzeVerletzt(f"'{ziel}' could not be read ({fehler}).") from fehler
    except MemoryError:
        raise grenzen.GrenzeVerletzt(
            f"'{ziel}' exceeds this machine's available memory. Use run_command with a "
            "suitable program instead."
        ) from None

    modellbild(ziel.name, daten_url, str(ziel))
    # The sentence lives in app/werkzeugbild.py, next to the message that
    # carries the picture: a later request rebuilding the history has to
    # recognise this very result and say something else instead, and one
    # module owns both halves of that (`gelesener_bildpfad`).
    from app import werkzeugbild

    return werkzeugbild.bildsatz(str(ziel), eigen_bytes)


async def ausfuehren(
    argumente: dict[str, Any], ordner: list[str], modellbild=None, data_dir=None
) -> str:
    """Reads a file for the model.

    ``modellbild`` takes (file name, data URL) and is how an image reaches the
    model at all; left out — a model that cannot see, a caller that cannot
    carry a picture — an image is not read and the tool says so. ``data_dir``
    is the data folder the run belongs to (the registry hands it over): the
    model's picture copies live under it, so a caller carrying its own folder
    — a test — never writes into the installed one. A missing file in a
    chat that shares no folder is measured against it too (``grenzen.missing``).
    """
    from app.api.v1.bilder import ANZEIGBARE_ENDUNGEN

    roh = str(argumente.get("path") or "").strip()
    if not roh:
        raise grenzen.GrenzeVerletzt("No path provided.")
    ziel = grenzen.ziel(roh, ordner, data_dir)

    if not ziel.exists():
        raise grenzen.GrenzeVerletzt(grenzen.missing(ziel, ordner, data_dir))
    if ziel.is_dir():
        raise grenzen.GrenzeVerletzt(f"'{ziel}' is a folder. Use list_dir to read it.")

    endung = ziel.suffix.lower()
    if endung in ANZEIGBARE_ENDUNGEN and medientyp_aus_pfad(str(ziel)) is not None:
        # The SIGNATURE decides first, on the handful of bytes it needs: a
        # real picture goes in whatever its size — through the same one
        # place as an upload (app/model_image.py) — and only what is NOT a
        # picture is read as the text it may be, below.
        return await _bild_lesen(ziel, modellbild, data_dir=data_dir)

    if endung == pdfseiten.ENDUNG and _opens_like_pdf(ziel):
        # The BYTES decide, not the name: only a file that opens with a PDF
        # header is read whole here. A picture name or a .pdf name on
        # something else is read like any text file below, in pieces and
        # once, whatever its size.
        #
        # Read whole, so a ceiling has to stand before the read rather than
        # after it: a raw scan dump in a shared folder would otherwise be
        # pulled into memory at whatever size it happens to have. The ceiling
        # is the one a document already has in this house — what may be
        # uploaded as a document may be read as one.
        from app.api.v1.dokumente import MAX_BYTES as GANZ_LESEN_HOECHSTENS

        try:
            groesse = ziel.stat().st_size
        except OSError as fehler:
            raise grenzen.GrenzeVerletzt(
                f"'{ziel}' could not be read ({fehler})."
            ) from fehler
        if groesse > GANZ_LESEN_HOECHSTENS:
            raise grenzen.GrenzeVerletzt(
                f"'{ziel}' is {groesse:,} bytes, exceeding the limit of "
                f"{GANZ_LESEN_HOECHSTENS:,} for reading a file in full. Use run_command with a "
                "suitable program instead."
            )
        # Read whole, because a page cannot be taken out of the first block
        # alone.
        try:
            daten = ziel.read_bytes()
        except OSError as fehler:
            raise grenzen.GrenzeVerletzt(
                f"'{ziel}' could not be read ({fehler})."
            ) from fehler
        return _pdf_lesen(ziel, daten, argumente)

    try:
        with ziel.open("rb") as datei:
            probe = datei.read(PROBE_BYTES)
    except OSError as fehler:
        raise grenzen.GrenzeVerletzt(f"'{ziel}' could not be read ({fehler}).") from fehler
    if b"\0" in probe:
        raise grenzen.GrenzeVerletzt(
            f"'{ziel}' is a binary file. If run_command is available, use it with a suitable "
            "program to read the file."
        )

    try:
        text = ziel.read_text(encoding="utf-8", errors="replace")
    except OSError as fehler:
        raise grenzen.GrenzeVerletzt(f"'{ziel}' could not be read ({fehler}).") from fehler

    return _ausschnitt(text, argumente)
