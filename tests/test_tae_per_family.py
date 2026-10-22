"""A tiny autoencoder (TAE) belongs to the family whose latent space it decodes.

Each family of the table names the kinds of TAE that decode it; the kind of a
file stands in its name. The picture service lists each file's kind, and a
model remembered with a TAE of another kind draws with its VAE, as if none was
chosen (the remembered choice itself stays stored). A model whose family is
not read takes any TAE as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildbausatz, image_families
from app.api.v1 import bild
from app.bildbausatz import TAE_PREFIX
from app.bildrunner import Bildrunner
from app.config import Config

# Every family with the kinds of TAE that decode it; a family not listed has none.
KINDS = {
    "sd15": ("taesd",), "sd2": ("taesd",), "sd15_pix2pix": ("taesd",),
    "sdxl": ("taesdxl",), "sdxl_pix2pix": ("taesdxl",),
    "pixart": ("taesd", "taesdxl"),
    "sd3": ("taesd3",),
    "flux": ("taef1",), "chroma": ("taef1",), "zimage": ("taef1",), "longcat": ("taef1",),
    "ovis": ("taef1",), "boogu": ("taef1",),
    "flux2": ("taef2",), "flux2_klein": ("taef2",), "flux3_klein": ("taef2",), "moss_image": ("taef2",), "lens": ("taef2",), "ernie": ("taef2",),
    "ideogram4": ("taef2",), "llada_image": ("taef2",), "sefi": ("taef2",),
    "qwen_image": ("taew2_1",), "qwen_image_layered": ("taew2_1",), "anima": ("taew2_1",),
    "krea2": ("taew2_1",), "wan": ("taew2_1",), "wan22_i2v": ("taew2_1",),
    "wan22_s2v": ("taew2_1",), "lingbot_video": ("taew2_1",),
    "wan22_ti2v": ("taew2_2",),
    "qwen_image_2_1": ("taeqi2_1",),
}


def test_every_family_carries_exactly_the_kinds_that_decode_it():
    table = {family.name: family.tae for family in image_families.FAMILIES}
    assert table == {name: KINDS.get(name, ()) for name in table}
    assert set(KINDS) <= set(table)


def test_the_table_as_the_window_reads_it_carries_the_kinds():
    shown = {row["name"]: row["tae"] for row in image_families.as_json()}
    assert shown["wan"] == ["taew2_1"] and shown["pixart"] == ["taesd", "taesdxl"] and shown["pid"] == []


@pytest.mark.parametrize("name,kind", [
    ("taesd_decoder.safetensors", "taesd"),
    ("taesd.safetensors", "taesd"),
    ("taesdxl.safetensors", "taesdxl"),
    ("taesd3_encoder.pth", "taesd3"),
    ("taef1.safetensors", "taef1"),
    ("taef2.safetensors", "taef2"),
    ("taew2_1.safetensors", "taew2_1"),
    ("taew2_2.safetensors", "taew2_2"),
    ("taeqi2_1.safetensors", "taeqi2_1"),
    ("TAEW2_1.SAFETENSORS", "taew2_1"),
    ("my-taesdxl-fp16.safetensors", "taesdxl"),
    ("diffusion_pytorch_model.safetensors", ""),
    ("mytaesdx.safetensors", ""),
    ("taesdx.safetensors", ""),
    ("taew2_10.safetensors", ""),
])
def test_the_kind_of_a_file_stands_in_its_name(name, kind):
    assert bildbausatz.tae_kind(name) == kind


def test_a_choice_fits_a_family_by_its_kind_and_any_where_no_family_is_read():
    qwen = image_families.get("qwen_image_2_1")
    assert bildbausatz.tae_fits(f"{TAE_PREFIX}taeqi2_1.safetensors", qwen) is True
    assert bildbausatz.tae_fits(f"{TAE_PREFIX}taew2_1.safetensors", qwen) is False
    # A name that carries no kind fits no family that is read.
    assert bildbausatz.tae_fits(f"{TAE_PREFIX}diffusion_pytorch_model.safetensors", qwen) is False
    assert bildbausatz.tae_fits(f"{TAE_PREFIX}taew2_1.safetensors", None) is True
    assert bildbausatz.tae_fits(f"{TAE_PREFIX}diffusion_pytorch_model.safetensors", None) is True


# --- The service ---

MODEL = "tae-family-model.safetensors"
FILES = ("taew2_1.safetensors", "taeqi2_1.safetensors", "taesdxl.safetensors", "diffusion_pytorch_model.safetensors")


@pytest.fixture
def served(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """The service with a picture folder holding four tiny autoencoders and a
    model whose family is made up per case; its picture server is a recorder."""
    folder = tmp_path / "bildmodelle"
    (folder / "vae").mkdir(parents=True)
    (folder / "taesd").mkdir()
    (folder / MODEL).write_bytes(b"x")
    (folder / "vae" / "ae.safetensors").write_bytes(b"x")
    for name in FILES:
        (folder / "taesd" / name).write_bytes(b"x")
    state: dict = {"started": [], "family": "qwen_image_2_1"}
    monkeypatch.setattr(bild.bildinhalt, "family", lambda path: state["family"])
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    turbo = client.app.state.bildturbo
    monkeypatch.setattr(turbo, "starten", lambda *a, **k: state["started"].append(k))
    monkeypatch.setattr(turbo, "laeuft", lambda: True)
    monkeypatch.setattr(turbo, "passt_zu", lambda *a, **k: False)
    monkeypatch.setattr(turbo, "bereit_abwarten", lambda *a, **k: True)
    monkeypatch.setattr(turbo, "zeichnen", lambda body, **k: b"PNG")
    monkeypatch.setattr(turbo, "belegt_gb", lambda: None)
    return state


def _remember(client: TestClient, **values) -> None:
    answer = client.patch(
        "/api/v1/settings/global/bildmodellwerte", json={"wert": {MODEL: values}}
    )
    assert answer.status_code == 200, answer.text


def _hand_start(client: TestClient) -> None:
    assert client.post("/api/v1/bild/turbo/start", json={"modell": MODEL}).status_code == 200


def test_the_model_list_names_the_kind_of_each_tiny_autoencoder(client: TestClient, served):
    answer = client.get("/api/v1/bild/modelle").json()
    assert sorted(answer["taesd_files"]) == sorted(FILES)
    assert answer["tae_kinds"] == {
        "taew2_1.safetensors": "taew2_1", "taeqi2_1.safetensors": "taeqi2_1",
        "taesdxl.safetensors": "taesdxl", "diffusion_pytorch_model.safetensors": "",
    }


def test_a_remembered_tae_of_another_kind_is_not_drawn_with_but_stays_remembered(
    client: TestClient, served, tmp_path: Path
):
    _remember(client, vae=f"{TAE_PREFIX}taew2_1.safetensors")
    _hand_start(client)
    started = served["started"][-1]
    assert not started.get("vae") and not started.get("vae_tae"), started
    # The window is told no such part, and the choice itself is still stored.
    assert "vae" not in client.get("/api/v1/bild/vorgaben", params={"modell": MODEL}).json()["parts"]
    stored = client.get("/api/v1/settings/global/bildmodellwerte").json()["wert"]
    assert stored[MODEL]["vae"] == f"{TAE_PREFIX}taew2_1.safetensors"


def test_a_remembered_tae_of_the_kind_of_the_family_is_drawn_with(client: TestClient, served, tmp_path: Path):
    _remember(client, vae=f"{TAE_PREFIX}taeqi2_1.safetensors")
    _hand_start(client)
    started = served["started"][-1]
    assert started["vae"] == tmp_path / "bildmodelle" / "taesd" / "taeqi2_1.safetensors"
    assert started["vae_tae"] is True


def test_a_picture_of_a_model_with_a_tae_of_another_kind_starts_the_server_on_its_vae(
    client: TestClient, served
):
    _remember(client, vae=f"{TAE_PREFIX}taew2_1.safetensors")
    answer = client.post("/api/v1/bild", json={"prompt": "x", "modell": MODEL})
    assert answer.status_code == 201, answer.text
    started = served["started"][-1]
    assert not started.get("vae") and not started.get("vae_tae"), started


def test_silence_a_model_whose_family_is_not_read_keeps_any_tae(client: TestClient, served, tmp_path: Path):
    client.patch(
        "/api/v1/settings/global/bildmodellwerte",
        json={"wert": {MODEL: {"vae": f"{TAE_PREFIX}taew2_1.safetensors", "family_detection": False}}},
    )
    _hand_start(client)
    started = served["started"][-1]
    assert started["vae"] == tmp_path / "bildmodelle" / "taesd" / "taew2_1.safetensors"
    assert started["vae_tae"] is True


def test_silence_a_model_with_no_family_the_header_names_keeps_any_tae(client: TestClient, served, tmp_path: Path):
    served["family"] = ""
    _remember(client, vae=f"{TAE_PREFIX}taew2_1.safetensors")
    _hand_start(client)
    assert served["started"][-1]["vae"] == tmp_path / "bildmodelle" / "taesd" / "taew2_1.safetensors"


def test_silence_a_plain_vae_is_drawn_with_whatever_the_family(client: TestClient, served, tmp_path: Path):
    _remember(client, vae="ae.safetensors")
    _hand_start(client)
    started = served["started"][-1]
    assert started["vae"] == tmp_path / "bildmodelle" / "vae" / "ae.safetensors"
    assert not started.get("vae_tae")
