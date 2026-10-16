"""The service's own way from one sentence to a picture.

``POST /api/v1/bild/satz`` takes a sentence and a chat and draws with exactly
the values ``draw_image`` takes in that chat — they come together in one
place (``bild_werkzeug.draw_with_window``). The picture stays in the pictures
folder and the answer says where. The drawing itself is the only stand-in:
everything between the request and the painter is the code that runs.
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bildrunner import Bildrunner
from app.config import Config
from app.speicherorte import ort
from app.tools import bild_werkzeug

# What a picture is drawn with, apart from the seed (random per picture) and
# the paths.
_VALUES = (
    "breite", "hoehe", "schritte", "cfg", "sampler", "scheduler", "guidance", "negativ",
)


class _ToTheService:
    """``httpx.AsyncClient``'s shape, answered by the service under test: the
    tool calls its own service over HTTP, here through the test client."""

    def __init__(self, client: TestClient):
        self._client = client

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, params=None, **_):
        return self._client.get(url, params=params)

    async def post(self, url, json=None, **_):
        return self._client.post(url, json=json)


@pytest.fixture
def painter(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """A model in the folder and a painter that writes a file per picture and
    keeps the job it was given."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    ordner = tmp_path / "bildmodelle"
    ordner.mkdir(parents=True)
    (ordner / "base.safetensors").write_bytes(b"x")
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    jobs: list = []

    def draw(self, auftrag, ziel):
        jobs.append(auftrag)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG" + str(len(jobs)).encode())
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", draw)
    return jobs


def _default_model(client: TestClient, **values) -> None:
    """The folder's model chosen as the picture server's default, with the
    values the user set for it there."""
    from app import bildmodellwerte

    einstellungen = client.app.state.repositories.einstellungen
    einstellungen.setzen("global", "bild_standardmodell", "base.safetensors")
    if values:
        einstellungen.setzen("global", bildmodellwerte.SCHLUESSEL, {"base.safetensors": values})


def _values_of(job) -> dict:
    fields = dataclasses.asdict(job)
    return {name: fields[name] for name in _VALUES}


def test_a_sentence_draws_with_the_values_the_tool_takes(
    painter, client: TestClient, monkeypatch, chat_id, config: Config, tmp_path: Path,
):
    _default_model(client, breite=640, hoehe=384, schritte=7, cfg=3.5, sampler="euler")
    answer = client.post(
        "/api/v1/bild/satz", json={"prompt": "a lighthouse at dusk", "chat_id": chat_id},
    )
    assert answer.status_code == 201, answer.text
    assert len(painter) == 1
    from_sentence = _values_of(painter[0])
    assert from_sentence == {
        "breite": 640, "hoehe": 384, "schritte": 7, "cfg": 3.5, "sampler": "euler",
        "scheduler": "", "guidance": None, "negativ": "",
    }

    # The model's way: draw_image reads the same values.
    monkeypatch.setattr(
        bild_werkzeug.httpx, "AsyncClient", lambda timeout, headers: _ToTheService(client)
    )
    text = asyncio.run(bild_werkzeug.ausfuehren(
        {"prompt": "a lighthouse at dusk"}, "/api/v1", tmp_path / "bilder",
        client.app.state.sitzungsschluessel, chat_id=chat_id,
    ))
    assert text.startswith("The image was generated"), text
    assert len(painter) == 2
    assert _values_of(painter[1]) == from_sentence
    assert painter[0].modell == painter[1].modell


def test_the_answer_says_where_the_picture_lies_and_with_what(
    painter, client: TestClient, chat_id, config: Config,
):
    _default_model(client, schritte=7)
    answer = client.post("/api/v1/bild/satz", json={"prompt": "a harbour", "chat_id": chat_id})
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert Path(body["pfad"]) == ort(config, "images") / body["bild"]
    assert Path(body["pfad"]).is_file()
    assert body["modell"] == "base.safetensors"
    assert body["prompt"] == "a harbour"
    assert body["werte"]["schritte"] == 7
    assert "prompt" not in body["werte"] and "chat_id" not in body["werte"]
    # The picture is not written into the chat: nobody is writing an answer there.
    rows = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert rows == []


@pytest.mark.parametrize("prompt", ["", "   ", "\n\t"])
def test_a_sentence_of_nothing_is_refused_before_anything_is_drawn(
    painter, client: TestClient, chat_id, prompt,
):
    answer = client.post("/api/v1/bild/satz", json={"prompt": prompt, "chat_id": chat_id})
    assert answer.status_code == 422, answer.text
    assert painter == []


def test_a_chat_that_does_not_exist_draws_nothing(painter, client: TestClient):
    answer = client.post(
        "/api/v1/bild/satz", json={"prompt": "a harbour", "chat_id": "no-such-chat"},
    )
    assert answer.status_code == 404, answer.text
    assert painter == []


def test_without_a_model_the_sentence_says_why_and_nothing_is_drawn(
    painter, client: TestClient, chat_id,
):
    """Silence: no default model is set — the same refusal the tool gives,
    and the painter is never asked."""
    answer = client.post("/api/v1/bild/satz", json={"prompt": "a harbour", "chat_id": chat_id})
    assert answer.status_code == 409, answer.text
    assert "no default image model" in answer.json()["detail"]
    assert painter == []


def test_there_is_no_way_to_open_a_picture_beside_it(painter, client: TestClient, chat_id):
    """Silence: the answer names the file and the route is for drawing only."""
    assert client.get("/api/v1/bild/satz").status_code in (404, 405)
    paths = {getattr(route, "path", "") for route in client.app.routes}
    assert not any(path.startswith("/api/v1/bild/satz/") for path in paths)


def test_what_a_chat_stored_for_its_picture_window_is_not_read(
    painter, client: TestClient, chat_id,
):
    """The picture studio and the chats share nothing: a window an older chat
    stored — its own size and steps — does not reach a sentence drawn in that
    chat. The default model and its start values do."""
    _default_model(client)
    stored = client.put(
        f"/api/v1/settings/chat:{chat_id}/bildfenster",
        json={"wert": {"modell": "base.safetensors", "breite": 640, "hoehe": 384, "schritte": 3}},
    )
    assert stored.status_code == 200, stored.text
    answer = client.post("/api/v1/bild/satz", json={"prompt": "a harbour", "chat_id": chat_id})
    assert answer.status_code == 201, answer.text
    assert (painter[0].breite, painter[0].hoehe) == (512, 512)
