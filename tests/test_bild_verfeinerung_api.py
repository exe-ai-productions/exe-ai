"""Auftrag B's twelve refinement fields on their way from a request into an
Auftrag.

Same shape as test_bild_bausatz_api.py: ``Bildrunner.erzeugen`` is mocked so
the test never needs a real sd-cli — it only needs to see the Auftrag that
would have been handed to it. What matters here is the wiring the fields
add: a request that never mentions any of them must build exactly today's
Auftrag (empty means UNSET, never an explicit zero), a request that does
must arrive checked and clamped, and an upscaler name that is neither a
built-in nor a file in the upscaler folder must be refused rather than
riding on and silently falling back to the default.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v1.bild import _turbo_auftrag
from app.bildrunner import Bildrunner
from app.config import Config


@pytest.fixture
def bild_senden(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """Sends a POST /bild with the given extra fields and returns the
    Auftrag that would have reached the generator."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")
    upscaler_ordner = bildordner / "upscaler"
    upscaler_ordner.mkdir()
    (upscaler_ordner / "esrgan-x4.pth").write_bytes(b"x")
    yolo_ordner = bildordner / "adetailer"
    yolo_ordner.mkdir()
    (yolo_ordner / "face.pt").write_bytes(b"x")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    aufgerufen: dict = {}

    def _erzeugen(self, auftrag, ziel):
        aufgerufen["auftrag"] = auftrag
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    def _senden(**felder):
        body = {"prompt": "x", "modell": "base.safetensors", **felder}
        antwort = client.post("/api/v1/bild", json=body)
        assert antwort.status_code == 201, antwort.text
        return aufgerufen["auftrag"]

    return _senden


def test_ohne_die_neuen_felder_bleibt_der_auftrag_wie_heute(bild_senden):
    """The whole point of "unset by default": a request that never mentions
    any of the twelve fields builds an Auftrag in which every one of them
    is still unset — no zeros, no empty strings turned into switches."""
    auftrag = bild_senden()
    assert auftrag.hires_steps == 0
    assert auftrag.hires_denoise == 0.0
    assert auftrag.hires_upscaler == ""
    assert auftrag.hires_width == 0
    assert auftrag.hires_height == 0
    assert auftrag.eta is None
    assert auftrag.flow_shift is None
    assert auftrag.sigmas == ""
    assert auftrag.extra_sample_args == ""
    assert auftrag.prediction == ""
    assert auftrag.ad_negativ == ""
    assert auftrag.ad_confidence is None


def test_die_hires_felder_kommen_aufs_raster_gelegt_an(bild_senden):
    auftrag = bild_senden(
        hires=True, hires_steps=120, hires_denoise=0.55,
        hires_width=1664, hires_height=2436,
    )
    assert auftrag.hires_steps == 120
    assert auftrag.hires_denoise == 0.55
    assert auftrag.hires_width == 1664
    # Rounded up onto the same grid the base edges use, as sd.cpp rounds.
    assert auftrag.hires_height == 2496


def test_hires_zielkante_null_bleibt_null(bild_senden):
    """0 means "not set" — it must never be pulled up to the minimum edge."""
    auftrag = bild_senden(hires=True, hires_width=0, hires_height=0)
    assert auftrag.hires_width == 0
    assert auftrag.hires_height == 0


def test_fester_upscaler_name_kommt_durch(bild_senden):
    auftrag = bild_senden(hires=True, hires_upscaler="Lanczos")
    assert auftrag.hires_upscaler == "Lanczos"


def test_upscaler_aus_dem_ordner_kommt_mit_ordner_an(bild_senden):
    auftrag = bild_senden(hires=True, hires_upscaler="esrgan-x4.pth")
    assert auftrag.hires_upscaler == "esrgan-x4"
    assert auftrag.hires_upscalers_ordner is not None
    assert auftrag.hires_upscalers_ordner.name == "upscaler"


def test_upscaler_aus_dem_ordner_geht_ohne_endung_hinaus(bild_senden, tmp_path: Path):
    """sd.cpp refuses a model upscaler named with its extension on both
    paths: sd-cli exits at once, sd-server answers "invalid params". The
    file name picked from the folder list leaves without it."""
    auftrag = bild_senden(hires=True, hires_upscaler="esrgan-x4.pth")

    befehl = Bildrunner(tmp_path).befehl(auftrag, tmp_path / "a.png")
    assert befehl[befehl.index("--hires-upscaler") + 1] == "esrgan-x4"
    assert befehl[befehl.index("--hires-upscalers-dir") + 1] == str(auftrag.hires_upscalers_ordner)

    assert _turbo_auftrag(auftrag)["hires"]["upscaler"] == "esrgan-x4"


@pytest.mark.parametrize(
    ("files", "chosen", "name"),
    [
        (["x.pth", "x.safetensors"], "x.pth", "x"),
        (["X.pth", "x.safetensors"], "X.pth", "X"),
        (["Lanczos.pth"], "Lanczos.pth", "Lanczos"),
    ],
)
def test_a_name_two_upscalers_share_is_refused(
    client: TestClient, bild_senden, tmp_path: Path, files, chosen, name,
):
    """Without the extension two files, or a file and a built-in name, are
    one name to sd.cpp, which would draw with whichever it finds first."""
    from app.i18n import t

    for file in files:
        (tmp_path / "bildmodelle" / "upscaler" / file).write_bytes(b"x")
    response = client.post(
        "/api/v1/bild",
        json={"prompt": "x", "modell": "base.safetensors", "hires": True, "hires_upscaler": chosen},
    )
    assert response.status_code == 409
    assert response.json()["detail"] in {
        t("bild.upscaler_doppelt", "de", name=name), t("bild.upscaler_doppelt", "en", name=name),
    }


def test_the_built_in_name_still_draws_beside_a_file_of_that_name(bild_senden, tmp_path: Path):
    (tmp_path / "bildmodelle" / "upscaler" / "Lanczos.pth").write_bytes(b"x")
    auftrag = bild_senden(hires=True, hires_upscaler="Lanczos")
    assert auftrag.hires_upscaler == "Lanczos"


def test_a_shared_name_does_not_stop_a_picture_without_highres(bild_senden, tmp_path: Path):
    """The window sends the locked field along while highres is off; nothing
    is upscaled then, so nothing is refused."""
    (tmp_path / "bildmodelle" / "upscaler" / "x.pth").write_bytes(b"x")
    (tmp_path / "bildmodelle" / "upscaler" / "x.safetensors").write_bytes(b"x")
    auftrag = bild_senden(hires=False, hires_upscaler="x.pth")
    assert auftrag.hires is False


def test_unbekannter_upscaler_ist_404(config: Config, client: TestClient, bild_senden):
    """Refused, not silently folded to the default upscaler — a control
    that quietly draws with something else than it names is a lie."""
    antwort = client.post(
        "/api/v1/bild",
        json={"prompt": "x", "modell": "base.safetensors",
              "hires": True, "hires_upscaler": "gibtsnicht.pth"},
    )
    assert antwort.status_code == 404


def test_eta_und_flow_shift_reisen_auch_als_null_wert(bild_senden):
    """0 is a REAL eta (a change for euler_a) — None and 0 must stay two
    different things all the way to the Auftrag."""
    auftrag = bild_senden(eta=0.0, flow_shift=3.0)
    assert auftrag.eta == 0.0
    assert auftrag.flow_shift == 3.0


def test_sigmas_und_sampler_args_werden_getrimmt(bild_senden):
    auftrag = bild_senden(sigmas="  14.61,7.8,3.5,0.0  ", extra_sample_args=" base_shift=0.5 ")
    assert auftrag.sigmas == "14.61,7.8,3.5,0.0"
    assert auftrag.extra_sample_args == "base_shift=0.5"


def test_unbekannte_prediction_faellt_auf_unbesetzt(bild_senden):
    """Same fold as live_preview: an unknown value becomes "no flag", never
    a guessed member of the table."""
    assert bild_senden(prediction="flux_flow").prediction == "flux_flow"
    assert bild_senden(prediction="quatsch").prediction == ""


def test_ad_negativ_und_schwelle_kommen_an(bild_senden):
    auftrag = bild_senden(ad_modell="face.pt", ad_negativ="blurry", ad_confidence=0.4)
    assert auftrag.ad_negativ == "blurry"
    assert auftrag.ad_confidence == 0.4


def test_ad_schwelle_ausserhalb_des_bereichs_ist_422(config: Config, client: TestClient, bild_senden):
    antwort = client.post(
        "/api/v1/bild",
        json={"prompt": "x", "modell": "base.safetensors", "ad_confidence": 1.5},
    )
    assert antwort.status_code == 422


def test_der_modellstand_nennt_die_upscaler(config: Config, client: TestClient, bild_senden):
    """The window's list comes from the server: the folder's files plus
    sd-cli's built-in names, and the folder's own path for the ortzeile."""
    stand = client.get("/api/v1/bild/modelle").json()
    assert stand["upscalers"] == ["esrgan-x4.pth"]
    assert "Lanczos" in stand["hires_upscaler_feste"]
    assert stand["upscaler_ordner"].endswith("upscaler")
