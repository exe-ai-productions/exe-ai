"""An LTX-2.3 checkpoint without its text encoder starts with the parts of
its family: the text encoder (Gemma 3), the sound decoder and, where the
folder holds one, the embeddings connectors.

The checkpoint of LTX-2.3 holds the diffusion model with its connectors, both
VAEs and the vocoder, and no text encoder. sd.cpp stops at the first weight of
the text encoder it misses, so the encoder has to be at hand — and named
when it is not. Only headers are written here: they are all that is read
before a start.

Only LTX is refused without its text encoder. Every other family goes on
with the encoders it is given: sd.cpp warns and fills what is missing with
zeros (SD3 without T5, Flux without CLIP-L), and the picture is drawn."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildbausatz, bildinhalt, kit_bond
from app.bildrunner import Bildrunner
from app.config import Config
from tests.test_bild_bausatz_api import _kopf
from tests.test_bildturbo import _LebtImmer

CHECKPOINT = "ltx-2.3-22b-distilled.q8_0.gguf"
GEMMA = "gemma-3-12b-it-UD-Q4_K_XL.gguf"
AUDIO_VAE = "ltx-2.3-22b-dev_audio_vae.safetensors"
CONNECTORS = "ltx-2.3-22b-dev_embeddings_connectors.safetensors"

# The groups of weights a checkpoint of LTX-2.3 holds, one name each.
_CHECKPOINT_WEIGHTS = {
    "model.diffusion_model.adaln_single.emb.timestep_embedder.linear_1.bias": [4096],
    "model.diffusion_model.audio_patchify_proj.weight": [2048, 128],
    "model.diffusion_model.transformer_blocks.0.attn1.to_q.weight": [4096, 4096],
    "model.diffusion_model.audio_embeddings_connector.transformer_1d_blocks.0.attn1.to_q.weight": [2048, 2048],
    "model.diffusion_model.video_embeddings_connector.transformer_1d_blocks.0.attn1.to_q.weight": [4096, 4096],
    "text_embedding_projection.video_aggregate_embed.weight": [4096, 188160],
    "vae.decoder.conv_in.conv.weight": [1024, 128, 3, 3],
    "audio_vae.decoder.conv_in.conv.weight": [512, 8, 3, 3],
    "vocoder.vocoder.conv_pre.weight": [1536, 128, 7],
}
_AUDIO_VAE_WEIGHTS = {
    "audio_vae.decoder.conv_in.conv.weight": [512, 8, 3, 3],
    "audio_vae.per_channel_statistics.mean-of-means": [128],
    "vocoder.vocoder.conv_pre.weight": [1536, 128, 7],
}
_CONNECTOR_WEIGHTS = {
    "model.diffusion_model.video_embeddings_connector.transformer_1d_blocks.0.attn1.to_q.weight": [4096, 4096],
    "model.diffusion_model.audio_embeddings_connector.transformer_1d_blocks.0.attn1.to_q.weight": [2048, 2048],
    "text_embedding_projection.video_aggregate_embed.weight": [4096, 188160],
}


def _folder(root: Path, *, gemma: bool = True, audio: bool = True, connectors: bool = False) -> Path:
    folder = root / "bildmodelle"
    _kopf(folder / CHECKPOINT, dict(_CHECKPOINT_WEIGHTS), "ltxv")
    if gemma:
        _kopf(folder / "text_encoders" / GEMMA, {"token_embd.weight": [262208, 3840]}, "gemma3")
    if audio:
        _kopf(folder / "vae" / AUDIO_VAE, dict(_AUDIO_VAE_WEIGHTS))
    if connectors:
        _kopf(folder / "text_encoders" / CONNECTORS, dict(_CONNECTOR_WEIGHTS))
    return folder


def test_gemma_3_is_read_as_a_text_encoder_and_as_the_llm_of_ltx(tmp_path):
    folder = _folder(tmp_path)
    assert bildinhalt.companion(folder / "text_encoders" / GEMMA) == ("llm", None)
    assert bildinhalt.llm(folder / "text_encoders" / GEMMA) == ("gemma3", 3840)


def test_the_two_further_parts_are_told_by_their_weights(tmp_path):
    folder = _folder(tmp_path, connectors=True)
    assert bildinhalt.companion(folder / "vae" / AUDIO_VAE)[0] == "audio_vae"
    assert bildinhalt.companion(folder / "text_encoders" / CONNECTORS)[0] == "embeddings_connectors"
    # The checkpoint holds both beside its diffusion model: it is no part.
    assert bildinhalt.companion(folder / CHECKPOINT)[0] == ""


def test_the_folder_offers_the_parts_the_family_reads(tmp_path):
    from app import image_families

    folder = _folder(tmp_path, connectors=True)
    family = image_families.get("ltx")
    assert kit_bond.matching_parts(folder, family) == {
        "llm": GEMMA, "audio_vae": AUDIO_VAE, "embeddings_connectors": CONNECTORS,
    }


def test_silence_the_sound_decoder_of_ltx_is_offered_to_no_other_family(tmp_path):
    from app import image_families

    folder = _folder(tmp_path)
    assert "audio_vae" not in kit_bond.matching_parts(folder, image_families.get("minimax_h3"))


def test_a_folder_without_the_parts_offers_none(tmp_path):
    from app import image_families

    folder = _folder(tmp_path, gemma=False, audio=False)
    assert kit_bond.matching_parts(folder, image_families.get("ltx")) == {}


def test_the_parts_of_the_family_go_beside_m_in_the_family_s_order():
    gemma, audio, connectors = Path("/e/gemma.gguf"), Path("/v/audio.safetensors"), Path("/e/c.safetensors")
    assert bildbausatz.checkpoint_switches(
        "ltx", llm=gemma, audio_vae=audio, embeddings_connectors=connectors,
    ) == [
        "--llm", str(gemma), "--audio-vae", str(audio), "--embeddings-connectors", str(connectors),
    ]
    bildbausatz.familie_pruefen(
        "ltx", diffusion_model=None, t5xxl=None, clip_l=None, clip_g=None, llm=gemma,
        bare_checkpoint=True, audio_vae=audio, embeddings_connectors=connectors,
    )


def test_silence_other_families_give_no_further_part_beside_m():
    """Flux reads no sound decoder: a part that is handed in is not passed."""
    assert bildbausatz.checkpoint_switches(
        "flux", t5xxl=Path("/e/t5.gguf"), clip_l=Path("/e/cl.safetensors"),
        audio_vae=Path("/v/audio.safetensors"),
    ) == ["--t5xxl", str(Path("/e/t5.gguf")), "--clip_l", str(Path("/e/cl.safetensors"))]


@pytest.fixture
def hand_start(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    turbo = client.app.state.bildturbo
    monkeypatch.setattr(type(turbo), "programm", property(lambda self: Path("/fake/sd-server")))
    caught: list[list[str]] = []

    def _popen(command, **kwargs):
        caught.append(command)
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", _popen)

    def _start(folder: Path, model: str = CHECKPOINT):
        config.app.bildmodelle_verzeichnis = str(folder)
        answer = client.post(
            "/api/v1/bild/turbo/start", json={"modell": model},
            headers={"Accept-Language": "en"},
        )
        return answer, caught[-1] if caught else None

    yield _start
    turbo._prozess = None


def test_the_server_starts_on_the_checkpoint_with_the_text_encoder_and_the_sound_decoder(
    hand_start, tmp_path
):
    folder = _folder(tmp_path)
    answer, command = hand_start(folder)
    assert answer.status_code == 200, answer.text
    assert command[command.index("-m") + 1] == str(folder / CHECKPOINT)
    assert command[command.index("--llm") + 1] == str(folder / "text_encoders" / GEMMA)
    assert command[command.index("--audio-vae") + 1] == str(folder / "vae" / AUDIO_VAE)
    assert "--diffusion-model" not in command
    assert "--embeddings-connectors" not in command


def test_the_connectors_of_the_folder_go_along(hand_start, tmp_path):
    folder = _folder(tmp_path, connectors=True)
    answer, command = hand_start(folder)
    assert answer.status_code == 200, answer.text
    assert command[command.index("--embeddings-connectors") + 1] == str(
        folder / "text_encoders" / CONNECTORS
    )


def test_a_checkpoint_without_its_text_encoder_is_refused_and_names_it(hand_start, tmp_path):
    answer, command = hand_start(_folder(tmp_path, gemma=False))
    assert answer.status_code == 412
    assert "LLM" in answer.json()["detail"]
    assert command is None


def test_silence_a_checkpoint_that_carries_its_text_encoder_starts_on_m_alone(
    hand_start, tmp_path
):
    folder = _folder(tmp_path)
    _kopf(
        folder / CHECKPOINT,
        {**_CHECKPOINT_WEIGHTS, "text_encoders.llm.model.embed_tokens.weight": [262208, 3840]},
        "ltxv",
    )
    answer, command = hand_start(folder)
    assert answer.status_code == 200, answer.text
    assert "--llm" not in command
    assert command[command.index("-m") + 1] == str(folder / CHECKPOINT)


@pytest.fixture
def draw(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    seen: dict = {}

    def _generate(self, auftrag, target):
        seen["auftrag"] = auftrag
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"PNG")
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", _generate)

    def _draw(folder: Path, model: str = CHECKPOINT):
        config.app.bildmodelle_verzeichnis = str(folder)
        answer = client.post("/api/v1/bild", json={"prompt": "x", "modell": model})
        return answer, seen.get("auftrag")

    return _draw


def test_a_drawing_on_the_checkpoint_carries_the_parts_into_the_command(draw, tmp_path):
    folder = _folder(tmp_path)
    answer, auftrag = draw(folder)
    assert answer.status_code == 201, answer.text
    assert auftrag.llm == folder / "text_encoders" / GEMMA
    assert auftrag.audio_vae == folder / "vae" / AUDIO_VAE
    command = Bildrunner(tmp_path).befehl(auftrag, tmp_path / "out.mp4")
    assert command[command.index("--llm") + 1] == str(folder / "text_encoders" / GEMMA)
    assert command[command.index("--audio-vae") + 1] == str(folder / "vae" / AUDIO_VAE)


def test_a_drawing_on_the_checkpoint_without_its_text_encoder_is_refused(draw, tmp_path):
    answer, auftrag = draw(_folder(tmp_path, gemma=False))
    assert answer.status_code == 412
    assert auftrag is None


# A checkpoint of SD3.5 and one of Flux, each with its VAE and no text encoder.
SD3_CHECKPOINT = "sd3.5_large.safetensors"
FLUX_CHECKPOINT = "flux1-dev.safetensors"
_SD3_WEIGHTS = {
    "model.diffusion_model.joint_blocks.0.x_block.attn.qkv.weight": [4608, 1536],
    "vae.decoder.conv_in.weight": [512, 16, 3, 3],
}
_FLUX_WEIGHTS = {
    "model.diffusion_model.double_blocks.0.img_attn.qkv.weight": [9216, 3072],
    "vae.decoder.conv_in.weight": [512, 16, 3, 3],
}
_CLIP_L = {"text_model.embeddings.token_embedding.weight": [49408, 768]}
_CLIP_G = {"text_model.embeddings.token_embedding.weight": [49408, 1280]}
_T5 = {
    "shared.weight": [32128, 4096],
    "encoder.block.0.layer.0.SelfAttention.k.weight": [4096, 4096],
}


def _encoder_folder(root: Path, checkpoint: str, weights: dict, **encoders) -> Path:
    """A folder with a bare checkpoint and the text encoders named in
    ``encoders`` (file name → header)."""
    folder = root / "bildmodelle"
    _kopf(folder / checkpoint, dict(weights))
    for name, header in encoders.items():
        _kopf(folder / "text_encoders" / f"{name}.safetensors", dict(header))
    return folder


def test_sd3_without_its_t5_starts_with_the_two_clip_encoders(hand_start, tmp_path):
    folder = _encoder_folder(tmp_path, SD3_CHECKPOINT, _SD3_WEIGHTS, clip_l=_CLIP_L, clip_g=_CLIP_G)
    answer, command = hand_start(folder, SD3_CHECKPOINT)
    assert answer.status_code == 200, answer.text
    assert command[command.index("--clip_l") + 1] == str(folder / "text_encoders" / "clip_l.safetensors")
    assert command[command.index("--clip_g") + 1] == str(folder / "text_encoders" / "clip_g.safetensors")
    assert "--t5xxl" not in command


def test_flux_without_its_clip_l_starts_with_the_t5(hand_start, tmp_path):
    folder = _encoder_folder(tmp_path, FLUX_CHECKPOINT, _FLUX_WEIGHTS, t5xxl=_T5)
    answer, command = hand_start(folder, FLUX_CHECKPOINT)
    assert answer.status_code == 200, answer.text
    assert command[command.index("--t5xxl") + 1] == str(folder / "text_encoders" / "t5xxl.safetensors")
    assert "--clip_l" not in command


def test_a_checkpoint_of_such_a_family_without_any_encoder_starts_on_itself(hand_start, tmp_path):
    folder = _encoder_folder(tmp_path, FLUX_CHECKPOINT, _FLUX_WEIGHTS)
    answer, command = hand_start(folder, FLUX_CHECKPOINT)
    assert answer.status_code == 200, answer.text
    assert command[command.index("-m") + 1] == str(folder / FLUX_CHECKPOINT)
    assert "--t5xxl" not in command and "--clip_l" not in command


def test_a_drawing_on_sd3_without_its_t5_is_not_refused(draw, tmp_path):
    folder = _encoder_folder(tmp_path, SD3_CHECKPOINT, _SD3_WEIGHTS, clip_l=_CLIP_L, clip_g=_CLIP_G)
    answer, auftrag = draw(folder, SD3_CHECKPOINT)
    assert answer.status_code == 201, answer.text
    assert auftrag.clip_l == folder / "text_encoders" / "clip_l.safetensors"
    assert auftrag.t5xxl is None


def test_silence_only_the_family_that_cannot_do_without_is_asked_for_its_encoder():
    from app import image_families

    assert bildbausatz.fehlender_textversteher("ltx", {}) == "llm"
    for name in ("flux", "sd3"):
        assert image_families.get(name).needs_text_encoder is False
        assert bildbausatz.fehlender_textversteher(name, {}) is None
    assert image_families.get("ltx").needs_text_encoder is True
