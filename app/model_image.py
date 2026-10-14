"""What the MODEL sees of an uploaded picture: the original, or a smaller copy.

A photo straight off a phone is 12 MB and 4032 pixels wide. Sending that on
the wire costs every round anew and buys nothing: the model scales what it
gets down to its own vision size anyway. So the file that goes into a message
is the original while it is small, and a copy at 1920 pixels on its longest
side as JPEG otherwise — two thresholds, 1920 pixels on the longest side and
3 MB, with JPEG quality 0.85, and only what is over ONE of the two is
touched.

The original is never opened for writing, and it is never replaced: it stays
in the picture folder exactly as it was uploaded, and a message names it.
The copy lives in the program's own work folder under its data directory —
asked for by name in ``app/speicherorte.py``; a folder the wall does not
list, so the smaller twin never shows up as a work of its own — and
carries a name derived from the source, so the SECOND round of a conversation
hands the model the very same bytes as the first (byte-identical reuse is
what keeps a provider's prompt cache worth something).

Shrinking is done with Pillow, which travels with the package on every
system (it sets a drawn piece back into its picture in ``paste_back.py``
too). One way for macOS and Windows alike: the system tools that stood here
before — ``sips`` on the Mac, ``System.Drawing`` over PowerShell on
Windows — climbed the same ladder in two scripts, and the Windows one left
the picture at its full size. Where the file is not a picture at all, or
the library fails on it, the ORIGINAL goes out: a message with a large
picture is worth more than a message that lost one.
"""

from __future__ import annotations

import base64
import logging
import os
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from app import atomic_file

log = logging.getLogger(__name__)

# Over one of the two, the copy is made. Below both, the file travels as it
# is — no re-encoding, no quality loss for a picture that fits.
KANTE_MAX = 1920
BYTES_MAX = 3 * 1024 * 1024
QUALITAET = 85

# The ladder: every rung takes the longest side times this, down to this many
# pixels at the most. Constants like the three above.
STUFENFAKTOR = 0.8
KLEINSTE_KANTE = 100

# The suffix of an empty file that says "this picture needs no copy". It lies
# beside where the copy would be and carries the same key, so the answer of a
# round is found by the next one instead of being worked out again.
_GANZ_MARKE = "-ganz"


def verfuegbar() -> bool:
    """Whether this system can shrink a picture. The library travels with
    the package, so the answer is yes everywhere; the question stays
    because every caller asks it before it measures (app/draw_input.py,
    app/verlaufsbau.py, and the tests that stand in for a system without
    a tool)."""
    return True


def kopie(quelle: Path, ziel_ordner: Path) -> Path:
    """The file that goes to the model: ``quelle`` itself where it is small
    enough, otherwise a JPEG copy at ``KANTE_MAX`` on its longest side.

    Both answers are looked up, not made twice: where there is a copy, its
    name carries the source's own size, modification time and extension, so a
    second round finds the file from the first and hands out the same bytes;
    where the answer is "no copy needed", the empty marker file beside it says
    so. Both lookups happen BEFORE anything is measured: a picture that has an
    answer on record costs two ``stat`` calls and no decoding.

    This is the BUILDING door — the warm-up calls it, in its own thread
    (app/verlaufsbau.bilder_vorbereiten); the request's no-await stretch
    calls ``nachschlag`` instead, which never decodes a picture.

    Nothing here may cost a message: an unreadable file, a folder that cannot
    be made, a library that fails — the original goes out.
    """
    return _antwort(quelle, ziel_ordner, bauen=True)


def nachschlag(quelle: Path, ziel_ordner: Path) -> Path:
    """The same answer, but LOOKUP ONLY: the copy where one is on record, the
    original where the marker says so — and the original when NOTHING is on
    record either, without ever decoding a picture. The stretch from the read
    to the placeholder expects no await; a picture the warm-up could not
    prepare — a failed run — therefore goes out whole instead of being
    decoded on the event loop. The next answer's warm-up tries again, off the
    loop."""
    return _antwort(quelle, ziel_ordner, bauen=False)


def data_url(roh: bytes) -> str:
    """The data URL a picture travels in — ``data:<media type>;base64,…`` —
    for every way a picture reaches a model: the chat history
    (app/verlaufsbau.py) and ``read_file`` (app/tools/datei_lesen.py). What
    each of them strips off before is theirs; how the URL is written is
    here, once.

    The media type comes from the bytes, never from a name: a JPEG copy
    under a ``.png`` name is announced as JPEG, and a provider that checks
    the announcement does not reject the request. Bytes that are no picture
    this system knows raise ``ValueError`` — a label that is not true is
    worse than none, so no type is ever assumed.
    """
    from app.tools.datei_lesen import medientyp

    typ = medientyp(roh)
    if typ is None:
        raise ValueError("The data is not a PNG, JPEG, or WebP image.")
    return f"data:{typ};base64," + base64.b64encode(roh).decode()


def _antwort(quelle: Path, ziel_ordner: Path, *, bauen: bool) -> Path:
    quelle = Path(quelle)
    try:
        if not quelle.is_file():
            return quelle
        kennung = _kennung(quelle)
    except OSError:
        return quelle

    ziel_ordner = Path(ziel_ordner)
    ziel = ziel_ordner / f"{quelle.stem}-{kennung}.jpg"
    ganz = ziel_ordner / f"{quelle.stem}-{kennung}{_GANZ_MARKE}"
    try:
        if ziel.is_file():
            # A copy built by an older one-pass version may sit ABOVE the
            # threshold (exactly the noisy pictures that
            # motivated the ladder). The building door takes that as "not on
            # record" and lets the ladder replace it; the lookup-only door
            # hands it out — the smaller file is still the better answer
            # under a stretch that must not decode a picture.
            if not bauen or ziel.stat().st_size <= BYTES_MAX:
                return ziel
        elif ganz.is_file():
            return quelle
    except OSError:
        pass

    if not bauen:
        return quelle

    # Only now the picture itself: nothing is on record yet, so the file has
    # to be looked at — and only where this system has something to look at
    # it with (`gesichteraufbereitung.aufbereiten` asks the same question
    # first, and for the same reason).
    if not verfuegbar():
        log.info("Picture %s stays whole: no tool to shrink it here", quelle.name)
        return quelle
    # Beside the goal and then renamed: a stopped run must never leave a
    # half-written file under the name every later round would trust. The
    # token in the name is what keeps two calls for the SAME picture from
    # writing into each other's file — a fixed name would let the second
    # call delete what the first is still writing, and the half-finished
    # file could end up under the final name, where every round would trust
    # it from then on.
    roh = ziel_ordner / f"{quelle.stem}-{kennung}-{uuid.uuid4().hex}-teil.jpg"
    try:
        if not _zu_gross(quelle):
            _merken(ganz)
            return quelle
        ziel_ordner.mkdir(parents=True, exist_ok=True)
        if not _verkleinern(quelle, roh) or not roh.is_file():
            raise OSError("The copy was not written.")
        atomic_file.rename_onto(roh, ziel)
        return ziel
    except Exception as fehler:  # noqa: BLE001 — every one of them means "original"
        _weg(roh)
        log.warning("Picture %s goes out whole: %s", quelle.name, fehler)
        return quelle


def _merken(marke: Path) -> None:
    """Writes down the answer "this picture needs no copy", as an empty file
    beside where its copy would lie.

    Without it every round would measure the picture anew, and measuring
    means opening the file and reading its header. That is the cost this
    folder exists to keep out of a chat, and it is paid per attachment in
    EVERY round, because a picture that needs no copy never writes one to be
    found again.

    Failing to write it costs nothing but the next look: the answer is the
    same, only arrived at the slow way.
    """
    try:
        marke.parent.mkdir(parents=True, exist_ok=True)
        marke.touch()
    except OSError:
        pass


def _weg(datei: Path) -> None:
    """Removes what a stopped run may have left — and is allowed to fail:
    where the work folder could not even be made, its path is not a directory
    and the removal throws an error of its own. Nothing may escape the
    fallback that way."""
    try:
        datei.unlink(missing_ok=True)
    except OSError:
        pass


def aufraeumen(bilder_ordner: Path, kopien_ordner: Path) -> int:
    """Removes copies and markers whose picture no longer exists — the work
    folder is a cache, not an archive: it may only carry what a picture in
    the picture folder can still be answered with. A copy for a file OUTSIDE
    the picture folder — a picture read through `read_file` — has no picture
    here to be answered with either and goes with the others; the next read
    builds it again from the source (measured). Called once
    when the service starts (app/main.py).

    Matched by stem AND key, both: a picture renamed in place (same size,
    time, inode) keeps its key, and only the stem tells the old record from
    the current one — with the key alone the cache would grow by one entry
    per rename, forever.

    A folder that is not THERE is no empty one: it may be a volume that
    mounts late, and its copies are all it left — wiping them would be the
    wrong reading of "gone". The same for a walk that cannot look into every
    folder: nothing is removed on a partial list, because half a list would
    declare the other half gone (os.walk reports the folders it could not
    open, and rglob used to swallow exactly that).

    A file whose name does not carry a readable record exactly is not ours
    to judge and stays: an ordinary name with dashes
    (``urlaub-2024-08-01-12-30.jpg``), a half-written ``-teil`` file, and a
    picture dated before 1970 (its negative stamp cannot be told from the
    delimiters). Every removal may fail on its own: the start goes on and
    takes the rest."""
    kopien_ordner = Path(kopien_ordner)
    try:
        if not kopien_ordner.is_dir():
            return 0
        bilder_ordner = Path(bilder_ordner)
        if not bilder_ordner.is_dir():
            return 0
        # The pictures and the copies may never be the SAME folder (a
        # config.yaml or an old override can name it so): cleaning then
        # would compare the cache to itself, find every record unmatched
        # and unlink everything, at every start. The setzen path refuses
        # this; a hand-written value lands here.
        try:
            if bilder_ordner.samefile(kopien_ordner):
                log.warning(
                    "Picture folder and copies folder are the same folder — nothing removed"
                )
                return 0
        except OSError:
            pass
        vorhanden: set[tuple[str, str]] = set()
        gestolpert: list[OSError] = []
        unlesbar = False
        for wurzel, _ordner, dateinamen in os.walk(bilder_ordner, onerror=gestolpert.append):
            for name in dateinamen:
                pfad = Path(wurzel) / name
                try:
                    # One stat per entry (`_kennung` carries it), and what
                    # cannot be read counts as UNREADABLE, not as gone: a
                    # folder the walk cannot look into must not widen the
                    # list of the deceased (is_file()
                    # turned a chmod-0400 folder into "every copy is an
                    # orphan"). The stem is compared case-folded: a rename
                    # that only changes case keeps the key, and both names
                    # are one file on this platform's volumes.
                    vorhanden.add((pfad.stem.casefold(), _kennung(pfad)))
                except OSError:
                    unlesbar = True
                    break
            if unlesbar:
                break
        if gestolpert or unlesbar:
            log.warning(
                "Picture folder not fully readable (%d folder(s), unreadable files: %s)"
                " — nothing removed",
                len(gestolpert),
                unlesbar,
            )
            return 0
        dateien = list(kopien_ordner.iterdir())
    except OSError:
        return 0
    entfernt = 0
    for datei in dateien:
        try:
            if not datei.is_file():
                continue
            gelesen = _kennung_aus_name(datei.name)
            if gelesen is None or (gelesen[0].casefold(), gelesen[1]) in vorhanden:
                continue
            datei.unlink()
            entfernt += 1
        except OSError:
            continue
    return entfernt


def _zu_gross(datei: Path) -> bool:
    """Whether the file is over one of the two thresholds. Called only where
    the tool is there; a file whose size cannot be read counts as too large,
    and the copy falls back to the original anyway."""
    if datei.stat().st_size > BYTES_MAX:
        return True
    breite, hoehe = masse(datei)
    if breite is None or hoehe is None:
        return False
    return max(breite, hoehe) > KANTE_MAX


def _kennung(datei: Path) -> str:
    """What the copy was made from, in its name: size, modification time and
    the source's own extension.

    All four, because files really do agree in the others: `foto.png` and
    `foto.jpg` of the same size share a stem, and the extension tells them
    apart — the same trap `gesichteraufbereitung.py` names for its prepared
    photos. The time is taken in nanoseconds, not in whole seconds: a file
    rewritten within the second with the same byte count — an export over the
    old file, a copy that keeps times — would otherwise go on being answered
    with the copy of the PREVIOUS picture, silently. And the number every file
    on the volume has exactly once is what still separates two DIFFERENT
    pictures that agree in size, time and extension but carry one stem: two
    subfolders of the picture folder may each hold their own `foto.png`, and
    the model would otherwise be sent one of them twice."""
    stand = datei.stat()
    endung = datei.suffix.lstrip(".").lower() or "ohne"
    return f"{stand.st_size}-{stand.st_mtime_ns}-{stand.st_ino}-{endung}"


def _kennung_aus_name(name: str) -> tuple[str, str] | None:
    """The stem and key inside a work file's name, or ``None`` for a name
    that does not carry a record exactly. Read from the END — the stem of
    its own may contain dashes — and held to the SHAPE ``_kennung`` writes:
    three numeric fields and a non-numeric suffix. So an ordinary name with
    dashes (``urlaub-2024-08-01-12-30.jpg``) is not mistaken for a record,
    and neither is a half-written ``-teil`` file (its trailing fields are a
    token and ``teil``). A picture dated before 1970 writes a negative stamp
    whose leading minus eats a delimiter — such a record cannot be read back
    and stays, rather than being deleted at every start."""
    if name.endswith(".jpg"):
        rumpf = name[:-4]
    elif name.endswith(_GANZ_MARKE):
        rumpf = name[: -len(_GANZ_MARKE)]
    else:
        return None
    teile = rumpf.rsplit("-", 4)
    if len(teile) != 5 or not teile[0]:
        return None
    _stem, groesse, zeit, nummer, endung = teile
    if not (groesse.isdigit() and zeit.isdigit() and nummer.isdigit()):
        return None
    if not endung or endung.isdigit() or not endung.isalnum():
        return None
    return teile[0], "-".join(teile[1:])


def masse(datei: Path) -> tuple[int | None, int | None]:
    """Width and height as they stand in the file, or ``(None, None)`` for
    something the library does not read as a picture. Only the header is
    read: opening is lazy, the pixels stay on disk."""
    try:
        with Image.open(datei) as bild:
            breite, hoehe = bild.size
    except Exception:  # noqa: BLE001 — not a picture, whatever the reason
        return (None, None)
    return (breite, hoehe)


def scaled_copy(source: Path, target: Path, width: int, height: int) -> bool:
    """Writes ``source`` to ``target`` as a PNG of exactly ``width`` by
    ``height`` pixels. The source is only read, and read as it stands — no
    orientation applied, because the caller measured it the same way
    (``masse``) and the size it asks for follows those numbers. False where
    the library fails on the file — the reason is in the log."""
    try:
        with Image.open(source) as bild:
            bild.resize((int(width), int(height))).save(target, "PNG")
    except Exception as fehler:  # noqa: BLE001 — every one of them means "no copy"
        log.warning("Scaling %s: %s", source.name, fehler)
        return False
    return True


def geoeffnet(quelle: Path) -> Image.Image:
    """The picture as it stands: decoded, with the orientation a camera
    wrote into the file applied to the pixels and the file closed again. A
    copy written from this carries no metadata, so a phone photo taken
    upright would otherwise reach a model or a painter lying on its side.
    The one place that reads a picture for a copy (``_verkleinern`` here,
    ``gesichteraufbereitung._ein_foto_aufbereiten``) — raises what the
    library raises for a file that is no picture."""
    with Image.open(quelle) as datei:
        return ImageOps.exif_transpose(datei)


def on_white(bild: Image.Image) -> Image.Image:
    """The picture a copy is written from: one with see-through areas lies
    on white, the way a viewer shows it on paper, and is RGB afterwards.
    The one place this rule stands — the model's copy and the prepared face
    photos both come through here.

    JPEG carries no alpha channel, and ``convert("RGB")`` alone drops it
    without a ground: a fully see-through pixel is (0, 0, 0, 0) and turns
    black, so dark writing on a see-through ground would reach a model as
    black on black. A half see-through pixel mixes with white by its alpha.
    A picture without see-through areas keeps its colours, and a grey one
    stays grey."""
    if bild.has_transparency_data:
        # One white RGB ground and the alpha as the paste mask: no second
        # full-size RGBA copy for a picture of many megapixels.
        rgba = bild if bild.mode == "RGBA" else bild.convert("RGBA")
        ground = Image.new("RGB", rgba.size, (255, 255, 255))
        ground.paste(rgba, mask=rgba.getchannel("A"))
        return ground
    if bild.mode not in ("RGB", "L"):
        return bild.convert("RGB")
    return bild


def _verkleinern(quelle: Path, ziel: Path) -> bool:
    """One pass per rung, every rung resampled FROM THE SOURCE (re-encoding
    an already-encoded copy would stack JPEG generations): the picture's
    longest side is brought onto the rung with the ratio kept, then written
    as JPEG with the house quality.

    The first rung is ``KANTE_MAX`` — or the picture's own longer side where
    only the bytes were over; that edge must not grow, and ``thumbnail``
    never enlarges. While the result is still over ``BYTES_MAX``, the next
    rung is ``STUFENFAKTOR`` of this one, down to ``KLEINSTE_KANTE`` pixels
    at the most. A picture the ladder cannot bring under the threshold stays
    at its smallest attempt.

    The orientation a camera wrote into the file is applied to the pixels
    first: the copy carries no metadata, so a phone photo taken upright
    would otherwise reach the model lying on its side. A file the library
    cannot open, or a rung that fails, is False with the reason in the log —
    the caller falls back to the original, and the next warm-up tries
    again."""
    try:
        bild = on_white(geoeffnet(quelle))
        lang = max(bild.size)
        kante = min(lang, KANTE_MAX)
        while True:
            # ``thumbnail`` works in place, so a rung that resamples works
            # on a copy; a rung at the picture's own size (only the bytes
            # were over) writes the picture as it is.
            stufe = bild
            if kante < lang:
                stufe = bild.copy()
                stufe.thumbnail((kante, kante))
            stufe.save(ziel, "JPEG", quality=QUALITAET)
            if ziel.stat().st_size <= BYTES_MAX or kante <= KLEINSTE_KANTE:
                return True
            kante = max(KLEINSTE_KANTE, int(kante * STUFENFAKTOR))
    except Exception as fehler:  # noqa: BLE001 — every one of them means "original"
        log.warning("Shrinking %s: %s", quelle.name, fehler)
        return False
