"""A tiny autoencoder (TAE) chosen where a VAE is chosen decodes the finished picture.

The choice stands under ``taesd:`` in front of its file name (a name of one
folder is never looked up in the other). Where one is chosen, sd-cli, the kit
switches and the picture server start with ``--taesd <file>`` instead of
``--vae <file>``, never with ``--taesd-preview-only`` and never with a second
tiny autoencoder for the preview. A VAE gives the command it always gave, and a
change between the two is another start for the picture server.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildbausatz, bildrunner
from app.api.v1 import bild
from app.bildbausatz import TAE_PREFIX, Gespann
from app.bildrunner import Auftrag, BildFehler, Bildrunner
from app.bildturbo import PROGRAMM, Bildturbo
from app.config import Config
from tests.test_bildturbo import _LebtImmer

MODEL = "tae-model.safetensors"
TAE = "taew2_1.safetensors"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """An image folder with a model, a VAE and a tiny autoencoder of the same
    name — the case where taking one folder's file for the other's would show."""
    (tmp_path / "vae").mkdir()
    (tmp_path / "taesd").mkdir()
    (tmp_path / MODEL).write_bytes(b"x")
    (tmp_path / "vae" / "ae.safetensors").write_bytes(b"x")
    (tmp_path / "vae" / "twin.safetensors").write_bytes(b"x")
    (tmp_path / "taesd" / TAE).write_bytes(b"x")
    (tmp_path / "taesd" / "twin.safetensors").write_bytes(b"x")
    return tmp_path


def _sd_cli(monkeypatch) -> None:
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/somewhere/sd-cli")


# --- The choice and the file it names ---


def test_the_vae_choices_list_the_vaes_then_the_tiny_autoencoders_under_their_word(folder: Path):
    choices = bildrunner.vae_choices(folder)
    vaes = bildrunner.vaes(folder)
    assert choices[: len(vaes)] == vaes
    assert choices[len(vaes):] == [f"{TAE_PREFIX}{TAE}", f"{TAE_PREFIX}twin.safetensors"]


def test_a_choice_is_resolved_in_the_folder_of_its_kind(folder: Path):
    assert bildrunner.vae_choice_path(folder, "twin.safetensors") == folder / "vae" / "twin.safetensors"
    assert bildrunner.vae_choice_path(folder, f"{TAE_PREFIX}twin.safetensors") == (
        folder / "taesd" / "twin.safetensors"
    )


def test_a_name_of_one_folder_is_never_taken_for_a_name_of_the_other(folder: Path):
    # The tiny autoencoder's bare name is no VAE, and a VAE's name behind the word is no tiny autoencoder.
    with pytest.raises(BildFehler):
        bildrunner.vae_choice_path(folder, TAE)
    with pytest.raises(BildFehler):
        bildrunner.vae_choice_path(folder, f"{TAE_PREFIX}ae.safetensors")


def test_only_the_word_marks_a_tiny_autoencoder():
    assert bildbausatz.is_tae_choice(f"{TAE_PREFIX}x.safetensors") is True
    for name in (None, "", "x.safetensors", "taesd.safetensors"):
        assert bildbausatz.is_tae_choice(name) is False


# --- sd-cli ---


def test_a_tiny_autoencoder_as_the_vae_gives_taesd_without_preview_only_and_without_vae(
    folder: Path, monkeypatch
):
    _sd_cli(monkeypatch)
    command = Bildrunner(folder).befehl(
        Auftrag(modell=folder / MODEL, prompt="x", vae=folder / "taesd" / TAE, vae_is_tae=True),
        folder / "a.png",
    )
    assert command[command.index("--taesd") + 1] == str(folder / "taesd" / TAE)
    assert command.count("--taesd") == 1
    assert "--vae" not in command and "--taesd-preview-only" not in command


def test_a_vae_gives_the_command_it_always_gave(folder: Path, monkeypatch):
    _sd_cli(monkeypatch)
    command = Bildrunner(folder).befehl(
        Auftrag(modell=folder / MODEL, prompt="x", vae=folder / "vae" / "ae.safetensors"),
        folder / "a.png",
    )
    assert command[command.index("--vae") + 1] == str(folder / "vae" / "ae.safetensors")
    assert "--taesd" not in command


def test_no_second_tiny_autoencoder_is_added_for_the_preview(folder: Path, monkeypatch):
    _sd_cli(monkeypatch)
    command = Bildrunner(folder).befehl(
        Auftrag(
            modell=folder / MODEL, prompt="x", vae=folder / "taesd" / TAE, vae_is_tae=True,
            live_preview="tae", taesd=folder / "taesd" / "twin.safetensors",
        ),
        folder / "a.png",
    )
    # The preview still asks for the tiny autoencoder's painting, with the one file of the run.
    assert command[command.index("--preview") + 1] == "tae"
    assert command.count("--taesd") == 1 and "--taesd-preview-only" not in command


def test_silence_the_preview_with_a_vae_keeps_its_own_tiny_autoencoder_for_the_preview_only(
    folder: Path, monkeypatch
):
    _sd_cli(monkeypatch)
    command = Bildrunner(folder).befehl(
        Auftrag(
            modell=folder / MODEL, prompt="x", vae=folder / "vae" / "ae.safetensors",
            live_preview="tae", taesd=folder / "taesd" / TAE,
        ),
        folder / "a.png",
    )
    assert command[command.index("--taesd") + 1] == str(folder / "taesd" / TAE)
    assert "--taesd-preview-only" in command
    assert command[command.index("--vae") + 1] == str(folder / "vae" / "ae.safetensors")


# --- The kit ---


def test_the_kit_gives_taesd_for_a_tiny_autoencoder_and_vae_for_a_vae():
    tae = bildbausatz.schalter(
        Gespann(familie="flux", diffusion_model=Path("/m/f.gguf"), vae=Path("/t/x.safetensors"), vae_tae=True)
    )
    vae = bildbausatz.schalter(
        Gespann(familie="flux", diffusion_model=Path("/m/f.gguf"), vae=Path("/v/x.safetensors"))
    )
    assert tae[tae.index("--taesd") + 1] == str(Path("/t/x.safetensors")) and "--vae" not in tae
    assert vae[vae.index("--vae") + 1] == str(Path("/v/x.safetensors")) and "--taesd" not in vae


# --- The picture server ---


def _server(tmp_path: Path, monkeypatch) -> tuple[Bildturbo, dict]:
    build = tmp_path / "stable-diffusion.cpp" / "master-1"
    build.mkdir(parents=True)
    program = build / PROGRAMM
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    caught: dict = {}

    def popen(command, **kwargs):
        caught["command"] = command
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", popen)
    return Bildturbo(tmp_path), caught


def test_the_server_starts_with_taesd_instead_of_vae(tmp_path: Path, monkeypatch):
    turbo, caught = _server(tmp_path, monkeypatch)
    turbo.starten(Path("/m/m.safetensors"), vae=Path("/t/taew2_1.safetensors"), vae_tae=True)
    command = caught["command"]
    assert command[command.index("--taesd") + 1] == str(Path("/t/taew2_1.safetensors"))
    assert command.count("--taesd") == 1
    assert "--vae" not in command and "--taesd-preview-only" not in command


def test_the_server_with_a_vae_starts_as_it_did(tmp_path: Path, monkeypatch):
    turbo, caught = _server(tmp_path, monkeypatch)
    turbo.starten(Path("/m/m.safetensors"), vae=Path("/v/ae.safetensors"))
    command = caught["command"]
    assert command[command.index("--vae") + 1] == str(Path("/v/ae.safetensors"))
    assert "--taesd" not in command


def test_a_change_between_a_tiny_autoencoder_and_a_vae_is_another_server(tmp_path: Path, monkeypatch):
    turbo, _ = _server(tmp_path, monkeypatch)
    turbo.starten(Path("/m/m.safetensors"), vae=Path("/t/twin.safetensors"), vae_tae=True)
    assert turbo.passt_zu("m.safetensors", f"{TAE_PREFIX}twin.safetensors")
    # The same file name under the other kind is not the server that runs.
    assert not turbo.passt_zu("m.safetensors", "twin.safetensors")
    assert not turbo.passt_zu("m.safetensors", None)
    turbo.starten(Path("/m/m.safetensors"), vae=Path("/v/twin.safetensors"))
    assert turbo.passt_zu("m.safetensors", "twin.safetensors")
    assert not turbo.passt_zu("m.safetensors", f"{TAE_PREFIX}twin.safetensors")


# --- The routes ---


@pytest.fixture
def served(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """The service with the folder above, its picture server replaced by a recorder."""
    folder = tmp_path / "bildmodelle"
    (folder / "vae").mkdir(parents=True)
    (folder / "taesd").mkdir()
    (folder / MODEL).write_bytes(b"x")
    (folder / "vae" / "ae.safetensors").write_bytes(b"x")
    (folder / "taesd" / TAE).write_bytes(b"x")
    monkeypatch.setattr(bild.bildinhalt, "family", lambda path: "")
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    turbo = client.app.state.bildturbo
    state: dict = {"started": []}
    monkeypatch.setattr(turbo, "starten", lambda *a, **k: state["started"].append(k))
    monkeypatch.setattr(turbo, "laeuft", lambda: True)
    monkeypatch.setattr(turbo, "passt_zu", lambda *a, **k: False)
    monkeypatch.setattr(turbo, "bereit_abwarten", lambda *a, **k: True)
    monkeypatch.setattr(turbo, "zeichnen", lambda body, **k: b"PNG")
    monkeypatch.setattr(turbo, "belegt_gb", lambda: None)
    return state


def _give_the_model_a_vae(client: TestClient, choice: str) -> None:
    answer = client.patch(
        "/api/v1/settings/global/bildmodellwerte", json={"wert": {MODEL: {"vae": choice}}}
    )
    assert answer.status_code == 200, answer.text


def test_the_model_values_keep_the_choice_with_its_word(client: TestClient, served):
    _give_the_model_a_vae(client, f"{TAE_PREFIX}{TAE}")
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": MODEL}).json()
    assert answer["parts"]["vae"] == f"{TAE_PREFIX}{TAE}"


def test_a_choice_that_names_no_file_of_its_folder_is_dropped(client: TestClient, served):
    _give_the_model_a_vae(client, f"{TAE_PREFIX}ae.safetensors")
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": MODEL}).json()
    assert "vae" not in answer["parts"]


def test_the_hand_start_takes_the_tiny_autoencoder_from_its_folder(client: TestClient, served, tmp_path: Path):
    _give_the_model_a_vae(client, f"{TAE_PREFIX}{TAE}")
    assert client.post("/api/v1/bild/turbo/start", json={"modell": MODEL}).status_code == 200
    started = served["started"][-1]
    assert started["vae"] == tmp_path / "bildmodelle" / "taesd" / TAE and started["vae_tae"] is True


def test_the_hand_start_with_a_vae_names_no_tiny_autoencoder(client: TestClient, served, tmp_path: Path):
    _give_the_model_a_vae(client, "ae.safetensors")
    assert client.post("/api/v1/bild/turbo/start", json={"modell": MODEL}).status_code == 200
    started = served["started"][-1]
    assert started["vae"] == tmp_path / "bildmodelle" / "vae" / "ae.safetensors"
    assert not started.get("vae_tae")


def test_a_picture_starts_the_server_on_the_tiny_autoencoder_the_model_carries(
    client: TestClient, served, tmp_path: Path
):
    _give_the_model_a_vae(client, f"{TAE_PREFIX}{TAE}")
    answer = client.post("/api/v1/bild", json={"prompt": "x", "modell": MODEL})
    assert answer.status_code == 201, answer.text
    started = served["started"][-1]
    assert started["vae"] == tmp_path / "bildmodelle" / "taesd" / TAE and started["vae_tae"] is True
