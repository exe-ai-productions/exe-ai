"""Every video family comes with all the parts its docs name, and the LLM of a
kit family is put in from the folder.

The parts: a sound decoder (LTX-2.3, MiniMax-H3), the embeddings connectors
(LTX-2.3), a speech encoder (Wan 2.2 S2V) and the image encoder of Wan 2.1's
I2V and FLF2V models. A diffusion model on its own is not started without the
ones its docs name for it, and the answer names the one that is missing; a
checkpoint is started as before. The file of a part that no header tells apart
is the one of the name the family's kit gives it, when it lies in the folder.

Only headers are written here: they are all that is read before a start."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildmodellwerte, image_families, kit_bond
from app.bildrunner import Auftrag, Bildrunner
from app.config import Config
from tests.test_bild_bausatz_api import _kopf
from tests.test_image_families import _HEADERS
from tests.test_ltx_checkpoint_kit import (
    _CHECKPOINT_WEIGHTS,
    CHECKPOINT,
    GEMMA,
)
from tests.test_ltx_checkpoint_kit import hand_start as _hand_start_of_the_ltx_tests

# The fixture of the LTX tests: the server's start command, caught instead of run.
hand_start = _hand_start_of_the_ltx_tests

_UMT5 = {
    "encoder.block.0.layer.0.SelfAttention.q.weight": [4096, 4096],
    "shared.weight": [256384, 4096],
}
_WAN_VAE = {
    "decoder.conv1.weight": [384, 16, 3, 3, 3], "encoder.conv1.weight": [96, 3, 3, 3, 3],
}
_ANY = {"some.weight": [4]}
_AUDIO_VAE_HEAD = {
    "audio_vae.decoder.conv_in.conv.weight": [512, 8, 3, 3],
    "audio_vae.per_channel_statistics.mean-of-means": [128],
    "vocoder.vocoder.conv_pre.weight": [1536, 128, 7],
}
_CONNECTORS_HEAD = {
    "model.diffusion_model.video_embeddings_connector.transformer_1d_blocks.0.attn1.to_q.weight":
        [4096, 4096],
    "model.diffusion_model.audio_embeddings_connector.transformer_1d_blocks.0.attn1.to_q.weight":
        [2048, 2048],
    "text_embedding_projection.video_aggregate_embed.weight": [4096, 188160],
}

WAN_I2V = "wan2.1_i2v_480p_14B_fp16.safetensors"
WAN_T2V = "wan2.1_t2v_1.3B_fp16.safetensors"
WAN_S2V = "wan2.2_s2v_14B_fp16.safetensors"
MINIMAX = "minimax_h3_fl2va-Q4_K_M.gguf"
LTX_MODEL = "ltx-2.3-22b-dev-UD-Q4_K_M.gguf"
CLIP_VISION = "clip_vision_h.safetensors"
SPEECH = "wav2vec2_large_english_fp16.safetensors"
MINIMAX_LLM = "qwen3vl_32b_minimax_h3-Q4_K_M.gguf"
MINIMAX_AUDIO = "minimax_h3_audio_vae_fp32.safetensors"
LTX_AUDIO = "ltx-2.3-22b-dev_audio_vae.safetensors"
LTX_CONNECTORS = "ltx-2.3-22b-dev_embeddings_connectors.safetensors"


def _folder(root: Path) -> Path:
    folder = root / "bildmodelle"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _model(folder: Path, name: str, family: str) -> None:
    """A diffusion model of the family, on its own: its header carries the
    family's weights and nothing of a checkpoint. A safetensors file: the five
    dimensions of Wan's patch embedding do not fit a GGUF header."""
    _kopf(folder / name, dict(_HEADERS[family]))


def _wan_kit(folder: Path) -> None:
    _kopf(folder / "text_encoders" / "umt5.safetensors", dict(_UMT5))
    _kopf(folder / "vae" / "wan_vae.safetensors", dict(_WAN_VAE))


def _own_vae(client: TestClient, model: str, vae: str) -> None:
    bildmodellwerte.set_part(client.app.state.repositories, model, "vae", vae)


def _after(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


# --- The table: what each family brings -----------------------------------------


def _parts_of(name: str) -> dict[str, str]:
    return {part.part: part.name for part in image_families.kit_of_file(name)}


def test_the_kits_of_the_video_families_name_their_further_parts():
    assert _parts_of(MINIMAX)["audio_vae"] == MINIMAX_AUDIO
    assert _parts_of(WAN_S2V)["audio_encoder"] == SPEECH
    assert _parts_of(WAN_I2V)["clip_vision"] == CLIP_VISION
    assert _parts_of("wan2.1_flf2v_720p_14B_fp16.safetensors")["clip_vision"] == CLIP_VISION
    ltx = _parts_of(LTX_MODEL)
    assert (ltx["audio_vae"], ltx["embeddings_connectors"]) == (LTX_AUDIO, LTX_CONNECTORS)


def test_a_sound_decoder_lies_in_the_folder_of_the_vaes_and_the_rest_with_the_encoders():
    folders = {
        part.part: part.folder
        for family in image_families.FAMILIES for part in family.kit_parts
    }
    assert folders["audio_vae"] == "vae"
    for field in ("audio_encoder", "clip_vision", "embeddings_connectors", "llm", "t5xxl"):
        assert folders[field] == "text_encoders", field


def test_silence_the_models_that_do_without_an_image_encoder_keep_their_kit():
    """Wan 2.1 text-to-video and every Wan 2.2 model: the kit they had, and no
    CLIP Vision — not for a Wan 2.2 file named i2v either."""
    for name in (
        WAN_T2V, "Wan2.2-T2V-A14B-LowNoise-Q8_0.gguf", "Wan2.2-I2V-A14B-HighNoise-Q8_0.gguf",
        "wan2.2_ti2v_5B_fp16.safetensors", "wan2.1-vace-14b.gguf",
    ):
        assert "clip_vision" not in _parts_of(name), name
        assert {"t5xxl", "vae"} <= set(_parts_of(name)), name
    wan = image_families.get("wan")
    assert "clip_vision" not in {p.part for p in image_families.kit_of_family(wan, "wan2.2_i2v.gguf")}
    # A family said by hand gives its kit to a name that shows none.
    assert {p.part for p in image_families.kit_of_family(wan, "model.safetensors")} == {"t5xxl", "vae"}


def test_an_optional_part_that_matches_does_not_make_up_for_a_required_one_that_does_not():
    """Half a kit is none: the image encoder a model takes must not count
    toward the parts every model of the family needs."""
    import dataclasses

    wan = image_families.get("wan")
    required = dataclasses.replace(wan.kit_parts[0], when=r"never-matches-anything")
    optional = next(p for p in wan.kit_parts if p.optional)
    family = dataclasses.replace(wan, kit_parts=(required, optional))
    assert image_families.kit_of_family(family, "wan2.1_i2v_480p_14B_fp16.safetensors") == ()


def test_silence_a_ltx_model_the_docs_name_no_files_for_has_no_kit_and_needs_nothing():
    ltx = image_families.get("ltx")
    assert image_families.kit_of_family(ltx, "ltx-2.5-22b-dev-transformer-Q8_0.gguf") == ()
    assert image_families.needed_parts(ltx, "ltx-2.5-22b-dev-transformer-Q8_0.gguf") == ()


@pytest.mark.parametrize(("family", "model", "needed"), [
    ("wan", WAN_I2V, ("clip_vision",)),
    ("wan", WAN_T2V, ()),
    ("wan22_s2v", WAN_S2V, ("audio_encoder",)),
    ("minimax_h3", MINIMAX, ("audio_vae",)),
    ("ltx", LTX_MODEL, ("audio_vae", "embeddings_connectors")),
    ("wan22_i2v", "Wan2.2-I2V-A14B-HighNoise-Q8_0.gguf", ()),
    ("flux", "flux1-dev.safetensors", ()),
])
def test_a_diffusion_model_needs_the_further_parts_its_docs_name(family, model, needed):
    assert image_families.needed_parts(image_families.get(family), model) == needed


# --- The start by hand -------------------------------------------------------------


def test_a_wan_i2v_model_is_not_started_without_its_image_encoder_and_names_it(
    hand_start, client, tmp_path,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_I2V, "wan")
    _wan_kit(folder)
    _own_vae(client, WAN_I2V, "wan_vae.safetensors")
    answer, command = hand_start(folder, WAN_I2V)
    assert answer.status_code == 412, answer.text
    assert "CLIP Vision" in answer.json()["detail"]
    assert command is None


def test_a_wan_i2v_model_starts_with_the_image_encoder_of_the_folder(hand_start, client, tmp_path):
    folder = _folder(tmp_path)
    _model(folder, WAN_I2V, "wan")
    _wan_kit(folder)
    _kopf(folder / "text_encoders" / CLIP_VISION, dict(_ANY))
    _own_vae(client, WAN_I2V, "wan_vae.safetensors")
    answer, command = hand_start(folder, WAN_I2V)
    assert answer.status_code == 200, answer.text
    assert _after(command, "--clip_vision") == str(folder / "text_encoders" / CLIP_VISION)
    assert command.count("--clip_vision") == 1


def test_silence_a_wan_t2v_model_starts_without_an_image_encoder_even_where_one_lies_there(
    hand_start, client, tmp_path,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_T2V, "wan")
    _wan_kit(folder)
    _own_vae(client, WAN_T2V, "wan_vae.safetensors")
    answer, command = hand_start(folder, WAN_T2V)
    assert answer.status_code == 200, answer.text
    assert "--clip_vision" not in command
    # The file lies in the folder: the model still takes none.
    _kopf(folder / "text_encoders" / CLIP_VISION, dict(_ANY))
    answer, command = hand_start(folder, WAN_T2V)
    assert answer.status_code == 200, answer.text
    assert "--clip_vision" not in command


def test_a_speech_to_video_model_needs_its_speech_encoder_and_is_started_with_it(
    hand_start, client, tmp_path,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_S2V, "wan22_s2v")
    _wan_kit(folder)
    _own_vae(client, WAN_S2V, "wan_vae.safetensors")
    answer, command = hand_start(folder, WAN_S2V)
    assert answer.status_code == 412, answer.text
    assert "Audio encoder" in answer.json()["detail"]
    assert command is None
    _kopf(folder / "text_encoders" / SPEECH, dict(_ANY))
    answer, command = hand_start(folder, WAN_S2V)
    assert answer.status_code == 200, answer.text
    assert _after(command, "--audio-encoder") == str(folder / "text_encoders" / SPEECH)


def _minimax_folder(root: Path, *, audio: bool) -> Path:
    folder = _folder(root)
    _kopf(folder / MINIMAX, dict(_HEADERS["minimax_h3"]), "minimax")
    _kopf(folder / "text_encoders" / MINIMAX_LLM, {"token_embd.weight": [151936, 5120]}, "qwen3vl")
    _kopf(folder / "vae" / "minimax_h3_video_vae_fp16.safetensors", dict(_ANY))
    if audio:
        _kopf(folder / "vae" / MINIMAX_AUDIO, dict(_ANY))
    return folder


def test_minimax_h3_needs_its_sound_decoder_and_is_started_with_it(hand_start, client, tmp_path):
    folder = _minimax_folder(tmp_path, audio=False)
    _own_vae(client, MINIMAX, "minimax_h3_video_vae_fp16.safetensors")
    answer, command = hand_start(folder, MINIMAX)
    assert answer.status_code == 412, answer.text
    assert "Audio VAE" in answer.json()["detail"]
    _kopf(folder / "vae" / MINIMAX_AUDIO, dict(_ANY))
    answer, command = hand_start(folder, MINIMAX)
    assert answer.status_code == 200, answer.text
    assert _after(command, "--audio-vae") == str(folder / "vae" / MINIMAX_AUDIO)
    # Its LLM is the file of the kit's name, without anybody picking it.
    assert _after(command, "--llm") == str(folder / "text_encoders" / MINIMAX_LLM)


def _ltx_folder(root: Path, *, audio: bool, connectors: bool) -> Path:
    folder = _folder(root)
    _kopf(folder / LTX_MODEL, dict(_HEADERS["ltx"]), "ltxv")
    _kopf(folder / "text_encoders" / GEMMA, {"token_embd.weight": [262208, 3840]}, "gemma3")
    _kopf(folder / "vae" / "ltx-2.3-22b-dev_video_vae.safetensors", dict(_ANY))
    if audio:
        _kopf(folder / "vae" / LTX_AUDIO, dict(_AUDIO_VAE_HEAD))
    if connectors:
        _kopf(folder / "text_encoders" / LTX_CONNECTORS, dict(_CONNECTORS_HEAD))
    return folder


def test_a_ltx_diffusion_model_is_refused_for_each_part_it_misses_and_then_starts(
    hand_start, client, tmp_path,
):
    folder = _ltx_folder(tmp_path, audio=False, connectors=False)
    _own_vae(client, LTX_MODEL, "ltx-2.3-22b-dev_video_vae.safetensors")
    answer, command = hand_start(folder, LTX_MODEL)
    assert answer.status_code == 412 and "Audio VAE" in answer.json()["detail"], answer.text
    _kopf(folder / "vae" / LTX_AUDIO, dict(_AUDIO_VAE_HEAD))
    answer, command = hand_start(folder, LTX_MODEL)
    assert answer.status_code == 412 and "Embeddings connectors" in answer.json()["detail"], answer.text
    assert command is None
    _kopf(folder / "text_encoders" / LTX_CONNECTORS, dict(_CONNECTORS_HEAD))
    answer, command = hand_start(folder, LTX_MODEL)
    assert answer.status_code == 200, answer.text
    assert _after(command, "--audio-vae") == str(folder / "vae" / LTX_AUDIO)
    assert _after(command, "--embeddings-connectors") == str(
        folder / "text_encoders" / LTX_CONNECTORS
    )


def test_silence_a_ltx_checkpoint_is_still_started_without_asking_for_its_parts(
    hand_start, tmp_path,
):
    """The checkpoint holds the sound decoder and the connectors; the folder
    has neither, and the start asks for the text encoder alone."""
    folder = _folder(tmp_path)
    _kopf(folder / CHECKPOINT, dict(_CHECKPOINT_WEIGHTS), "ltxv")
    _kopf(folder / "text_encoders" / GEMMA, {"token_embd.weight": [262208, 3840]}, "gemma3")
    answer, command = hand_start(folder)
    assert answer.status_code == 200, answer.text
    assert "--audio-vae" not in command and "--embeddings-connectors" not in command


# --- The answer about a model: which parts it shows and which it needs -----------------


def test_the_answer_for_a_ltx_checkpoint_tells_it_is_one_and_needs_nothing(
    client, config, tmp_path,
):
    folder = _folder(tmp_path)
    config.app.bildmodelle_verzeichnis = str(folder)
    _kopf(folder / CHECKPOINT, dict(_CHECKPOINT_WEIGHTS), "ltxv")
    _kopf(folder / "text_encoders" / GEMMA, {"token_embd.weight": [262208, 3840]}, "gemma3")
    _kopf(folder / "vae" / LTX_AUDIO, dict(_AUDIO_VAE_HEAD))
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": CHECKPOINT}).json()
    assert answer["family"] == "ltx"
    assert (answer["bare"], answer["standalone"], answer["needed_parts"]) == (True, False, [])
    assert answer["parts"] == {"llm": GEMMA, "audio_vae": LTX_AUDIO}
    # The window reads the four rows from the table: the VAE, the LLM, the two parts.
    ltx = image_families.get("ltx")
    assert ["vae", *ltx.encoders, *ltx.parts] == ["vae", "llm", "audio_vae", "embeddings_connectors"]


def test_the_answer_for_a_diffusion_model_names_the_parts_it_cannot_start_without(
    client, config, tmp_path,
):
    folder = _ltx_folder(tmp_path, audio=True, connectors=False)
    config.app.bildmodelle_verzeichnis = str(folder)
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": LTX_MODEL}).json()
    assert (answer["bare"], answer["standalone"]) == (False, True)
    assert answer["needed_parts"] == ["audio_vae", "embeddings_connectors"]
    assert answer["parts"] == {"llm": GEMMA, "audio_vae": LTX_AUDIO}


def test_silence_a_checkpoint_of_a_family_without_a_kit_shows_nothing_more(
    client, config, tmp_path,
):
    name = "sdxl.safetensors"
    folder = _folder(tmp_path)
    config.app.bildmodelle_verzeichnis = str(folder)
    _kopf(folder / name, {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
        "conditioner.embedders.1.model.token_embedding.weight": [49408, 1280],
        "first_stage_model.decoder.conv_in.weight": [512, 4, 3, 3],
    })
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": name}).json()
    assert (answer["bare"], answer["needed_parts"]) == (False, [])


# --- The model's own value for the new part -------------------------------------------


def test_the_model_values_hold_a_part_for_the_image_encoder(client):
    repositories = client.app.state.repositories
    bildmodellwerte.set_part(repositories, WAN_I2V, "clip_vision", CLIP_VISION)
    assert bildmodellwerte.eigene(repositories, WAN_I2V)["clip_vision"] == CLIP_VISION
    assert "clip_vision" in kit_bond.FIELDS


# --- The drawing -----------------------------------------------------------------------


@pytest.fixture
def draw_with(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    seen: dict = {}

    def _generate(self, auftrag, target):
        seen["auftrag"] = auftrag
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x1aE\xdf\xa3webm")
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", _generate)

    def _draw(folder: Path, model: str, **wish):
        config.app.bildmodelle_verzeichnis = str(folder)
        answer = client.post(
            "/api/v1/bild", json={"prompt": "x", "modell": model, **wish},
            headers={"Accept-Language": "en"},
        )
        return answer, seen.get("auftrag")

    return _draw


def _command(auftrag: Auftrag, tmp_path: Path, monkeypatch) -> list[str]:
    from app import bildrunner

    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    return Bildrunner(tmp_path).befehl(auftrag, tmp_path / "out.webm")


def test_a_drawing_on_a_wan_i2v_model_is_refused_without_its_image_encoder(
    draw_with, client, tmp_path,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_I2V, "wan")
    _wan_kit(folder)
    _own_vae(client, WAN_I2V, "wan_vae.safetensors")
    answer, auftrag = draw_with(folder, WAN_I2V)
    assert answer.status_code == 412, answer.text
    assert "CLIP Vision" in answer.json()["detail"]
    assert auftrag is None


def test_a_drawing_on_a_wan_i2v_model_carries_the_image_encoder_into_the_command(
    draw_with, client, tmp_path, monkeypatch,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_I2V, "wan")
    _wan_kit(folder)
    _kopf(folder / "text_encoders" / CLIP_VISION, dict(_ANY))
    _own_vae(client, WAN_I2V, "wan_vae.safetensors")
    answer, auftrag = draw_with(folder, WAN_I2V)
    assert answer.status_code == 201, answer.text
    assert auftrag.clip_vision == folder / "text_encoders" / CLIP_VISION
    command = _command(auftrag, tmp_path, monkeypatch)
    assert _after(command, "--clip_vision") == str(folder / "text_encoders" / CLIP_VISION)


def test_sd_cpp_is_given_one_clip_vision_the_one_of_the_model(
    draw_with, client, tmp_path, monkeypatch,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_I2V, "wan")
    _wan_kit(folder)
    _kopf(folder / "text_encoders" / CLIP_VISION, dict(_ANY))
    _kopf(folder / "text_encoders" / "other_clip_vision.safetensors", dict(_ANY))
    _own_vae(client, WAN_I2V, "wan_vae.safetensors")
    answer, auftrag = draw_with(
        folder, WAN_I2V, switches={"clip_vision": "other_clip_vision.safetensors"},
    )
    assert answer.status_code == 201, answer.text
    command = _command(auftrag, tmp_path, monkeypatch)
    assert command.count("--clip_vision") == 1
    assert _after(command, "--clip_vision") == str(folder / "text_encoders" / CLIP_VISION)


def test_the_switch_row_still_gives_a_wan_i2v_model_its_image_encoder(
    draw_with, client, tmp_path, monkeypatch,
):
    """A request that names the encoder through the switch row, as before the
    model had a part of its own, is not refused for the missing part."""
    folder = _folder(tmp_path)
    _model(folder, WAN_I2V, "wan")
    _wan_kit(folder)
    _kopf(folder / "text_encoders" / "other_clip_vision.safetensors", dict(_ANY))
    _own_vae(client, WAN_I2V, "wan_vae.safetensors")
    answer, auftrag = draw_with(
        folder, WAN_I2V, switches={"clip_vision": "other_clip_vision.safetensors"},
    )
    assert answer.status_code == 201, answer.text
    command = _command(auftrag, tmp_path, monkeypatch)
    assert command.count("--clip_vision") == 1
    assert _after(command, "--clip_vision") == str(folder / "text_encoders" / "other_clip_vision.safetensors")


def test_silence_the_switch_row_still_serves_a_model_without_the_part(
    draw_with, client, tmp_path, monkeypatch,
):
    """A model of Wan 2.1 text-to-video has no CLIP Vision of its own: the
    row of the same name goes to sd.cpp as it always did."""
    folder = _folder(tmp_path)
    _model(folder, WAN_T2V, "wan")
    _wan_kit(folder)
    _kopf(folder / "text_encoders" / "other_clip_vision.safetensors", dict(_ANY))
    _own_vae(client, WAN_T2V, "wan_vae.safetensors")
    answer, auftrag = draw_with(
        folder, WAN_T2V, switches={"clip_vision": "other_clip_vision.safetensors"},
    )
    assert answer.status_code == 201, answer.text
    assert auftrag.clip_vision is None
    command = _command(auftrag, tmp_path, monkeypatch)
    assert command.count("--clip_vision") == 1
    assert _after(command, "--clip_vision") == str(folder / "text_encoders" / "other_clip_vision.safetensors")


def test_a_drawing_on_a_speech_to_video_model_is_refused_without_its_speech_encoder(
    draw_with, client, tmp_path, monkeypatch,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_S2V, "wan22_s2v")
    _wan_kit(folder)
    _own_vae(client, WAN_S2V, "wan_vae.safetensors")
    answer, auftrag = draw_with(folder, WAN_S2V)
    assert answer.status_code == 412 and "Audio encoder" in answer.json()["detail"], answer.text
    _kopf(folder / "text_encoders" / SPEECH, dict(_ANY))
    answer, auftrag = draw_with(folder, WAN_S2V)
    assert answer.status_code == 201, answer.text
    command = _command(auftrag, tmp_path, monkeypatch)
    assert _after(command, "--audio-encoder") == str(folder / "text_encoders" / SPEECH)


def test_a_drawing_on_minimax_h3_carries_the_sound_decoder_and_is_refused_without_it(
    draw_with, client, tmp_path, monkeypatch,
):
    folder = _minimax_folder(tmp_path, audio=False)
    _own_vae(client, MINIMAX, "minimax_h3_video_vae_fp16.safetensors")
    answer, auftrag = draw_with(folder, MINIMAX)
    assert answer.status_code == 412 and "Audio VAE" in answer.json()["detail"], answer.text
    _kopf(folder / "vae" / MINIMAX_AUDIO, dict(_ANY))
    answer, auftrag = draw_with(folder, MINIMAX)
    assert answer.status_code == 201, answer.text
    command = _command(auftrag, tmp_path, monkeypatch)
    assert _after(command, "--audio-vae") == str(folder / "vae" / MINIMAX_AUDIO)


# --- The LLM, put in from the folder ---------------------------------------------------

# A model of the family on its own and the LLM its docs run it with: the pair
# the GGUF header names (architecture, width of the token embedding).
_BY_HEADER = [
    ("longcat", "LongCat-Image-Q4_K_M.gguf", "Qwen2.5-VL-7B-Instruct.Q8_0.gguf", "qwen2vl", 3584),
    ("hunyuan_video", "hunyuanvideo1.5_720p_t2v_fp16.safetensors",
     "Qwen2.5-VL-7B-Instruct.Q8_0.gguf", "qwen2vl", 3584),
    ("boogu", "boogu_image_base_bf16.safetensors", "Qwen3-VL-8B-Instruct-Q4_K_M.gguf",
     "qwen3vl", 4096),
    ("ideogram4", "ideogram4-Q8_0.gguf", "Qwen3-VL-8B-Instruct-Q4_K_M.gguf", "qwen3vl", 4096),
    ("mage_flow", "Mage-Flow-Turbo.safetensors", "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
     "qwen3vl", 2560),
    ("lingbot_video", "lingbot-video-dense-1.3b.safetensors", "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
     "qwen3vl", 2560),
]
# The same, by the name the kit gives the file, for the families whose LLM no
# measured pair is known for.
_BY_NAME = [
    ("lens", "lens_turbo_bf16.safetensors"),
    ("pid", "pid_flux1_512_to_2048_4step_bf16.safetensors"),
    ("ovis", "ovis_image-Q4_0.gguf"),
    ("anima", "anima_preview.safetensors"),
    ("ernie", "ernie_image_turbo.safetensors"),
    ("minimax_h3", MINIMAX),
]


def _ask(client, config, folder: Path, model: str) -> dict:
    config.app.bildmodelle_verzeichnis = str(folder)
    return client.get("/api/v1/bild/vorgaben", params={"modell": model}).json()


def _llm_model(folder: Path, family: str, model: str) -> None:
    architecture = "minimax" if model.endswith(".gguf") else None
    _kopf(folder / model, dict(_HEADERS[family]), architecture)


@pytest.mark.parametrize(("family", "model", "llm", "architecture", "width"), _BY_HEADER)
def test_the_llm_of_a_family_is_put_in_when_its_header_names_the_pair_the_family_reads(
    client, config, tmp_path, family, model, llm, architecture, width,
):
    folder = _folder(tmp_path)
    _llm_model(folder, family, model)
    _kopf(folder / "text_encoders" / llm, {"token_embd.weight": [152064, width]}, architecture)
    answer = _ask(client, config, folder, model)
    assert answer["family"] == family
    assert answer["parts"].get("llm") == llm


@pytest.mark.parametrize(("family", "model", "llm", "architecture", "width"), _BY_HEADER)
def test_silence_an_llm_of_another_width_stays_the_users(
    client, config, tmp_path, family, model, llm, architecture, width,
):
    folder = _folder(tmp_path)
    _llm_model(folder, family, model)
    _kopf(folder / "text_encoders" / llm, {"token_embd.weight": [152064, width + 512]}, architecture)
    answer = _ask(client, config, folder, model)
    assert "llm" not in answer["parts"]


@pytest.mark.parametrize(("family", "model"), _BY_NAME)
def test_the_llm_of_a_family_without_a_measured_pair_is_the_file_of_the_kit_s_name(
    client, config, tmp_path, family, model,
):
    folder = _folder(tmp_path)
    _llm_model(folder, family, model)
    kit = image_families.kit_of_family(image_families.get(family), model)
    llm = next(part.name for part in kit if part.part == "llm")
    _kopf(folder / "text_encoders" / llm, {"token_embd.weight": [152064, 2048]}, "qwen3vl")
    answer = _ask(client, config, folder, model)
    assert answer["family"] == family
    assert answer["parts"].get("llm") == llm


@pytest.mark.parametrize(("family", "model"), _BY_NAME)
def test_silence_a_file_of_another_name_is_not_taken_for_the_llm(
    client, config, tmp_path, family, model,
):
    folder = _folder(tmp_path)
    _llm_model(folder, family, model)
    _kopf(folder / "text_encoders" / "some-other-llm.gguf", {"token_embd.weight": [152064, 2048]}, "qwen3vl")
    answer = _ask(client, config, folder, model)
    assert "llm" not in answer["parts"]


def test_silence_families_that_name_no_llm_keep_the_field_to_the_user(client, config, tmp_path):
    folder = _folder(tmp_path)
    _kopf(folder / "Qwen-Image-Layered.gguf", dict(_HEADERS["qwen_image_layered"]), "qwen_image")
    _kopf(folder / "text_encoders" / "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
          {"token_embd.weight": [152064, 2560]}, "qwen3vl")
    answer = _ask(client, config, folder, "Qwen-Image-Layered.gguf")
    assert answer["family"] == "qwen_image_layered"
    assert "llm" not in answer["parts"]


def test_silence_a_flux2_klein_folder_with_both_sizes_leaves_the_llm_to_the_user(
    client, config, tmp_path,
):
    folder = _folder(tmp_path)
    model = "flux-2-klein-4b.safetensors"
    _kopf(folder / model, dict(_HEADERS["flux2_klein"]))
    kit = image_families.kit_of_family(image_families.get("flux2_klein"), model)
    names = [part.name for part in kit if part.part == "llm"]
    assert names, kit
    _kopf(folder / "text_encoders" / names[0], {"token_embd.weight": [151936, 2560]}, "qwen3")
    _kopf(folder / "text_encoders" / "Qwen3-8B-other.gguf", {"token_embd.weight": [151936, 4096]}, "qwen3")
    answer = _ask(client, config, folder, model)
    assert answer["family"] == "flux2_klein"
    assert "llm" not in answer["parts"]


def test_the_llm_the_user_chose_by_hand_stays(client, config, tmp_path):
    folder = _folder(tmp_path)
    model = "boogu_image_base_bf16.safetensors"
    _llm_model(folder, "boogu", model)
    _kopf(folder / "text_encoders" / "Qwen3-VL-8B-Instruct-Q4_K_M.gguf",
          {"token_embd.weight": [152064, 4096]}, "qwen3vl")
    _kopf(folder / "text_encoders" / "my-own-llm.gguf", {"token_embd.weight": [152064, 4096]}, "qwen3vl")
    config.app.bildmodelle_verzeichnis = str(folder)
    bildmodellwerte.set_part(client.app.state.repositories, model, "llm", "my-own-llm.gguf")
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": model}).json()
    assert answer["parts"]["llm"] == "my-own-llm.gguf"


# --- A part stands at the models that take it ---------------------------------------------

WAN_22_T2V = "wan2.2_t2v_low_noise_14B_fp16.safetensors"
HIGH_NOISE_MODEL = "wan2.2_t2v_high_noise_14B_fp16.safetensors"
_HIGH_NOISE_FLAG = "--high-noise-diffusion-model"


@pytest.mark.parametrize(("name", "taken"), [
    (WAN_T2V, ()),
    ("wan2.1_vace_1.3B_fp16.safetensors", ()),
    (WAN_I2V, ("clip_vision",)),
    ("wan2.1_flf2v_14B_720p_fp16.safetensors", ("clip_vision",)),
    (WAN_22_T2V, ("high_noise_diffusion_model",)),
    ("Wan2_2-T2V-A14B-LowNoise-Q4_K_M.gguf", ("high_noise_diffusion_model",)),
])
def test_a_wan_model_takes_the_parts_its_file_name_shows(name, taken):
    assert image_families.parts_taken(image_families.get("wan"), name) == taken


def test_a_wan_2_2_i2v_model_takes_the_high_noise_model_and_no_image_encoder():
    family = image_families.get("wan22_i2v")
    assert image_families.parts_taken(family, "wan2.2_i2v_low_noise_14B_fp16.safetensors") == (
        "high_noise_diffusion_model",
    )


def test_silence_every_other_family_takes_every_part_it_names():
    """Only Wan restricts a part by the file name; LTX, MiniMax-H3, the editing
    families and the rest take all of theirs."""
    for family in image_families.FAMILIES:
        if family.name != "wan":
            assert image_families.parts_taken(family, "a-model.safetensors") == family.parts, family.name


@pytest.mark.parametrize(("name", "taken"), [
    (WAN_T2V, []), (WAN_I2V, ["clip_vision"]), (WAN_22_T2V, ["high_noise_diffusion_model"]),
])
def test_the_answer_for_a_wan_model_names_the_parts_it_takes(client, config, tmp_path, name, taken):
    folder = _folder(tmp_path)
    config.app.bildmodelle_verzeichnis = str(folder)
    _model(folder, name, "wan")
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": name}).json()
    assert answer["parts_taken"] == taken, answer


def test_silence_the_answer_for_a_ltx_model_names_all_its_parts(client, config, tmp_path):
    folder = _ltx_folder(tmp_path, audio=True, connectors=True)
    config.app.bildmodelle_verzeichnis = str(folder)
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": LTX_MODEL}).json()
    assert answer["parts_taken"] == ["audio_vae", "embeddings_connectors"], answer


def test_a_wan_t2v_model_is_not_started_with_an_image_encoder_it_was_given_once(
    hand_start, client, tmp_path,
):
    """The part is stored at the model (an older program offered the row at every Wan
    model): it stays stored and is not sent."""
    folder = _folder(tmp_path)
    _model(folder, WAN_T2V, "wan")
    _wan_kit(folder)
    _kopf(folder / "text_encoders" / CLIP_VISION, dict(_ANY))
    _own_vae(client, WAN_T2V, "wan_vae.safetensors")
    bildmodellwerte.set_part(client.app.state.repositories, WAN_T2V, "clip_vision", CLIP_VISION)
    answer, command = hand_start(folder, WAN_T2V)
    assert answer.status_code == 200, answer.text
    assert "--clip_vision" not in command


def test_a_wan_2_1_model_is_not_started_with_a_high_noise_model_it_was_given_once(
    hand_start, client, tmp_path,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_T2V, "wan")
    _model(folder, HIGH_NOISE_MODEL, "wan")
    _wan_kit(folder)
    _own_vae(client, WAN_T2V, "wan_vae.safetensors")
    bildmodellwerte.set_part(
        client.app.state.repositories, WAN_T2V, "high_noise_diffusion_model", HIGH_NOISE_MODEL,
    )
    answer, command = hand_start(folder, WAN_T2V)
    assert answer.status_code == 200, answer.text
    assert _HIGH_NOISE_FLAG not in command


def test_silence_a_wan_2_2_model_is_started_with_its_high_noise_model(hand_start, client, tmp_path):
    folder = _folder(tmp_path)
    _model(folder, WAN_22_T2V, "wan")
    _model(folder, HIGH_NOISE_MODEL, "wan")
    _wan_kit(folder)
    _own_vae(client, WAN_22_T2V, "wan_vae.safetensors")
    bildmodellwerte.set_part(
        client.app.state.repositories, WAN_22_T2V, "high_noise_diffusion_model", HIGH_NOISE_MODEL,
    )
    answer, command = hand_start(folder, WAN_22_T2V)
    assert answer.status_code == 200, answer.text
    assert _after(command, _HIGH_NOISE_FLAG) == str(folder / HIGH_NOISE_MODEL)


def test_silence_a_wan_i2v_model_without_its_image_encoder_is_still_refused(
    hand_start, client, tmp_path,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_I2V, "wan")
    _wan_kit(folder)
    _own_vae(client, WAN_I2V, "wan_vae.safetensors")
    answer, command = hand_start(folder, WAN_I2V)
    assert answer.status_code == 412 and "CLIP Vision" in answer.json()["detail"], answer.text
    assert command is None


def test_a_drawing_on_a_wan_t2v_model_sends_neither_part_it_was_given_once(
    draw_with, client, tmp_path,
):
    folder = _folder(tmp_path)
    _model(folder, WAN_T2V, "wan")
    _model(folder, HIGH_NOISE_MODEL, "wan")
    _wan_kit(folder)
    _kopf(folder / "text_encoders" / CLIP_VISION, dict(_ANY))
    _own_vae(client, WAN_T2V, "wan_vae.safetensors")
    repositories = client.app.state.repositories
    bildmodellwerte.set_part(repositories, WAN_T2V, "clip_vision", CLIP_VISION)
    bildmodellwerte.set_part(repositories, WAN_T2V, "high_noise_diffusion_model", HIGH_NOISE_MODEL)
    answer, auftrag = draw_with(folder, WAN_T2V)
    assert answer.status_code == 201, answer.text
    assert auftrag.clip_vision is None
    assert auftrag.high_noise_diffusion_model is None
