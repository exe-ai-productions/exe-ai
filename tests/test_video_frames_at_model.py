"""Frames and frames per second are values of a video model, like its steps.

A model of a family that starts with them can set its own; ``/bild/vorgaben``
answers it over the family's and names it, and the drawing of a video starts
from there. A family that draws at one frame rate (Wan 2.2 S2V) has no rate to
set: none is answered and none goes to sd.cpp, while its frames stay.

Only headers are written here: they are all that is read before a start."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildmodellwerte, image_families
from app.bildrunner import Auftrag, Bildrunner
from app.config import Config
from app.tools import video_tool
from tests.test_video_kit_parts import (
    _ANY,
    SPEECH,
    WAN_S2V,
    WAN_T2V,
    _folder,
    _kopf,
    _model,
    _own_vae,
    _wan_kit,
)


def _save(client: TestClient, model: str, **values) -> None:
    answer = client.patch(
        "/api/v1/settings/global/bildmodellwerte", json={"wert": {model: values}},
    )
    assert answer.status_code == 200, answer.text


def _presets(client: TestClient, model: str) -> dict:
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": model})
    assert answer.status_code == 200, answer.text
    return answer.json()


# --- The check -----------------------------------------------------------------


def test_the_check_keeps_a_whole_number_from_one_up_for_frames_and_rate():
    kept = bildmodellwerte.pruefen({"a.gguf": {"video_frames": 17, "fps": 12}})
    assert kept == {"a.gguf": {"video_frames": 17, "fps": 12}}


@pytest.mark.parametrize("bad", [0, -1, 1.5, "x", True, None])
def test_the_check_drops_what_is_no_whole_number_from_one_up(bad):
    kept = bildmodellwerte.pruefen({"a.gguf": {"video_frames": bad, "fps": bad}})
    assert kept == {"a.gguf": {"video_frames": None, "fps": None}}


# --- What the model answers ------------------------------------------------------


def test_a_frame_count_saved_at_the_model_is_answered_and_named(client, config, tmp_path):
    folder = _folder(tmp_path)
    _model(folder, WAN_T2V, "wan")
    config.app.bildmodelle_verzeichnis = str(folder)
    _save(client, WAN_T2V, video_frames=17)
    answer = _presets(client, WAN_T2V)
    assert answer["video_frames"] == 17
    assert "video_frames" in answer["eigene"]
    # The rate was not set: the family's.
    assert answer["fps"] == image_families.get("wan").start.fps
    assert "fps" not in answer["eigene"]


def test_a_rate_saved_at_the_model_is_answered_and_named(client, config, tmp_path):
    folder = _folder(tmp_path)
    _model(folder, WAN_T2V, "wan")
    config.app.bildmodelle_verzeichnis = str(folder)
    _save(client, WAN_T2V, fps=12)
    answer = _presets(client, WAN_T2V)
    assert answer["fps"] == 12 and "fps" in answer["eigene"]
    assert answer["video_frames"] == image_families.get("wan").start.frames


def test_silence_without_a_value_of_its_own_the_family_s_frames_and_rate_are_answered(
    client, config, tmp_path,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_T2V, "wan")
    config.app.bildmodelle_verzeichnis = str(folder)
    answer = _presets(client, WAN_T2V)
    start = image_families.get("wan").start
    assert (answer["video_frames"], answer["fps"]) == (start.frames, start.fps)
    assert not {"video_frames", "fps"} & set(answer["eigene"])


def test_silence_a_picture_family_answers_neither_frames_nor_rate(client, config, tmp_path):
    folder = _folder(tmp_path)
    _model(folder, "sdxl.safetensors", "sdxl")
    config.app.bildmodelle_verzeichnis = str(folder)
    answer = _presets(client, "sdxl.safetensors")
    assert answer["video_frames"] is None and answer["fps"] is None


def test_a_speech_to_video_model_answers_no_rate_even_where_one_was_saved(client, config, tmp_path):
    folder = _folder(tmp_path)
    _model(folder, WAN_S2V, "wan22_s2v")
    config.app.bildmodelle_verzeichnis = str(folder)
    _save(client, WAN_S2V, video_frames=33, fps=30)
    answer = _presets(client, WAN_S2V)
    assert answer["fps"] is None and "fps" not in answer["eigene"]
    # Its frames are its own to set.
    assert answer["video_frames"] == 33 and "video_frames" in answer["eigene"]


def test_the_family_table_tells_which_family_draws_at_one_rate():
    fixed = {entry["name"] for entry in image_families.as_json() if entry["fixed_fps"]}
    assert fixed == {"wan22_s2v"}


# --- The drawing -----------------------------------------------------------------------


@pytest.fixture
def draw_with(config: Config, client: TestClient, monkeypatch):
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    seen: dict = {}

    def _generate(self, auftrag, target):
        seen["auftrag"] = auftrag
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x1aE\xdf\xa3webm")
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", _generate)

    def _draw(folder: Path, model: str, **wish) -> Auftrag:
        config.app.bildmodelle_verzeichnis = str(folder)
        answer = client.post(
            "/api/v1/bild", json={"prompt": "x", "modell": model, **wish},
            headers={"Accept-Language": "en"},
        )
        assert answer.status_code == 201, answer.text
        return seen["auftrag"]

    return _draw


def test_a_video_drawing_carries_the_frames_and_rate_it_is_sent(draw_with, client, tmp_path):
    folder = _folder(tmp_path)
    _model(folder, WAN_T2V, "wan")
    _wan_kit(folder)
    _own_vae(client, WAN_T2V, "wan_vae.safetensors")
    auftrag = draw_with(folder, WAN_T2V, video_frames=17, fps=12)
    assert (auftrag.video_frames, auftrag.fps) == (17, 12)


def test_a_speech_to_video_drawing_carries_its_frames_and_no_rate(draw_with, client, tmp_path):
    folder = _folder(tmp_path)
    _model(folder, WAN_S2V, "wan22_s2v")
    _wan_kit(folder)
    _kopf(folder / "text_encoders" / SPEECH, dict(_ANY))
    _own_vae(client, WAN_S2V, "wan_vae.safetensors")
    auftrag = draw_with(folder, WAN_S2V, video_frames=33, fps=30)
    assert auftrag.video_frames == 33
    assert auftrag.fps is None


def test_the_drawing_of_a_video_starts_from_the_frames_saved_at_the_model(
    draw_with, client, tmp_path,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_T2V, "wan")
    _wan_kit(folder)
    _own_vae(client, WAN_T2V, "wan_vae.safetensors")
    _save(client, WAN_T2V, video_frames=17)
    answer = _presets(client, WAN_T2V)
    # The body the video tool builds from the answer about the model.
    body = {
        name: answer[name] for name in video_tool._START_FIELDS
        if answer.get(name) not in (None, "", {})
    }
    auftrag = draw_with(folder, WAN_T2V, **body)
    assert auftrag.video_frames == 17
