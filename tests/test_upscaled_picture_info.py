"""A picture that was enlarged says by what factor and how large it is now.

The route keeps, for a picture it enlarged, what its original was kept with
(the drawing values stay as they were) and beside them ``upscaled``: the
factor and the finished picture's size, both read from the files
(app/upscaled_info.py). Where the original cannot be read only the size
stands. A picture that was drawn, or whose faces were repaired, has none.

The studio draws without a chat and keeps the same values for its pictures
(app/studio_pictures.py), so its pictures answer the same way.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import studio_pictures, upscaled_info
from app.bildrunner import Bildrunner
from app.config import Config
from tests import upscaler_file
from app.speicherorte import ort
from tests.test_bild_lauf_api import _info, bild_senden  # noqa: F401


@pytest.fixture
def paints(monkeypatch):
    """Sets the size of the next picture the painter writes."""
    size = {"now": (8, 8)}

    def paint(self, job, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size["now"]).save(target, "PNG")
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", paint)

    def set_size(width: int, height: int) -> None:
        size["now"] = (width, height)

    return set_size


@pytest.fixture
def enlarge(bild_senden, paints, config: Config, tmp_path: Path, chat_id):  # noqa: F811
    """Draws an original of the given size, then enlarges it into a result of
    another, and hands back the names of both."""
    models = tmp_path / "bildmodelle"
    (models / "upscaler").mkdir(parents=True, exist_ok=True)
    upscaler_file.write(models / "upscaler" / "big.pth")
    (models / "adetailer").mkdir(parents=True, exist_ok=True)
    (models / "adetailer" / "face.pt").write_bytes(b"x")

    def run(original: tuple[int, int], result: tuple[int, int], *, mode: str = "upscale",
            unreadable: bool = False) -> tuple[str, str]:
        paints(*original)
        first = bild_senden(chat_id, prompt="a lighthouse", breite=original[0], hoehe=original[1], seed=7)["bild"]
        if unreadable:
            (ort(config, "images") / first).write_bytes(b"not a picture")
        paints(*result)
        second = bild_senden(
            chat_id, startbild=first, mode=mode, upscale_model="big.pth", ad_modell="face.pt",
            frage_erstellen=False,
        )["bild"]
        return first, second

    return run


def test_an_enlarged_picture_keeps_its_drawing_values_and_says_factor_and_size(
    enlarge, client: TestClient,
):
    first, second = enlarge((512, 768), (2048, 3072))
    original = _info(client, first)
    enlarged = _info(client, second)
    assert enlarged.pop("upscaled") == {"faktor": 4, "breite": 2048, "hoehe": 3072}
    # The values the original was drawn with stand as they were.
    assert enlarged == original
    assert (original["breite"], original["hoehe"]) == (512, 768)


def test_a_factor_that_is_no_whole_number_has_one_decimal(enlarge, client: TestClient):
    _, second = enlarge((1024, 1536), (1536, 2304))
    assert _info(client, second)["upscaled"] == {"faktor": 1.5, "breite": 1536, "hoehe": 2304}


def test_where_the_original_cannot_be_read_only_the_size_stands(enlarge, client: TestClient):
    _, second = enlarge((512, 512), (2048, 2048), unreadable=True)
    assert _info(client, second)["upscaled"] == {"breite": 2048, "hoehe": 2048}


def test_enlarging_again_says_only_the_new_step(enlarge, bild_senden, paints, client, chat_id):  # noqa: F811
    _, second = enlarge((256, 256), (1024, 1024))
    paints(2048, 2048)
    third = bild_senden(
        chat_id, startbild=second, mode="upscale", upscale_model="big.pth", frage_erstellen=False,
    )["bild"]
    assert _info(client, third)["upscaled"] == {"faktor": 2, "breite": 2048, "hoehe": 2048}


def test_silence_a_drawn_picture_and_a_repair_say_nothing_of_an_enlarging(
    enlarge, bild_senden, client: TestClient, chat_id,  # noqa: F811
):
    first, repaired = enlarge((64, 64), (64, 64), mode="adetailer")
    assert "upscaled" not in _info(client, first)
    assert "upscaled" not in _info(client, repaired)


def test_the_size_and_the_factor_come_out_of_the_files(tmp_path: Path):
    original = tmp_path / "a.png"
    result = tmp_path / "b.png"
    Image.new("RGB", (100, 50)).save(original)
    Image.new("RGB", (300, 150)).save(result)
    assert upscaled_info.of(original, result) == {"faktor": 3, "breite": 300, "hoehe": 150}
    assert upscaled_info.of(None, result) == {"breite": 300, "hoehe": 150}
    assert upscaled_info.of(original, tmp_path / "gone.png") is None


@pytest.fixture
def studio(bild_senden, paints, tmp_path: Path, client: TestClient):  # noqa: F811
    """Draws in the studio: no chat, the studio's mark, with the metadata
    protection at its default (on)."""
    models = tmp_path / "bildmodelle"
    (models / "upscaler").mkdir(parents=True, exist_ok=True)
    upscaler_file.write(models / "upscaler" / "big.pth")

    def draw(size: tuple[int, int], **fields) -> str:
        paints(*size)
        answer = client.post("/api/v1/bild", json={
            "prompt": "a lighthouse", "modell": "base.safetensors", "studio": True,
            "breite": size[0], "hoehe": size[1], "seed": 7, **fields,
        })
        assert answer.status_code == 201, answer.text
        assert answer.json()["frage_id"] is None
        return answer.json()["bild"]

    return draw


def test_a_studio_picture_answers_with_the_values_it_was_drawn_with(studio, client: TestClient):
    name = studio((512, 768))
    info = _info(client, name)
    assert info["prompt"] == "a lighthouse"
    assert (info["breite"], info["hoehe"]) == (512, 768)
    assert "upscaled" not in info


def test_an_enlarged_studio_picture_keeps_the_values_of_its_original_and_says_factor_and_size(
    studio, paints, client: TestClient,
):
    first = studio((512, 768))
    second = studio((2048, 3072), startbild=first, mode="upscale", upscale_model="big.pth")
    enlarged = _info(client, second)
    assert enlarged.pop("upscaled") == {"faktor": 4, "breite": 2048, "hoehe": 3072}
    assert enlarged == _info(client, first)


def test_a_second_studio_picture_leaves_the_values_of_the_first(studio, client: TestClient):
    first = studio((64, 64), prompt="first")
    second = studio((80, 96), prompt="second")
    assert _info(client, first)["prompt"] == "first"
    assert (_info(client, first)["breite"], _info(client, first)["hoehe"]) == (64, 64)
    assert _info(client, second)["prompt"] == "second"


def test_silence_a_name_nobody_drew_and_a_chat_picture_stay_as_they_were(
    studio, enlarge, client: TestClient,
):
    assert _info(client, "nobody-drew-this.png") == {}
    first, second = enlarge((512, 512), (1024, 1024))
    assert _info(client, second)["upscaled"] == {"faktor": 2, "breite": 1024, "hoehe": 1024}
    assert studio_pictures.drawn_with(client.app.state.repositories, first) == {}
