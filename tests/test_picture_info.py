"""Picture infos: the prompt and values a picture carries, read back."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app import picture_info

TEXT = (
    "a red lighthouse, sunset\nNegative prompt: blurry\n"
    "Steps: 20, CFG scale: 7.000000, Guidance: 3.500000, Eta: 0.000000, "
    "ADetailer prompt: a face, smiling, Seed: 1234, Size: 512x768, "
    "Model: sd15.safetensors, RNG: cuda, Sampler: euler_a karras, VAE: vae.safetensors, "
)


def test_prompt_steps_cfg_and_seed_come_out():
    values = picture_info.parse(TEXT)
    assert values == {
        "prompt": "a red lighthouse, sunset", "negativ": "blurry", "schritte": 20, "cfg": 7,
        "guidance": 3.5, "seed": 1234, "breite": 512, "hoehe": 768,
        "modell": "sd15.safetensors", "sampler": "euler_a", "scheduler": "karras",
        "vae": "vae.safetensors",
    }


def test_a_kit_names_its_diffusion_model_and_no_empty_model():
    values = picture_info.parse("x\nSteps: 4, Model: , Sampler: euler [1.0000, 0.0000], Unet: f.gguf, ")
    assert values["diffusion_model"] == "f.gguf"
    assert "modell" not in values and "scheduler" not in values


def test_the_text_is_found_in_a_png_and_a_jpeg_answer():
    png = {"entries": [{"data": {"keyword": "parameters", "text": "p"}}]}
    jpeg = {"entries": [{"payload": [{"label": "parameters", "text": "q"}]}]}
    assert picture_info.parameters_text(png) == "p"
    assert picture_info.parameters_text(jpeg) == "q"
    assert picture_info.parameters_text({"entries": []}) is None


def test_silence_a_picture_without_data_says_nothing(monkeypatch, tmp_path: Path):
    answer = json.dumps({"entries": [{"name": "IHDR", "data": {"width": 4}}]})
    monkeypatch.setattr(
        picture_info.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=answer, stderr=""),
    )
    assert picture_info.read(Path("/sd-cli"), tmp_path / "a.png") == {}


def test_reading_asks_sd_cli_in_metadata_mode(monkeypatch, tmp_path: Path):
    seen = {}

    def run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"entries": [{"keyword": "parameters", "text": TEXT}]}),
            stderr="",
        )

    monkeypatch.setattr(picture_info.subprocess, "run", run)
    assert picture_info.read(Path("/sd-cli"), tmp_path / "a.png")["seed"] == 1234
    assert seen["command"][1:] == ["-M", "metadata", "--image", str(tmp_path / "a.png"),
                                   "--metadata-format", "json"]
