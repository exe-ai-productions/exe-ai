"""The studio offers a ControlNet only for the families sd.cpp computes it
for, and a draw sends none for the others.

sd.cpp hands the guide images to the model only where it is a UNet (SD 1.x,
SD 2.x, SDXL and their variants); for Flux, SD3, Qwen-Image and the rest the
option is passed over without a word. A control that does nothing is not
offered: the family table says which families have it, the window reads that
one field, and the draw route leaves the option out for the others.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import image_families
from app.bildrunner import Auftrag, Bildrunner
from app.config import Config

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src"

UNET = ("sd15", "sd2", "sdxl", "sdxs", "sd15_pix2pix", "sdxl_pix2pix")


def test_the_unet_families_carry_the_fact_and_no_other_family_does():
    names = {f.name for f in image_families.FAMILIES if f.control_net}
    assert names == set(UNET)
    for name in ("flux", "sd3", "qwen_image", "zimage", "krea2"):
        assert image_families.get(name).control_net is False


def test_the_table_hands_the_fact_to_the_window(client: TestClient):
    table = {f["name"]: f for f in client.get("/api/v1/bild/familien").json()}
    assert table["sdxl"]["control_net"] is True
    assert table["flux"]["control_net"] is False


def test_the_window_stands_the_section_only_where_the_family_has_it():
    details = (FRONTEND / "teile" / "StudioDetails.svelte").read_text(encoding="utf-8")
    assert "$derived(!familyEntry || familyEntry.control_net !== false)" in details
    assert "{#if controlNetOffered}\n  <StudioSection titel={t('bild.gruppe_pose')}>" in details
    draw = (FRONTEND / "lib" / "studiozeichnen.svelte.js").read_text(encoding="utf-8")
    assert "const controlNet = !fam || fam.control_net !== false" in draw


@pytest.fixture
def senden(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """Sends a POST /bild with a ControlNet and a guide image and returns the
    Auftrag that would have reached the generator."""
    bildordner = tmp_path / "bildmodelle"
    (bildordner / "controlnet").mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")
    (bildordner / "controlnet" / "canny.safetensors").write_bytes(b"x")
    config.app.bildmodelle_verzeichnis = str(bildordner)
    bilder = tmp_path / "bilder"
    bilder.mkdir()
    config.app.bilder_verzeichnis = str(bilder)
    (bilder / "vorlage.png").write_bytes(b"PNG")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    gesehen: dict = {}

    def _erzeugen(self, auftrag: Auftrag, ziel, **kwargs):
        gesehen["auftrag"] = auftrag
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    def _senden(**felder):
        body = {
            "prompt": "x",
            "modell": "base.safetensors",
            "control_net": "canny.safetensors",
            "control_image": "vorlage.png",
            "canny": True,
            **felder,
        }
        antwort = client.post("/api/v1/bild", json=body)
        assert antwort.status_code == 201, antwort.text
        return gesehen["auftrag"]

    return _senden


def test_a_family_with_a_unet_draws_with_the_control_net(senden):
    auftrag = senden(familie="sd15")
    assert auftrag.control_net is not None
    assert auftrag.control_net.name == "canny.safetensors"
    assert auftrag.control_image is not None and auftrag.canny is True


def test_a_family_without_one_draws_without_it(senden):
    auftrag = senden(familie="hidream_o1")
    assert auftrag.control_net is None
    assert auftrag.control_image is None
    assert auftrag.canny is False
