"""A drawn piece is set back into the picture it was cut from: the result has
the picture's size, carries the piece where it was cut out, and the picture
everywhere else; the edge of what is set in fades inwards over a few pixels;
and the picture the piece came from is never written to."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageCms
from PIL.PngImagePlugin import PngInfo

from app import paste_back

OLD = (10, 60, 200)
NEW = (240, 180, 20)
BOX = (50, 100, 100, 100)


def _whole() -> Image.Image:
    return Image.new("RGB", (200, 300), OLD)


def _piece(size: tuple[int, int] = (50, 50)) -> Image.Image:
    """The drawn piece, at another size than its place in the picture."""
    return Image.new("RGB", size, NEW)


def _mask() -> Image.Image:
    """The piece's mask: a white square in its middle. In the picture the
    square reaches from 80 to 119 across and from 130 to 169 down."""
    mask = Image.new("L", (50, 50), 0)
    mask.paste(255, (15, 15, 35, 35))
    return mask


def _between(colour: tuple[int, ...]) -> bool:
    """Neither the old colour nor the new one, and between the two."""
    return colour not in (OLD, NEW) and all(
        min(old, new) <= value <= max(old, new)
        for value, old, new in zip(colour, OLD, NEW, strict=True)
    )


def test_with_a_mask_only_what_was_painted_replaces_the_picture():
    result = paste_back.paste_back(_whole(), _piece(), BOX, _mask())
    assert result.size == (200, 300)
    # The middle of the square carries the piece.
    assert result.getpixel((100, 150)) == NEW
    # Outside the piece's place the picture stays.
    assert result.getpixel((10, 10)) == OLD
    assert result.getpixel((49, 150)) == OLD
    # Inside the place but outside the mask it stays too.
    assert result.getpixel((55, 105)) == OLD
    assert result.getpixel((75, 150)) == OLD
    # The square's edge lies between the two.
    assert _between(result.getpixel((81, 150)))
    assert _between(result.getpixel((100, 168)))


def test_the_edge_fades_over_four_pixels_towards_the_inside():
    result = paste_back.paste_back(_whole(), _piece(), BOX)
    row = [result.getpixel((x, 150))[0] for x in range(48, 56)]
    # Two pixels of the picture, four steps towards the piece, then the piece.
    assert row[:2] == [OLD[0], OLD[0]]
    assert row[2] < row[3] < row[4] < row[5] < row[6]
    assert row[6:] == [NEW[0], NEW[0]]
    assert all(_between(result.getpixel((x, 150))) for x in range(50, 54))


def test_without_a_mask_the_whole_place_carries_the_piece():
    result = paste_back.paste_back(_whole(), _piece(), BOX)
    assert result.size == (200, 300)
    for point in ((100, 150), (54, 104), (145, 104), (54, 195), (145, 195)):
        assert result.getpixel(point) == NEW, point
    for point in ((49, 150), (150, 150), (100, 99), (100, 200), (10, 290)):
        assert result.getpixel(point) == OLD, point


def test_a_place_on_the_picture_s_border_does_not_fade_there():
    """Where the piece's place is the whole picture, the result is the piece."""
    result = paste_back.paste_back(_whole(), _piece((100, 150)), (0, 0, 200, 300))
    assert result.getcolors() == [(200 * 300, NEW)]
    # In a corner the two outer edges stay whole, the two inner ones fade.
    corner = paste_back.paste_back(_whole(), _piece(), (0, 0, 100, 100))
    assert corner.getpixel((0, 0)) == NEW
    assert corner.getpixel((0, 50)) == NEW
    assert _between(corner.getpixel((99, 50)))
    assert corner.getpixel((100, 50)) == OLD


def test_a_place_that_does_not_lie_in_the_picture_is_refused():
    for box in ((150, 100, 100, 100), (50, 250, 100, 100), (-1, 0, 50, 50), (0, -1, 50, 50),
                (50, 100, 0, 100), (50, 100, 100, 0), (0, 0, 201, 300)):
        assert paste_back.paste_back(_whole(), _piece(), box) is None, box


def test_the_picture_the_piece_came_from_is_not_changed():
    whole = _whole()
    before = whole.tobytes()
    paste_back.paste_back(whole, _piece(), BOX, _mask())
    assert whole.tobytes() == before


def test_a_picture_with_transparency_keeps_it():
    whole = Image.new("RGBA", (200, 300), (*OLD, 0))
    result = paste_back.paste_back(whole, _piece(), BOX)
    assert result.mode == "RGBA"
    assert result.getpixel((10, 10)) == (*OLD, 0)
    assert result.getpixel((100, 150)) == (*NEW, 255)


def test_a_grey_picture_of_16_bits_keeps_its_brightness():
    whole = Image.new("I;16", (200, 300), 30000)
    result = paste_back.paste_back(whole, _piece(), BOX)
    assert result.getpixel((10, 10)) == (117, 117, 117)
    assert result.getpixel((100, 150)) == NEW


def _files(tmp_path: Path, kind: str = "PNG") -> tuple[Path, Path, Path]:
    whole = tmp_path / "whole.png"
    _whole().save(whole)
    mask = tmp_path / "mask.png"
    _mask().save(mask)
    drawn = tmp_path / ("drawn.png" if kind == "PNG" else "drawn.jpg")
    if kind == "PNG":
        beside = PngInfo()
        beside.add_text("parameters", "a lighthouse\nSteps: 8, Seed: 7")
        _piece().save(drawn, pnginfo=beside)
    else:
        _piece().save(drawn, "JPEG", comment=b"a lighthouse", quality=88)
    return whole, mask, drawn


def test_the_painter_s_file_becomes_the_whole_picture_with_its_settings(tmp_path):
    whole, mask, drawn = _files(tmp_path)
    before = whole.read_bytes()
    assert paste_back.into_whole(drawn, whole, BOX, mask) is True
    with Image.open(drawn) as result:
        assert (result.format, result.size) == ("PNG", (200, 300))
        assert result.text == {"parameters": "a lighthouse\nSteps: 8, Seed: 7"}
        assert result.convert("RGB").getpixel((100, 150)) == NEW
        assert result.convert("RGB").getpixel((10, 10)) == OLD
    assert whole.read_bytes() == before


def test_a_jpeg_stays_a_jpeg(tmp_path):
    whole, _mask_file, drawn = _files(tmp_path, "JPEG")
    with Image.open(drawn) as painted:
        tables = painted.quantization
    assert paste_back.into_whole(drawn, whole, BOX) is True
    with Image.open(drawn) as result:
        assert (result.format, result.size) == ("JPEG", (200, 300))
        assert result.info["comment"] == b"a lighthouse"
        # Compressed with the painter's own tables.
        assert result.quantization == tables


def test_a_webp_stays_a_webp(tmp_path):
    """A piece the painter wrote as WebP comes back as a WebP of the whole
    picture, with what the painter wrote beside its pixels; the picture
    around the piece is the source picture's, pixel for pixel."""
    whole, _mask_file, _png = _files(tmp_path)
    drawn = tmp_path / "drawn.webp"
    note = Image.Exif()
    note[0x010E] = "a lighthouse"
    _piece().save(drawn, "WEBP", lossless=True, exif=note)
    assert paste_back.into_whole(drawn, whole, BOX) is True
    with Image.open(drawn) as result:
        assert (result.format, result.size) == ("WEBP", (200, 300))
        assert Image.Exif.tobytes(result.getexif()) == Image.Exif.tobytes(note)
        assert result.convert("RGB").getpixel((100, 150)) == NEW
        assert result.convert("RGB").getpixel((10, 10)) == OLD


def test_a_photo_stored_on_its_side_is_taken_the_way_it_is_shown(tmp_path):
    """Stored 300 by 200 with the note to turn it: it is looked at as 200 by
    300, the piece's place was measured on that, and so is the result."""
    whole, mask, drawn = _files(tmp_path)
    turn = Image.Exif()
    turn[0x0112] = 6
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (300, 200), OLD).save(photo, "JPEG", exif=turn)
    assert paste_back.into_whole(drawn, photo, BOX, mask) is True
    with Image.open(drawn) as result:
        assert result.size == (200, 300)
        assert result.convert("RGB").getpixel((100, 150)) == NEW


def test_the_picture_s_colour_profile_goes_into_the_result(tmp_path):
    whole, mask, drawn = _files(tmp_path)
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    _whole().save(whole, icc_profile=profile)
    assert paste_back.into_whole(drawn, whole, BOX, mask) is True
    with Image.open(drawn) as result:
        assert result.info["icc_profile"] == profile
        assert result.text == {"parameters": "a lighthouse\nSteps: 8, Seed: 7"}


def test_the_painter_s_file_stays_where_the_piece_cannot_be_set_in(tmp_path):
    """The silence check: a place beyond the picture, a picture that is not
    one, a missing picture and a painter's file that is no picture."""
    whole, mask, drawn = _files(tmp_path)
    painted = drawn.read_bytes()
    assert paste_back.into_whole(drawn, whole, (150, 100, 100, 100), mask) is False
    assert drawn.read_bytes() == painted
    no_picture = tmp_path / "text.png"
    no_picture.write_bytes(b"not a picture")
    assert paste_back.into_whole(drawn, no_picture, BOX, mask) is False
    assert paste_back.into_whole(drawn, tmp_path / "gone.png", BOX, mask) is False
    assert paste_back.into_whole(drawn, whole, BOX, no_picture) is False
    assert drawn.read_bytes() == painted
    assert paste_back.into_whole(no_picture, whole, BOX) is False
    assert no_picture.read_bytes() == b"not a picture"
