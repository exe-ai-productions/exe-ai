"""Getting a person's ID photos into a shape sd-cli's PhotoMaker path can
actually use.

sd-cli scales every ID photo to 224 pixels internally, and on some source
dimensions that scale rounds down to 223 — one pixel short, and the face
transfer is silently skipped for the WHOLE batch, because all photos are
read together. Center-cropping to a square and resizing to a fixed edge
length here removes the rounding entirely: every photo that comes out has
exactly the same, exact dimensions, on purpose.

Pillow does the crop and the resize, on every system alike — it travels
with the package (``paste_back.py``, ``model_image.py``). The system tools
that stood here before (``sips`` on the Mac, ``System.Drawing`` over
PowerShell on Windows) took the same two steps in two scripts; now it is one
library and one path, the two steps in the same order as the hand-run helper
script (``Bildmodelle/Gesichter aufbereiten.command``) that came before all
of this.

The originals in ``faces/`` are never opened for writing — a prepared
copy lives in its own work folder, rebuilt only when the source photos
actually changed (a marker file holds ``photomaker.fingerabdruck()`` of the
last run), so Image-Turbo's own fingerprint of that folder
stays stable across repeated draws with the same photos.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app import model_image
from app.photomaker import BILDENDUNGEN, fingerabdruck

log = logging.getLogger(__name__)

# Measured: both 512 and 224 work on every problem photo
# from the table in the Auftrag. 512 is the choice — it leaves more detail
# for the face to be read from before PhotoMaker's own internal scale-down
# to 224, and it is the size the trusted hand-run helper script already used.
ZIEL_KANTE = 512

# The prepared copies' own companion folder, alongside vae/lora/photomaker/
# faces (app/api/v1/bild.py) — never in the whitelist that opens a
# folder by hand, since nobody is meant to put anything in it themselves.
ARBEITSORDNER = "faces_prepared"

_MARKENDATEI = ".quelle-fingerabdruck"

# How the copies are made. Part of the marker, so a folder prepared by an
# earlier way (see-through areas on black) is rebuilt instead of being taken
# for current because its photos have not changed. Raise it when the way the
# copies are made changes.
_AUFBEREITUNG = "weiss-1"


def verfuegbar() -> bool:
    """Whether this system can prepare a photo. The library travels with
    the package, so the answer is yes everywhere; the question stays
    because ``aufbereiten`` asks it first and a test that stands in for a
    system without the library answers it."""
    return True


def aufbereiten(
    gesichter_ordner: Path, arbeitsordner: Path, *, kante: int = ZIEL_KANTE
) -> Path | None:
    """Prepares a working copy of every photo in ``gesichter_ordner`` inside
    ``arbeitsordner`` and returns it. Only the top level of the source is
    read — a subfolder is where people keep an old set, not more photos to
    include (checked: sd-cli itself only reads the top level too).

    Not available (``verfuegbar`` says no): returns ``gesichter_ordner``
    unchanged. The 223-pixel gap this module exists to close stays open
    then, but nothing here makes it worse.

    Skipped, rather than rebuilt, when the source has not changed since the
    last call — the marker file is a fingerprint of the CURRENT photos, the
    same one Image-Turbo's own Gespann check uses, so a rebuild
    only ever happens when there is actually something new to read.

    ``None`` when nothing in the prepared folder is actually usable — every
    source photo turned out unreadable, say — the same silent gap
    ``photomaker.gesichter()`` itself already guards against for an empty
    ``faces/``: better no flags at all than flags pointing at an empty
    folder, which would load the generator, find no face, and draw an
    ordinary picture without saying why.
    """
    if not verfuegbar():
        return gesichter_ordner

    quelle_stand = f"{fingerabdruck(gesichter_ordner)}:{_AUFBEREITUNG}"
    marke = arbeitsordner / _MARKENDATEI
    bereits_aktuell = (
        arbeitsordner.is_dir() and marke.is_file()
        and marke.read_text(encoding="utf-8") == quelle_stand
    )
    if not bereits_aktuell:
        arbeitsordner.mkdir(parents=True, exist_ok=True)
        for alt in arbeitsordner.iterdir():
            if alt.is_file():
                alt.unlink()

        for datei in sorted(Path(gesichter_ordner).iterdir()):
            if not (datei.is_file() and datei.suffix.lower() in BILDENDUNGEN):
                continue
            # The extension travels into the name — the stem alone collides
            # the moment two photos share one (portrait.jpg, portrait.png).
            endung = datei.suffix.lstrip(".").lower()
            _ein_foto_aufbereiten(datei, arbeitsordner / f"{datei.stem}-{endung}.jpeg", kante)

        marke.write_text(quelle_stand, encoding="utf-8")

    if not any(datei.suffix == ".jpeg" for datei in arbeitsordner.iterdir()):
        return None
    return arbeitsordner


def _ein_foto_aufbereiten(quelle: Path, ziel: Path, kante: int) -> None:
    """A centred square off the shorter side, resampled to ``kante`` by
    ``kante``, written as JPEG — the same two steps, in the same order, the
    trusted hand-run helper script took. The original is only read; the
    orientation a phone wrote into it is applied first (``model_image.geoeffnet``),
    because the copy carries no metadata and sd-cli reads none. Any step failing (a file
    that is no picture, say) leaves nothing behind for this one photo
    instead of a half-processed file that would look like a real, safe
    one."""
    try:
        # See-through areas lie on white (the rule the model's picture copy
        # has, app/model_image.py): ``convert("RGB")`` alone turns them black,
        # and a face painted from a black ground is not the face of the photo.
        bild = model_image.on_white(model_image.geoeffnet(quelle))
        if bild.mode != "RGB":
            # Before the resample, not after: a palette picture resampled
            # as a palette is picked pixel by pixel, not blended.
            bild = bild.convert("RGB")
        seite = min(bild.size)
        links = (bild.width - seite) // 2
        oben = (bild.height - seite) // 2
        bild.crop((links, oben, links + seite, oben + seite)).resize((kante, kante)).save(ziel, "JPEG")
    except Exception as fehler:  # noqa: BLE001 — every one of them means "this photo is skipped"
        log.warning("Face %s skipped: %s", quelle.name, fehler)
        ziel.unlink(missing_ok=True)


def _masse(datei: Path) -> tuple[int | None, int | None]:
    """Width and height, or ``(None, None)`` for a file the library does
    not recognise as a picture — the one reading of a picture's size the
    program has (app/model_image.py)."""
    return model_image.masse(datei)
