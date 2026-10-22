"""FLUX.3 Klein, MOSS-Image and Iris-3B: told from their weights, drawn with the values of their docs.

sd.cpp build 975 tells the three by the names of their weights
(src/model_loader.cpp): FLUX.3 and MOSS-Image before any other rule, Iris in
the walk behind MiniMax. The table gives each its kit and its start values with
a source, and a file's name shows the family only where the header cannot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import bildinhalt, image_families, kit_bond
from tests.test_image_families import _gguf, _safetensors

FLUX3 = {"emb_in.image.weight": [3072, 128], "txt_mode_blocks.0.q_proj.weight": [3072, 3072]}
MOSS = {"video_embedder.weight": [3072, 128], "shared_block_modulation.weight": [3072]}
IRIS = {"y_embedder.layer_pool.weight": [3072, 2560], "modulation_cores.adaln_img.weight": [3072]}
HEADERS = {"flux3_klein": FLUX3, "moss_image": MOSS, "iris": IRIS}
PREFIX = "model.diffusion_model."


def _read(tmp_path: Path, shapes: dict[str, list[int]], prefix: str = "") -> str | None:
    path = _safetensors(tmp_path / "w.safetensors", {prefix + name: shape for name, shape in shapes.items()})
    return bildinhalt.family(path)


# --- The header ---


@pytest.mark.parametrize("family", sorted(HEADERS))
@pytest.mark.parametrize("prefix", ["", PREFIX], ids=["bare", "prefixed"])
def test_the_family_comes_from_the_names_of_the_weights_with_or_without_the_prefix(tmp_path, family, prefix):
    assert _read(tmp_path, HEADERS[family], prefix) == family


def test_a_flux3_header_that_carries_the_names_of_a_flux_rule_stays_flux3(tmp_path):
    flux_names = {
        "double_blocks.0.img_attn.qkv.weight": [9216, 3072],
        "double_stream_modulation_img.lin.weight": [18432, 3072],
        "single_blocks.47.linear1.weight": [18432, 3072],
    }
    assert _read(tmp_path, {**FLUX3, **flux_names}) == "flux3_klein"
    # Without the two names of FLUX.3 the same weights are Flux.2.
    assert _read(tmp_path, flux_names) == "flux2"


def test_a_moss_header_that_carries_the_names_of_an_earlier_rule_stays_moss(tmp_path):
    assert _read(tmp_path, {**MOSS, "cap_embedder.0.weight": [2560]}) == "moss_image"
    assert _read(tmp_path, {"cap_embedder.0.weight": [2560]}) == "zimage"


def test_iris_needs_its_pooling_layer_by_that_name_and_its_modulation_beside_it(tmp_path):
    assert _read(tmp_path, {"y_embedder.layer_pool.weight": [3072, 2560]}) is None
    assert _read(tmp_path, {"modulation_cores.adaln_img.weight": [3072]}) is None
    # sd.cpp compares the whole name: a longer one does not tell Iris.
    assert _read(tmp_path, {"x.y_embedder.layer_pool.weight": [3072, 2560],
                            "modulation_cores.adaln_img.weight": [3072]}) is None


def test_either_half_of_the_names_of_flux3_or_moss_is_not_enough(tmp_path):
    assert _read(tmp_path, {"emb_in.image.weight": [3072, 128]}) is None
    assert _read(tmp_path, {"txt_mode_blocks.0.q_proj.weight": [3072, 3072]}) is None
    assert _read(tmp_path, {"video_embedder.weight": [3072, 128]}) is None
    assert _read(tmp_path, {"shared_block_modulation.weight": [3072]}) is None


def test_a_gguf_of_the_three_is_read_the_same(tmp_path):
    for family, shapes in HEADERS.items():
        path = _gguf(tmp_path / f"{family}.gguf", "flux", {PREFIX + name: shape for name, shape in shapes.items()})
        assert bildinhalt.family(path) == family


# --- The table ---


def test_flux3_klein_has_the_start_values_of_its_docs_with_their_places():
    family = image_families.get("flux3_klein")
    assert family.label == "FLUX.3 Klein" and family.kit and family.encoders == ("llm",)
    assert (family.vae_channels, family.tae, family.llms) == (32, ("taef2",), (("qwen3vl", 2560),))
    assert family.tasks == ("txt2img", "edit") and family.many_references and family.on_server
    start = family.start
    assert (start.width, start.height, start.steps, start.cfg, start.sampler) == (1024, 1024, 16, 1.0, "euler")
    assert start.flow_shift is None and start.guidance is None
    assert "docs/flux3.md" in start.sources["steps"] and "docs/flux3.md" in start.sources["cfg"]
    assert "image_flux3_klein_t2i" in start.sources["width"]


def test_the_base_model_of_flux3_starts_with_twenty_steps_and_a_cfg_of_three_and_a_half():
    base = image_families.start_values("flux3_klein", "flux-3-image-klein-base.safetensors")
    plain = image_families.start_values("flux3_klein", "flux-3-image-klein.safetensors")
    assert (base.steps, base.cfg, base.width) == (20, 3.5, 1024)
    assert (plain.steps, plain.cfg) == (16, 1.0)
    assert "docs/flux3.md" in base.sources["steps"] and "docs/flux3.md" in base.sources["cfg"]


def test_moss_image_has_its_own_tokenizer_part_and_the_flux2_vae():
    family = image_families.get("moss_image")
    assert family.label == "MOSS-Image" and family.encoders == ("llm",) and family.parts == ("tokenizer",)
    assert (family.vae_channels, family.tae, family.llms) == (32, ("taef2",), (("qwen35", 4096),))
    assert family.tasks == ("txt2img",)
    start = family.start
    assert (start.width, start.height, start.steps, start.cfg, start.sampler) == (1024, 1024, 50, 3.0, "euler")
    assert "docs/moss_image.md" in start.sources["cfg"] and "MOSS-Image-Base" in start.sources["steps"]
    sources = {part.part: (part.repo, part.file) for part in family.kit_parts}
    assert sources["llm"] == ("unsloth/Qwen3.5-9B-GGUF", "Qwen3.5-9B-Q4_K_M.gguf")
    assert sources["tokenizer"] == ("OpenMOSS-Team/MOSS-Image-Base", "tokenizer/tokenizer.json")
    assert sources["vae"][1].endswith("flux2-vae.safetensors")


def test_iris_draws_in_pixel_space_and_needs_no_vae_and_no_tae():
    family = image_families.get("iris")
    assert family.label == "Iris-3B" and family.encoders == ("llm",) and family.tae == ()
    assert family.vae_channels is None and not image_families.needs_vae(family)
    assert [part.part for part in family.kit_parts] == ["llm"]
    start = family.start
    assert (start.width, start.height, start.steps, start.cfg, start.sampler) == (1024, 1024, 100, 3.0, "euler")
    assert "docs/iris.md" in start.sources["cfg"] and "iris-3b" in start.sources["steps"]


def test_every_value_of_the_three_names_a_place():
    for name in HEADERS:
        start = image_families.get(name).start
        for value in ("width", "height", "steps", "cfg", "sampler"):
            assert start.sources.get(value), (name, value)


@pytest.mark.parametrize("file,family", [
    ("flux-3-image-klein.safetensors", "flux3_klein"),
    ("flux-3-image-klein-base.safetensors", "flux3_klein"),
    ("flux3_klein_fp8.safetensors", "flux3_klein"),
    ("moss_image_base_int8_convrot_attn.safetensors", "moss_image"),
    ("MOSS-Image-SFT.gguf", "moss_image"),
    ("iris-3b.safetensors", "iris"),
    ("iris_3b_q8.gguf", "iris"),
])
def test_the_name_of_a_file_shows_its_family(file, family):
    assert image_families.family_of_file(file).name == family


@pytest.mark.parametrize("file,family", [
    ("iris.safetensors", None),
    ("iris-3.safetensors", None),
    ("flux-2-klein-4b.safetensors", "flux2_klein"),
    ("flux-2-dev.safetensors", "flux2"),
    ("flux1-dev.safetensors", "flux"),
    ("moss.safetensors", None),
])
def test_silence_the_other_names_keep_their_family(file, family):
    found = image_families.family_of_file(file)
    assert (found.name if found else None) == family


def test_silence_the_values_of_the_other_families_stay():
    names = [family.name for family in image_families.FAMILIES]
    assert len(names) == len(set(names)) and {"flux2", "flux2_klein", "lens", "krea2"} <= set(names)
    assert image_families.get("flux2_klein").start.steps == 4
    assert image_families.get("krea2").start.cfg == 1.0


# --- The text encoder and the folder ---


def test_the_qwen35_encoder_is_told_by_its_header_and_read_as_a_pair(tmp_path):
    path = _gguf(tmp_path / "Qwen3.5-9B-Q4_K_M.gguf", "qwen35", {"token_embd.weight": [248320, 4096]})
    assert bildinhalt.companion(path) == ("llm", None)
    assert bildinhalt.llm(path) == ("qwen35", 4096)


def test_the_folder_puts_in_the_encoder_whose_architecture_and_width_fit_moss(tmp_path):
    folder = tmp_path / "bild"
    _gguf(folder / "text_encoders" / "a-qwen3-4b.gguf", "qwen3", {"token_embd.weight": [151936, 2560]})
    _gguf(folder / "text_encoders" / "b-qwen35-9b.gguf", "qwen35", {"token_embd.weight": [248320, 4096]})
    found = kit_bond.matching_parts(folder, image_families.get("moss_image"))
    assert found == {"llm": "b-qwen35-9b.gguf"}


def test_the_folder_puts_in_qwen3_vl_4b_for_flux3_and_iris(tmp_path):
    folder = tmp_path / "bild"
    _gguf(folder / "text_encoders" / "vl4b.gguf", "qwen3vl", {"token_embd.weight": [151936, 2560]})
    for name in ("flux3_klein", "iris"):
        assert kit_bond.matching_parts(folder, image_families.get(name)) == {"llm": "vl4b.gguf"}


def test_the_tokenizer_a_kit_reads_is_the_file_of_the_tokenizer_list(tmp_path):
    folder = tmp_path / "bild"
    (folder / "text_encoders").mkdir(parents=True)
    (folder / "text_encoders" / "tokenizer.json").write_text("{}", encoding="utf-8")
    assert kit_bond.offered(folder, "tokenizer") == ["tokenizer.json"]
    assert "tokenizer" in kit_bond.FIELDS
