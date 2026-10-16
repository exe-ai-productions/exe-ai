"""The values each picture model starts with, set once in the picture server.

What is stored is checked field by field and keyed by the model's file name;
``/bild/vorgaben`` lays the stored values over the family's start values and
names them; ``draw_image`` outside a chat draws with them; and "reset" takes
a model back to its family.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import bildbausatz, bildmodellwerte, bildrunner
from app.config import Config
from app.tools import bild_werkzeug
from tests.conftest import Bilddienst
from tests.test_image_families import _HEADERS, _gguf


@pytest.fixture
def picture_folder(config: Config, tmp_path: Path) -> Path:
    ordner = tmp_path / "bildmodelle"
    ordner.mkdir()
    config.app.bildmodelle_verzeichnis = str(ordner)
    _gguf(ordner / "flux.gguf", "flux", _HEADERS["flux"])
    return ordner


def _setzen(client: TestClient, wert) -> None:
    answer = client.patch("/api/v1/settings/global/bildmodellwerte", json={"wert": wert})
    assert answer.status_code == 200, answer.text


def _vorgaben(client: TestClient, modell: str = "flux.gguf") -> dict:
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": modell})
    assert answer.status_code == 200, answer.text
    return answer.json()


# --- The check -----------------------------------------------------------------


def test_the_check_keeps_the_fields_it_knows_and_drops_the_rest():
    sauber = bildmodellwerte.pruefen({
        "a.gguf": {
            "schritte": 8, "cfg": 2.5, "sampler": "euler", "vae": "ae.safetensors",
            "clip_skip": 2, "prediction": "v", "trigger": "sks dog", "hinweis": "fine",
            "unbekannt": 1,
        },
    })
    assert sauber == {"a.gguf": {
        "schritte": 8, "cfg": 2.5, "sampler": "euler", "vae": "ae.safetensors",
        "clip_skip": 2, "prediction": "v", "trigger": "sks dog", "hinweis": "fine",
    }}


def test_a_value_out_of_its_range_is_not_kept():
    sauber = bildmodellwerte.pruefen({
        "a.gguf": {
            "sampler": "no-such-sampler", "clip_skip": 99, "prediction": "wrong",
            "vae": "../outside.safetensors", "cfg": float("nan"), "schritte": True,
        },
    })
    assert all(wert is None for wert in sauber["a.gguf"].values())


def test_a_name_that_is_a_path_is_no_model():
    assert bildmodellwerte.pruefen({"../a.gguf": {"schritte": 4}, "sub/b.gguf": {"schritte": 4}}) == {}


def test_a_model_sent_as_nothing_loses_its_own_values():
    assert bildmodellwerte.pruefen({"a.gguf": None}) == {"a.gguf": None}


def test_the_cfg_has_no_upper_limit_and_is_never_negative():
    sauber = bildmodellwerte.pruefen({"a.gguf": {"cfg": 500, "guidance": -3}})["a.gguf"]
    assert sauber["cfg"] == 500.0
    assert sauber["guidance"] == 0.0


# --- The route -----------------------------------------------------------------


def test_a_model_without_values_of_its_own_opens_on_its_family(
    client: TestClient, picture_folder: Path
):
    v = _vorgaben(client)
    assert v["family"] == "flux"
    assert (v["cfg"], v["guidance"], v["sampler"]) == (1.0, 3.5, "euler")
    assert v["eigene"] == []
    assert (v["vae"], v["clip_skip"], v["prediction"], v["trigger"], v["hinweis"]) == ("", None, "", "", "")


def test_the_stored_values_lie_over_the_family_and_are_named(
    client: TestClient, picture_folder: Path
):
    _setzen(client, {"flux.gguf": {"schritte": 6, "cfg": 2.0, "trigger": "sks", "clip_skip": 2}})
    v = _vorgaben(client)
    assert (v["schritte"], v["cfg"], v["trigger"], v["clip_skip"]) == (6, 2.0, "sks", 2)
    # What was not set stays the family's own.
    assert (v["guidance"], v["sampler"]) == (3.5, "euler")
    assert v["eigene"] == ["cfg", "clip_skip", "schritte", "trigger"]
    assert v["sources"]["cfg"] == "model"
    assert v["sources"]["guidance"] != "model"


def test_one_change_keeps_the_other_values_of_the_model(
    client: TestClient, picture_folder: Path
):
    _setzen(client, {"flux.gguf": {"schritte": 6}})
    _setzen(client, {"flux.gguf": {"cfg": 2.0}})
    v = _vorgaben(client)
    assert (v["schritte"], v["cfg"]) == (6, 2.0)


def test_a_value_set_back_to_nothing_is_the_family_s_again(
    client: TestClient, picture_folder: Path
):
    _setzen(client, {"flux.gguf": {"schritte": 6, "cfg": 2.0}})
    _setzen(client, {"flux.gguf": {"cfg": None}})
    v = _vorgaben(client)
    assert (v["schritte"], v["cfg"]) == (6, 1.0)
    assert v["eigene"] == ["schritte"]


def test_reset_takes_the_model_back_to_its_family(client: TestClient, picture_folder: Path):
    _setzen(client, {"flux.gguf": {"schritte": 6, "hinweis": "x"}})
    _setzen(client, {"flux.gguf": None})
    v = _vorgaben(client)
    assert v["schritte"] == 20
    assert v["eigene"] == []


def test_the_values_of_one_model_do_not_reach_another(client: TestClient, picture_folder: Path):
    _gguf(picture_folder / "other.gguf", "flux", _HEADERS["flux"])
    _setzen(client, {"flux.gguf": {"schritte": 6}})
    assert _vorgaben(client, "other.gguf")["schritte"] == 20


# --- draw_image ------------------------------------------------------------------


_FLUX = {
    "breite": 1024, "hoehe": 1024, "schritte": 20, "cfg": 1.0, "guidance": 3.5,
    "sampler": "euler", "scheduler": "", "family": "flux",
    "standalone": True, "parts": {"t5xxl": "t5.gguf", "clip_l": "clip.safetensors"},
}


def _draw(tmp_path, monkeypatch, vorgaben, chat_id=None):
    service = Bilddienst(modelle=["flux.gguf"], vorgaben=vorgaben)
    monkeypatch.setattr(bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: service)
    asyncio.run(
        bild_werkzeug.ausfuehren(
            {"prompt": "a dog"}, "http://x", tmp_path, "testschluessel", chat_id=chat_id,
        )
    )
    return service.gezeichnet[-1]


def test_a_run_without_a_chat_draws_with_the_model_s_own_values(tmp_path, monkeypatch):
    vorgaben = {**_FLUX, "schritte": 6, "cfg": 2.0, "vae": "ae.safetensors", "clip_skip": 2,
                "eigene": ["schritte", "cfg", "vae", "clip_skip"]}
    body = _draw(tmp_path, monkeypatch, vorgaben)
    assert (body["schritte"], body["cfg"], body["guidance"]) == (6, 2.0, 3.5)
    assert body["clip_skip"] == 2
    # The model's VAE is part of its kit: the draw route adds it.
    assert "vae" not in body


def test_a_model_without_values_of_its_own_draws_at_its_family(tmp_path, monkeypatch):
    body = _draw(tmp_path, monkeypatch, _FLUX)
    assert (body["schritte"], body["cfg"]) == (20, 1.0)
    assert "vae" not in body
    assert "clip_skip" not in body


# --- The switch for reading the family --------------------------------------------


def _parts_folder(picture_folder: Path) -> Path:
    """An LLM, a tokenizer and a VAE beside the model, as a kit's parts lie."""
    encoders = picture_folder / "text_encoders"
    encoders.mkdir()
    (encoders / "llm.gguf").write_bytes(b"x")
    (encoders / "tokenizer.json").write_bytes(b"{}")
    (picture_folder / "vae").mkdir()
    (picture_folder / "vae" / "ae.safetensors").write_bytes(b"x")
    return encoders


_GIVEN = {"llm": "llm.gguf", "tokenizer": "tokenizer.json", "vae": "ae.safetensors"}


@pytest.fixture
def command_of_a_drawing(client: TestClient, monkeypatch):
    """POST /bild for the model; returns the answer and the sd-cli command
    the picture would have been drawn with."""
    monkeypatch.setattr(
        bildrunner.Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli"))
    )
    monkeypatch.setattr(bildrunner.shutil, "which", lambda _: "/fake/sd-cli")
    caught: dict = {}

    def _erzeugen(self, auftrag, ziel):
        caught["command"] = self.befehl(auftrag, ziel)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG")
        return ziel

    monkeypatch.setattr(bildrunner.Bildrunner, "erzeugen", _erzeugen)

    def _send(**fields):
        caught.clear()
        answer = client.post(
            "/api/v1/bild", json={"prompt": "x", "modell": "flux.gguf", **fields},
            headers={"Accept-Language": "en"},
        )
        return answer, caught.get("command")

    return _send


def test_the_check_keeps_the_switch_as_a_switch_and_nothing_else():
    sauber = bildmodellwerte.pruefen({
        "a.gguf": {"family_detection": False}, "b.gguf": {"family_detection": True},
        "c.gguf": {"family_detection": 0}, "d.gguf": {"family_detection": "off"},
    })
    assert sauber == {
        "a.gguf": {"family_detection": False}, "b.gguf": {"family_detection": True},
        "c.gguf": {"family_detection": None}, "d.gguf": {"family_detection": None},
    }


def test_a_model_without_an_entry_has_its_family_read(client: TestClient, picture_folder: Path):
    v = _vorgaben(client)
    assert (v["family_detection"], v["family"]) == (True, "flux")


def test_the_switch_is_kept_for_the_one_model(client: TestClient, picture_folder: Path):
    _gguf(picture_folder / "other.gguf", "flux", _HEADERS["flux"])
    _setzen(client, {"flux.gguf": {"family_detection": False}})
    v = _vorgaben(client)
    assert (v["family_detection"], v["family"]) == (False, "")
    # A switch, not one of the model's values.
    assert v["eigene"] == []
    other = _vorgaben(client, "other.gguf")
    assert (other["family_detection"], other["family"]) == (True, "flux")
    listed = client.get("/api/v1/bild/modelle").json()["families"]
    assert listed == {"flux.gguf": "", "other.gguf": "flux"}


def test_the_switch_stays_when_another_value_of_the_model_changes(
    client: TestClient, picture_folder: Path
):
    _setzen(client, {"flux.gguf": {"family_detection": False}})
    _setzen(client, {"flux.gguf": {"schritte": 6}})
    v = _vorgaben(client)
    assert (v["family_detection"], v["schritte"], v["eigene"]) == (False, 6, ["schritte"])


def test_switched_on_again_the_family_is_read_again(client: TestClient, picture_folder: Path):
    _setzen(client, {"flux.gguf": {"family_detection": False, "schritte": 6}})
    _setzen(client, {"flux.gguf": {"family_detection": None}})
    v = _vorgaben(client)
    assert (v["family_detection"], v["family"], v["schritte"]) == (True, "flux", 6)


def test_reset_switches_the_reading_on_again(client: TestClient, picture_folder: Path):
    _setzen(client, {"flux.gguf": {"family_detection": False}})
    _setzen(client, {"flux.gguf": None})
    assert _vorgaben(client)["family_detection"] is True


def test_without_the_reading_the_model_s_values_stand_at_no_family(
    client: TestClient, picture_folder: Path
):
    """No family, so none of its start values: they stand where a model
    without a family stands, until the user sets them."""
    _setzen(client, {"flux.gguf": {"family_detection": False}})
    v = _vorgaben(client)
    nothing = _vorgaben(client, "")
    for name in ("breite", "hoehe", "schritte", "cfg", "guidance", "sampler", "scheduler"):
        assert v[name] == nothing[name], name
    assert v["sources"]["cfg"] != "model"


def test_without_the_reading_exactly_the_given_parts_are_the_kit(
    client: TestClient, picture_folder: Path
):
    """Every part can be given, the tokenizer among them, which a Flux kit
    does not read; the folder offers none by itself."""
    _parts_folder(picture_folder)
    _setzen(client, {"flux.gguf": {"family_detection": False}})
    assert _vorgaben(client)["parts"] == {}
    _setzen(client, {"flux.gguf": _GIVEN})
    assert _vorgaben(client)["parts"] == _GIVEN


def test_with_the_reading_a_part_the_family_does_not_read_is_no_part(
    client: TestClient, picture_folder: Path
):
    """The silence probe: read as Flux, the model's kit knows neither an LLM
    nor a tokenizer, whatever was given to it."""
    _parts_folder(picture_folder)
    _setzen(client, {"flux.gguf": _GIVEN})
    assert _vorgaben(client)["parts"] == {"vae": "ae.safetensors"}


def test_the_check_keeps_a_chosen_diffusion_model_as_a_file_name():
    sauber = bildmodellwerte.pruefen({
        "a.gguf": {"diffusion_model": "b.gguf"}, "c.gguf": {"diffusion_model": "../b.gguf"},
    })
    assert sauber == {"a.gguf": {"diffusion_model": "b.gguf"}, "c.gguf": {"diffusion_model": None}}


def test_the_chosen_diffusion_model_is_told_only_while_the_family_is_not_read(
    client: TestClient, picture_folder: Path
):
    _setzen(client, {"flux.gguf": {"family_detection": False}})
    assert _vorgaben(client)["diffusion_model"] == ""
    _setzen(client, {"flux.gguf": {"diffusion_model": "flux.gguf"}})
    assert _vorgaben(client)["diffusion_model"] == "flux.gguf"
    # A file that left the folder is no choice any more.
    _setzen(client, {"flux.gguf": {"diffusion_model": "gone.gguf"}})
    assert _vorgaben(client)["diffusion_model"] == ""
    # The silence probe: read again, the model is its family's kit as before.
    _setzen(client, {"flux.gguf": {"diffusion_model": "flux.gguf", "family_detection": None}})
    v = _vorgaben(client)
    assert (v["diffusion_model"], v["family"], v["standalone"]) == ("", "flux", True)


def test_a_drawing_without_the_reading_sends_exactly_the_given_parts(
    client: TestClient, picture_folder: Path, command_of_a_drawing
):
    """No diffusion model chosen: the model's own file goes as ``-m``."""
    encoders = _parts_folder(picture_folder)
    _setzen(client, {"flux.gguf": {"family_detection": False, **_GIVEN}})
    answer, command = command_of_a_drawing()
    assert answer.status_code == 201, answer.text
    assert "--diffusion-model" not in command
    at = command.index
    assert command[at("-m") + 1] == str(picture_folder / "flux.gguf")
    assert command[at("--llm") + 1] == str(encoders / "llm.gguf")
    assert command[at("--tokenizer") + 1] == str(encoders / "tokenizer.json")
    assert command[at("--vae") + 1] == str(picture_folder / "vae" / "ae.safetensors")
    # Nothing that was not given: no encoder of the family the header names.
    assert not {"--t5xxl", "--clip_l", "--clip_g", "--llm_vision"} & set(command)


def test_a_drawing_without_the_reading_and_without_parts_is_not_refused(
    client: TestClient, picture_folder: Path, command_of_a_drawing
):
    """Every field may stay empty: the model alone is sent, and no part is
    asked for."""
    _setzen(client, {"flux.gguf": {"family_detection": False}})
    answer, command = command_of_a_drawing()
    assert answer.status_code == 201, answer.text
    assert command[command.index("-m") + 1] == str(picture_folder / "flux.gguf")
    assert not {
        "--diffusion-model", "--t5xxl", "--clip_l", "--llm", "--tokenizer", "--vae",
    } & set(command)


def test_a_drawing_without_the_reading_takes_the_chosen_diffusion_model(
    client: TestClient, picture_folder: Path, command_of_a_drawing
):
    """A diffusion model chosen: it goes as ``--diffusion-model`` with the
    given parts, and the model's own file is not sent as ``-m``."""
    encoders = _parts_folder(picture_folder)
    _gguf(picture_folder / "other.gguf", "flux", _HEADERS["flux"])
    _setzen(client, {"flux.gguf": {
        "family_detection": False, "diffusion_model": "other.gguf", **_GIVEN,
    }})
    answer, command = command_of_a_drawing()
    assert answer.status_code == 201, answer.text
    assert "-m" not in command
    at = command.index
    assert command[at("--diffusion-model") + 1] == str(picture_folder / "other.gguf")
    assert command[at("--llm") + 1] == str(encoders / "llm.gguf")
    assert command[at("--tokenizer") + 1] == str(encoders / "tokenizer.json")
    assert command[at("--vae") + 1] == str(picture_folder / "vae" / "ae.safetensors")


def test_a_drawing_with_the_reading_still_refuses_half_a_kit(
    client: TestClient, picture_folder: Path, command_of_a_drawing
):
    """The silence probe: the same model, read as Flux, does not draw
    without its text encoders, and the answer names the missing part."""
    _parts_folder(picture_folder)
    _setzen(client, {"flux.gguf": _GIVEN})
    answer, command = command_of_a_drawing()
    assert answer.status_code == 412, answer.text
    assert "T5" in answer.json()["detail"]
    assert command is None


def test_the_server_started_by_hand_takes_the_same_free_kit(
    client: TestClient, picture_folder: Path, monkeypatch
):
    """The picture server started at the tile is given what a drawing is
    given: the model with exactly the given parts, as ``-m`` without a
    chosen diffusion model and as ``--diffusion-model`` with one."""
    from tests.test_bildturbo import _LebtImmer

    encoders = _parts_folder(picture_folder)
    _setzen(client, {"flux.gguf": {"family_detection": False, **_GIVEN}})
    turbo = client.app.state.bildturbo
    monkeypatch.setattr(type(turbo), "programm", property(lambda self: Path("/fake/sd-server")))
    caught: list[list[str]] = []

    def _popen(command, **kwargs):
        caught.append(command)
        return _LebtImmer()

    monkeypatch.setattr("subprocess.Popen", _popen)

    def start() -> list[str]:
        try:
            answer = client.post(
                "/api/v1/bild/turbo/start", json={"modell": "flux.gguf"},
                headers={"Accept-Language": "en"},
            )
        finally:
            turbo._prozess = None
        assert answer.status_code == 200, answer.text
        return caught[-1]

    command = start()
    assert "--diffusion-model" not in command
    at = command.index
    assert command[at("-m") + 1] == str(picture_folder / "flux.gguf")
    assert command[at("--llm") + 1] == str(encoders / "llm.gguf")
    assert command[at("--tokenizer") + 1] == str(encoders / "tokenizer.json")
    assert command[at("--vae") + 1] == str(picture_folder / "vae" / "ae.safetensors")
    assert not {"--t5xxl", "--clip_l"} & set(command)

    _setzen(client, {"flux.gguf": {"diffusion_model": "flux.gguf"}})
    command = start()
    assert "-m" not in command
    at = command.index
    assert command[at("--diffusion-model") + 1] == str(picture_folder / "flux.gguf")
    assert command[at("--tokenizer") + 1] == str(encoders / "tokenizer.json")


def test_the_free_word_cannot_be_said_by_a_request(
    client: TestClient, picture_folder: Path, command_of_a_drawing
):
    """The silence probe: the word the service puts in for "no family" is no
    family a request may name."""
    answer, command = command_of_a_drawing(familie=bildbausatz.FREE)
    assert answer.status_code == 400, answer.text
    assert command is None


def test_the_drawing_tool_draws_such_a_model_with_the_parts_the_window_draws_it_with(
    client: TestClient, picture_folder: Path, command_of_a_drawing, tmp_path, monkeypatch
):
    """What the tool sends for the model, put to the picture route, is drawn
    with the very kit a request of the picture window is drawn with."""
    _parts_folder(picture_folder)
    _setzen(client, {"flux.gguf": {"family_detection": False, **_GIVEN}})
    body = _draw(tmp_path, monkeypatch, _vorgaben(client))
    assert "familie" not in body and "tokenizer" not in body

    def kit(command: list[str]) -> dict[str, str]:
        switches = ("--diffusion-model", "-m", "--t5xxl", "--clip_l", "--llm", "--tokenizer", "--vae")
        return {name: command[command.index(name) + 1] for name in switches if name in command}

    answer, from_the_tool = command_of_a_drawing(**body)
    assert answer.status_code == 201, answer.text
    answer, from_the_window = command_of_a_drawing()
    assert answer.status_code == 201, answer.text
    assert kit(from_the_tool) == kit(from_the_window)
    assert set(kit(from_the_tool)) == {"-m", "--llm", "--tokenizer", "--vae"}
