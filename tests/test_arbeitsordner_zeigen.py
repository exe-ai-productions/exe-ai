"""Showing a working folder in the file manager.

The route exists to be refused: what matters is not that it opens a folder
but that it opens no other one. A path the chat never shared is turned down
even when it exists, and the opening itself is only reached after that
check — which is why it is patched away here.
"""

from __future__ import annotations

from pathlib import Path

from app import dokumentablage, sprachwahl
from app.i18n import t


def _real_opener(monkeypatch) -> list[list[str]]:
    """The real opener, with only the file manager it would start left out —
    so what it creates on the disk is what a test measures."""
    started: list[list[str]] = []
    monkeypatch.setattr("app.ordner_oeffnen._befehl", lambda: ["open"])
    monkeypatch.setattr(
        "app.ordner_oeffnen.subprocess.Popen", lambda command, **_: started.append(command)
    )
    return started


def test_ein_freigegebener_ordner_wird_geoeffnet(client, chat_id, tmp_path, monkeypatch):
    geoeffnet: list[Path] = []
    monkeypatch.setattr(
        "app.api.v1.arbeitsordner.ordner_oeffnen", lambda pfad: geoeffnet.append(pfad)
    )
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(tmp_path)]})

    antwort = client.post(
        "/api/v1/ordner/oeffnen",
        json={"chat_id": chat_id, "pfad": str(tmp_path.resolve())},
    )
    assert antwort.status_code == 200
    assert geoeffnet == [tmp_path.resolve()]


def test_ein_fremder_ordner_wird_abgewiesen(client, chat_id, tmp_path, monkeypatch):
    geoeffnet: list[Path] = []
    monkeypatch.setattr(
        "app.api.v1.arbeitsordner.ordner_oeffnen", lambda pfad: geoeffnet.append(pfad)
    )
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(tmp_path)]})

    antwort = client.post(
        "/api/v1/ordner/oeffnen", json={"chat_id": chat_id, "pfad": "/etc"}
    )
    assert antwort.status_code == 403
    assert geoeffnet == []


def test_ohne_chat_gibt_es_nichts_zu_zeigen(client, tmp_path):
    antwort = client.post(
        "/api/v1/ordner/oeffnen", json={"chat_id": "gibtsnicht", "pfad": str(tmp_path)}
    )
    assert antwort.status_code == 404


def test_no_path_opens_the_chats_own_folder(client, chat_id, monkeypatch):
    """No path names the chat's own folder: built by the service from the
    chat's id and the data folder, never taken from the request."""
    opened: list[Path] = []
    monkeypatch.setattr(
        "app.api.v1.arbeitsordner.ordner_oeffnen", lambda path: opened.append(path)
    )
    own = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)

    response = client.post("/api/v1/ordner/oeffnen", json={"chat_id": chat_id})
    assert response.status_code == 200
    assert opened == [own]


def test_own_folder_is_created_when_opened(client, chat_id, monkeypatch):
    """A chat that never needed its folder has none yet; opening it makes it
    first, so the file manager shows a folder and not an error."""
    started = _real_opener(monkeypatch)
    own = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    assert own is not None and not own.exists()

    response = client.post("/api/v1/ordner/oeffnen", json={"chat_id": chat_id})
    assert response.status_code == 200
    assert own.is_dir()
    assert started == [["open", str(own)]]


def test_another_chats_own_folder_stays_refused(client, chat_id, monkeypatch):
    """Another chat's own folder, named as a path, is still not one this chat
    shared — refused like any other folder."""
    opened: list[Path] = []
    monkeypatch.setattr(
        "app.api.v1.arbeitsordner.ordner_oeffnen", lambda path: opened.append(path)
    )
    other = client.post("/api/v1/chats", json={"title": "other"}).json()["id"]
    foreign = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, other)
    assert foreign is not None
    foreign.mkdir(parents=True, exist_ok=True)

    response = client.post(
        "/api/v1/ordner/oeffnen", json={"chat_id": chat_id, "pfad": str(foreign)}
    )
    assert response.status_code == 403
    assert opened == []


def test_no_path_and_no_chat_shows_nothing(client):
    response = client.post("/api/v1/ordner/oeffnen", json={"chat_id": "missing"})
    assert response.status_code == 404


def test_chat_with_a_share_still_opens_and_creates_its_own_folder(
    client, chat_id, tmp_path, monkeypatch
):
    """Sharing folders of the user's takes nothing away: the chat's own
    folder is opened all the same, and made first when it is missing."""
    started = _real_opener(monkeypatch)
    client.patch(f"/api/v1/chats/{chat_id}", json={"working_dirs": [str(tmp_path)]})
    own = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    assert own is not None and not own.exists()

    response = client.post("/api/v1/ordner/oeffnen", json={"chat_id": chat_id})
    assert response.status_code == 200
    assert own.is_dir()
    assert started == [["open", str(own)]]


def test_folder_that_cannot_be_made_gives_the_usual_message(client, chat_id, monkeypatch):
    """A file where the chats' folders should lie: the folder cannot be made,
    and the answer is the one a system without a file manager gets."""
    started = _real_opener(monkeypatch)
    data_dir = client.app.state.config.datenverzeichnis
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / dokumentablage.CHATDATEIEN).write_text("not a folder", encoding="utf-8")

    response = client.post(
        "/api/v1/ordner/oeffnen",
        json={"chat_id": chat_id},
        headers={sprachwahl.HEADER_UI: "en"},
    )
    assert response.status_code == 501
    assert response.json()["detail"] == t("fehler.ordner_oeffnen", "en")
    assert started == []


def test_without_a_file_manager_no_empty_folder_is_left(client, chat_id, monkeypatch):
    """A system that cannot show a folder is told so before anything is made:
    no empty own folder stays behind."""
    monkeypatch.setattr("app.ordner_oeffnen._befehl", lambda: None)
    own = dokumentablage.chatordner(client.app.state.config.datenverzeichnis, chat_id)
    assert own is not None

    response = client.post("/api/v1/ordner/oeffnen", json={"chat_id": chat_id})
    assert response.status_code == 501
    assert not own.exists()
