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
