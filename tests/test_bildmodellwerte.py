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

from app import bildmodellwerte
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


def _draw(tmp_path, monkeypatch, vorgaben, fenster=None, chat_id=None):
    service = Bilddienst(fenster or {}, modelle=["flux.gguf"], vorgaben=vorgaben)
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


def test_the_chat_s_own_window_wins_over_the_model_s_values(tmp_path, monkeypatch):
    vorgaben = {**_FLUX, "schritte": 6, "eigene": ["schritte"]}
    body = _draw(tmp_path, monkeypatch, vorgaben,
                 fenster={"c1": {"modell": "flux.gguf", "schritte": 30}}, chat_id="c1")
    assert body["schritte"] == 30


def test_a_family_named_by_hand_starts_at_its_own_values(tmp_path, monkeypatch):
    """The model's values were set for the family its header names; a window
    that says another family draws another model, at that family's start."""
    vorgaben = {**_FLUX, "schritte": 6, "eigene": ["schritte"]}
    body = _draw(tmp_path, monkeypatch, vorgaben,
                 fenster={"c1": {"modell": "flux.gguf", "familie": "sdxl"}}, chat_id="c1")
    assert body["schritte"] != 6
