"""The Turbo model of Qwen-Image 2.1 is drawn with the noise schedule its docs
give it.

The schedule is a start value of the model's variant, as the numbers both
programs take (the picture server takes only numbers), and it travels the way
every other start value does: the table the window reads, the answer of the
start values, the body of the picture server, the line of sd-cli, and the
drawing tool. Every other family and variant starts without one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import image_families
from app.api.v1 import bild as bildapi
from app.bildrunner import Auftrag, Bildrunner
from app.config import Config
from tests.test_bild_werkzeug import _zeichnen_mit_dienst

SIGMAS = "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0"
NUMBERS = [1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0]
TURBO_FILE = "Qwen-Image-2.1-Turbo-Q4_K_M.gguf"
BASE_FILE = "Qwen-Image-2.1-Q4_K_M.gguf"


def test_the_turbo_model_starts_with_the_schedule_of_its_docs():
    start = image_families.start_values("qwen_image_2_1", TURBO_FILE)
    assert start.sigmas == SIGMAS
    assert [float(number) for number in start.sigmas.split(",")] == NUMBERS
    assert len(NUMBERS) == 9 and NUMBERS[-1] == 0.0
    assert (start.steps, start.cfg, start.sampler) == (8, 1.0, "euler")
    assert "docs/qwen_image_2.1.md" in start.sources["sigmas"]
    assert start.sources["sigmas"] == start.sources["steps"] == start.sources["cfg"]


def test_the_base_model_and_every_other_start_carries_none():
    assert image_families.start_values("qwen_image_2_1", BASE_FILE).sigmas == ""
    assert image_families.start_values("qwen_image_2_1").sigmas == ""
    assert image_families.start_values(None).sigmas == ""
    carrying = []
    for family in image_families.FAMILIES:
        if family.start.sigmas:
            carrying.append((family.name, ""))
        for pattern, values in image_families._VARIANT_STARTS[family.name]:
            if values.sigmas:
                carrying.append((family.name, pattern))
    assert carrying == [("qwen_image_2_1", r"(?<![a-z])turbo(?![a-z])")]


def test_the_table_as_the_window_reads_it_carries_the_schedule():
    shown = {row["name"]: row["start"]["sigmas"] for row in image_families.as_json()}
    # The family's own start has none: the schedule belongs to the Turbo model.
    assert shown["qwen_image_2_1"] == "" and set(shown.values()) == {""}


# --- The start values of a model ---


@pytest.fixture
def served(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    folder = tmp_path / "bildmodelle"
    folder.mkdir()
    for name in (TURBO_FILE, BASE_FILE):
        (folder / name).write_bytes(b"x")
    monkeypatch.setattr(bildapi.bildinhalt, "family", lambda path: "qwen_image_2_1")
    return client


def test_the_start_values_of_the_turbo_model_carry_the_schedule(served: TestClient):
    turbo = served.get("/api/v1/bild/vorgaben", params={"modell": TURBO_FILE}).json()
    assert turbo["sigmas"] == SIGMAS
    assert (turbo["schritte"], turbo["cfg"], turbo["sampler"]) == (8, 1.0, "euler")
    assert "docs/qwen_image_2.1.md" in turbo["sources"]["sigmas"]


def test_silence_the_base_model_and_a_model_without_a_family_start_without_one(served: TestClient):
    base = served.get("/api/v1/bild/vorgaben", params={"modell": BASE_FILE}).json()
    assert base["sigmas"] == ""
    assert served.get("/api/v1/bild/vorgaben").json()["sigmas"] == ""


# --- A family said by hand brings the model's variant with it ---


@pytest.fixture
def headerless(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """The same two files, read as models whose header names no family."""
    folder = tmp_path / "bildmodelle"
    folder.mkdir()
    for name in (TURBO_FILE, BASE_FILE):
        (folder / name).write_bytes(b"x")
    monkeypatch.setattr(bildapi.bildinhalt, "family", lambda path: None)
    return client


def _preset(client: TestClient, model: str, **query) -> dict:
    answer = client.get("/api/v1/bild/vorgaben", params={"modell": model, **query})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_the_turbo_file_with_a_family_said_by_hand_starts_at_the_turbo_values(headerless):
    asked = _preset(headerless, TURBO_FILE, chosen_family="qwen_image_2_1")
    assert asked["sigmas"] == SIGMAS
    assert (asked["schritte"], asked["cfg"], asked["sampler"]) == (8, 1.0, "euler")
    assert "docs/qwen_image_2.1.md" in asked["sources"]["sigmas"]
    # Said by hand only decides the start values: the family field, the kit
    # and its parts stay what the header says.
    assert asked["family"] == "" and asked["parts"] == {}


def test_silence_a_file_without_a_variant_word_starts_at_the_family_without_a_schedule(headerless):
    asked = _preset(headerless, BASE_FILE, chosen_family="qwen_image_2_1")
    assert asked["sigmas"] == "" and asked["schritte"] == 20
    assert asked["family"] == ""


def test_silence_without_a_family_said_by_hand_the_answer_is_what_it_was(headerless):
    asked = _preset(headerless, TURBO_FILE)
    assert asked["sigmas"] == "" and asked["family"] == ""
    assert _preset(headerless, TURBO_FILE, chosen_family="") == asked


def test_a_family_nobody_knows_is_refused(headerless):
    answer = headerless.get(
        "/api/v1/bild/vorgaben", params={"modell": TURBO_FILE, "chosen_family": "no_such_family"},
    )
    assert answer.status_code == 400


def test_the_own_values_of_the_model_lie_over_a_family_said_by_hand(headerless):
    answer = headerless.patch(
        "/api/v1/settings/global/bildmodellwerte", json={"wert": {TURBO_FILE: {"schritte": 6}}},
    )
    assert answer.status_code == 200, answer.text
    asked = _preset(headerless, TURBO_FILE, chosen_family="qwen_image_2_1")
    assert asked["schritte"] == 6 and "schritte" in asked["eigene"]
    # What the model does not set stays the variant's.
    assert asked["sigmas"] == SIGMAS and asked["cfg"] == 1.0


# --- The two programs take it the same ---


def test_the_picture_server_takes_the_schedule_as_nine_numbers():
    job = Auftrag(modell=Path("/m"), prompt="x", sigmas=SIGMAS)
    assert bildapi._cli_only_reason(job, False) is None
    assert bildapi._turbo_auftrag(job)["sample_params"]["custom_sigmas"] == NUMBERS


def test_sd_cli_takes_the_same_numbers(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.bildrunner.shutil.which", lambda _: "/somewhere/sd-cli")
    line = Bildrunner(tmp_path).befehl(
        Auftrag(modell=tmp_path / "m.gguf", prompt="x", sigmas=SIGMAS), tmp_path / "a.png"
    )
    assert line[line.index("--sigmas") + 1] == SIGMAS


def test_silence_a_picture_without_a_schedule_sends_none_and_a_hand_value_goes_out(
    tmp_path: Path, monkeypatch,
):
    monkeypatch.setattr("app.bildrunner.shutil.which", lambda _: "/somewhere/sd-cli")
    plain = Auftrag(modell=tmp_path / "m.gguf", prompt="x")
    assert "--sigmas" not in Bildrunner(tmp_path).befehl(plain, tmp_path / "a.png")
    assert "custom_sigmas" not in bildapi._turbo_auftrag(plain)["sample_params"]
    by_hand = Auftrag(modell=tmp_path / "m.gguf", prompt="x", sigmas="1.0,0.5,0.0")
    assert bildapi._turbo_auftrag(by_hand)["sample_params"]["custom_sigmas"] == [1.0, 0.5, 0.0]
    line = Bildrunner(tmp_path).befehl(by_hand, tmp_path / "a.png")
    assert line[line.index("--sigmas") + 1] == "1.0,0.5,0.0"


# --- The drawing tool starts where the model starts ---


def test_the_drawing_tool_draws_the_turbo_model_with_its_schedule(tmp_path, monkeypatch):
    vorgaben = {"family": "qwen_image_2_1", "standalone": False, "parts": {}}
    drawn = {}
    for name in (TURBO_FILE, BASE_FILE):
        service, _ = _zeichnen_mit_dienst(
            tmp_path, monkeypatch, "c1", standardmodell=name, modelle=[TURBO_FILE, BASE_FILE],
            familien={TURBO_FILE: "qwen_image_2_1", BASE_FILE: "qwen_image_2_1"}, vorgaben=vorgaben,
        )
        drawn[name] = service.gezeichnet[0]
    assert drawn[TURBO_FILE]["sigmas"] == SIGMAS
    assert "sigmas" not in drawn[BASE_FILE]
