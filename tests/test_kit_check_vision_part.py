"""A drawing with a kit that holds its vision part or its tokenizer is not
refused for a part it has. The check before sd.cpp starts is handed every
part the request resolved, and the one that is really missing is named the
way the docs name it.

``Bildrunner.erzeugen`` is caught, so no sd-cli is needed: the tests only see
whether the route answers and which files would reach the generator.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildbausatz, image_families
from app.api.v1 import bild
from app.bildrunner import Bildrunner
from app.config import Config
from tests.test_bildinhalt import clip_gguf_bytes
from tests.test_image_families import _HEADERS, _llm, _safetensors

_EN = {"Accept-Language": "en"}


@pytest.fixture
def picture_folder(config: Config, tmp_path: Path) -> Path:
    ordner = tmp_path / "bildmodelle"
    ordner.mkdir()
    config.app.bildmodelle_verzeichnis = str(ordner)
    return ordner


@pytest.fixture
def drawn(monkeypatch, tmp_path: Path):
    """The Auftrag that reached the generator, by call."""
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    calls: list = []

    def _erzeugen(self, auftrag, ziel):
        calls.append(auftrag)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)
    return calls


def _vae_of(client: TestClient, model: str, vae: str) -> None:
    """The VAE a model was given on the picture server page: a kit's VAE is
    the user's choice, never put in by the folder."""
    answer = client.patch(
        "/api/v1/settings/global/bildmodellwerte", json={"wert": {model: {"vae": vae}}},
    )
    assert answer.status_code == 200, answer.text


def _qwen_image_2_1(folder: Path, vision: bool = True) -> None:
    _safetensors(folder / "q21.safetensors", _HEADERS["qwen_image_2_1"])
    _llm(folder / "text_encoders" / "qwen3vl-8b-q4.gguf", "qwen3vl", 4096)
    _safetensors(folder / "vae" / "qwen_image_2.1_vae.safetensors", {
        "decoder.conv_in.weight": [512, 16, 3, 3],
    })
    if vision:
        (folder / "text_encoders" / "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf").write_bytes(
            clip_gguf_bytes(vision=True)
        )


def _moss_image(folder: Path, tokenizer: bool = True) -> None:
    _safetensors(folder / "moss.safetensors", _HEADERS["moss_image"])
    _llm(folder / "text_encoders" / "qwen3.5-9b-q4.gguf", "qwen35", 4096)
    _safetensors(folder / "vae" / "flux2_ae.safetensors", {
        "decoder.conv_in.weight": [512, 32, 3, 3],
    })
    if tokenizer:
        (folder / "text_encoders" / "tokenizer.json").write_text("{}")


def test_a_qwen_image_2_1_kit_with_its_vision_part_draws(
    client: TestClient, picture_folder: Path, drawn
):
    _qwen_image_2_1(picture_folder)
    _vae_of(client, "q21.safetensors", "qwen_image_2.1_vae.safetensors")
    answer = client.post("/api/v1/bild", json={"prompt": "x", "modell": "q21.safetensors"})
    assert answer.status_code == 201, answer.text
    assert drawn[-1].llm_vision == picture_folder / "text_encoders" / "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf"


def test_a_qwen_image_2_1_kit_without_its_vision_part_is_refused_and_names_it(
    client: TestClient, picture_folder: Path, drawn
):
    """The silence probe: a part that is really missing still stops the
    drawing, and is called "LLM Vision" and not by its key."""
    _qwen_image_2_1(picture_folder, vision=False)
    _vae_of(client, "q21.safetensors", "qwen_image_2.1_vae.safetensors")
    answer = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "q21.safetensors"}, headers=_EN,
    )
    assert answer.status_code == 412, answer.text
    assert "LLM Vision" in answer.json()["detail"]
    assert "llm_vision" not in answer.json()["detail"]
    assert not drawn


def test_a_moss_image_kit_with_its_tokenizer_draws(
    client: TestClient, picture_folder: Path, drawn
):
    _moss_image(picture_folder)
    _vae_of(client, "moss.safetensors", "flux2_ae.safetensors")
    answer = client.post("/api/v1/bild", json={"prompt": "x", "modell": "moss.safetensors"})
    assert answer.status_code == 201, answer.text
    assert drawn[-1].tokenizer == picture_folder / "text_encoders" / "tokenizer.json"


def test_a_moss_image_kit_without_its_tokenizer_is_refused_and_names_it(
    client: TestClient, picture_folder: Path, drawn
):
    _moss_image(picture_folder, tokenizer=False)
    _vae_of(client, "moss.safetensors", "flux2_ae.safetensors")
    answer = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "moss.safetensors"}, headers=_EN,
    )
    assert answer.status_code == 412, answer.text
    assert "Tokenizer" in answer.json()["detail"]
    assert not drawn


def test_the_check_is_given_every_part_a_family_can_name(
    client: TestClient, picture_folder: Path, drawn, monkeypatch
):
    """Whatever a family's kit can ask for (``needed_parts``), the dict the
    drawing hands to the check carries a key for it, so no later part is
    asked for and never looked at."""
    _qwen_image_2_1(picture_folder)
    _vae_of(client, "q21.safetensors", "qwen_image_2.1_vae.safetensors")
    seen: list[dict] = []
    real = bild._kit_complete

    def _record(family_name, parts, sprache, model=None):
        seen.append(parts)
        real(family_name, parts, sprache, model)

    monkeypatch.setattr(bild, "_kit_complete", _record)
    assert client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "q21.safetensors"}
    ).status_code == 201
    nameable = {
        kit_part.part
        for family in image_families.FAMILIES
        for kit_part in family.kit_parts
        if kit_part.part in family.parts
    }
    encoders = {name for family in image_families.FAMILIES for name in family.encoders}
    assert (nameable | encoders | {"vae"}) <= set(seen[-1])


def test_a_part_is_named_as_the_docs_call_it():
    assert bildbausatz.teil_name("qwen_image_2_1", "llm_vision") == "LLM Vision"
    assert bildbausatz.teil_name("moss_image", "tokenizer") == "Tokenizer"
    assert bildbausatz.teil_name("qwen_image_2_1", "vae") == "VAE"


def test_a_checkpoint_of_a_family_without_a_kit_draws_as_before(
    client: TestClient, picture_folder: Path, drawn
):
    _safetensors(picture_folder / "sdxl.safetensors", _HEADERS["sdxl"])
    answer = client.post("/api/v1/bild", json={"prompt": "x", "modell": "sdxl.safetensors"})
    assert answer.status_code == 201, answer.text
