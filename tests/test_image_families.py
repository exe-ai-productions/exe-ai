"""The one table of model families and everything that reads it.

A model's family comes from the weights in its own header, never from its
file name; the table gives every family its start values with their source;
the window, the draw route and the ``draw_image`` tool all read that one
table; and the CFG stays free for every family.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildfensterwahl, bildinhalt, image_families, image_switches
from app.config import Config
from app.tools import bild_werkzeug
from tests.conftest import Bilddienst

# --- Header dummies --------------------------------------------------------


def _safetensors(path: Path, shapes: dict[str, list[int]]) -> Path:
    header = {
        name: {"dtype": "F16", "shape": shape, "data_offsets": [0, 0]}
        for name, shape in shapes.items()
    }
    raw = json.dumps(header).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)
    return path


def _gguf(path: Path, architecture: str, shapes: dict[str, list[int]]) -> Path:
    """A GGUF header with one string key and the tensor table. GGUF stores
    a shape innermost first, so the dims are written reversed."""
    def text_bytes(text: str) -> bytes:
        raw = text.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    header = bytearray(b"GGUF") + struct.pack("<I", 3)
    header += struct.pack("<Q", len(shapes)) + struct.pack("<Q", 1)
    header += text_bytes("general.architecture") + struct.pack("<I", 8) + text_bytes(architecture)
    for name, shape in shapes.items():
        header += text_bytes(name) + struct.pack("<I", len(shape))
        for dim in reversed(shape):
            header += struct.pack("<Q", dim)
        header += struct.pack("<I", 1) + struct.pack("<Q", 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header))
    return path


# The weights sd.cpp tells each family apart by (``get_sd_version``).
_HEADERS = {
    "flux": {"double_blocks.0.img_attn.qkv.weight": [9216, 3072]},
    # Flux.2 dev has 48 single blocks; klein fewer (model_loader.cpp:669-674).
    "flux2": {
        "double_stream_modulation_img.lin.weight": [18432, 3072],
        "single_blocks.47.linear1.weight": [18432, 3072],
    },
    "flux2_klein": {"double_stream_modulation_img.lin.weight": [18432, 3072]},
    # The names sd.cpp build 975 tells these three by (model_loader.cpp).
    "flux3_klein": {"emb_in.image.weight": [3072, 128], "txt_mode_blocks.0.q_proj.weight": [3072, 3072]},
    "moss_image": {"video_embedder.weight": [3072, 128], "shared_block_modulation.weight": [3072]},
    "iris": {"y_embedder.layer_pool.weight": [3072, 2560], "modulation_cores.adaln_img.weight": [3072]},
    "zimage": {"cap_embedder.0.weight": [2560]},
    "sdxl": {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
        "conditioner.embedders.1.model.token_embedding.weight": [49408, 1280],
    },
    "sd15": {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
        "model.diffusion_model.middle_block.1.norm.weight": [1280],
        "model.diffusion_model.output_blocks.7.1.norm.weight": [640],
        "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight": [49408, 768],
    },
    "sd2": {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
        "model.diffusion_model.middle_block.1.norm.weight": [1280],
        "cond_stage_model.model.token_embedding.weight": [49408, 1024],
    },
    # A tiny U-Net: no second middle block, no output block 7.1.
    "sdxs": {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
        "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight": [49408, 768],
    },
    # instruct-pix2pix: eight input channels.
    "sd15_pix2pix": {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 8, 3, 3],
        "model.diffusion_model.middle_block.1.norm.weight": [1280],
        "cond_stage_model.transformer.text_model.embeddings.token_embedding.weight": [49408, 768],
    },
    "sdxl_pix2pix": {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 8, 3, 3],
        "conditioner.embedders.1.model.token_embedding.weight": [49408, 1280],
    },
    "hidream_o1": {
        "model.x_embedder.proj1.weight": [4096, 64],
        "model.language_model.layers.0.self_attn.q_proj.weight": [4096, 4096],
    },
    "sd3": {"joint_blocks.0.x_block.attn.qkv.weight": [4608, 1536]},
    "chroma": {
        "double_blocks.0.img_attn.qkv.weight": [9216, 3072],
        "distilled_guidance_layer.in_proj.weight": [5120, 64],
    },
    "chroma_radiance": {"nerf_final_layer_conv.conv.weight": [3, 64, 3, 3]},
    "qwen_image": {"transformer_blocks.0.img_mod.1.weight": [18432, 3072]},
    "qwen_image_layered": {
        "transformer_blocks.0.img_mod.1.weight": [18432, 3072],
        "time_text_embed.addition_t_embedding.weight": [2, 3072],
    },
    "mage_flow": {
        "transformer_blocks.0.img_mod.1.weight": [18432, 3072],
        "img_in.weight": [3072, 128],
    },
    "qwen_image_2_1": {"txt_in.text_norm.weight": [4096]},
    "krea2": {"txtfusion.projector.weight": [3072, 2560]},
    "lens": {
        "transformer_blocks.0.attn.norm_added_q.weight": [128],
        "transformer_blocks.0.img_mlp.w1.weight": [8192, 3072],
    },
    "pid": {"net.lq_proj.latent_proj.0.weight": [3072, 64]},
    "longcat": {
        "double_blocks.0.img_attn.qkv.weight": [9216, 3072],
        "txt_in.weight": [3072, 3584],
    },
    "minit2i": {"net.img_embedder.proj1.weight": [1024, 64]},
    "ovis": {"double_blocks.0.img_mlp.gate_proj.weight": [8192, 3072]},
    "ernie": {"layers.0.adaLN_sa_ln.weight": [4096]},
    "sefi": {"dual_time_embed.semantic_embedder.linear_1.weight": [1024, 256]},
    "anima": {"llm_adapter.blocks.0.cross_attn.q_proj.weight": [1024, 1024]},
    "boogu": {"double_stream_layers.0.img_instruct_attn.processor.img_to_q.weight": [3072, 3072]},
    "ideogram4": {"embed_image_indicator.weight": [2, 3072]},
    "pixart": {"t_block.1.weight": [6912, 1152], "x_embedder.proj.weight": [1152, 4, 2, 2]},
    # The video models (model_loader.cpp:506-633): Wan by its cross
    # attention, its 2.2 variants by the patch embedding's channels.
    "wan": {
        "blocks.0.cross_attn.norm_k.weight": [1536],
        "patch_embedding.weight": [1536, 16, 1, 2, 2],
    },
    "wan22_i2v": {
        "blocks.0.cross_attn.norm_k.weight": [5120],
        "patch_embedding.weight": [5120, 36, 1, 2, 2],
    },
    "wan22_ti2v": {
        "blocks.0.cross_attn.norm_k.weight": [3072],
        "patch_embedding.weight": [3072, 48, 1, 2, 2],
    },
    "wan22_s2v": {
        "blocks.0.cross_attn.norm_k.weight": [5120],
        "patch_embedding.weight": [5120, 16, 1, 2, 2],
        "casual_audio_encoder.weights": [1],
    },
    "ltx": {"adaln_single.emb.timestep_embedder.linear_1.bias": [4096]},
    "minimax_h3": {"video_patch_proj.weight": [3072, 128], "audio_patch_proj.weight": [3072, 64]},
    "hunyuan_video": {
        "txt_in.individual_token_refiner.blocks.0.adaLN_modulation.1.weight": [6144, 3072],
    },
    "lingbot_video": {"patch_embedder.weight": [1536, 64]},
    "llada_image": {"sigvq_embedder.1.weight": [1536]},
}


def test_every_family_of_the_table_is_read_off_a_header():
    # One header per family: a family the reader cannot answer would be
    # offered by hand only.
    # SenseNova U1.5 is a folder: its family is read off the folder's index.
    assert set(_HEADERS) | {"sensenova_u1"} == {family.name for family in image_families.FAMILIES}


@pytest.mark.parametrize("family", sorted(_HEADERS))
def test_the_family_comes_from_the_header(tmp_path, family):
    # A name that points the other way: the header decides.
    path = _safetensors(tmp_path / "flux-sdxl-mix.safetensors", _HEADERS[family])
    assert bildinhalt.family(path) == family


def test_a_gguf_diffusion_model_is_read_like_a_safetensors_one(tmp_path):
    path = _gguf(tmp_path / "model.gguf", "flux", _HEADERS["flux"])
    assert bildinhalt.family(path) == "flux"
    assert bildinhalt.standalone_diffusion_model(path) is True


def test_an_unknown_header_has_no_family(tmp_path):
    """The silence probe: a file of no family in the table answers None,
    whatever its name says — no guess from the name."""
    path = _safetensors(tmp_path / "flux1-dev-sdxl.safetensors", {"foo.weight": [3, 3]})
    assert bildinhalt.family(path) is None
    assert bildinhalt.family(tmp_path / "missing.safetensors") is None


def test_a_checkpoint_is_no_standalone_diffusion_model(tmp_path):
    path = _safetensors(tmp_path / "sd.safetensors", _HEADERS["sd15"])
    assert bildinhalt.standalone_diffusion_model(path) is False


def test_the_companions_are_told_apart_by_their_weights(tmp_path):
    t5 = _safetensors(tmp_path / "a.safetensors", {
        "encoder.block.0.layer.0.SelfAttention.q.weight": [4096, 4096],
        "shared.weight": [32128, 4096],
    })
    umt5 = _gguf(tmp_path / "b.gguf", "t5encoder", {"token_embd.weight": [256384, 4096]})
    clip_l = _safetensors(tmp_path / "c.safetensors", {
        "text_model.embeddings.token_embedding.weight": [49408, 768],
    })
    clip_g = _safetensors(tmp_path / "d.safetensors", {
        "text_model.embeddings.token_embedding.weight": [49408, 1280],
    })
    vae16 = _safetensors(tmp_path / "e.safetensors", {"decoder.conv_in.weight": [512, 16, 3, 3]})
    vae4 = _safetensors(tmp_path / "f.safetensors", {"decoder.conv_in.weight": [512, 4, 3, 3]})
    llm = _gguf(tmp_path / "g.gguf", "qwen3", {"blk.0.attn_q.weight": [4096, 2560]})
    assert bildinhalt.companion(t5) == ("t5xxl", None)
    # UMT5 shares the build but not Flux's vocabulary: its own kind, for
    # the Wan models alone.
    assert bildinhalt.companion(umt5) == ("umt5", None)
    assert bildinhalt.companion(clip_l) == ("clip_l", None)
    assert bildinhalt.companion(clip_g) == ("clip_g", None)
    assert bildinhalt.companion(vae16) == (bildinhalt.VAE, 16)
    assert bildinhalt.companion(vae4) == (bildinhalt.VAE, 4)
    assert bildinhalt.companion(llm) == ("llm", None)
    # Wan's VAE: the same 16 channels as Flux's, over a 3D kernel.
    wan_vae = _safetensors(tmp_path / "h.safetensors", {"decoder.conv1.weight": [384, 16, 3, 3, 3]})
    assert bildinhalt.companion(wan_vae) == (bildinhalt.VIDEO_VAE, 16)


# --- The table ---------------------------------------------------------------


def test_every_start_value_names_its_source():
    fields = {field.name for field in dataclasses.fields(image_families.StartValues)}
    for family in image_families.FAMILIES:
        start = family.start
        needed = {"width", "height", "steps", "cfg", "sampler", "scheduler"}
        if start.guidance is not None:
            needed.add("guidance")
        assert needed <= set(start.sources), family.name
        # A source stands for a value there is: a misspelt name would leave
        # the value it was meant for with the wrong place.
        for variant in family.variants:
            # A variant names a place only for what it sets itself.
            assert set(variant.sources) == set(variant.own), family.name
        for values in (start, *(variant.start(start) for variant in family.variants)):
            # A switch line the family starts with has its place under its key.
            switch_keys = {switch.key for switch in image_switches.SWITCHES}
            assert set(values.sources) <= (fields - {"sources"}) | switch_keys, family.name
            assert set(values.switches) <= switch_keys & set(values.sources), family.name
            for name in ("flow_shift", "frames", "fps"):
                assert (getattr(values, name) is None) or name in values.sources, (family.name, name)
            for name in ("vae_format", "rng"):
                assert (not getattr(values, name)) or name in values.sources, (family.name, name)


def test_the_kit_families_start_at_the_docs_cfg_and_sdxl_at_its_authors():
    assert image_families.start_values("flux").cfg == 1.0
    assert image_families.start_values("zimage").cfg == 1.0
    sdxl = image_families.start_values("sdxl")
    assert (sdxl.width, sdxl.height, sdxl.steps, sdxl.cfg) == (1024, 1024, 20, 5.0)


def test_an_unknown_family_starts_where_sd_cli_starts():
    assert image_families.start_values("") is image_families.CLI_START
    assert image_families.start_values("unknown") is image_families.CLI_START


def test_the_json_table_is_the_table():
    table = image_families.as_json()
    assert [f["name"] for f in table] == [f.name for f in image_families.FAMILIES]
    flux = next(f for f in table if f["name"] == "flux")
    assert flux["encoders"] == ["t5xxl", "clip_l"]
    assert flux["start"]["sources"]["cfg"].startswith("sd.cpp docs/")


_FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"


def test_the_frontend_keeps_no_family_list_of_its_own():
    """The silence probe for the one table: no family name that only the
    table knows appears as a literal anywhere in the window's source."""
    for file in _FRONTEND.rglob("*"):
        if file.suffix in {".svelte", ".js"}:
            text = file.read_text(encoding="utf-8")
            assert "'zimage'" not in text and '"zimage"' not in text, file


# --- The routes -------------------------------------------------------------


@pytest.fixture
def picture_folder(config: Config, tmp_path: Path) -> Path:
    ordner = tmp_path / "bildmodelle"
    ordner.mkdir()
    config.app.bildmodelle_verzeichnis = str(ordner)
    return ordner


def test_the_window_reads_the_table_over_the_api(client: TestClient):
    answer = client.get("/api/v1/bild/familien")
    assert answer.status_code == 200
    assert answer.json() == image_families.as_json()


def test_the_defaults_of_a_flux_diffusion_model_come_with_their_parts(
    client: TestClient, picture_folder: Path
):
    _gguf(picture_folder / "my-model.gguf", "flux", _HEADERS["flux"])
    _safetensors(picture_folder / "text_encoders" / "enc1.safetensors", {
        "encoder.block.0.layer.0.SelfAttention.q.weight": [4096, 4096],
        "shared.weight": [32128, 4096],
    })
    _safetensors(picture_folder / "text_encoders" / "enc2.safetensors", {
        "text_model.embeddings.token_embedding.weight": [49408, 768],
    })
    _safetensors(picture_folder / "vae" / "small.safetensors", {"decoder.conv_in.weight": [512, 4, 3, 3]})
    _safetensors(picture_folder / "vae" / "wide.safetensors", {"decoder.conv_in.weight": [512, 16, 3, 3]})
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "my-model.gguf"}).json()
    assert v["family"] == "flux"
    assert v["standalone"] is True
    assert (v["cfg"], v["guidance"], v["sampler"]) == (1.0, 3.5, "euler")
    # No VAE by itself: a 16-channel VAE may be SD3's as well as Flux's, and
    # no header tells them apart. The model's own setting holds it.
    assert v["parts"] == {"t5xxl": "enc1.safetensors", "clip_l": "enc2.safetensors"}
    assert v["sources"]["cfg"].startswith("sd.cpp docs/flux.md")


def test_a_model_of_no_family_opens_on_sd_cli_values(client: TestClient, picture_folder: Path):
    _safetensors(picture_folder / "sdxl-looking-name.safetensors", {"foo.weight": [3]})
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "sdxl-looking-name.safetensors"}).json()
    assert v["family"] == ""
    assert (v["breite"], v["hoehe"], v["cfg"], v["scheduler"]) == (512, 512, 7.0, "")
    assert v["parts"] == {}


def test_the_old_global_picture_defaults_are_no_setting_any_more(client: TestClient):
    answer = client.put("/api/v1/settings/global/bild_vorgaben", json={"wert": {"breite": 768}})
    assert answer.status_code == 400


def test_nothing_reads_the_old_global_picture_defaults():
    app_ordner = Path(__file__).resolve().parents[1] / "app"
    for file in app_ordner.rglob("*.py"):
        assert "bild_vorgaben\"" not in file.read_text(encoding="utf-8"), file


# --- draw_image ---------------------------------------------------------------


# What the service's ``/bild/vorgaben`` answers per model: the start values
# of the two shapes this file is about (app/image_families.py). The stand-in
# itself is shared — tests/conftest.py, ``Bilddienst``.
_VORGABEN = {
    "flux.gguf": {
        "breite": 512, "hoehe": 512, "schritte": 20, "cfg": 1.0, "guidance": 3.5,
        "sampler": "euler", "scheduler": "", "family": "flux",
        "standalone": True, "parts": {"t5xxl": "t5.gguf", "clip_l": "clip.safetensors"},
    },
    "a.safetensors": {
        "breite": 1024, "hoehe": 1024, "schritte": 20, "cfg": 7.0, "guidance": None,
        "sampler": "euler_a", "scheduler": "", "family": "sdxl",
        "standalone": False, "parts": {},
    },
}


def _dienst(**werte) -> Bilddienst:
    """The shared stand-in, holding the two models of this file — and what
    this file knows about them. A test that wants another answer for
    ``/bild/vorgaben`` hands one in; it then wins over the table here."""
    eigene = {
        "modelle": ["a.safetensors", "flux.gguf"],
        "vorgaben": lambda modell: _VORGABEN.get(modell, _VORGABEN["a.safetensors"]),
    }
    return Bilddienst(**{**eigene, **werte})


def _draw(tmp_path, monkeypatch, service, chat_id=None):
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: service)
    asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel", chat_id=chat_id,
        )
    )
    return service.gezeichnet[-1]


def test_draw_image_draws_with_the_default_model_at_its_start_values(tmp_path, monkeypatch):
    """Every caller — a chat, another chat, a run without one — gets the
    picture server's default model at its family's start values."""
    bodies = [
        _draw(tmp_path, monkeypatch, _dienst(standardmodell="a.safetensors"), chat_id=chat)
        for chat in ("c1", "c2", None)
    ]
    for body in bodies:
        assert body["modell"] == "a.safetensors"
        assert (body["breite"], body["hoehe"], body["schritte"], body["cfg"]) == (1024, 1024, 20, 5.0)
        assert body["sampler"] == "euler"
        # The route's own defaults stand for what is not sent.
        assert "seed" not in body and "loras" not in body
        assert body["prompt"] == "a dog"
        for name in ("startbild", "maske", "pulid_id_embedding", "control_image"):
            assert name not in body


def test_a_flux_diffusion_model_goes_out_with_its_start_cfg_and_without_its_kit(
    tmp_path, monkeypatch,
):
    """The model's kit is the picture server's: the tool names the model and
    its family, the draw route adds the parts (app/api/v1/bild.py
    ``_model_kit``)."""
    service = _dienst(standardmodell="flux.gguf")
    body = _draw(tmp_path, monkeypatch, service, chat_id="c1")
    assert body["modell"] == "flux.gguf"
    for part in ("diffusion_model", "t5xxl", "clip_l", "vae"):
        assert part not in body
    assert body["familie"] == "flux"
    assert (body["cfg"], body["guidance"]) == (image_families.get("flux").start.cfg, 3.5)


def _llm(path: Path, architecture: str, width: int) -> Path:
    return _gguf(path, architecture, {"token_embd.weight": [151936, width]})


def _mmproj(path: Path) -> Path:
    """A vision projector: a GGUF that names the clip architecture and holds
    no token embedding, so it is no text encoder."""
    return _gguf(path, "clip", {"v.blk.0.attn_q.weight": [1152, 1152]})


def test_the_llm_whose_architecture_and_width_fit_is_put_in(client: TestClient, picture_folder: Path):
    """Z-Image reads Qwen3 4B: of a Qwen3 8B, a Qwen3-VL 4B and a Qwen3 4B
    in the folder, only the last one fits — and the 16-channel VAE beside
    them stays the model's own choice."""
    _safetensors(picture_folder / "zi.safetensors", _HEADERS["zimage"])
    _llm(picture_folder / "text_encoders" / "a-qwen3-8b.gguf", "qwen3", 4096)
    _llm(picture_folder / "text_encoders" / "b-qwen3vl-4b.gguf", "qwen3vl", 2560)
    _llm(picture_folder / "text_encoders" / "c-qwen3-4b.gguf", "qwen3", 2560)
    _safetensors(picture_folder / "vae" / "wide.safetensors", {"decoder.conv_in.weight": [512, 16, 3, 3]})
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "zi.safetensors"}).json()
    assert v["family"] == "zimage"
    assert v["parts"] == {"llm": "c-qwen3-4b.gguf"}


def test_no_llm_is_put_in_when_none_fits(client: TestClient, picture_folder: Path):
    """The silence probe: an LLM of the wrong width, or one whose header
    names no architecture, leaves the field empty."""
    _safetensors(picture_folder / "zi.safetensors", _HEADERS["zimage"])
    _llm(picture_folder / "text_encoders" / "qwen3-8b.gguf", "qwen3", 4096)
    _safetensors(picture_folder / "text_encoders" / "qwen_3_4b.safetensors", {
        "model.layers.0.self_attn.q_proj.weight": [4096, 2560],
        "model.embed_tokens.weight": [151936, 2560],
    })
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "zi.safetensors"}).json()
    assert v["parts"] == {}


@pytest.mark.parametrize(("family", "architecture", "width"), [
    ("flux2", "llama", 5120), ("flux2_klein", "qwen3", 2560), ("flux2_klein", "qwen3", 4096),
])
def test_flux2_gets_its_llm_and_its_own_vae(
    client: TestClient, picture_folder: Path, family, architecture, width
):
    """Flux.2 reads Mistral-Small-3.2, klein Qwen3 4B or 8B; both decode
    with Flux.2's own VAE, whose 32 channels no other VAE has."""
    _safetensors(picture_folder / "f2.safetensors", _HEADERS[family])
    _llm(picture_folder / "text_encoders" / "enc.gguf", architecture, width)
    _safetensors(picture_folder / "vae" / "ae.safetensors", {"decoder.conv_in.weight": [512, 16, 3, 3]})
    _safetensors(picture_folder / "vae" / "flux2-vae.safetensors", {"decoder.conv_in.weight": [512, 32, 3, 3]})
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "f2.safetensors"}).json()
    assert v["family"] == family
    assert v["parts"] == {"llm": "enc.gguf", "vae": "flux2-vae.safetensors"}


def test_flux2_klein_leaves_the_llm_open_when_4b_and_8b_both_fit(client: TestClient, picture_folder: Path):
    """klein 4B reads Qwen3 4B, klein 9B Qwen3 8B: with both in the folder
    the header of the encoders cannot say which one this model wants."""
    _safetensors(picture_folder / "klein.safetensors", _HEADERS["flux2_klein"])
    _llm(picture_folder / "text_encoders" / "qwen3-4b.gguf", "qwen3", 2560)
    _llm(picture_folder / "text_encoders" / "qwen3-8b.gguf", "qwen3", 4096)
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "klein.safetensors"}).json()
    assert "llm" not in v["parts"]


def test_two_copies_of_the_same_llm_still_fit(client: TestClient, picture_folder: Path):
    """The silence probe: two files of one width are the same choice."""
    _safetensors(picture_folder / "zi.safetensors", _HEADERS["zimage"])
    _llm(picture_folder / "text_encoders" / "qwen3-4b-q4.gguf", "qwen3", 2560)
    _llm(picture_folder / "text_encoders" / "qwen3-4b-q8.gguf", "qwen3", 2560)
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "zi.safetensors"}).json()
    assert v["parts"] == {"llm": "qwen3-4b-q4.gguf"}


def test_the_qwen3vl_8b_encoder_comes_to_qwen_image_2_1_in_any_quantisation(
    client: TestClient, picture_folder: Path
):
    """Qwen-Image 2.1 reads Qwen3-VL 8B (architecture qwen3vl, width 4096):
    of a 4B (2560), the 8B in two quantisations and the vision projector in
    the folder, an 8B is put in — and only one of the two quantisations."""
    _safetensors(picture_folder / "q21.safetensors", _HEADERS["qwen_image_2_1"])
    _llm(picture_folder / "text_encoders" / "a-qwen3vl-4b.gguf", "qwen3vl", 2560)
    _mmproj(picture_folder / "text_encoders" / "b-mmproj-qwen3vl-8b.gguf")
    _llm(picture_folder / "text_encoders" / "c-qwen3vl-8b-q8.gguf", "qwen3vl", 4096)
    _llm(picture_folder / "text_encoders" / "d-qwen3vl-8b-q4.gguf", "qwen3vl", 4096)
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "q21.safetensors"}).json()
    assert v["family"] == "qwen_image_2_1"
    assert v["parts"]["llm"] == "c-qwen3vl-8b-q8.gguf"


def test_nothing_that_is_not_qwen3vl_8b_comes_to_qwen_image_2_1(client: TestClient, picture_folder: Path):
    """The silence probe: the 4B of Krea 2, a vision projector and a
    safetensors encoder that names no architecture leave the field to the
    user, and Krea 2 still takes its 4B with the 8B beside it."""
    _safetensors(picture_folder / "q21.safetensors", _HEADERS["qwen_image_2_1"])
    _llm(picture_folder / "text_encoders" / "qwen3vl-4b.gguf", "qwen3vl", 2560)
    _mmproj(picture_folder / "text_encoders" / "mmproj-qwen3vl-8b.gguf")
    _safetensors(picture_folder / "text_encoders" / "qwen3vl_8b_bf16.safetensors", {
        "model.layers.0.self_attn.q_proj.weight": [4096, 4096],
        "model.embed_tokens.weight": [151936, 4096],
    })
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "q21.safetensors"}).json()
    assert "llm" not in v["parts"]
    _safetensors(picture_folder / "k2.safetensors", _HEADERS["krea2"])
    _llm(picture_folder / "text_encoders" / "qwen3vl-8b.gguf", "qwen3vl", 4096)
    k = client.get("/api/v1/bild/vorgaben", params={"modell": "k2.safetensors"}).json()
    assert k["family"] == "krea2"
    assert k["parts"]["llm"] == "qwen3vl-4b.gguf"


def test_flux1_reads_no_llm(client: TestClient, picture_folder: Path):
    _gguf(picture_folder / "my-model.gguf", "flux", _HEADERS["flux"])
    _llm(picture_folder / "text_encoders" / "enc.gguf", "qwen3", 2560)
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "my-model.gguf"}).json()
    assert "llm" not in v["parts"]


def test_a_kit_checkpoint_with_its_own_vae_brings_no_parts(client: TestClient, picture_folder: Path):
    _safetensors(picture_folder / "merged.safetensors", {
        "model.diffusion_model.double_blocks.0.img_attn.qkv.weight": [9216, 3072],
        "first_stage_model.decoder.conv_in.weight": [512, 16, 3, 3],
    })
    _safetensors(picture_folder / "vae" / "wide.safetensors", {"decoder.conv_in.weight": [512, 16, 3, 3]})
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "merged.safetensors"}).json()
    assert (v["family"], v["standalone"], v["parts"]) == ("flux", False, {})


def test_a_diffusion_model_of_no_family_is_still_told_standalone(client: TestClient, picture_folder: Path):
    """So a family said by hand can fill the diffusion field (a model the
    table does not hold)."""
    _safetensors(picture_folder / "unheard.safetensors", {
        "unheard_of_blocks.1.weight": [1536],
    })
    v = client.get("/api/v1/bild/vorgaben", params={"modell": "unheard.safetensors"}).json()
    assert (v["family"], v["standalone"], v["parts"]) == ("", True, {})


def test_a_gguf_with_more_dimensions_than_ggml_holds_is_unread(tmp_path):
    path = _gguf(tmp_path / "broken.gguf", "flux", {"double_blocks.0.x": [1, 2, 3, 4, 5]})
    assert bildinhalt.tensors(path) is None


def test_the_studio_starts_a_chosen_model_at_its_own_values():
    """A model chosen by hand starts the chat at that model's values; the
    studio holds no kit to clear, the picture server holds it per model."""
    source = (_FRONTEND / "teile" / "StudioBasics.svelte").read_text(encoding="utf-8")
    chosen = source.split("async function modellGewaehlt(name) {", 1)[1].split("\n  }\n", 1)[0]
    assert "Object.assign(werte, startwerte(v))" in chosen
    # An answer that comes back after the next choice changes nothing.
    assert "if (!v || werte.modell !== name) return" in chosen
    assert "diffusionModell" not in source and "KIT_EXTRAS" not in source


def test_a_free_prompt_style_text_is_no_stored_value():
    """A free text kept beside the style's id is no style: the service keeps
    none."""
    assert bildfensterwahl.wahl_pruefen({"stil": "Photo", "prompt_stil": "cinematic"}) == {
        "stil": "Photo",
    }


def test_the_chat_keeps_a_fractional_cfg():
    """A CFG of 3.5 set in the window is stored as 3.5, not rounded to 4."""
    assert bildfensterwahl.wahl_pruefen({"cfg": 3.5}) == {"cfg": 3.5}
    assert bildfensterwahl.wahl_pruefen({"cfg": 99}) == {"cfg": 99.0}
    assert bildfensterwahl.wahl_pruefen({"cfg": float("nan")}) is None


def test_a_diffusion_model_with_the_prefix_is_still_standalone(tmp_path):
    """Measured on a real file: a Flux diffusion model can carry every
    weight under ``model.diffusion_model.`` and nothing else. sd.cpp adds the
    prefix only where it is missing, so it is a kit part like one without."""
    path = _safetensors(tmp_path / "merged-looking.safetensors", {
        "model.diffusion_model.double_blocks.0.img_attn.qkv.weight": [9216, 3072],
    })
    assert bildinhalt.family(path) == "flux"
    assert bildinhalt.standalone_diffusion_model(path) is True


def test_a_family_said_by_hand_starts_at_the_values_the_service_answers_with():
    column = (_FRONTEND / "teile" / "StudioDetails.svelte").read_text(encoding="utf-8")
    assert "gewaehlt={familieWaehlen}" in column
    store = (_FRONTEND / "lib" / "studio.svelte.js").read_text(encoding="utf-8")
    said = store.split("export async function familieWaehlen(name) {", 1)[1].split("\n}\n", 1)[0]
    assert "werte.familie = name" in said
    # The service works the values out from the family and the file name.
    assert "vorgabenHolen(name)" in said
    assert "Object.assign(werte, startwerte(v))" in said
    assert "familyOf(werte.familie)" not in store.split("export function startwerte(v) {", 1)[1].split("\n}\n", 1)[0]
    # Said by hand only for a model whose header names none: a header that
    # names one takes over on the next model change.
    basics = (_FRONTEND / "teile" / "StudioBasics.svelte").read_text(encoding="utf-8")
    assert "if (v.family) werte.familie = ''" in basics


def test_chroma_is_no_flux(tmp_path):
    """Chroma shares Flux's blocks; sd.cpp tells it apart by its distilled
    guidance layer. It is its own family, not Flux."""
    path = _safetensors(tmp_path / "flux-chroma.safetensors", {
        "double_blocks.0.img_attn.qkv.weight": [9216, 3072],
        "distilled_guidance_layer.in_proj.weight": [5120, 64],
    })
    assert bildinhalt.family(path) == "chroma"


def test_a_file_of_no_family_answers_none(tmp_path):
    """The silence probe: a model the table does not hold, a VAE and a bare
    text encoder name no family."""
    wan = _safetensors(tmp_path / "unheard.safetensors", {"unheard_of_blocks.1.weight": [1536]})
    vae = _safetensors(tmp_path / "vae.safetensors", {"decoder.conv_in.weight": [512, 16, 3, 3]})
    clip = _safetensors(tmp_path / "clip.safetensors", {
        "text_model.embeddings.token_embedding.weight": [49408, 768],
    })
    assert [bildinhalt.family(p) for p in (wan, vae, clip)] == [None, None, None]


@pytest.fixture
def draw_job(client: TestClient, picture_folder: Path, monkeypatch):
    """POST /bild up to the job that would reach sd-cli, and that job."""
    from app.bildrunner import Bildrunner

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    seen: dict = {}

    def _generate(self, job, target):
        seen["job"] = job
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"PNG")
        return target

    monkeypatch.setattr(Bildrunner, "erzeugen", _generate)

    def _send(**fields):
        answer = client.post("/api/v1/bild", json={"prompt": "x", **fields})
        return answer, seen.get("job")

    return _send


def _flux_kit(folder: Path) -> None:
    _gguf(folder / "d.gguf", "flux", _HEADERS["flux"])
    _safetensors(folder / "text_encoders" / "t5.safetensors", {
        "encoder.block.0.layer.0.SelfAttention.q.weight": [4096, 4096],
        "shared.weight": [32128, 4096],
    })
    _safetensors(folder / "text_encoders" / "clip.safetensors", {
        "text_model.embeddings.token_embedding.weight": [49408, 768],
    })
    _safetensors(folder / "vae" / "ae.safetensors", {"decoder.conv_in.weight": [512, 16, 3, 3]})


def test_the_draw_route_reads_the_family_off_the_header_before_it_checks_the_parts(
    draw_job, picture_folder: Path
):
    """A request with a kit's parts but no family is judged by the header:
    the diffusion model says flux, so a T5 beside it is no mistake."""
    _flux_kit(picture_folder)
    answer, job = draw_job(
        modell="d.gguf", diffusion_model="d.gguf", t5xxl="t5.safetensors",
        clip_l="clip.safetensors", vae="ae.safetensors",
    )
    assert answer.status_code == 201, answer.text
    assert job.familie == "flux"


def test_an_unknown_family_word_is_refused_even_when_the_header_knows(
    draw_job, picture_folder: Path
):
    """The silence probe: a family word said is checked as said, never
    replaced by what the header says."""
    _flux_kit(picture_folder)
    answer, _ = draw_job(
        modell="d.gguf", diffusion_model="d.gguf", t5xxl="t5.safetensors", familie="cosmos",
    )
    assert answer.status_code == 400


def test_the_tool_takes_the_family_the_route_names(tmp_path, monkeypatch):
    """The route names the family of the default model: the tool draws
    with that family's start values and sends no kit parts."""
    service = _dienst(
        standardmodell="flux.gguf",
        vorgaben=lambda modell: {**_VORGABEN["a.safetensors"], "family": "sdxl"},
    )
    body = _draw(tmp_path, monkeypatch, service, chat_id="c1")
    assert body["familie"] == "sdxl"
    assert "diffusion_model" not in body
    assert (body["breite"], body["cfg"]) == (1024, 5.0)


def test_the_model_list_names_each_model_s_family(client: TestClient, picture_folder: Path):
    """The window groups its model list by family: the list answer carries
    each model's family from its header, empty for one that names none."""
    _gguf(picture_folder / "f.gguf", "flux", _HEADERS["flux"])
    _safetensors(picture_folder / "x.safetensors", {"foo.weight": [3]})
    answer = client.get("/api/v1/bild/modelle").json()
    assert answer["families"] == {"f.gguf": "flux", "x.safetensors": ""}


# --- Every family's command line, editing, PuLID ---------------------------

from app import bildrunner  # noqa: E402
from app.api.v1.bild import _turbo_auftrag  # noqa: E402
from app.bildrunner import Auftrag, Bildrunner  # noqa: E402

_KITS = [family for family in image_families.FAMILIES if family.kit]


def _command(tmp_path: Path, monkeypatch, **fields) -> list[str]:
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    return Bildrunner(tmp_path).befehl(
        Auftrag(modell=tmp_path / "m.gguf", prompt="x", **fields), tmp_path / "out.png"
    )


@pytest.mark.parametrize("family", _KITS, ids=lambda f: f.name)
def test_each_kit_family_builds_its_command_from_the_table(tmp_path, monkeypatch, family):
    """Every file the table says the family reads rides on its own switch,
    and a file it does not read is refused."""
    files = {name: tmp_path / f"{name}.bin" for name in (*family.encoders, *family.parts)}
    command = _command(
        tmp_path, monkeypatch, familie=family.name, diffusion_model=tmp_path / "d.gguf",
        model_args=family.model_args,
        **files,
    )
    assert command[command.index("--diffusion-model") + 1] == str(tmp_path / "d.gguf")
    switches = {
        "t5xxl": "--t5xxl", "clip_l": "--clip_l", "clip_g": "--clip_g", "llm": "--llm",
        "llm_vision": "--llm_vision", "tokenizer": "--tokenizer",
        "uncond_diffusion_model": "--uncond-diffusion-model",
        "high_noise_diffusion_model": "--high-noise-diffusion-model",
        "audio_vae": "--audio-vae", "audio_encoder": "--audio-encoder",
        "embeddings_connectors": "--embeddings-connectors", "clip_vision": "--clip_vision",
    }
    for name, path in files.items():
        assert command[command.index(switches[name]) + 1] == str(path)
    if family.model_args:
        assert command[command.index("--model-args") + 1] == family.model_args
    else:
        assert "--model-args" not in command
    stranger = next(n for n in ("llm", "t5xxl", "clip_l") if n not in family.encoders)
    with pytest.raises(bildrunner.BildFehler):
        _command(tmp_path, monkeypatch, familie=family.name,
                 diffusion_model=tmp_path / "d.gguf", **{stranger: tmp_path / "x.bin"})


def test_sdxl_draws_with_the_same_command_as_before(tmp_path, monkeypatch):
    """The silence probe: a plain SDXL checkpoint gains no switch."""
    command = _command(tmp_path, monkeypatch, familie="sdxl", breite=1024, hoehe=1024)
    assert command[1:3] == ["-m", str(tmp_path / "m.gguf")]
    for switch in ("--diffusion-model", "--llm_vision", "--tokenizer",
                   "--uncond-diffusion-model", "--model-args", "-r", "--img-cfg-scale",
                   "--ref-image-args", "--increase-ref-index"):
        assert switch not in command


def test_an_edit_carries_its_references_and_values(tmp_path, monkeypatch):
    refs = (tmp_path / "a.png", tmp_path / "b.png")
    command = _command(tmp_path, monkeypatch, ref_bilder=refs, img_cfg=2.5,
                       ref_image_args="preset=qwen", increase_ref_index=True)
    assert [command[i + 1] for i, part in enumerate(command) if part == "-r"] == [str(r) for r in refs]
    assert command[command.index("--img-cfg-scale") + 1] == "2.5"
    assert command[command.index("--ref-image-args") + 1] == "preset=qwen"
    assert "--increase-ref-index" in command


def test_text_to_image_carries_no_reference_values(tmp_path, monkeypatch):
    """The silence probe: without a reference picture the edit's values
    act on nothing and stay off."""
    command = _command(tmp_path, monkeypatch, img_cfg=2.5, ref_image_args="preset=qwen",
                       increase_ref_index=True)
    for switch in ("-r", "--img-cfg-scale", "--ref-image-args", "--increase-ref-index"):
        assert switch not in command


def test_the_server_body_carries_the_references(tmp_path):
    ref = tmp_path / "a.png"
    ref.write_bytes(b"PNG")
    body = _turbo_auftrag(Auftrag(modell=tmp_path / "m.gguf", prompt="x", ref_bilder=(ref,),
                                  img_cfg=3.0, ref_image_args="preset=qwen",
                                  increase_ref_index=True))
    assert len(body["ref_images"]) == 1
    assert body["sample_params"]["guidance"]["img_cfg"] == 3.0
    assert body["ref_image_args"] == "preset=qwen"
    assert body["increase_ref_index"] is True
    plain = _turbo_auftrag(Auftrag(modell=tmp_path / "m.gguf", prompt="x"))
    assert "ref_images" not in plain and "img_cfg" not in plain["sample_params"]["guidance"]


def test_the_draw_route_hands_the_references_on(draw_job, picture_folder: Path, config: Config):
    _safetensors(picture_folder / "m.safetensors", _HEADERS["sd15"])
    from app.api.v1.bild import _bilderziel
    stored = _bilderziel(config)
    stored.mkdir(parents=True, exist_ok=True)
    names = ["a" * 32 + ".png", "b" * 32 + ".png"]
    for name in names:
        (stored / name).write_bytes(b"PNG")
    answer, job = draw_job(modell="m.safetensors", ref_bilder=names, img_cfg=2.0)
    assert answer.status_code == 201, answer.text
    assert job.ref_bilder == tuple(stored / name for name in names)
    assert job.img_cfg == 2.0
    # Without a reference the image CFG is dropped.
    answer, job = draw_job(modell="m.safetensors", img_cfg=2.0)
    assert job.ref_bilder == () and job.img_cfg is None


def test_pulid_takes_an_embedding_and_refuses_a_photo(draw_job, picture_folder: Path, client):
    _safetensors(picture_folder / "m.safetensors", _HEADERS["flux"])
    # A whole Flux kit, the VAE given to the model in the picture server.
    _safetensors(picture_folder / "text_encoders" / "t5.safetensors", {
        "encoder.block.0.layer.0.SelfAttention.q.weight": [4096, 4096],
        "shared.weight": [32128, 4096],
    })
    _safetensors(picture_folder / "text_encoders" / "clip.safetensors", {
        "text_model.encoder.layers.0.self_attn.q_proj.weight": [768, 768],
        "text_model.embeddings.token_embedding.weight": [49408, 768],
    })
    _safetensors(picture_folder / "vae" / "ae.safetensors", {"decoder.conv_in.weight": [512, 16, 3, 3]})
    client.put("/api/v1/settings/global/bildmodellwerte",
               json={"wert": {"m.safetensors": {"vae": "ae.safetensors"}}})
    pulid = picture_folder / "pulid"
    _safetensors(pulid / "pulid_flux.safetensors", {"id_adapter.weight": [8, 8]})
    (pulid / "me.pulidembd").write_bytes(b"EMBD")
    (pulid / "me.png").write_bytes(b"PNG")
    answer, _ = draw_job(modell="m.safetensors", pulid_weights="pulid_flux.safetensors",
                         pulid_id_embedding="me.png")
    assert answer.status_code == 404
    answer, job = draw_job(modell="m.safetensors", pulid_weights="pulid_flux.safetensors",
                           pulid_id_embedding="me.pulidembd")
    assert answer.status_code == 201, answer.text
    assert job.pulid_id_embedding == pulid / "me.pulidembd"


def test_without_pulid_the_command_stays_as_it_was(tmp_path, monkeypatch):
    """The silence probe."""
    command = _command(tmp_path, monkeypatch)
    assert "--pulid-weights" not in command and "--pulid-id-embedding" not in command


def test_a_checkpoint_and_a_standalone_file_are_read_alike(tmp_path):
    """sd.cpp prefixes a standalone file's names on loading; a rule written
    with the prefix finds its name in either spelling."""
    raw = _safetensors(tmp_path / "raw.safetensors", {"txt_in.text_norm.weight": [4096]})
    prefixed = _safetensors(tmp_path / "prefixed.safetensors",
                            {"model.diffusion_model.txt_in.text_norm.weight": [4096]})
    assert bildinhalt.family(raw) == bildinhalt.family(prefixed) == "qwen_image_2_1"


def test_the_three_gguf_files_of_qwen_image_2_1_are_one_family(tmp_path):
    """Measured on the files of the model: the turbo file names its weights
    with sd.cpp's prefix and an architecture of its own, the plain one has
    none worth the name and no prefix, and the UC one names a third
    architecture. One family, whichever way the converter wrote it. (The
    helper writes a GGUF only when it is given an architecture; an empty one
    stands for the plain file's.)"""
    from tests.test_bild_bausatz_api import _kopf

    weights = {"txt_in.text_norm.weight": [4096], "img_in.weight": [3072, 64]}
    prefixed = {f"model.diffusion_model.{name}": shape for name, shape in weights.items()}
    for name, names, architecture in (
        ("turbo.gguf", prefixed, "qwen_image"),
        ("plain.gguf", weights, ""),
        ("uc.gguf", weights, "qwen_image21"),
    ):
        _kopf(tmp_path / name, dict(names), architecture)
        assert bildinhalt.family(tmp_path / name) == "qwen_image_2_1", name


def test_silence_a_gguf_of_qwen_image_without_the_2_1_layer_stays_qwen_image(tmp_path):
    from tests.test_bild_bausatz_api import _kopf

    _kopf(tmp_path / "qwen.gguf", {
        "model.diffusion_model.transformer_blocks.0.img_mod.1.weight": [18432, 3072],
        "model.diffusion_model.img_in.weight": [3072, 64],
    }, "qwen_image")
    assert bildinhalt.family(tmp_path / "qwen.gguf") == "qwen_image"


def test_silence_a_gguf_that_cannot_be_read_has_no_family(tmp_path):
    broken = tmp_path / "broken.gguf"
    broken.write_bytes(b"GGUF" + b"\x00" * 12)
    assert bildinhalt.family(broken) is None


def test_only_a_t5_xxl_counts_as_t5xxl(tmp_path):
    """flan-t5-large shares T5-XXL's vocabulary at a width of 1024 and is
    not offered as the T5 of a Flux."""
    xxl = _safetensors(tmp_path / "xxl.safetensors", {
        "encoder.block.0.layer.0.SelfAttention.q.weight": [4096, 4096],
        "shared.weight": [32128, 4096],
    })
    large = _safetensors(tmp_path / "large.safetensors", {
        "encoder.block.0.layer.0.SelfAttention.q.weight": [1024, 1024],
        "shared.weight": [32128, 1024],
    })
    assert bildinhalt.companion(xxl)[0] == "t5xxl"
    assert bildinhalt.companion(large)[0] == ""


def test_an_old_photo_stored_as_pulid_embedding_is_dropped():
    """What the old picture drop stored (a photo) is no embedding."""
    stored = bildfensterwahl.wahl_pruefen({"pulid_id_embedding": "c" * 32 + ".png", "breite": 512})
    assert stored == {"breite": 512}
    kept = bildfensterwahl.wahl_pruefen({"pulid_id_embedding": "me.pulidembd"})
    assert kept == {"pulid_id_embedding": "me.pulidembd"}


def test_an_embedding_name_without_pulid_weights_stops_no_picture(draw_job, picture_folder: Path):
    _safetensors(picture_folder / "m.safetensors", _HEADERS["sd15"])
    answer, job = draw_job(modell="m.safetensors", pulid_id_embedding="gone.pulidembd")
    assert answer.status_code == 201, answer.text
    assert job.pulid_id_embedding is None


def test_a_safetensors_header_is_read_by_name_whatever_its_order(tmp_path):
    """sd.cpp reads a safetensors header through a JSON object, sorted by
    name: Lens is Lens even when its img_mod weight is written first."""
    path = _safetensors(tmp_path / "lens.safetensors", {
        "transformer_blocks.0.img_mod.1.weight": [18432, 3072],
        "transformer_blocks.0.attn.norm_added_q.weight": [128],
        "transformer_blocks.0.img_mlp.w1.weight": [8192, 3072],
    })
    assert bildinhalt.family(path) == "lens"


def test_dit_families_start_with_sd_cli_s_own_sampler():
    """euler for every DiT model, lcm for PiD, euler_a for the U-Net ones
    (sd.cpp src/pipeline/request.cpp:45-55) — but for the families whose
    authors name another one."""
    named = {
        "pid": "lcm", "sd2": "dpm++2m", "sdxl": "euler", "sdxl_pix2pix": "euler",
        "anima": "er_sde", "pixart": "dpm++2m", "sensenova_u1": "euler",
    }
    for family in image_families.FAMILIES:
        if family.name in named:
            assert family.start.sampler == named[family.name], family.name
            assert not family.start.sources["sampler"].startswith("sd-cli --help"), family.name
        elif family.kit or family.name == "hidream_o1":
            assert family.start.sampler == "euler", family.name
        else:
            assert family.start.sampler == "euler_a", family.name


# --- Where a kit's parts come from ------------------------------------------

# The kit families the table names no source for, each with what its doc
# leaves open. A family missing here must name its parts.
_NO_SOURCE = {
    # Its doc lies only in sd.cpp's own tree; where its parts are fetched
    # from is not entered.
    "llada_image",
    # No doc of its own in sd.cpp's docs/.
    "qwen_image_layered",
    # Its text encoder exists only as the output of a conversion script.
    "sefi",
    # Its text encoder lies in a repository under the bare name
    # model.safetensors, and its model under diffusion_pytorch_model.
    "minit2i",
    # Its T5 lies in two shards, which sd.cpp does not read as one file.
    "pixart",
}
# Chroma1-Radiance draws the picture itself, and an SD3 checkpoint carries
# its VAE: their docs name none.
_NO_VAE = {"chroma_radiance", "sd3", "iris"}


def test_every_family_with_a_kit_names_a_source_for_each_part():
    from app import image_families

    kits = [f for f in image_families.FAMILIES if f.kit]
    assert {f.name for f in kits if not f.kit_parts} == _NO_SOURCE
    for family in kits:
        if not family.kit_parts:
            continue
        fields = {part.part for part in family.kit_parts}
        # The text encoders, the VAE and the further parts the family
        # declares (the vision half of an encoder).
        assert fields - {"vae"} - set(family.parts) == set(family.encoders), family.name
        assert ("vae" in fields) == (family.name not in _NO_VAE), family.name
        for part in family.kit_parts:
            assert "/" in part.repo and part.file and part.source, family.name
            assert part.name == part.file.rsplit("/", 1)[-1]
            assert part.folder == ("vae" if part.part in ("vae", "audio_vae") else "text_encoders")
        # Every family with parts is told by its file name, or nothing finds
        # its kit.
        assert family.file_patterns, family.name


def test_no_part_comes_from_a_repository_that_asks_for_a_login():
    from app import image_families

    # Measured on the hub: these answer 401 without a login.
    closed = {"black-forest-labs/FLUX.1-dev", "black-forest-labs/FLUX.1-schnell",
              "black-forest-labs/FLUX.2-dev", "Lightricks/LTX-2.5"}
    for family in image_families.FAMILIES:
        for part in family.kit_parts:
            assert part.repo not in closed, (family.name, part.part)


def test_a_file_one_name_stands_for_is_one_file():
    """Two parts saved under one name in one folder have to be one file:
    the second is never fetched once the first is there."""
    from app import image_families

    seen = {}
    # The same file under one name in two repositories (measured: one size
    # and one SHA-256 each).
    same = {
        ("text_encoders", "clip_l.safetensors"), ("text_encoders", "t5xxl_fp16.safetensors"),
        ("vae", "qwen_image_vae.safetensors"),
    }
    for family in image_families.FAMILIES:
        for part in family.kit_parts:
            key = (part.folder, part.name)
            if key not in same:
                assert seen.setdefault(key, part.repo) == part.repo, key


def test_the_file_name_shows_the_family():
    from app import image_families

    expected = {
        "z_image_turbo-Q4_K_M.gguf": "zimage",
        "Z-Image-Turbo.safetensors": "zimage",
        "Krea-2-Raw-Q8_0.gguf": "krea2",
        "flux1-dev-Q8_0.gguf": "flux",
        "FLUX.1-schnell-Q4.gguf": "flux",
        "flux1-kontext-dev-Q8_0.gguf": "flux",
        "chroma-unlocked-v40-q8_0.gguf": "chroma",
        "Chroma1-Radiance-Q8.gguf": "chroma_radiance",
        "Qwen-Image-Edit-2511-Q4_K_M.gguf": "qwen_image",
        "sub/ordner/qwen_image_Q4.gguf": "qwen_image",
        "ernie-image-turbo.safetensors": "ernie",
        "anima2.safetensors": "anima",
        "sd3.5_large.safetensors": "sd3",
        "sd3_medium.safetensors": "sd3",
        "flux2-dev-Q4_K_S.gguf": "flux2",
        "FLUX.2-dev-Q8_0.gguf": "flux2",
        "flux-2-klein-4b.safetensors": "flux2_klein",
        "flux-2-klein-base-9b-Q4_K_M.gguf": "flux2_klein",
        "qwen_image_2.1_int8_convrot.safetensors": "qwen_image_2_1",
        "Qwen-Image-2.1-Q4_K_M.gguf": "qwen_image_2_1",
        "Qwen Image 2.1 Q4.gguf": "qwen_image_2_1",
        "sd3.5m_turbo.safetensors": "sd3",
        "lens_turbo_bf16.safetensors": "lens",
        # A model trained on another carries that one's name behind its own.
        "pid_flux1_512_to_2048_4step_bf16.safetensors": "pid",
        "pid_1.5_flux2_1024_to_4096_bf16.safetensors": "pid",
        "pid_sd3_512_to_2048_4step_bf16.safetensors": "pid",
        "LongCat-Image-Q4_K_M.gguf": "longcat",
        "ovis_image-Q4_0.gguf": "ovis",
        "boogu_image_base_bf16.safetensors": "boogu",
        "Mage-Flow-Turbo.safetensors": "mage_flow",
        "ideogram4-Q8_0.gguf": "ideogram4",
        "wan2.1_t2v_1.3B_fp16.safetensors": "wan",
        "wan2.1-i2v-14b-480p-Q8_0.gguf": "wan",
        "Wan2.2-T2V-A14B-LowNoise-Q8_0.gguf": "wan",
        "Wan2.2-I2V-A14B-HighNoise-Q8_0.gguf": "wan22_i2v",
        "wan2.2_ti2v_5B_fp16.safetensors": "wan22_ti2v",
        "wan2.2_s2v-14B-Q8_0.gguf": "wan22_s2v",
        "ltx-2.3-22b-dev-UD-Q4_K_M.gguf": "ltx",
        "minimax_h3_fl2va-Q4_K_M.gguf": "minimax_h3",
        "minimax_h3_ref2va_pruned-Q4_K_M.gguf": "minimax_h3",
        "hunyuanvideo1.5_720p_t2v_fp16.safetensors": "hunyuan_video",
        "lingbot-video-dense-1.3b.safetensors": "lingbot_video",
    }
    for name, family in expected.items():
        found = image_families.family_of_file(name)
        assert found is not None and found.name == family, name


def test_a_name_without_family_shows_none():
    from app import image_families

    for name in (
        "sd_xl_base_1.0.safetensors", "animagine-xl.safetensors", "Qwen-Image-Layered.gguf",
        "internet.gguf", "novis.gguf", "chromatic-xl.safetensors", "jazz_image.safetensors",
        "reflux1.gguf", "sd30.safetensors", "fisheye-lens-xl.safetensors", "swan2.1.gguf",
        "sd_3d_render_xl.safetensors", "sd3_medium_incl_clips.safetensors",
        # The encoder of MiniMax-H3 carries the family's name and is no model.
        "qwen3vl_32b_minimax_h3-Q4_K_M.gguf",
    ):
        assert image_families.family_of_file(name) is None, name
        assert image_families.kit_of_file(name) == (), name


def _kit(name: str) -> dict[str, str]:
    from app import image_families

    return {part.part: part.name for part in image_families.kit_of_file(name)}


def test_the_kit_goes_with_the_model_the_name_shows():
    # The encoder of a Flux.2 klein goes with its size.
    assert _kit("flux-2-klein-4b.safetensors") == {
        "llm": "Qwen3-4B-Q4_K_M.gguf", "vae": "flux2-vae.safetensors",
    }
    assert _kit("flux-2-klein-base-9b-Q4_K_M.gguf") == {
        "llm": "Qwen3-8B-Q4_K_M.gguf", "vae": "flux2-vae.safetensors",
    }
    # The VAE of a PiD is the one of the model it was trained on.
    assert _kit("pid_flux1_512_to_2048_4step_bf16.safetensors")["vae"] == "ae.safetensors"
    assert _kit("pid_1.5_flux2_1024_to_4096_bf16.safetensors")["vae"] == "flux2-vae.safetensors"
    # Wan 2.2 TI2V 5B alone decodes with the Wan 2.2 VAE.
    assert _kit("wan2.2_ti2v_5B_fp16.safetensors")["vae"] == "wan2.2_vae.safetensors"
    assert _kit("Wan2.2-I2V-A14B-HighNoise-Q8_0.gguf")["vae"] == "wan_2.1_vae.safetensors"
    assert _kit("sd3.5_large.safetensors") == {
        "clip_l": "clip_l.safetensors", "clip_g": "clip_g.safetensors",
        "t5xxl": "t5xxl_fp16.safetensors",
    }


def test_half_a_kit_is_none():
    """A model its family names a field's file only for others gets no kit:
    a block that lists some of its parts would call it complete without the
    rest."""
    # A klein whose name carries no size has no encoder to go with.
    assert _kit("flux-2-klein.safetensors") == {}
    assert _kit("flux-2-klein-14b.safetensors") == {}
    # A PiD trained on a model whose VAE the doc names no single file for.
    assert _kit("pid_sd3_512_to_2048_4step_bf16.safetensors") == {}
    assert _kit("pid_qwenimage_1024_to_4096_4step_bf16.safetensors") == {}
    # LTX-2.5 reads files of its own, which lie behind a login.
    assert _kit("ltx-2.5-22b-dev-transformer-Q8_0.gguf") == {}
    assert _kit("ltx-2.3-22b-dev-UD-Q4_K_M.gguf") == {
        "llm": "gemma-3-12b-it-UD-Q4_K_XL.gguf",
        "vae": "ltx-2.3-22b-dev_video_vae.safetensors",
        "audio_vae": "ltx-2.3-22b-dev_audio_vae.safetensors",
        "embeddings_connectors": "ltx-2.3-22b-dev_embeddings_connectors.safetensors",
    }


def test_krea2_draws_from_a_start_picture():
    """sd-cli draws picture to picture and through a mask with a Krea 2
    model, so the family carries the task and the studio offers the kind."""
    assert image_families.get("krea2").tasks == ("txt2img", "img2img", "edit")
    listed = {entry["name"]: entry["tasks"] for entry in image_families.as_json()}
    assert "img2img" in listed["krea2"]
    # The silence check: the families nobody has measured it with keep theirs.
    for name in ("qwen_image", "longcat", "anima", "boogu", "mage_flow"):
        assert image_families.get(name).tasks == ("txt2img", "edit"), name


def test_qwen_image_2_1_draws_from_a_start_picture():
    """sd-cli draws picture to picture and through a mask with a
    Qwen-Image 2.1 model: the start picture's layout stays, and with a mask
    the part outside it stays as it was. The family carries the task and the
    studio offers the kind; its edit stays beside it."""
    assert image_families.get("qwen_image_2_1").tasks == ("txt2img", "img2img", "edit")
    listed = {entry["name"]: entry["tasks"] for entry in image_families.as_json()}
    assert "img2img" in listed["qwen_image_2_1"]
    # The silence check: the families nobody has measured it with keep theirs.
    for name in ("qwen_image", "qwen_image_layered", "longcat", "anima", "boogu", "mage_flow"):
        assert "img2img" not in image_families.get(name).tasks, name


def test_krea2_edits_only_with_a_lora_and_the_table_says_so():
    """Krea 2 reads reference images only with a LoRA made for it; every
    other family that edits does so by itself. The table handed to the
    studio names it for each family."""
    assert image_families.get("krea2").edit_needs_lora is True
    others = [
        family for family in image_families.FAMILIES
        if "edit" in family.tasks and family.name != "krea2"
    ]
    assert len(others) > 1
    for family in others:
        assert family.edit_needs_lora is False, family.name
    listed = {entry["name"]: entry["edit_needs_lora"] for entry in image_families.as_json()}
    assert listed == {
        family.name: family.name == "krea2" for family in image_families.FAMILIES
    }
    # The silence check: what Krea 2 can be asked for is what it was.
    assert image_families.get("krea2").tasks == ("txt2img", "img2img", "edit")


# What the families start with whose distilled model is the one people draw
# with: that model's steps and CFG, and the family's own size and shift.
_TURBO_START = {
    "krea2": (1024, 1024, 8, 1.0, "euler", 1.15),
    "zimage": (1024, 1024, 8, 1.0, "euler", 3.0),
    "lens": (1440, 1440, 4, 1.0, "euler", None),
    "longcat": (1024, 1024, 8, 1.0, "euler", 3.0),
    "ernie": (1024, 1024, 8, 1.0, "euler", 4.0),
    "sefi": (1024, 1024, 4, 1.0, "euler", None),
    "anima": (1024, 1024, 8, 1.0, "er_sde", None),
    "boogu": (1024, 1024, 4, 1.0, "euler", None),
    "mage_flow": (1024, 1024, 4, 1.0, "euler", 6.0),
}


@pytest.mark.parametrize("family", sorted(_TURBO_START))
def test_a_family_with_a_turbo_model_starts_at_the_turbo_s_values(family):
    """Whatever its file is called — with the word, without it, or not named
    at all — a model of such a family starts in the distilled model's few
    steps at CFG 1, and each of the two values names its place."""
    own = image_families.get(family)
    for file in ("model-q8.gguf", f"{family}_turbo-Q4_K_M.gguf", "models/Raw-Q8_0.gguf", None):
        start = image_families.start_values(family, file)
        assert start is own.start, file
        assert (
            start.width, start.height, start.steps, start.cfg, start.sampler, start.flow_shift,
        ) == _TURBO_START[family], file
    assert own.variants == ()
    for name in ("steps", "cfg"):
        assert not own.start.sources[name].startswith("sd-cli --help"), name


def test_krea2_names_the_places_of_its_turbo_values():
    start = image_families.start_values("krea2", "Krea-2-Raw-Q8_0.gguf")
    assert start.sources["steps"] == "sd.cpp docs/int8_convrot.md:105 (--steps 8 --cfg-scale 1)"
    assert start.sources["cfg"] == start.sources["steps"]
    assert start.sources["flow_shift"] == "huggingface.co/krea/Krea-2-Turbo (model card)"
    assert start.sources["width"] == (
        "github.com/Comfy-Org/workflow_templates templates/image_krea2_turbo_t2i.json"
    )


def test_a_family_without_variants_is_not_touched_by_a_word():
    assert image_families.start_values("chroma", "chroma_turbo.gguf") is (
        image_families.get("chroma").start
    )


# --- The start values of the families and of their variants -----------------

# What each family starts with where its authors, the diffusers pipeline or
# a template name another value than sd-cli's own. The CFG of the families
# in ``_TURBO_START`` is their distilled model's.
_NEW_START = {
    "sd15": {"cfg": 7.5},
    "sd2": {"cfg": 7.5, "sampler": "dpm++2m"},
    "sdxl": {"cfg": 5.0, "sampler": "euler"},
    "sd15_pix2pix": {"cfg": 7.5},
    "sdxl_pix2pix": {"cfg": 5.0, "sampler": "euler"},
    "hidream_o1": {"width": 2048, "height": 2048, "flow_shift": 1.0},
    "sd3": {"flow_shift": 3.0},
    "flux": {"width": 1024, "height": 1024},
    "chroma": {"width": 1024, "height": 1024, "cfg": 3.0},
    "chroma_radiance": {"width": 1024, "height": 1024},
    "flux2": {"width": 1024, "height": 1024, "guidance": 4.0},
    "flux2_klein": {"width": 1024, "height": 1024},
    "zimage": {"width": 1024, "flow_shift": 3.0},
    "qwen_image": {"width": 1328, "height": 1328, "cfg": 4.0},
    "qwen_image_2_1": {"width": 2048, "height": 2048, "cfg": 1.0},
    "qwen_image_layered": {"width": 640, "height": 640, "cfg": 4.0},
    "krea2": {"width": 1024, "height": 1024, "cfg": 1.0, "flow_shift": 1.15},
    "lens": {"width": 1440, "height": 1440},
    "longcat": {"width": 1024, "height": 1024, "cfg": 1.0},
    "ovis": {"width": 1024, "height": 1024},
    "ernie": {"width": 1024, "height": 1024, "cfg": 1.0, "flow_shift": 4.0},
    "anima": {"width": 1024, "height": 1024, "cfg": 1.0, "sampler": "er_sde"},
    "boogu": {"width": 1024, "height": 1024, "cfg": 1.0},
    "mage_flow": {"width": 1024, "height": 1024, "cfg": 1.0, "flow_shift": 6.0},
    "pixart": {"sampler": "dpm++2m"},
    "wan": {"cfg": 5.0, "flow_shift": 5.0, "frames": 81, "fps": 16},
    "wan22_i2v": {"flow_shift": 5.0, "frames": 81, "fps": 16},
    "wan22_ti2v": {"width": 1280, "height": 704, "cfg": 5.0, "flow_shift": 5.0, "frames": 121,
                   "fps": 24},
    "wan22_s2v": {"width": 1024, "height": 704, "cfg": 4.5, "fps": 16},
    "ltx": {"cfg": 3.0, "scheduler": "ltx2", "frames": 121},
    "minimax_h3": {"width": 1344, "height": 768, "flow_shift": 12.0, "frames": 124},
    "hunyuan_video": {"flow_shift": 9.0, "frames": 121, "fps": 24},
    "lingbot_video": {"width": 832, "height": 480, "flow_shift": 3.0, "frames": 121, "fps": 24},
}

# The step count every family starts with: the one of sd.cpp's docs or of
# sd-cli itself, whatever else a family takes from elsewhere — and the
# distilled model's where that is the model people draw with.
_STEPS = {
    "llada_image": 4, "sensenova_u1": 50,
    "sd15": 20, "sd2": 20, "sdxl": 20, "sdxs": 1, "sd15_pix2pix": 20, "sdxl_pix2pix": 20,
    "hidream_o1": 20, "sd3": 20, "flux": 20, "chroma": 20, "chroma_radiance": 20, "flux2": 20,
    "flux2_klein": 4, "zimage": 8, "qwen_image": 20, "qwen_image_2_1": 20,
    "qwen_image_layered": 20, "krea2": 8, "lens": 4, "pid": 4, "longcat": 8, "minit2i": 100,
    "ovis": 20, "ernie": 8, "sefi": 4, "anima": 8, "boogu": 4, "mage_flow": 4,
    "ideogram4": 20, "pixart": 20, "wan": 20, "wan22_i2v": 10, "wan22_ti2v": 20,
    "wan22_s2v": 20, "ltx": 20, "minimax_h3": 20, "hunyuan_video": 20, "lingbot_video": 20,
    "flux3_klein": 16, "moss_image": 50, "iris": 100,
}


_VALUE_NAMES = ("width", "height", "steps", "cfg", "guidance", "sampler", "scheduler",
                "flow_shift", "frames", "fps")


def _values(
    width: int, height: int, steps: int, cfg: float, sampler: str = "euler",
    flow_shift: float | None = None, scheduler: str = "", frames: int | None = None,
    fps: int | None = None,
) -> dict:
    """Every start value of a variant; none of them has a guidance."""
    return {
        "width": width, "height": height, "steps": steps, "cfg": cfg, "guidance": None,
        "sampler": sampler, "scheduler": scheduler, "flow_shift": flow_shift,
        "frames": frames, "fps": fps,
    }


# The family, the word a file name shows the variant by, a file of it, and
# everything such a model starts with.
_VARIANTS = [
    ("flux", "schnell", "flux1-schnell-Q4_K_S.gguf", _values(1024, 1024, 4, 1.0)),
    ("flux2_klein", "base", "flux-2-klein-base-4b.safetensors", _values(1024, 1024, 20, 4.0)),
    ("flux3_klein", "base", "flux-3-image-klein-base.safetensors", _values(1024, 1024, 20, 3.5)),
    ("sd3", "turbo", "sd3.5_large_turbo.safetensors", _values(1024, 1024, 4, 1.0, flow_shift=3.0)),
    ("ltx", "distilled", "ltx-2.3-22b-distilled.safetensors",
     _values(1280, 720, 8, 1.0, scheduler="ltx2", frames=121, fps=24)),
    ("sdxl", "turbo", "sd_xl_turbo_1.0_fp16.safetensors", _values(512, 512, 1, 1.0)),
    ("sdxl", "lcm", "sdxl_lcm.safetensors", _values(1024, 1024, 4, 1.0, sampler="lcm")),
    ("sd15", "lcm", "sd15_lcm.safetensors", _values(512, 512, 4, 1.0, sampler="lcm", frames=8, fps=8)),
    ("qwen_image", "lightning", "qwen-image-lightning-8steps.safetensors",
     _values(1328, 1328, 8, 1.0, flow_shift=3.0)),
    ("wan", "lightx2v", "wan2.1_t2v_14B_lightx2v_4steps.safetensors",
     _values(832, 480, 4, 1.0, flow_shift=5.0, frames=81, fps=16)),
    ("qwen_image_2_1", "turbo", "qwen-image-2.1-turbo-Q4_K_M.gguf", _values(2048, 2048, 8, 1.0)),
]


def _as_dict(start: image_families.StartValues) -> dict:
    return {name: getattr(start, name) for name in _VALUE_NAMES}


@pytest.mark.parametrize("family", sorted(_NEW_START))
def test_a_family_starts_where_its_authors_start_it(family):
    """Size, CFG, guidance, sampler, scheduler, flow shift and a video's
    frames come from the place that knows the model, each with that place."""
    start = image_families.start_values(family)
    for name, value in _NEW_START[family].items():
        assert getattr(start, name) == value, name
        assert start.sources[name], name
        assert not start.sources[name].startswith("sd-cli --help"), name
    listed = next(entry for entry in image_families.as_json() if entry["name"] == family)
    for name, value in _NEW_START[family].items():
        assert listed["start"][name] == value, name


def test_no_family_changes_its_step_count():
    """The silence check: the steps stay the ones of sd.cpp's docs or of
    sd-cli, also where everything else comes from a model's authors — but
    for the families that start as their distilled model does."""
    assert {family.name: family.start.steps for family in image_families.FAMILIES} == _STEPS


def test_no_picture_family_starts_at_sd_cli_s_512_any_more_where_its_model_draws_larger():
    """Only the U-Net families of 512 pixels and the ones nobody names a size
    for keep sd-cli's own."""
    small = {
        family.name for family in image_families.FAMILIES
        if (family.start.width, family.start.height) == (512, 512)
    }
    assert small == {"sd15", "sd2", "sdxs", "sd15_pix2pix", "minit2i"}


@pytest.mark.parametrize(("family", "word", "file", "values"), _VARIANTS,
                         ids=[f"{row[0]}-{row[1]}" for row in _VARIANTS])
def test_a_file_named_for_a_variant_starts_at_the_variant_s_values(family, word, file, values):
    own = image_families.get(family)
    start = image_families.start_values(family, file)
    assert start is not own.start
    assert _as_dict(start) == values
    # In a folder and in capitals it is the same model.
    assert image_families.start_values(family, f"models/{file.upper()}") is start
    # The values that are the variant's own name the variant's place, the
    # others the family's.
    assert start.sources["steps"] != own.start.sources["steps"]
    assert start.sources["scheduler"] == own.start.sources["scheduler"]
    # The silence checks: a file of the family without the word, and one that
    # carries the word inside a longer one, start where the family starts.
    assert image_families.start_values(family, "model-q4.gguf") is own.start
    assert image_families.start_values(family, f"model-a{word}b-q4.gguf") is own.start
    assert image_families.start_values(family, f"model-{word}ed-q4.gguf") is own.start
    assert image_families.start_values(family) is own.start


def test_the_turbo_model_of_qwen_image_2_1_names_the_doc_it_starts_by():
    start = image_families.start_values("qwen_image_2_1", "qwen-image-2.1-turbo-Q8_0.gguf")
    assert "docs/qwen_image_2.1.md" in start.sources["steps"]
    assert "docs/qwen_image_2.1.md" in start.sources["cfg"]
    # The plain model, and the other Qwen-Image families, keep their start.
    plain = image_families.get("qwen_image_2_1").start
    assert image_families.start_values("qwen_image_2_1", "qwen_image_2.1-Q8_0.gguf") is plain
    assert image_families.start_values("qwen_image", "qwen-image-turbo.gguf").steps == 20


def test_the_kit_of_qwen_image_2_1_brings_the_vision_part_of_its_encoder():
    kit = image_families.kit_of_file("qwen-image-2.1-Q4_K_M.gguf")
    vision = [part for part in kit if part.part == "llm_vision"]
    assert [(part.repo, part.file) for part in vision] == [
        ("Qwen/Qwen3-VL-8B-Instruct-GGUF", "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf")
    ]
    assert vision[0].folder == "text_encoders"
    # Another family that edits from references has no such part named.
    assert not [p for p in image_families.kit_of_file("Qwen-Image-Q4_K_M.gguf")
                if p.part == "llm_vision"]


def test_the_first_variant_of_a_family_wins():
    """An SDXL file named for both starts as the one the table names first."""
    turbo = image_families.start_values("sdxl", "sdxl_turbo.safetensors")
    assert image_families.start_values("sdxl", "sdxl_lcm_turbo.safetensors") is turbo


def test_only_the_named_families_have_variants():
    with_variants = {family.name for family in image_families.FAMILIES if family.variants}
    # PiD's are of another kind: the backbone a checkpoint was trained on.
    assert with_variants == {row[0] for row in _VARIANTS} | {"pid"}
    assert len(image_families.get("pid").variants) == 3
    assert sum(len(family.variants) for family in image_families.FAMILIES) == len(_VARIANTS) + 3


# --- Start values for the VAE format, the RNG and further switch lines -------

# A PiD checkpoint's file and the VAE format it starts with: the format of
# the model it was trained on (sd.cpp docs/pid.md:18-21), Flux's where the
# name shows none (the docs' own example, :30).
_PID_FORMATS = [
    ("pid_flux1_512_to_2048_4step_bf16.safetensors", "flux"),
    ("pid_zimage_1024_to_2048.safetensors", "flux"),
    ("pid_flux2_512_to_2048_4step_bf16.safetensors", "flux2"),
    ("pid-flux.2-klein.gguf", "flux2"),
    ("pid_sd3_512_to_2048.safetensors", "sd3"),
    ("pid_qwen_image_1024_to_2048.safetensors", "wan"),
    ("pid_checkpoint.safetensors", "flux"),
]
_HIGH_NOISE = {
    "high_noise_cfg_scale": 3.5, "high_noise_sampling_method": "euler", "high_noise_steps": 8,
}


@pytest.mark.parametrize(("file", "vae_format"), _PID_FORMATS)
def test_pid_starts_with_its_backbone_s_vae_format_and_the_cpu_rng(file, vae_format, tmp_path, monkeypatch):
    """A PiD drawn at its start values: the command carries the VAE format
    of the checkpoint's backbone and ``--rng cpu``, each with its place."""
    start = image_families.start_values("pid", file)
    assert (start.vae_format, start.rng) == (vae_format, "cpu")
    assert start.sources["vae_format"].startswith("sd.cpp docs/pid.md")
    assert start.sources["rng"].startswith("sd.cpp docs/pid.md:30")
    # Nothing else of the start moves with the backbone.
    own = image_families.get("pid").start
    assert dataclasses.replace(start, vae_format="", sources={}) == dataclasses.replace(
        own, vae_format="", sources={},
    )
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    command = bildrunner.Bildrunner(tmp_path).befehl(
        bildrunner.Auftrag(
            modell=tmp_path / file, diffusion_model=tmp_path / file, familie="pid", prompt="x",
            llm=tmp_path / "gemma.safetensors", vae_format=start.vae_format, rng=start.rng,
        ),
        tmp_path / "out.png",
    )
    assert command[command.index("--vae-format") + 1] == vae_format
    assert command[command.index("--rng") + 1] == "cpu"


def test_the_wan_a14b_models_start_with_the_docs_high_noise_values():
    """Wan 2.2 I2V A14B and the family of Wan 2.2 T2V A14B start the
    high-noise pass where the docs draw it; beside a high-noise model the
    command carries the three switches, without one none of them."""
    for name, line in (("wan22_i2v", "101"), ("wan", "93")):
        start = image_families.start_values(name)
        assert start.switches == _HIGH_NOISE
        for key in _HIGH_NOISE:
            assert start.sources[key].startswith(f"sd.cpp docs/wan.md:{line} ")
        beside = image_switches.active(start.switches, {"video": True, "high_noise": True})
        assert image_switches.cli_parts(beside, {}) == [
            "--high-noise-steps", "8", "--high-noise-cfg-scale", "3.5",
            "--high-noise-sampling-method", "euler",
        ]
        assert image_switches.active(start.switches, {"video": True}) == {}
    # A lightx2v model's few steps are the whole draw's.
    assert image_families.start_values("wan", "wan2.2_t2v_lightx2v_4steps.safetensors").switches == {}


def test_a_family_the_docs_start_plainly_names_no_format_no_rng_and_no_switch():
    """Silence: Flux, SDXL and Wan 2.2 TI2V 5B start as before — no VAE
    format, the program's own RNG, no switch line."""
    for name in ("flux", "sdxl", "zimage", "wan22_ti2v", None):
        start = image_families.start_values(name)
        assert (start.vae_format, start.rng, start.switches) == ("", "", {}), name
    assert bildrunner.Auftrag(modell=Path("/m.gguf"), prompt="x").rng == "cuda"


def test_the_table_names_the_new_start_values_with_their_places():
    """``GET /bild/familien`` hands this table on: under ``start`` stand
    ``vae_format``, ``rng`` and ``switches`` for every family, with the
    place of each one that is set."""
    table = {row["name"]: row["start"] for row in image_families.as_json()}
    assert all({"vae_format", "rng", "switches"} <= set(start) for start in table.values())
    assert (table["pid"]["vae_format"], table["pid"]["rng"]) == ("flux", "cpu")
    assert {"vae_format", "rng"} <= set(table["pid"]["sources"])
    for name in ("wan", "wan22_i2v"):
        assert table[name]["switches"] == _HIGH_NOISE
        assert set(_HIGH_NOISE) <= set(table[name]["sources"])
    assert (table["flux"]["vae_format"], table["flux"]["rng"], table["flux"]["switches"]) == ("", "", {})


# --- LLaDA-Image, and SenseNova U1.5 as a folder -----------------------------


def _folder_model(path: Path, weights: list[str]) -> Path:
    """A model as a folder: the index naming each weight's shard, as a
    safetensors model split into shards has it."""
    path.mkdir(parents=True)
    (path / bildinhalt.FOLDER_INDEX).write_text(json.dumps({
        "metadata": {"total_size": 1}, "weight_map": dict.fromkeys(weights, "model-00001-of-00002.safetensors"),
    }))
    return path


_SENSENOVA_WEIGHTS = [
    "language_model.model.layers.0.self_attn.q_proj.weight",
    "language_model.model.layers.0.self_attn.q_proj_mot_gen.weight",
]


def test_llada_image_draws_from_its_kit_as_the_table_says(tmp_path, monkeypatch):
    """LLaDA-Image is a family of parts: the command carries the diffusion
    model, the LLM, its tokenizer, the embeddings connectors and the VAE;
    it draws from text and edits, and starts at the docs' turbo values."""
    family = image_families.get("llada_image")
    assert (family.kit, family.encoders, family.parts, family.tasks, family.vae_channels) == (
        True, ("llm",), ("tokenizer", "embeddings_connectors"), ("txt2img", "edit"), 32,
    )
    start = family.start
    assert (start.width, start.height, start.steps, start.cfg) == (1024, 1024, 4, 1.0)
    for name in ("width", "height", "steps", "cfg"):
        assert start.sources[name].startswith("sd.cpp docs/llada_image.md:100-103")
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    model = tmp_path / "llada_image_turbo.safetensors"
    command = bildrunner.Bildrunner(tmp_path).befehl(
        bildrunner.Auftrag(
            modell=model, diffusion_model=model, familie="llada_image", prompt="x",
            llm=tmp_path / "llm.gguf", tokenizer=tmp_path / "tokenizer.json",
            embeddings_connectors=tmp_path / "connectors.safetensors",
            vae=tmp_path / "flux2_ae.safetensors",
        ),
        tmp_path / "out.png",
    )
    for switch, file in (
        ("--diffusion-model", model), ("--llm", tmp_path / "llm.gguf"),
        ("--tokenizer", tmp_path / "tokenizer.json"),
        ("--embeddings-connectors", tmp_path / "connectors.safetensors"),
        ("--vae", tmp_path / "flux2_ae.safetensors"),
    ):
        assert command[command.index(switch) + 1] == str(file), switch
    assert "-m" not in command


def test_sensenova_is_a_model_in_a_folder_and_drawn_with_the_folder(tmp_path, monkeypatch):
    """SenseNova U1.5 lies in a folder with the index of its shards: the
    folder stands in the model list under its name, its family is read off
    the index, and sd-cli is handed the folder as the model."""
    folder = _folder_model(tmp_path / "SenseNova-U1.5-8B-MoT", _SENSENOVA_WEIGHTS)
    assert bildinhalt.folder_model(folder) is True
    assert bildinhalt.family(folder) == "sensenova_u1"
    assert bildrunner.modelle(tmp_path) == ["SenseNova-U1.5-8B-MoT"]
    assert bildrunner.modell_pfad(tmp_path, "SenseNova-U1.5-8B-MoT") == folder
    family = image_families.get("sensenova_u1")
    assert (family.kit, family.tasks) == (False, ("txt2img",))
    start = family.start
    assert (start.width, start.height, start.steps, start.cfg, start.sampler, start.flow_shift) == (
        2048, 2048, 50, 4.0, "euler", 3.0,
    )
    assert start.sources["steps"].startswith("sd.cpp docs/sensenova_u1.md:20-31")
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")
    command = bildrunner.Bildrunner(tmp_path).befehl(
        bildrunner.Auftrag(modell=folder, prompt="x", familie="sensenova_u1"), tmp_path / "out.png",
    )
    assert command[command.index("-m") + 1] == str(folder)
    assert "--diffusion-model" not in command


def test_a_folder_without_an_index_is_no_model(tmp_path):
    """Silence: a folder without the index is not listed, one whose index
    names another model has no family, a single shard is no model, and a
    model file beside them is listed as before."""
    (tmp_path / "loras").mkdir()
    (tmp_path / "half").mkdir()
    (tmp_path / "half" / "model-00001-of-00002.safetensors").write_bytes(b"x")
    other = _folder_model(tmp_path / "other-model", ["transformer.blocks.0.weight"])
    _safetensors(tmp_path / "sdxl.safetensors", _HEADERS["sdxl"])
    shard = _safetensors(tmp_path / "shard.safetensors", dict.fromkeys(_SENSENOVA_WEIGHTS, [8]))
    assert bildrunner.modelle(tmp_path) == ["other-model", "sdxl.safetensors", "shard.safetensors"]
    assert bildinhalt.folder_model(tmp_path / "half") is False
    assert bildinhalt.family(other) is None
    assert bildinhalt.family(shard) is None
    assert bildinhalt.family(tmp_path / "sdxl.safetensors") == "sdxl"
    (other / bildinhalt.FOLDER_INDEX).write_text("no json")
    assert bildinhalt.family(other) is None


def test_an_sdxl_model_with_a_timestep_shift_carries_the_switch():
    """NitroFusion is an SDXL model by its header and draws as one; its
    timestep shift is the switch every SDXL model has."""
    assert image_switches.cli_parts(image_switches.check({"timestep_shift": 250}), {}) == [
        "--timestep-shift", "250",
    ]


def test_the_route_hands_a_checkpoint_without_encoders_its_family_s(client: TestClient, picture_folder: Path):
    """SD3.5 as one checkpoint without text encoders: the start values name
    the encoder of its family the folder holds, and no diffusion model —
    it is drawn with ``-m``. Silence: the same checkpoint with its own
    encoder inside is handed none."""
    weights = {
        "model.diffusion_model.joint_blocks.0.x_block.attn.qkv.weight": [8],
        "first_stage_model.decoder.conv_in.weight": [8],
    }
    _safetensors(picture_folder / "sd3.5_large.safetensors", weights)
    _safetensors(picture_folder / "sd3.5_whole.safetensors", {
        **weights,
        "text_encoders.clip_l.transformer.text_model.embeddings.token_embedding.weight": [49408, 768],
    })
    _safetensors(picture_folder / "text_encoders" / "clip_l.safetensors", {
        "text_model.embeddings.token_embedding.weight": [49408, 768],
    })
    bare = client.get("/api/v1/bild/vorgaben", params={"modell": "sd3.5_large.safetensors"}).json()
    assert (bare["family"], bare["standalone"]) == ("sd3", False)
    assert bare["parts"] == {"clip_l": "clip_l.safetensors"}
    whole = client.get("/api/v1/bild/vorgaben", params={"modell": "sd3.5_whole.safetensors"}).json()
    assert (whole["family"], whole["parts"]) == ("sd3", {})



def test_the_kit_of_a_family_told_by_the_head_does_not_need_the_name():
    """``turbo.safetensors`` shows no family by its name; given the family its
    head names, its kit is the family's."""
    assert image_families.kit_of_file("turbo.safetensors") == ()
    parts = image_families.kit_of_family(image_families.get("krea2"), "turbo.safetensors")
    assert {part.part: part.name for part in parts} == {
        "llm": "Qwen3VL-4B-Instruct-Q4_K_M.gguf", "vae": "wan_2.1_vae.safetensors",
    }


def test_no_family_has_no_kit():
    assert image_families.kit_of_family(None, "turbo.safetensors") == ()


# --- Which families cannot start without a VAE -----------------------------

# The eleven kit families whose table names a VAE among the kit's parts and
# gives no channel count, so the VAE counted for none of them.
_VAE_BY_KIT_ONLY = {
    "qwen_image", "qwen_image_2_1", "krea2", "lens", "ernie", "anima", "mage_flow",
    "ideogram4", "ltx", "minimax_h3", "hunyuan_video",
}


def test_a_family_whose_kit_names_a_vae_needs_one():
    """Every family of the table that is assembled from parts and names a
    VAE among them cannot start without it — channel count or not."""
    for family in image_families.FAMILIES:
        names_a_vae = any(part.part == "vae" for part in family.kit_parts)
        if names_a_vae:
            assert image_families.needs_vae(family), family.name
    assert {
        family.name for family in image_families.FAMILIES
        if family.kit and image_families.needs_vae(family) and family.vae_channels is None
    } == _VAE_BY_KIT_ONLY


def test_a_family_that_names_no_vae_and_no_channels_needs_none():
    """Silence probe: a kit that names no VAE and a checkpoint need none."""
    for name in ("sd3", "chroma_radiance", "sdxl", "sd15", "minit2i", "qwen_image_layered"):
        assert not image_families.needs_vae(image_families.get(name)), name


def test_the_families_whose_docs_pass_a_vae_cannot_start_without_one():
    """sd.cpp's docs pass a VAE in every example of SeFi-Image (the Flux.2
    VAE) and PixArt (a 4-channel one), so their kits are refused without
    one, naming the part — also with no kit source in the table."""
    from app import bildbausatz

    for name, text_encoder in (("sefi", "llm"), ("pixart", "t5xxl")):
        family = image_families.get(name)
        assert image_families.needs_vae(family), name
        assert bildbausatz.fehlendes_teil(name, {text_encoder: "enc"}) == "vae", name
        assert bildbausatz.fehlendes_teil(name, {text_encoder: "enc", "vae": "v"}) is None, name
    # Silence probe: the kit families whose docs name no VAE need none, and
    # every other kit family is asked for one as before.
    needing = {f.name for f in image_families.FAMILIES if f.kit and image_families.needs_vae(f)}
    assert {f.name for f in image_families.FAMILIES if f.kit} - needing == {
        "sd3", "chroma_radiance", "minit2i", "qwen_image_layered", "iris",
    }


def test_a_four_channel_vae_is_never_picked_by_itself():
    """SD1.x and SDXL VAEs share the channel count, and PixArt reads either:
    the header cannot say which fits, so the model's own setting decides."""
    assert not image_families.vae_by_itself(image_families.get("pixart"))
    assert image_families.vae_by_itself(image_families.get("sefi"))


def test_the_table_over_the_api_says_which_family_needs_a_vae():
    listed = {row["name"]: row["needs_vae"] for row in image_families.as_json()}
    assert listed["krea2"] is True
    assert listed["flux"] is True
    assert listed["sdxl"] is False
    assert listed["sd3"] is False
