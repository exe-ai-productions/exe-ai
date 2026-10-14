"""The model's picture copies (app/model_image.py), built with the library
that travels with the package: the edge, the ladder, the orientation a
camera wrote into a file, and what a file that is no picture gets. The
same on every system — there is one path now, not one tool per platform.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app import model_image


def _png(path: Path, width: int, height: int) -> Path:
    Image.new("RGB", (width, height), (90, 120, 200)).save(path, "PNG")
    return path


def _jpeg_turned(path: Path, width: int, height: int, orientation: int) -> Path:
    """A JPEG whose pixels lie ``width`` by ``height`` and whose EXIF says
    the camera held them turned — the shape every phone photo has."""
    exif = Image.Exif()
    exif[0x0112] = orientation
    Image.new("RGB", (width, height), (200, 90, 60)).save(path, "JPEG", exif=exif.tobytes())
    return path


def _copies(work: Path) -> list[Path]:
    return sorted(p for p in work.iterdir() if p.suffix == ".jpg") if work.is_dir() else []


def test_the_library_is_there_on_every_system():
    assert model_image.verfuegbar() is True


def test_a_large_picture_gets_a_copy_at_the_edge(tmp_path: Path):
    source = _png(tmp_path / "gross.png", 3000, 2000)
    work = tmp_path / "work"

    copy = model_image.kopie(source, work)

    assert copy != source and copy.suffix == ".jpg"
    assert model_image.masse(copy) == (model_image.KANTE_MAX, 1280)
    # Found again, not built twice: the same file on the second round.
    assert model_image.kopie(source, work) == copy
    assert _copies(work) == [copy]


def test_a_small_picture_travels_as_it_is(tmp_path: Path):
    source = _png(tmp_path / "klein.png", 800, 600)
    work = tmp_path / "work"

    assert model_image.kopie(source, work) == source
    assert _copies(work) == []
    # The answer "no copy needed" is on record beside where the copy would lie.
    assert any(p.name.endswith("-ganz") for p in work.iterdir())


def test_the_orientation_of_a_phone_photo_is_applied(tmp_path: Path):
    """Pixels 2500 by 1000, held turned by a quarter: the picture stands
    1000 by 2500, and the copy is built from the picture as it stands — the
    copy carries no metadata that could say so afterwards."""
    source = _jpeg_turned(tmp_path / "foto.jpg", 2500, 1000, orientation=6)
    assert model_image.masse(source) == (2500, 1000)

    copy = model_image.kopie(source, tmp_path / "work")

    assert copy != source
    assert model_image.masse(copy) == (768, model_image.KANTE_MAX)


def test_the_ladder_steps_down_while_the_bytes_are_over(tmp_path: Path, monkeypatch):
    """With a byte threshold nothing can fit under, the ladder walks every
    rung down to the smallest edge and stops there — the copy is the
    smallest attempt, not nothing."""
    monkeypatch.setattr(model_image, "BYTES_MAX", 1)
    source = _png(tmp_path / "gross.png", 3000, 2000)

    copy = model_image.kopie(source, tmp_path / "work")

    assert copy != source
    assert max(model_image.masse(copy)) == model_image.KLEINSTE_KANTE  # type: ignore[type-var]


def test_a_file_that_is_no_picture_goes_out_whole(tmp_path: Path):
    source = tmp_path / "kein.png"
    source.write_bytes(b"\x89PNG but nothing behind it" * 200_000)
    work = tmp_path / "work"

    assert model_image.masse(source) == (None, None)
    assert model_image.kopie(source, work) == source
    assert not work.is_dir() or list(work.iterdir()) == []


def test_a_failing_shrink_leaves_nothing_behind(tmp_path: Path, monkeypatch):
    """The silence side of the copy: a library that fails on the file
    hands the original on, and no half-written file stays under any name."""
    source = _png(tmp_path / "gross.png", 3000, 2000)
    work = tmp_path / "work"

    def fails(quelle, ziel):
        raise OSError("cannot write")

    monkeypatch.setattr(model_image, "_verkleinern", fails)
    assert model_image.kopie(source, work) == source
    assert list(work.iterdir()) == []


def test_scaled_copy_keeps_the_picture_as_it_stands(tmp_path: Path):
    """The copy for the painter follows the numbers ``masse`` read — the
    pixels as they lie in the file, orientation and all — because the size
    asked for was reckoned from those."""
    source = _jpeg_turned(tmp_path / "foto.jpg", 300, 100, orientation=6)
    target = tmp_path / "klein.png"

    assert model_image.scaled_copy(source, target, 30, 10) is True
    assert model_image.masse(target) == (30, 10)


def test_scaled_copy_says_false_for_a_file_that_is_no_picture(tmp_path: Path):
    source = tmp_path / "kein.png"
    source.write_bytes(b"nothing")
    target = tmp_path / "klein.png"

    assert model_image.scaled_copy(source, target, 30, 10) is False
    assert not target.exists()


def _large_see_through(path: Path, mode: str) -> Path:
    """A picture over the edge whose left half is fully see-through and
    whose right half is black: at half strength (alpha 128) in RGBA, fully
    opaque in a palette picture whose colour 0 is the see-through one."""
    width, height = model_image.KANTE_MAX + 400, 200
    if mode == "P":
        image = Image.new("P", (width, height), 0)
        image.putpalette([0, 0, 0, 0, 0, 0] + [0, 0, 0] * 254)
        image.paste(1, (width // 2, 0, width, height))
        image.info["transparency"] = 0
        image.save(path, "PNG", transparency=0)
        return path
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    image.paste((0, 0, 0, 128), (width // 2, 0, width, height))
    image.save(path, "PNG")
    return path


def _pixel(copy: Path, x_part: float) -> tuple[int, ...]:
    with Image.open(copy) as image:
        return image.convert("RGB").getpixel((int(image.width * x_part), image.height // 2))


def test_a_see_through_area_of_the_copy_lies_on_white(tmp_path: Path):
    source = _large_see_through(tmp_path / "durchsicht.png", "RGBA")

    copy = model_image.kopie(source, tmp_path / "work")

    assert copy != source and copy.suffix == ".jpg"
    # Fully see-through: white (JPEG tolerance); half see-through black: mid grey.
    assert all(channel >= 250 for channel in _pixel(copy, 0.25))
    assert all(115 <= channel <= 140 for channel in _pixel(copy, 0.75))


def test_a_palette_picture_with_a_see_through_colour_lies_on_white(tmp_path: Path):
    source = _large_see_through(tmp_path / "palette.png", "P")

    copy = model_image.kopie(source, tmp_path / "work")

    assert copy.suffix == ".jpg"
    assert all(channel >= 250 for channel in _pixel(copy, 0.25))
    assert all(channel <= 10 for channel in _pixel(copy, 0.75))


def test_a_picture_without_see_through_areas_keeps_its_colours(tmp_path: Path):
    """Silence: an RGB picture keeps its colours and a grey one stays grey."""
    source = tmp_path / "gross.png"
    Image.new("RGB", (model_image.KANTE_MAX + 400, 200), (90, 120, 200)).save(source, "PNG")
    grey = tmp_path / "grau.png"
    Image.new("L", (model_image.KANTE_MAX + 400, 200), 77).save(grey, "PNG")

    coloured = model_image.kopie(source, tmp_path / "work")
    greyed = model_image.kopie(grey, tmp_path / "work")

    red, green, blue = _pixel(coloured, 0.5)
    assert abs(red - 90) <= 4 and abs(green - 120) <= 4 and abs(blue - 200) <= 4
    with Image.open(greyed) as image:
        assert image.mode == "L"


def test_a_small_see_through_picture_goes_out_unchanged(tmp_path: Path):
    """Silence: under both thresholds the original is sent, not a copy."""
    source = tmp_path / "klein.png"
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(source, "PNG")

    assert model_image.kopie(source, tmp_path / "work") == source
