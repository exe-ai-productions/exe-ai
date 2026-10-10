"""The seven Bausatz fields, and ``familie`` alongside them, on their way
from a request into an Auftrag.

The picture itself is the generator's business (proved by running it, not
by asserting about pixels — see app/api/v1/bild.py's own docstring); what
matters here is the wiring this step adds: a request that never mentions
any of the seven fields must build exactly today's Auftrag, a request that
does must arrive with resolved paths, a checked vae_format and a clamped
guidance, and setting ``diffusion_model`` without a ``familie`` — or with
one that does not match its text encoder — must be refused rather than
guessed. ``Bildrunner.erzeugen`` is mocked so the test never needs a real
sd-cli — it only needs to see the Auftrag that would have been handed to
it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bildrunner import Bildrunner
from app.bildturbo import STARTFRIST, STARTFRIST_BAUSATZ
from app.config import Config
from tests.test_bildturbo import _LebtImmer


# A whole kit per family, filled in where a test sends a diffusion model:
# a kit missing a part never starts, and a test about one part must not be
# refused for the others it leaves out.
_GANZER_BAUSATZ = {
    "flux": {"t5xxl": "t5xxl.gguf", "clip_l": "clip_l.safetensors", "vae": "ae.safetensors"},
    "zimage": {"llm": "llm.gguf", "vae": "ae.safetensors"},
}


def _ganz(felder: dict) -> dict:
    if felder.get("diffusion_model"):
        for feld, name in _GANZER_BAUSATZ.get(felder.get("familie"), {}).items():
            felder.setdefault(feld, name)
    return felder


@pytest.fixture
def bausatz_senden(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """Sends a POST /bild with the given extra fields and returns the
    Auftrag that would have reached the generator."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")
    (bildordner / "flux1-dev.gguf").write_bytes(b"x")
    textversteher_ordner = bildordner / "text_encoders"
    textversteher_ordner.mkdir()
    for name in ("t5xxl.gguf", "clip_l.safetensors", "clip_g.safetensors", "llm.gguf"):
        (textversteher_ordner / name).write_bytes(b"x")
    (bildordner / "vae").mkdir()
    (bildordner / "vae" / "ae.safetensors").write_bytes(b"x")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    aufgerufen: dict = {}

    def _erzeugen(self, auftrag, ziel):
        aufgerufen["auftrag"] = auftrag
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", _erzeugen)

    def _senden(**felder):
        body = {"prompt": "x", "modell": "base.safetensors", **_ganz(felder)}
        antwort = client.post("/api/v1/bild", json=body)
        assert antwort.status_code == 201, antwort.text
        return aufgerufen["auftrag"]

    return _senden


def test_leeres_diffusion_model_ist_kein_bausatz(bausatz_senden):
    """A plain single-file model whose form sends an empty diffusion_model
    (Svelte's shape for "nothing chosen") must draw exactly as before —
    an empty string is unset, not a Bausatz asking for a missing family."""
    auftrag = bausatz_senden(diffusion_model="")
    assert auftrag.diffusion_model is None


def test_leerer_t5xxl_bei_zimage_wird_nicht_abgelehnt(bausatz_senden):
    """A dropdown left on "none" sends "", not null — zimage/flux2 must
    still go through even though the flux-only fields are present as
    empty strings rather than absent."""
    auftrag = bausatz_senden(
        diffusion_model="flux1-dev.gguf", familie="zimage",
        llm="llm.gguf", t5xxl="", clip_l="",
    )
    assert auftrag.familie == "zimage"
    assert auftrag.llm is not None


def test_unbekannte_familie_ist_400(bausatz_senden, config, client):
    antwort = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors",
                               "diffusion_model": "flux1-dev.gguf", "familie": "Flux"},
    )
    assert antwort.status_code == 400


def test_ohne_bausatz_felder_bleibt_der_auftrag_wie_heute(bausatz_senden):
    auftrag = bausatz_senden()
    assert auftrag.diffusion_model is None
    assert auftrag.t5xxl is None
    assert auftrag.clip_l is None
    assert auftrag.clip_g is None
    assert auftrag.llm is None
    assert auftrag.vae_format == ""
    assert auftrag.guidance is None


def test_diffusion_model_kommt_aufgeloest_an(bausatz_senden, tmp_path):
    auftrag = bausatz_senden(diffusion_model="flux1-dev.gguf", familie="flux")
    assert auftrag.diffusion_model == tmp_path / "bildmodelle" / "flux1-dev.gguf"


def test_familie_kommt_am_auftrag_an(bausatz_senden):
    auftrag = bausatz_senden(diffusion_model="flux1-dev.gguf", familie="flux")
    assert auftrag.familie == "flux"


def test_diffusion_model_ohne_familie_ist_400(bausatz_senden, config, client):
    antwort = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors",
                               "diffusion_model": "flux1-dev.gguf"},
    )
    assert antwort.status_code == 400


def test_textversteher_ohne_diffusion_model_ist_400(bausatz_senden, config, client):
    """The other direction, and the one that used to pass in silence: the
    plain-model branch builds "-m <file>" and never reads an encoder, so a
    Bausatz put together in the window was dropped without a word and the
    error that finally arrived named the model file instead."""
    faelle = (
        ("t5xxl", "flux"), ("clip_l", "flux"), ("llm", "zimage"),
        # clip_g goes through the same hole and was left in it a commit
        # longer: the window shows its field for EVERY Bausatz family, so
        # a merged single-file Flux plus a CLIP-G was accepted with a 201
        # and drew a picture that had never seen the encoder.
        ("clip_g", "flux"),
    )
    for feld, familie in faelle:
        antwort = client.post(
            "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors",
                                  "familie": familie, feld: "t5xxl.gguf"},
        )
        assert antwort.status_code == 400, f"{feld}: {antwort.text}"


def test_zimage_familie_mit_t5xxl_wird_abgelehnt_statt_als_flux_gebaut(bausatz_senden, config, client):
    antwort = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors",
                               "diffusion_model": "flux1-dev.gguf", "familie": "zimage",
                               "t5xxl": "t5xxl.gguf"},
    )
    assert antwort.status_code == 400


def test_t5xxl_kommt_aufgeloest_an(bausatz_senden, tmp_path):
    """Sent with the diffusion model it belongs to: that is the only
    request in which an encoder is ever read, and since the silent
    fallback was closed it is also the only one that is accepted."""
    auftrag = bausatz_senden(
        t5xxl="t5xxl.gguf", diffusion_model="flux1-dev.gguf", familie="flux",
    )
    assert auftrag.t5xxl == tmp_path / "bildmodelle" / "text_encoders" / "t5xxl.gguf"


def test_clip_l_kommt_aufgeloest_an(bausatz_senden, tmp_path):
    auftrag = bausatz_senden(
        clip_l="clip_l.safetensors", diffusion_model="flux1-dev.gguf", familie="flux",
    )
    assert auftrag.clip_l == tmp_path / "bildmodelle" / "text_encoders" / "clip_l.safetensors"


def test_clip_g_kommt_aufgeloest_an(bausatz_senden, tmp_path):
    """Sent with the diffusion model it belongs to, like the other three:
    the plain-model branch never reads clip_g either, so that is the only
    request in which it survives — and since that gap was closed, also the
    only one that is accepted. The family may be any Bausatz family; no
    family owns clip_g."""
    auftrag = bausatz_senden(
        clip_g="clip_g.safetensors", diffusion_model="flux1-dev.gguf", familie="flux",
    )
    assert auftrag.clip_g == tmp_path / "bildmodelle" / "text_encoders" / "clip_g.safetensors"


def test_llm_kommt_aufgeloest_an(bausatz_senden, tmp_path):
    auftrag = bausatz_senden(
        llm="llm.gguf", diffusion_model="flux1-dev.gguf", familie="zimage",
    )
    assert auftrag.llm == tmp_path / "bildmodelle" / "text_encoders" / "llm.gguf"


def test_vae_format_kommt_durch_wenn_gueltig(bausatz_senden):
    assert bausatz_senden(vae_format="flux").vae_format == "flux"


def test_unbekanntes_vae_format_wird_leer(bausatz_senden):
    """Like sampler/scheduler, an unknown value is brought into range, not
    refused — only a name that must exist on disk is refused outright."""
    assert bausatz_senden(vae_format="quatsch").vae_format == ""


def test_guidance_wird_geklemmt_wie_cfg(bausatz_senden):
    assert bausatz_senden(guidance=3.5).guidance == 3.5
    assert bausatz_senden(guidance=-5.0).guidance == 0.0


def test_ein_unbekannter_diffusion_model_name_ist_404(bausatz_senden, config, client):
    antwort = client.post(
        "/api/v1/bild", json={"prompt": "x", "modell": "base.safetensors",
                               "diffusion_model": "gibtsnicht.gguf", "familie": "flux"},
    )
    assert antwort.status_code == 404


@pytest.fixture
def bausatz_turbo_senden(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """Sends a POST /bild through the TURBO path — the only path that reads
    STARTFRIST/STARTFRIST_BAUSATZ — and returns the frist bereit_abwarten
    was called with."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    bildordner = tmp_path / "bildmodelle"
    bildordner.mkdir(parents=True)
    (bildordner / "base.safetensors").write_bytes(b"x")
    (bildordner / "flux1-dev.gguf").write_bytes(b"x")
    (bildordner / "text_encoders").mkdir()
    for name in ("t5xxl.gguf", "clip_l.safetensors", "llm.gguf"):
        (bildordner / "text_encoders" / name).write_bytes(b"x")
    (bildordner / "vae").mkdir()
    (bildordner / "vae" / "ae.safetensors").write_bytes(b"x")

    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))

    turbo = client.app.state.bildturbo
    turbo._prozess = object()  # laeuft() sagt ja
    monkeypatch.setattr(turbo, "laeuft", lambda: True)
    monkeypatch.setattr(turbo, "belegt_gb", lambda: None)
    # A Gespann mismatch on every request — the point is to always take the
    # starten()/bereit_abwarten() branch, so there is always a frist to see.
    monkeypatch.setattr(turbo, "passt_zu", lambda *a, **k: False)
    monkeypatch.setattr(turbo, "starten", lambda *a, **k: None)

    gesehen: dict = {}

    def _zeichnen(koerper, **k):
        gesehen["koerper"] = koerper
        return b"PNG"

    monkeypatch.setattr(turbo, "zeichnen", _zeichnen)

    def _bereit_abwarten(frist, stopped=None):
        gesehen["frist"] = frist
        return True

    monkeypatch.setattr(turbo, "bereit_abwarten", _bereit_abwarten)

    def _senden(**felder):
        body = {"prompt": "x", "modell": "base.safetensors", **_ganz(felder)}
        antwort = client.post("/api/v1/bild", json=body)
        assert antwort.status_code == 201, antwort.text
        return gesehen

    return _senden


def test_bausatz_wartet_mit_der_langen_startfrist(bausatz_turbo_senden):
    gesehen = bausatz_turbo_senden(
        diffusion_model="flux1-dev.gguf", familie="flux", t5xxl="t5xxl.gguf"
    )
    assert gesehen["frist"] == STARTFRIST_BAUSATZ
    # A Bausatz without a guidance value must not send a null through.
    assert "distilled_guidance" not in gesehen["koerper"]["sample_params"]["guidance"]


def test_ohne_bausatz_bleibt_die_kurze_startfrist(bausatz_turbo_senden):
    assert bausatz_turbo_senden()["frist"] == STARTFRIST


@pytest.mark.parametrize(
    ("familie", "teil"), [("flux", {"t5xxl": "t5xxl.gguf"}), ("zimage", {"llm": "llm.gguf"})]
)
def test_a_kit_picture_keeps_the_cfg_it_asks_for(bausatz_senden, familie, teil):
    """The CFG is free for every family: a kit picture that asks for 3.5
    draws with 3.5. The family's recommended 1.0 is a start value of the
    window, not a lock of the route."""
    auftrag = bausatz_senden(diffusion_model="flux1-dev.gguf", familie=familie, cfg=3.5, **teil)
    assert auftrag.cfg == 3.5


def test_sdxl_cfg_bleibt_frei(bausatz_senden):
    """No diffusion_model — the byte-identical case the step protects."""
    auftrag = bausatz_senden(cfg=7.0)
    assert auftrag.cfg == 7.0


def test_flux_server_body_carries_the_free_cfg_and_guidance(bausatz_turbo_senden):
    gesehen = bausatz_turbo_senden(
        diffusion_model="flux1-dev.gguf", familie="flux", t5xxl="t5xxl.gguf",
        cfg=3.5, guidance=2.5,
    )
    fuehrung = gesehen["koerper"]["sample_params"]["guidance"]
    assert fuehrung["txt_cfg"] == 3.5
    assert fuehrung["distilled_guidance"] == 2.5


def test_sdxl_server_body_carries_guidance_like_sd_cli(bausatz_turbo_senden):
    """The distilled guidance belongs to the model, not to the way its files
    arrived — sd-cli sends --guidance whenever it is set, and the server
    body carries it the same way now that the server reads it per job. The
    cfg stays untouched without a Bausatz."""
    gesehen = bausatz_turbo_senden(cfg=7.0, guidance=2.5)
    fuehrung = gesehen["koerper"]["sample_params"]["guidance"]
    assert fuehrung["txt_cfg"] == 7.0
    assert fuehrung["distilled_guidance"] == 2.5


# --- A kit missing a part never starts -------------------------------------


@pytest.mark.parametrize(("weg", "name"), [("vae", "VAE"), ("llm", "LLM")])
def test_a_kit_missing_a_part_is_refused_and_names_it(bausatz_senden, client, weg, name):
    """Z-Image needs its LLM and its VAE: without one, sd.cpp is never
    started, and the answer names the part instead of a load error."""
    body = {"prompt": "x", "modell": "base.safetensors", "diffusion_model": "flux1-dev.gguf",
            "familie": "zimage", "llm": "llm.gguf", "vae": "ae.safetensors"}
    del body[weg]
    antwort = client.post("/api/v1/bild", json=body, headers={"Accept-Language": "en"})
    assert antwort.status_code == 412
    assert name in antwort.json()["detail"]


def test_a_flux_kit_without_its_t5_is_refused(bausatz_senden, client):
    antwort = client.post("/api/v1/bild", json={
        "prompt": "x", "modell": "base.safetensors", "diffusion_model": "flux1-dev.gguf",
        "familie": "flux", "clip_l": "clip_l.safetensors", "vae": "ae.safetensors",
    }, headers={"Accept-Language": "en"})
    assert antwort.status_code == 412
    assert "T5-XXL" in antwort.json()["detail"]


def test_a_whole_kit_still_draws(bausatz_senden, tmp_path):
    """The silence probe: nothing missing, nothing refused."""
    auftrag = bausatz_senden(
        diffusion_model="flux1-dev.gguf", familie="zimage", llm="llm.gguf", vae="ae.safetensors",
    )
    assert auftrag.vae == tmp_path / "bildmodelle" / "vae" / "ae.safetensors"


# --- The server started by hand at the tile --------------------------------


def _kopf(path: Path, shapes: dict[str, list[int]], architecture: str | None = None) -> None:
    """A header-only model file: safetensors, or GGUF when an architecture
    is named. Only the header is ever read before a start."""
    import json
    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    if architecture is None:
        raw = json.dumps({
            name: {"dtype": "F16", "shape": shape, "data_offsets": [0, 0]}
            for name, shape in shapes.items()
        }).encode()
        path.write_bytes(struct.pack("<Q", len(raw)) + raw)
        return

    def text(value: str) -> bytes:
        data = value.encode()
        return struct.pack("<Q", len(data)) + data

    header = bytearray(b"GGUF") + struct.pack("<I", 3)
    header += struct.pack("<Q", len(shapes)) + struct.pack("<Q", 1)
    header += text("general.architecture") + struct.pack("<I", 8) + text(architecture)
    for name, shape in shapes.items():
        header += text(name) + struct.pack("<I", len(shape))
        for dim in reversed(shape):
            header += struct.pack("<Q", dim)
        header += struct.pack("<I", 1) + struct.pack("<Q", 0)
    path.write_bytes(bytes(header))


@pytest.fixture
def hand_start(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """A picture folder with a Z-Image diffusion model, its Qwen3 4B, a
    16-channel VAE and an SDXL checkpoint; the hand start's command line is
    caught instead of run."""
    ordner = tmp_path / "bildmodelle"
    config.app.bildmodelle_verzeichnis = str(ordner)
    _kopf(ordner / "z_image_turbo.gguf", {"cap_embedder.0.weight": [2560]}, "zimage")
    _kopf(ordner / "sdxl.safetensors", {
        "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
        "conditioner.embedders.1.model.token_embedding.weight": [49408, 1280],
        "first_stage_model.decoder.conv_in.weight": [512, 4, 3, 3],
    })
    _kopf(ordner / "text_encoders" / "qwen3-4b.gguf", {"token_embd.weight": [151936, 2560]}, "qwen3")
    _kopf(ordner / "vae" / "ae.safetensors", {"decoder.conv_in.weight": [512, 16, 3, 3]})

    turbo = client.app.state.bildturbo
    monkeypatch.setattr(type(turbo), "programm", property(lambda self: Path("/fake/sd-server")))
    gefangen: list[list[str]] = []

    def _popen(befehl, **kwargs):
        gefangen.append(befehl)
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", _popen)

    def _starten(modell: str, vae: str | None = None):
        if vae:
            antwort = client.patch(
                "/api/v1/settings/global/bildmodellwerte", json={"wert": {modell: {"vae": vae}}},
            )
            assert antwort.status_code == 200, antwort.text
        antwort = client.post(
            "/api/v1/bild/turbo/start", json={"modell": modell}, headers={"Accept-Language": "en"},
        )
        return antwort, gefangen[-1] if gefangen else None

    yield _starten
    turbo._prozess = None


def test_a_kit_model_starts_at_the_tile_with_its_parts(hand_start, tmp_path):
    """Z-Image at the tile: --diffusion-model with its Qwen3 and the VAE the
    model was given, never -m."""
    antwort, befehl = hand_start("z_image_turbo.gguf", vae="ae.safetensors")
    assert antwort.status_code == 200, antwort.text
    ordner = tmp_path / "bildmodelle"
    assert "-m" not in befehl
    assert befehl[befehl.index("--diffusion-model") + 1] == str(ordner / "z_image_turbo.gguf")
    assert befehl[befehl.index("--llm") + 1] == str(ordner / "text_encoders" / "qwen3-4b.gguf")
    assert befehl[befehl.index("--vae") + 1] == str(ordner / "vae" / "ae.safetensors")


def test_a_kit_model_without_its_vae_does_not_start_at_the_tile(hand_start):
    """A 16-channel VAE is never put in by itself: until the model is given
    one, sd.cpp does not start and the answer names the VAE."""
    antwort, befehl = hand_start("z_image_turbo.gguf")
    assert antwort.status_code == 412
    assert "VAE" in antwort.json()["detail"]
    assert befehl is None


def test_a_checkpoint_still_starts_with_m(hand_start, tmp_path):
    """The silence probe: SDXL starts with -m as before."""
    antwort, befehl = hand_start("sdxl.safetensors")
    assert antwort.status_code == 200, antwort.text
    assert befehl[befehl.index("-m") + 1] == str(tmp_path / "bildmodelle" / "sdxl.safetensors")
    assert "--diffusion-model" not in befehl


def test_a_flux_picture_without_a_sampler_names_none(bausatz_senden):
    """Neither the command nor the server's body carries a sampler the
    request did not name: sd.cpp draws a DiT with euler, not euler_a."""
    assert bausatz_senden(diffusion_model="flux1-dev.gguf", familie="flux").sampler == ""


def test_the_server_body_leaves_out_an_unnamed_sampler(bausatz_turbo_senden):
    gesehen = bausatz_turbo_senden(diffusion_model="flux1-dev.gguf", familie="flux")
    assert "sample_method" not in gesehen["koerper"]["sample_params"]


def test_the_server_body_carries_a_named_sampler(bausatz_turbo_senden):
    gesehen = bausatz_turbo_senden(diffusion_model="flux1-dev.gguf", familie="flux", sampler="dpm++2m")
    assert gesehen["koerper"]["sample_params"]["sample_method"] == "dpm++2m"


def test_a_vanished_own_vae_is_named_as_missing(hand_start):
    """The model was given a VAE that no longer lies in the folder: the
    answer names the VAE, not an unknown file."""
    antwort, befehl = hand_start("z_image_turbo.gguf", vae="weg.safetensors")
    assert antwort.status_code == 412
    assert "VAE" in antwort.json()["detail"]
    assert befehl is None
