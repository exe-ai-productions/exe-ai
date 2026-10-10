"""A drawn piece, set back into the picture it was cut from.

The drawing surface can hand the painter only a part of a picture: the part
its frame shows. The painter then draws that part and nothing else, and its
file is the part alone. Here the part goes back where it came from, so the
result is the whole picture again, at its own size, with the piece drawn anew
in its place.

With a mask only what was painted over replaces the picture; without one the
whole piece does. Either way the edge of what is set in fades out over a few
pixels, towards the inside: nothing of the drawn piece ever lands outside the
mask or outside the piece's place, and no hard seam shows where new meets
old. Where the piece's place lies on the picture's own border there is
nothing to fade into, and it stays whole there.

The picture the piece was cut from is only read. It is taken the way it is
looked at: a photo stored lying on its side with a note to turn it is turned
first, since the piece's place was measured on the picture as shown. Its
colour profile goes into the result, so what was not drawn keeps its colours;
and what the painter wrote beside its pixels — prompt, seed and settings —
stands in the result too.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, JpegImagePlugin
from PIL.PngImagePlugin import PngInfo

log = logging.getLogger(__name__)

# The pixels over which the edge of what is set in fades out.
FEATHER = 4

Box = tuple[int, int, int, int]


def paste_back(
    whole: Image.Image, piece: Image.Image, box: Box, mask: Image.Image | None = None,
) -> Image.Image | None:
    """``whole`` with ``piece`` in the place ``box`` names — x, y, width and
    height in the pixels of ``whole`` — or None where that place does not lie
    inside the picture with a width and a height.

    The piece is scaled to the size of its place. ``mask`` is the piece's
    own, white where it was drawn over; without one the whole piece counts
    as drawn."""
    x, y, width, height = box
    if (width <= 0 or height <= 0 or x < 0 or y < 0
            or x + width > whole.width or y + height > whole.height):
        return None
    size = (width, height)
    if mask is None:
        cover = Image.new("L", size, 255)
    else:
        cover = mask.convert("L").resize(size, Image.Resampling.BILINEAR)
    transparent = whole.mode in ("RGBA", "LA", "PA") or "transparency" in whole.info
    mode = "RGBA" if transparent else "RGB"
    result = _eight_bit(whole).convert(mode)
    drawn = _eight_bit(piece).convert(mode).resize(size, Image.Resampling.LANCZOS)
    result.paste(drawn, (x, y), _feathered(cover, x, y, whole.size))
    return result


def _eight_bit(picture: Image.Image) -> Image.Image:
    """A grey picture of 16 bits in 8. Converted as it is, every value above
    255 would be cut off at white."""
    if picture.mode == "I" or picture.mode.startswith("I;16"):
        return picture.convert("I").point(lambda value: value / 256).convert("L")
    return picture


def _feathered(cover: Image.Image, x: int, y: int, whole: tuple[int, int]) -> Image.Image:
    """``cover`` with its edges fading out over ``FEATHER`` pixels, inwards.

    It is laid into as much of its surroundings as the fade reaches, where it
    covers nothing; shrunk by half the fade and blurred over the same
    distance, it rises from nothing at its edge to full. The surroundings end
    at the picture's border, and both filters continue an image by its
    outermost pixels: an edge lying on that border does not fade."""
    width, height = cover.size
    left, top = max(0, x - FEATHER), max(0, y - FEATHER)
    right = min(whole[0], x + width + FEATHER)
    bottom = min(whole[1], y + height + FEATHER)
    around = Image.new("L", (right - left, bottom - top), 0)
    around.paste(cover, (x - left, y - top))
    around = around.filter(ImageFilter.MinFilter(FEATHER + 1)).filter(
        ImageFilter.BoxBlur(FEATHER / 2)
    )
    return around.crop((x - left, y - top, x - left + width, y - top + height))


def into_whole(drawn: Path, whole: Path, box: Box, mask: Path | None = None) -> bool:
    """Makes the painter's file ``drawn`` the picture ``whole`` with the
    drawn piece in its place, in the format the painter wrote. False, and
    the painter's file as it was, where the place does not lie in the
    picture or one of the files is no picture."""
    try:
        with Image.open(drawn) as piece, Image.open(whole) as stored:
            picture = ImageOps.exif_transpose(stored)
            if mask is None:
                result = paste_back(picture, piece, box)
            else:
                with Image.open(mask) as cover:
                    result = paste_back(picture, piece, box, cover)
            if result is None:
                log.info(
                    "Picture %s stays the drawn piece: %s does not lie in %s (%dx%d)",
                    drawn.name, list(box), whole.name, picture.width, picture.height,
                )
                return False
            written = _encoded(result, piece, stored.info.get("icc_profile"))
    except Exception as error:  # noqa: BLE001 — every one of them means "the painter's file stays"
        log.warning("Picture %s stays the drawn piece: %s", drawn.name, error)
        return False
    drawn.write_bytes(written)
    log.info("Picture %s is %s with the drawn piece at %s", drawn.name, whole.name, list(box))
    return True


def _encoded(result: Image.Image, painted: Image.Image, profile: bytes | None) -> bytes:
    """``result`` as a file of the format the painter wrote, with what the
    painter wrote beside its pixels and the colour profile ``profile``."""
    out = io.BytesIO()
    if painted.format == "JPEG":
        # Compressed the way the painter compressed its own file: with its
        # tables, so the result is neither coarser nor needlessly larger.
        kept = {name: painted.info[name] for name in ("exif", "comment") if name in painted.info}
        result.convert("RGB").save(
            out, "JPEG", qtables=painted.quantization,
            subsampling=JpegImagePlugin.get_sampling(painted), icc_profile=profile, **kept,
        )
    elif painted.format == "WEBP":
        # Lossless: the result is the painter's pixels and the picture's,
        # set together, and no second round of loss is laid over either.
        kept = {name: painted.info[name] for name in ("exif", "xmp") if name in painted.info}
        result.save(out, "WEBP", lossless=True, icc_profile=profile, **kept)
    else:
        beside = PngInfo()
        for key, text in getattr(painted, "text", {}).items():
            beside.add_text(key, text)
        result.save(out, "PNG", pnginfo=beside, icc_profile=profile)
    return out.getvalue()
