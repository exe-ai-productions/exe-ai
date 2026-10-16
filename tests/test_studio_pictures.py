"""The pictures the picture studio drew.

The studio belongs to no chat: its draw names none, writes into none, and the
finished picture goes on the studio's own list (``app/studio_pictures.py``),
which the row of pictures reads (``GET /bilder?studio=true``). A picture that
a chat, a job or a script draws is on no such list. The painter is the only
stand-in; everything between the request and it is the code that runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import studio_pictures
from app.bildrunner import BildFehler, Bildrunner
from app.config import Config


@pytest.fixture
def painter(config: Config, client: TestClient, monkeypatch, tmp_path: Path):
    """A model in the folder and a painter that writes a different file per
    picture and keeps the jobs it was given."""
    config.app.bildmodelle_verzeichnis = str(tmp_path / "bildmodelle")
    ordner = tmp_path / "bildmodelle"
    ordner.mkdir(parents=True)
    (ordner / "base.safetensors").write_bytes(b"x")
    monkeypatch.setattr(Bildrunner, "programm", property(lambda self: Path("/fake/sd-cli")))
    jobs: list = []

    def draw(self, auftrag, ziel):
        jobs.append(auftrag)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(b"PNG" + str(len(jobs)).encode() + b"x" * 8)
        return ziel

    monkeypatch.setattr(Bildrunner, "erzeugen", draw)
    return jobs


def _draw(client: TestClient, **fields):
    return client.post(
        "/api/v1/bild", json={"prompt": "a lighthouse", "modell": "base.safetensors", **fields},
    )


def _studio(client: TestClient) -> list[str]:
    answer = client.get("/api/v1/bilder", params={"studio": "true"})
    assert answer.status_code == 200, answer.text
    return answer.json()["bilder"]


def test_a_studio_draw_names_no_chat_and_lands_on_the_studios_list(
    painter, client: TestClient,
):
    chats_before = client.get("/api/v1/chats").json()
    answer = _draw(client, studio=True)
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert body["frage_id"] is None and body["antwort_id"] is None
    assert _studio(client) == [body["bild"]]
    # No chat was made and none was written into.
    assert client.get("/api/v1/chats").json() == chats_before


def test_the_newest_picture_of_the_studio_stands_first(painter, client: TestClient):
    names = [_draw(client, studio=True).json()["bild"] for _ in range(3)]
    assert len(set(names)) == 3
    assert _studio(client) == list(reversed(names))


def test_a_picture_drawn_again_is_listed_once_at_the_front(painter, client: TestClient):
    first = _draw(client, studio=True).json()["bild"]
    second = _draw(client, studio=True).json()["bild"]
    # The same file as the first: the painter is told to write the same bytes.
    repositories = client.app.state.repositories
    studio_pictures.add(repositories, first)
    assert _studio(client) == [first, second]


def test_a_draw_that_says_nothing_of_the_studio_is_on_no_list(painter, client: TestClient):
    """Silence: a script's picture, a chat tool's or a job's — the same
    route without the studio's mark — stays out of the studio's row, but is
    among every picture in the folder."""
    chat = client.post("/api/v1/chats", json={"title": "Chat"}).json()["id"]
    plain = _draw(client).json()["bild"]
    in_chat = _draw(client, chat_id=chat).json()["bild"]
    studio = _draw(client, studio=True).json()["bild"]
    assert _studio(client) == [studio]
    everything = client.get("/api/v1/bilder").json()["bilder"]
    assert {plain, in_chat, studio} <= set(everything)
    # The chat's own list is still the chat's.
    assert client.get("/api/v1/bilder", params={"chat": chat}).json()["bilder"] == [in_chat]


def test_a_picture_that_left_the_folder_leaves_the_row_not_the_list(
    painter, client: TestClient, config: Config,
):
    from app.speicherorte import ort

    kept, gone = (_draw(client, studio=True).json()["bild"] for _ in range(2))
    (ort(config, "images") / gone).unlink()
    assert _studio(client) == [kept]
    # Nothing here deleted the name: the file may come back.
    assert studio_pictures.names(client.app.state.repositories) == [gone, kept]


def test_a_stored_list_that_is_none_holds_nothing(client: TestClient):
    repositories = client.app.state.repositories
    from app.db.repositories.einstellungen import GLOBAL

    for broken in ("x", 5, {"a": 1}, ["../x.png", 3, "0" * 32 + ".png"]):
        repositories.einstellungen.setzen(GLOBAL, studio_pictures.KEY, broken)
        assert studio_pictures.names(repositories) == (
            ["0" * 32 + ".png"] if isinstance(broken, list) else []
        )
    assert _studio(client) == []


def test_a_failed_studio_draw_is_not_listed(painter, client: TestClient, monkeypatch):
    def broken(self, auftrag, ziel):
        raise BildFehler("bild.abgebrochen")

    monkeypatch.setattr(Bildrunner, "erzeugen", broken)
    answer = _draw(client, studio=True)
    assert answer.status_code >= 400
    assert _studio(client) == []


def _runs(client: TestClient, scope: str) -> list[dict]:
    answer = client.get(f"/api/v1/laeufe/{scope}")
    assert answer.status_code == 200, answer.text
    return answer.json()["laeufe"]


def test_a_studio_draw_leaves_its_run_under_the_studios_own_list(painter, client: TestClient):
    """The terminal shows the studio's work although no chat is open: the run
    of a picture that names no chat is filed under the studio's key, ends as
    finished, and carries the dials it was made with."""
    before = _runs(client, "studio")
    assert _draw(client, studio=True, prompt="a harbour").status_code == 201
    runs = _runs(client, "studio")
    assert len(runs) == len(before) + 1
    run = runs[-1]
    assert run["art"] == "bild" and run["zustand"] == "fertig"
    assert run["befehl"] == "a harbour"
    assert run["regler"]["modell"] == "base.safetensors"


def test_a_draw_that_is_not_the_studios_leaves_no_run_under_its_key(
    painter, client: TestClient,
):
    """Silence: a script's draw (no chat, no studio) opens no run anywhere,
    and a chat's draw is filed under the chat — not under the studio."""
    chat = client.post("/api/v1/chats", json={"title": "Chat"}).json()["id"]
    before = len(_runs(client, "studio"))
    assert _draw(client).status_code == 201
    assert _draw(client, chat_id=chat).status_code == 201
    assert len(_runs(client, "studio")) == before
    assert len(_runs(client, chat)) == 1
