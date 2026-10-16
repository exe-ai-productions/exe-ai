"""Images for vision input.

An image is uploaded BEFORE the message is sent and then lives as a file
under ``data/images/`` — the message only carries the file name. The bytes
belong in the filesystem, not in the database, and not in the API's chat
history.

The upload accepts raw bytes with a Content-Type (no multipart — that would
mean an extra dependency for a single purpose). Allowed are the three
formats that all vision servers understand. The server assigns the names
itself — nothing from the client reaches the filesystem.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import ordnerinhalt, studio_pictures
from app.api.abhaengigkeiten import hole_config, hole_repositories, hole_sprache
from app.bildmetadaten import metadaten_entfernen
from app.bildschutz import putzen_an
from app.config import Config
from app.db import Repositories
from app.i18n import t
from app.speicherorte import ort, scratch_pictures_dir

router = APIRouter(tags=["bilder"])

ERLAUBTE_TYPEN = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
# What the wall shows. Wider than what can be UPLOADED (``ERLAUBTE_TYPEN``
# above) on purpose: an upload is bytes this server has to name and vouch
# for, while the folder is the user's own — a picture a run generated, one
# dropped in from the file manager, one carried over from somewhere else.
# Every one of these renders in an <img> without a plugin.
#
# No SVG. It is markup, not pixels, and markup served from this origin can
# carry a script; a picture wall is not the place to open that door.
#
# And no GIF, which is the harder call: the folder may hold one, and this
# whole change exists to show what the folder holds. But every other path a
# picture takes in this program is png/jpeg/webp — what may be uploaded
# (``ERLAUBTE_TYPEN``), what the chat accepts as an attachment
# (``BILD_TYPEN``, Eingabeleiste.svelte), what a message carries to a model.
# A tile the window offers and then refuses when it is dragged into the chat
# is worse than one that is not there; widening those three is its own piece
# of work, and it has to start at the model end.
ANZEIGBARE_ENDUNGEN = frozenset({".png", ".jpg", ".jpeg", ".webp"})

# What each of them is served as.
MEDIENTYPEN = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# The videos the picture window draws (app/image_switches.py VIDEO_FORMATS;
# an animated WebP is served as a picture above). Served for the chat and
# the window's gallery, which play them; not on the wall, whose tiles are
# pictures one drags into a message.
VIDEO_MEDIENTYPEN = {
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
}

# Only genuinely empty files are held back. The hundred-byte floor that used
# to stand here was a junk filter from the days when ANY file in the folder
# could reach the wall; the suffix check above does that job now, and the
# floor only went on to hide real pictures — a 24-pixel square of one colour
# is 88 bytes, and a valid PNG can be 67. A folder that shows what is in it
# has to show those too; a truncated file shows as a broken tile, which is
# the honest answer and one the hand can act on, unlike silence.
MINDESTGROESSE = 1


def bilder_verzeichnis(config: Config):
    return ort(config, "images")


def bilder_entfernen(ordner, namen) -> list[str]:
    """Deletes these pictures from the picture folder and only there: a name
    that leaves the folder, or a link inside it pointing out, finds nothing
    (`ordnerinhalt.sicherer_pfad`). Returns the names that went."""
    weg: list[str] = []
    for name in namen:
        datei = ordnerinhalt.sicherer_pfad(ordner, name)
        if datei is None or not datei.is_file():
            continue
        try:
            datei.unlink()
        except OSError:
            continue
        weg.append(name)
    return weg


def empty_scratch_pictures(config: Config) -> int:
    """Removes the picture studio's working pictures, every one: what a
    draw was made from is made again for the next. Returns how many went. A
    folder that is not there is the state before the first one."""
    try:
        files = [entry for entry in scratch_pictures_dir(config).iterdir() if entry.is_file()]
    except OSError:
        return 0
    gone = 0
    for file in files:
        try:
            file.unlink()
        except OSError:
            continue
        gone += 1
    return gone


class BildAntwort(BaseModel):
    bild: str


class BilderListe(BaseModel):
    # The saved pictures, newest first — names only; the caller builds each
    # address with the existing /images/{name} route.
    bilder: list[str]


@router.get("/bilder", response_model=BilderListe, summary="List saved images")
def bilder_auflisten(
    chat: str | None = None,
    projekt: str | None = None,
    studio: bool = False,
    config: Config = Depends(hole_config),
    repositories: Repositories = Depends(hole_repositories),
) -> BilderListe:
    """Every saved picture in the picture folder, newest first. A missing
    folder is not an error — it is the state before the first picture, and
    the answer is simply an empty list.

    With ``chat`` only that chat's pictures, with ``projekt`` those of every
    chat of the project — found through the rows that name them, and only
    those still in the folder. With ``studio`` those the picture studio
    drew (app/studio_pictures.py), by the same rule."""
    # Whatever is in the folder, by what it IS rather than by what it is
    # called. The list used to be filtered by a name pattern this server
    # mints itself, so a picture a run wrote as `diagramm.png` sat in the
    # user's own picture folder and never appeared on the wall.
    treffer = ordnerinhalt.auflisten(
        bilder_verzeichnis(config),
        endungen=ANZEIGBARE_ENDUNGEN,
        mindestgroesse=MINDESTGROESSE,
    )
    if chat is None and projekt is None and not studio:
        return BilderListe(bilder=[p.name for p in treffer])
    da = {p.name for p in treffer}
    genannt = (
        studio_pictures.names(repositories) if studio
        else repositories.messages.bilder_von(chat_id=chat, projekt_id=None if chat else projekt)
    )
    return BilderListe(bilder=[name for name in genannt if name in da])


@router.post(
    "/images",
    response_model=BildAntwort,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an image for a message (raw bytes)",
)
async def bild_hochladen(
    request: Request,
    scratch: bool = False,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> BildAntwort:
    """``scratch`` lays the picture among the studio's working pictures
    instead of into the picture folder: made for a draw, on no wall, gone
    with the next start of the service."""
    typ = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if typ not in ERLAUBTE_TYPEN:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, t("fehler.bild_typ", sprache)
        )
    daten = await request.body()
    # No size ceiling here any more: every picture of the allowed kinds is
    # taken and stored as it came. What the MODEL gets is a smaller copy
    # where the file is large (app/model_image.py) — the upload is the
    # person's file and stays the person's file.
    if not daten:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, t("fehler.bild_typ", sprache))

    verzeichnis = scratch_pictures_dir(config) if scratch else bilder_verzeichnis(config)
    verzeichnis.mkdir(parents=True, exist_ok=True)
    # An uploaded photo can carry EXIF — camera, time, place — and it would
    # travel to a cloud vision model untouched. Stripped here when the switch
    # is on, on the one path every upload takes to disk.
    if putzen_an(request.app.state.repositories):
        daten = metadaten_entfernen(daten)
    # The name comes from the bytes as they are stored: the same picture
    # sent again — a message the service refused, sent once more — is the
    # same file, not a second one beside it. 16 bytes of digest are the 32
    # hex digits a stored picture's name has always had.
    name = hashlib.blake2b(daten, digest_size=16).hexdigest() + ERLAUBTE_TYPEN[typ]
    ziel = verzeichnis / name
    # A file of the same name and the same size is the same picture; a
    # shorter one is what a cut-off write left behind and is written again.
    if not (ziel.is_file() and ziel.stat().st_size == len(daten)):
        ziel.write_bytes(daten)
    return BildAntwort(bild=name)


@router.get("/images/{name}", summary="Serve an uploaded image")
def bild_holen(
    name: str,
    config: Config = Depends(hole_config),
    sprache: str = Depends(hole_sprache),
) -> FileResponse:
    # The name pattern used to be the guard here, and it was doing two jobs:
    # keeping path tricks out, and deciding which files exist at all. Only
    # the first was ever needed — that one is `sicherer_pfad`, which also
    # catches what a pattern never could, a link inside the folder pointing
    # out of it.
    datei = ordnerinhalt.sicherer_pfad(bilder_verzeichnis(config), name)
    medientyp = {**MEDIENTYPEN, **VIDEO_MEDIENTYPEN}.get(datei.suffix.lower()) if datei else None
    if datei is None or medientyp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("fehler.bild_fehlt", sprache))
    return FileResponse(datei, media_type=medientyp)
