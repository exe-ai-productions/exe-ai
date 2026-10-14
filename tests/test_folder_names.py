"""Folders made under their former German names are carried over to their
English ones once, at start (app/folder_names.py)."""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import folder_names, instanzschloss
from app.config import config_laden
from app.db import Database, repositories_erstellen
from app.speicherorte import ort, ueberschreibungen


# The module's own step, kept before any test shortens it.
REAL_WAIT_STEP = folder_names.MOVE_WAIT_STEP


@pytest.fixture(autouse=True)
def _short_wait_steps(monkeypatch):
    """The wait for the lock on the move asks once a second; the tests here
    hand the lock back within fractions of one, so they ask more often."""
    monkeypatch.setattr(folder_names, "MOVE_WAIT_STEP", 0.02)


def _start(config) -> TestClient:
    from app.main import app_erstellen

    app = app_erstellen(config)
    client = TestClient(app)
    client.headers["X-Sitzungsschluessel"] = app.state.sitzungsschluessel
    return client


def test_an_old_pictures_folder_is_renamed_with_its_file(config):
    old = config.datenverzeichnis / "bilder"
    old.mkdir(parents=True)
    (old / "a.png").write_bytes(b"picture")
    with _start(config):
        pass
    assert not old.exists()
    assert (config.datenverzeichnis / "images" / "a.png").read_bytes() == b"picture"
    assert ort(config, "images") == (config.datenverzeichnis / "images").resolve()


def test_a_script_lies_in_scripts_after_the_start(config):
    old = config.datenverzeichnis / "skripte"
    old.mkdir(parents=True)
    (old / "backup.sh").write_text("echo ok\n")
    with _start(config):
        pass
    assert (config.datenverzeichnis / "scripts" / "backup.sh").read_text() == "echo ok\n"
    assert not old.exists()


def test_an_override_under_an_old_key_is_read_under_the_new_one(config, tmp_path):
    elsewhere = tmp_path / "my-pictures"
    elsewhere.mkdir()
    config.datenverzeichnis.mkdir(parents=True)
    (config.datenverzeichnis / "speicherorte.json").write_text(
        json.dumps({"bilder": str(elsewhere), "agentendock": str(tmp_path / "dock")})
    )
    folder_names.carry_over(config)
    assert ueberschreibungen(config) == {
        "images": str(elsewhere), "agent_dock": str(tmp_path / "dock"),
    }
    assert ort(config, "images") == elsewhere.resolve()


def test_a_folder_the_user_moved_elsewhere_is_left_alone(config, tmp_path):
    """Silence probe: the location points at a path of the user's, which is
    not touched. The former default beside it gets the new name, so a
    reset to the default finds what was there."""
    elsewhere = tmp_path / "my-pictures"
    (elsewhere / "bilder").mkdir(parents=True)
    old = config.datenverzeichnis / "bilder"
    old.mkdir(parents=True)
    (old / "a.png").write_bytes(b"x")
    (config.datenverzeichnis / "speicherorte.json").write_text(
        json.dumps({"bilder": str(elsewhere)})
    )
    folder_names.carry_over(config)
    assert (elsewhere / "bilder").is_dir()
    assert ort(config, "images") == elsewhere.resolve()
    assert (config.datenverzeichnis / "images" / "a.png").is_file()


def test_an_empty_field_carries_the_folder_named_after_the_old_key(config):
    """An empty field meant data_dir/<key>, and for two locations the key
    was not the folder name the config line used: einbettung, sprache."""
    config.app.einbettungsmodelle_verzeichnis = ""
    config.app.sprachmodelle_verzeichnis = ""
    (config.datenverzeichnis / "einbettung").mkdir(parents=True)
    (config.datenverzeichnis / "einbettung" / "e.gguf").write_bytes(b"e")
    (config.datenverzeichnis / "sprache").mkdir()
    folder_names.carry_over(config)
    assert (ort(config, "embedding_models") / "e.gguf").is_file()
    assert ort(config, "speech_models").is_dir()


def test_a_symlinked_old_folder_is_renamed_as_a_link(config, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    config.datenverzeichnis.mkdir(parents=True)
    (config.datenverzeichnis / "skripte").symlink_to(target)
    folder_names.carry_over(config)
    assert (config.datenverzeichnis / "scripts").resolve() == target.resolve()
    assert ort(config, "scripts").is_dir()


def test_a_config_line_on_the_old_default_gets_the_new_name(tmp_path, monkeypatch):
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "app:\n"
        '  data_dir: "./data"\n'
        "  modelle_verzeichnis: ./data/modelle  # where the models live\n"
        f"  bildmodelle_verzeichnis: {tmp_path / 'own-models'}\n",
        encoding="utf-8",
    )
    (tmp_path / "data" / "modelle").mkdir(parents=True)
    (tmp_path / "data" / "modelle" / "m.gguf").write_bytes(b"model")
    config = config_laden(config_file)
    folder_names.carry_over(config)
    text = config_file.read_text(encoding="utf-8")
    assert "  modelle_verzeichnis: ./data/models  # where the models live\n" in text
    # Silence probe: a path of the user's own stays as it was written.
    assert f"  bildmodelle_verzeichnis: {tmp_path / 'own-models'}\n" in text
    assert config.app.modelle_verzeichnis == "./data/models"
    assert (ort(config, "models") / "m.gguf").read_bytes() == b"model"
    assert not (tmp_path / "data" / "modelle").exists()
    # Read again, as on the next start: the same folder.
    assert (ort(config_laden(config_file), "models") / "m.gguf").is_file()


def test_an_absolute_config_line_on_the_old_default_is_renamed_too(tmp_path, monkeypatch):
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    data = tmp_path / "data"
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"app:\n  data_dir: {data}\n  sprachmodelle_verzeichnis: '{data / 'sprachmodelle'}'\n",
        encoding="utf-8",
    )
    (data / "sprachmodelle").mkdir(parents=True)
    config = config_laden(config_file)
    folder_names.carry_over(config)
    assert f"  sprachmodelle_verzeichnis: '{data / 'speech_models'}'\n" in config_file.read_text()
    assert (data / "speech_models").is_dir()


def test_an_uploaded_document_stays_readable(config):
    with _start(config) as client:
        repositories = client.app.state.repositories
        chat = repositories.chats.erstellen(user_id="u", title="t")
        folder = config.datenverzeichnis / "chatdateien" / chat.id
        folder.mkdir(parents=True)
        (folder / "note.txt").write_text("hello")
        document = repositories.documents.speichern(
            chat_id=chat.id, filename="note.txt", mime_type="text/plain",
            pfad=str(folder / "note.txt"),
        )
    with _start(config) as client:
        response = client.get(f"/api/v1/documents/{document.id}/file")
        assert response.status_code == 200
        assert response.content == b"hello"
        renewed = client.app.state.repositories.documents.holen(document.id)
        assert renewed.pfad == str(config.datenverzeichnis / "chat_files" / chat.id / "note.txt")
    assert not (config.datenverzeichnis / "chatdateien").exists()


def test_the_model_picture_copies_move_to_their_english_folder(config):
    """The copies folder under its former name is carried over once at
    start, with what it holds."""
    old = config.datenverzeichnis / "modellbilder"
    old.mkdir(parents=True)
    # A name that carries no copy record: the start cleanup leaves it.
    (old / "holiday.jpg").write_bytes(b"copy")
    with _start(config):
        pass
    assert not old.exists()
    assert (config.datenverzeichnis / "model-images" / "holiday.jpg").read_bytes() == b"copy"


def test_the_move_of_the_copies_folder_is_logged(config, caplog):
    old = config.datenverzeichnis / "modellbilder"
    old.mkdir(parents=True)
    with caplog.at_level(logging.INFO, logger="app.folder_names"):
        folder_names.carry_over(config)
    assert any(
        "Folder renamed" in record.getMessage() and "model-images" in record.getMessage()
        for record in caplog.records
    )


def test_a_start_without_the_old_copies_folder_makes_neither_folder(config):
    """Silence probe: nothing under the former name, nothing created."""
    with _start(config):
        pass
    assert not (config.datenverzeichnis / "modellbilder").exists()
    assert not (config.datenverzeichnis / "model-images").exists()


def test_the_companion_folders_follow_the_image_models_folder(config):
    """The image models folder here is a path of the user's own; its
    companion folders are still renamed, since the program looks for them
    there by name."""
    image_folder = ort(config, "image_models")
    (image_folder / "gesichter").mkdir(parents=True)
    (image_folder / "gesichter" / "me.jpg").write_bytes(b"face")
    (image_folder / "textversteher").mkdir()
    (image_folder / "gesichter_aufbereitet").mkdir()
    folder_names.carry_over(config)
    assert (image_folder / "faces" / "me.jpg").read_bytes() == b"face"
    assert (image_folder / "text_encoders").is_dir()
    assert (image_folder / "faces_prepared").is_dir()
    assert not (image_folder / "gesichter").exists()


def test_a_second_start_moves_nothing_and_overwrites_nothing(config):
    old = config.datenverzeichnis / "bilder"
    old.mkdir(parents=True)
    (old / "a.png").write_bytes(b"first")
    folder_names.carry_over(config)
    # A folder under the former name turning up again next to the new one
    # is neither merged nor put over it.
    old.mkdir()
    (old / "a.png").write_bytes(b"second")
    folder_names.carry_over(config)
    assert (config.datenverzeichnis / "images" / "a.png").read_bytes() == b"first"
    assert (old / "a.png").read_bytes() == b"second"


def test_document_paths_of_every_chat_move_only_where_the_file_is():
    db = Database(":memory:")
    db.schema_einrichten()
    try:
        repositories = repositories_erstellen(db)
        first = repositories.chats.erstellen(user_id="u", title="a")
        second = repositories.chats.erstellen(user_id="u", title="b")
        a = repositories.documents.speichern(chat_id=first.id, filename="a", pfad="/d/chatdateien/x/a")
        b = repositories.documents.speichern(chat_id=second.id, filename="b", pfad="/d/chatdateien/y/b")
        assert repositories.documents.all_paths_moved(
            folder_names.following([("/d/chatdateien", "/d/chat_files")])
        ) == 0
        assert repositories.documents.holen(a.id).pfad == "/d/chatdateien/x/a"
        assert repositories.documents.holen(b.id).pfad == "/d/chatdateien/y/b"
    finally:
        db.schliessen()


def _old_install(tmp_path, monkeypatch, newline="\n"):
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    lines = [
        "app:",
        '  data_dir: "./data"',
        "  modelle_verzeichnis: ./data/modelle",
        "  sprachmodelle_verzeichnis: ./data/sprachmodelle",
        "",
    ]
    config_file.write_bytes(newline.join(lines).encode())
    (tmp_path / "data" / "modelle").mkdir(parents=True)
    (tmp_path / "data" / "sprachmodelle").mkdir()
    return config_file


def test_a_config_with_windows_line_endings_is_carried_over(tmp_path, monkeypatch):
    config_file = _old_install(tmp_path, monkeypatch, newline="\r\n")
    config = config_laden(config_file)
    folder_names.carry_over(config)
    raw = config_file.read_bytes()
    assert b"  modelle_verzeichnis: ./data/models\r\n" in raw
    assert b"  sprachmodelle_verzeichnis: ./data/speech_models\r\n" in raw
    assert (tmp_path / "data" / "models").is_dir()


def test_the_backup_holds_the_file_as_it_was(tmp_path, monkeypatch):
    config_file = _old_install(tmp_path, monkeypatch)
    config = config_laden(config_file)
    before = config_file.read_text()
    folder_names.carry_over(config)
    assert config_file.with_suffix(".yaml.before-rename").read_text() == before


def test_a_blocked_folder_keeps_its_config_line(tmp_path, monkeypatch):
    """The new name is taken: the folder cannot move, so the line keeps
    naming it and the models stay where the program looks."""
    config_file = _old_install(tmp_path, monkeypatch)
    (tmp_path / "data" / "modelle" / "m.gguf").write_bytes(b"m")
    (tmp_path / "data" / "models").mkdir()
    (tmp_path / "data" / "models" / "other.gguf").write_bytes(b"o")
    config = config_laden(config_file)
    folder_names.carry_over(config)
    assert "  modelle_verzeichnis: ./data/modelle\n" in config_file.read_text()
    assert (ort(config, "models") / "m.gguf").is_file()
    # The other location of the same file moved all the same.
    assert "  sprachmodelle_verzeichnis: ./data/speech_models\n" in config_file.read_text()


def test_a_config_file_that_cannot_be_written_takes_the_folders_back(tmp_path, monkeypatch):
    config_file = _old_install(tmp_path, monkeypatch)
    config = config_laden(config_file)
    monkeypatch.setattr(folder_names.configwanderung, "values_replaced", lambda *a: set())
    folder_names.carry_over(config)
    assert (tmp_path / "data" / "modelle").is_dir()
    assert not (tmp_path / "data" / "models").exists()
    assert (ort(config, "models")) == (tmp_path / "data" / "modelle").resolve()


def test_a_folder_an_override_names_keeps_its_name(config, tmp_path):
    """Silence probe: the user pointed the models at the data folder's own
    former folder by hand. It is theirs, so it is not renamed under them."""
    data = config.datenverzeichnis
    (data / "modelle").mkdir(parents=True)
    (data / "speicherorte.json").write_text(json.dumps({"modelle": str(data / "modelle")}))
    folder_names.carry_over(config)
    assert (data / "modelle").is_dir()
    assert ort(config, "models") == (data / "modelle").resolve()


def test_a_dangling_link_is_renamed_before_anything_takes_its_new_name(config, tmp_path):
    """A link to a drive that is not mounted still counts: renamed as a
    link, so the scripts are there again once the drive is."""
    config.datenverzeichnis.mkdir(parents=True)
    (config.datenverzeichnis / "skripte").symlink_to(tmp_path / "unmounted")
    folder_names.carry_over(config)
    assert (config.datenverzeichnis / "scripts").is_symlink()
    assert not (config.datenverzeichnis / "skripte").is_symlink()


def test_a_folder_shared_from_the_chat_files_moves_along(config):
    with _start(config) as client:
        repositories = client.app.state.repositories
        chat = repositories.chats.erstellen(user_id="u", title="t")
        shared = config.datenverzeichnis / "chatdateien" / chat.id / "reports"
        shared.mkdir(parents=True)
        other = str(config.datenverzeichnis / "elsewhere")
        repositories.chats.aktualisieren(chat.id, working_dirs=[str(shared), other])
    with _start(config) as client:
        stored = client.app.state.repositories.chats.holen(chat.id).working_dirs
    assert stored == [
        str(config.datenverzeichnis / "chat_files" / chat.id / "reports"), other,
    ]


def test_a_quoted_windows_style_value_is_found_by_its_meaning(tmp_path):
    from app.configwanderung import values_replaced

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        'app:\n  bildmodelle_verzeichnis: "C:\\\\data\\\\bildmodelle"\n  x: 1\n'
    )
    assert values_replaced(
        config_file,
        [("bildmodelle_verzeichnis", "C:\\data\\bildmodelle", "C:\\data\\image_models"),
         ("missing", "a", "b")],
    ) == {"bildmodelle_verzeichnis"}
    assert '  bildmodelle_verzeichnis: "C:\\\\data\\\\image_models"\n' in config_file.read_text()


def test_an_empty_folder_under_the_new_name_does_not_block(config):
    """A start that could not rename yet made the new folder empty (the
    scripts folder is made at every start); the next start still moves the
    old one in."""
    data = config.datenverzeichnis
    (data / "skripte").mkdir(parents=True)
    (data / "skripte" / "backup.sh").write_text("x")
    (data / "scripts").mkdir()
    folder_names.carry_over(config)
    assert (data / "scripts" / "backup.sh").is_file()


def test_an_override_inside_the_old_folder_pins_it(config):
    data = config.datenverzeichnis
    (data / "bilder" / "2025").mkdir(parents=True)
    (data / "speicherorte.json").write_text(json.dumps({"bilder": str(data / "bilder" / "2025")}))
    folder_names.carry_over(config)
    assert ort(config, "images") == (data / "bilder" / "2025").resolve()
    assert ort(config, "images").is_dir()


def test_a_config_line_and_an_override_on_the_same_folder_keep_it(tmp_path, monkeypatch):
    config_file = _old_install(tmp_path, monkeypatch)
    data = tmp_path / "data"
    (data / "speicherorte.json").write_text(json.dumps({"modelle": str(data / "modelle")}))
    config = config_laden(config_file)
    folder_names.carry_over(config)
    assert ort(config, "models").is_dir()
    assert "  modelle_verzeichnis: ./data/modelle\n" in config_file.read_text()


def test_a_link_to_a_folder_of_the_users_is_not_taken_for_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    own = tmp_path / "ext" / "sprachmodelle"
    own.mkdir(parents=True)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sprachmodelle").symlink_to(own)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f'app:\n  data_dir: "./data"\n  sprachmodelle_verzeichnis: {own}\n')
    config = config_laden(config_file)
    folder_names.carry_over(config)
    assert f"  sprachmodelle_verzeichnis: {own}\n" in config_file.read_text()
    assert ort(config, "speech_models") == own.resolve()


def test_a_missing_key_written_with_the_new_default_still_moves_the_folder(tmp_path, monkeypatch):
    """The configuration's own update writes a missing key with today's
    default; the folder under the former name follows."""
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text('app:\n  data_dir: "./data"\n')
    (tmp_path / "data" / "modelle").mkdir(parents=True)
    (tmp_path / "data" / "modelle" / "m.gguf").write_bytes(b"m")
    config = config_laden(config_file)
    folder_names.carry_over(config)
    assert (ort(config, "models") / "m.gguf").is_file()


def test_a_share_of_a_renamed_folder_moves_along(config):
    data = config.datenverzeichnis
    with _start(config) as client:
        repositories = client.app.state.repositories
        chat = repositories.chats.erstellen(user_id="u", title="t")
        (data / "bilder").mkdir(parents=True)
        repositories.chats.aktualisieren(chat.id, working_dirs=[str(data / "bilder")])
    with _start(config) as client:
        stored = client.app.state.repositories.chats.holen(chat.id).working_dirs
    assert stored == [str(data / "images")]


def test_uploads_in_a_shared_renamed_folder_move_along(config):
    data = config.datenverzeichnis
    with _start(config) as client:
        repositories = client.app.state.repositories
        chat = repositories.chats.erstellen(user_id="u", title="t")
        (data / "skripte").mkdir(parents=True)
        (data / "skripte" / "report.txt").write_text("r")
        document = repositories.documents.speichern(
            chat_id=chat.id, filename="report.txt", pfad=str(data / "skripte" / "report.txt"),
        )
    with _start(config) as client:
        stored = client.app.state.repositories.documents.holen(document.id).pfad
    assert stored == str(data / "scripts" / "report.txt")


def test_while_both_names_hold_files_no_row_is_redirected(config):
    data = config.datenverzeichnis
    with _start(config) as client:
        repositories = client.app.state.repositories
        chat = repositories.chats.erstellen(user_id="u", title="t")
        for folder in ("chatdateien", "chat_files"):
            (data / folder / chat.id).mkdir(parents=True)
            (data / folder / chat.id / "report.txt").write_text(folder)
        document = repositories.documents.speichern(
            chat_id=chat.id, filename="report.txt",
            pfad=str(data / "chatdateien" / chat.id / "report.txt"),
        )
    with _start(config) as client:
        stored = client.app.state.repositories.documents.holen(document.id).pfad
    assert stored == str(data / "chatdateien" / chat.id / "report.txt")


def test_an_empty_folder_another_location_names_is_not_taken_over(config):
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    (data / "images").mkdir()
    (data / "speicherorte.json").write_text(json.dumps({"skripte": str(data / "images")}))
    folder_names.carry_over(config)
    assert (data / "bilder").is_dir()
    assert ort(config, "scripts") == (data / "images").resolve()


def test_a_folder_holding_only_viewer_files_counts_as_empty(config):
    data = config.datenverzeichnis
    (data / "skripte").mkdir(parents=True)
    (data / "skripte" / "backup.sh").write_text("x")
    (data / "scripts").mkdir()
    (data / "scripts" / ".DS_Store").write_bytes(b"d")
    folder_names.carry_over(config)
    assert (data / "scripts" / "backup.sh").is_file()


def test_viewer_files_count_in_any_capitals(config):
    """A folder holding only ``thumbs.db`` and ``Desktop.ini`` counts as
    empty like one holding ``Thumbs.db`` and ``desktop.ini``. Silence probe:
    a name that only contains one of them is another file, and the folder
    holding it is not empty."""
    data = config.datenverzeichnis
    (data / "skripte").mkdir(parents=True)
    (data / "skripte" / "backup.sh").write_text("x")
    (data / "scripts").mkdir()
    (data / "scripts" / "thumbs.db").write_bytes(b"d")
    (data / "scripts" / "Desktop.ini").write_bytes(b"d")
    folder_names.carry_over(config)
    assert (data / "scripts" / "backup.sh").is_file()
    assert not (data / "skripte").exists()

    (data / "bilder").mkdir()
    (data / "bilder" / "a.png").write_bytes(b"d")
    (data / "images").mkdir()
    (data / "images" / "Thumbs.db.txt").write_text("mine")
    folder_names.carry_over(config)
    assert (data / "images" / "Thumbs.db.txt").read_text() == "mine"
    assert (data / "bilder" / "a.png").is_file()


def test_a_broken_stored_share_does_not_stop_the_start(config):
    with _start(config) as client:
        client.app.state.repositories.db.verbindung.execute(
            "INSERT INTO chats (id, user_id, title, created_at, updated_at, working_dirs)"
            " VALUES ('c', 'u', 't', '', '', 'not json')"
        )
    (config.datenverzeichnis / "bilder").mkdir()
    with _start(config) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_an_override_holding_the_data_folder_blocks_nothing(config, tmp_path):
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    (data / "speicherorte.json").write_text(json.dumps({"skripte": str(tmp_path)}))
    folder_names.carry_over(config)
    assert (data / "images").is_dir()


def test_a_link_pointing_at_a_pinned_folder_is_still_renamed(config, tmp_path):
    home = tmp_path / "home"
    (home / "Pictures").mkdir(parents=True)
    data = config.datenverzeichnis
    data.mkdir(parents=True)
    (data / "skripte").symlink_to(home)
    (data / "speicherorte.json").write_text(json.dumps({"bilder": str(home / "Pictures")}))
    folder_names.carry_over(config)
    assert (data / "scripts").is_symlink()


def test_a_share_list_that_is_not_a_list_does_not_stop_the_start(config):
    data = config.datenverzeichnis
    with _start(config) as client:
        repositories = client.app.state.repositories
        repositories.db.verbindung.execute(
            "INSERT INTO chats (id, user_id, title, created_at, updated_at, working_dirs)"
            " VALUES ('c', 'u', 't', '', '', 'null')"
        )
        chat = repositories.chats.erstellen(user_id="u", title="t")
        (data / "bilder").mkdir()
        repositories.chats.aktualisieren(chat.id, working_dirs=[str(data / "bilder")])
    with _start(config) as client:
        stored = client.app.state.repositories.chats.holen(chat.id).working_dirs
    assert stored == [str(data / "images")]


def test_a_share_of_a_companion_folder_moves_along(config):
    image_folder = ort(config, "image_models")
    with _start(config) as client:
        repositories = client.app.state.repositories
        chat = repositories.chats.erstellen(user_id="u", title="t")
        (image_folder / "gesichter").mkdir(parents=True)
        repositories.chats.aktualisieren(chat.id, working_dirs=[str(image_folder / "gesichter")])
    with _start(config) as client:
        stored = client.app.state.repositories.chats.holen(chat.id).working_dirs
    assert stored == [str(image_folder / "faces")]


def test_the_note_goes_once_the_paths_have_followed(config):
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    with _start(config):
        pass
    assert (data / "images").is_dir()
    assert not (data / folder_names.PENDING).exists()


def test_the_shipped_relative_default_under_another_data_folder_moves(tmp_path, monkeypatch):
    """data_dir is a folder of its own, but the model folder was never
    named: the shipped ./data/modelle beside the program was in force."""
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"app:\n  data_dir: {tmp_path / 'mydata'}\n")
    (tmp_path / "data" / "modelle").mkdir(parents=True)
    (tmp_path / "data" / "modelle" / "m.gguf").write_bytes(b"m")
    config = config_laden(config_file)
    folder_names.carry_over(config)
    assert (ort(config, "models") / "m.gguf").is_file()


def test_a_line_the_file_would_not_take_leaves_its_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text('app: {data_dir: "./data", modelle_verzeichnis: ./data/modelle}\n')
    (tmp_path / "data" / "modelle").mkdir(parents=True)
    config = config_laden(config_file)
    folder_names.carry_over(config)
    assert (tmp_path / "data" / "modelle").is_dir()
    assert ort(config, "models") == (tmp_path / "data" / "modelle").resolve()


def test_a_share_below_two_renames_of_one_start_is_followed_through_both(tmp_path, monkeypatch):
    """The image models folder and a companion folder inside it are renamed
    on the same start; a share of the companion follows both."""
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    data = tmp_path / "data"
    config_file = tmp_path / "config.yaml"
    config_file.write_text(f"app:\n  data_dir: {data}\n  bildmodelle_verzeichnis: {data / 'bildmodelle'}\n")
    (data / "bildmodelle" / "gesichter").mkdir(parents=True)
    config = config_laden(config_file)
    db = Database(":memory:")
    db.schema_einrichten()
    try:
        repositories = repositories_erstellen(db)
        chat = repositories.chats.erstellen(user_id="u", title="t")
        repositories.chats.aktualisieren(
            chat.id, working_dirs=[str((data / "bildmodelle" / "gesichter").resolve())]
        )
        folder_names.carry_over(config)
        folder_names.paths_carried_over(config, repositories)
        assert repositories.chats.holen(chat.id).working_dirs == [
            str((data / "image_models" / "faces").resolve())
        ]
    finally:
        db.schliessen()


def test_paths_are_followed_when_the_data_folder_is_reached_through_a_link(config, tmp_path):
    """Stored paths are written with links followed; the data folder here is
    named through a link, and the rows still follow."""
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real)
    config.app.data_dir = str(linked / "data")
    folder = real / "data" / "chatdateien" / "c1"
    folder.mkdir(parents=True)
    (folder / "n.txt").write_text("n")
    db = Database(":memory:")
    db.schema_einrichten()
    try:
        repositories = repositories_erstellen(db)
        chat = repositories.chats.erstellen(user_id="u", title="t")
        document = repositories.documents.speichern(
            chat_id=chat.id, filename="n.txt", pfad=str(folder / "n.txt")
        )
        folder_names.carry_over(config)
        folder_names.paths_carried_over(config, repositories)
        assert repositories.documents.holen(document.id).pfad == str(
            real / "data" / "chat_files" / "c1" / "n.txt"
        )
    finally:
        db.schliessen()


def test_a_stored_path_in_other_letter_case_is_followed(tmp_path):
    # The rule is named here: the case of a stored path is compared by the
    # disk's own rule, and this test is about the comparison, not the disk.
    follow = folder_names.following(
        [(str(tmp_path / "data" / "chatdateien"), str(tmp_path / "data" / "chat_files"))],
        ignore_case=True,
    )
    assert follow(str(tmp_path / "data" / "CHATDATEIEN" / "c" / "x.pdf")) == (
        tmp_path / "data" / "chat_files" / "c" / "x.pdf"
    )
    assert follow(str(tmp_path / "data" / "chatdateien-other" / "x.pdf")) is None


def test_an_override_under_a_former_key_counts_before_it_is_rewritten(config, tmp_path):
    """The start could not rewrite the file (or another service skipped the
    rename): the user's own location still counts."""
    elsewhere = tmp_path / "pictures"
    elsewhere.mkdir()
    config.datenverzeichnis.mkdir(parents=True)
    (config.datenverzeichnis / "speicherorte.json").write_text(json.dumps({"bilder": str(elsewhere)}))
    assert ort(config, "images") == elsewhere.resolve()


def test_a_companion_folder_another_location_names_keeps_its_name(config):
    image_folder = ort(config, "image_models")
    (image_folder / "textversteher").mkdir(parents=True)
    config.app.einbettungsmodelle_verzeichnis = str(image_folder / "textversteher")
    folder_names.carry_over(config)
    assert (image_folder / "textversteher").is_dir()


def test_the_new_name_another_location_uses_is_not_taken_by_a_line(tmp_path, monkeypatch):
    config_file = _old_install(tmp_path, monkeypatch)
    text = config_file.read_text().replace(
        "  sprachmodelle_verzeichnis: ./data/sprachmodelle", "  sprachmodelle_verzeichnis: ./data/models"
    )
    config_file.write_text(text)
    (tmp_path / "data" / "modelle").rmdir()
    config = config_laden(config_file)
    folder_names.carry_over(config)
    assert "  modelle_verzeichnis: ./data/modelle\n" in config_file.read_text()


def test_an_empty_entry_under_the_new_key_does_not_erase_the_users_path(config, tmp_path):
    elsewhere = tmp_path / "pictures"
    elsewhere.mkdir()
    config.datenverzeichnis.mkdir(parents=True)
    (config.datenverzeichnis / "speicherorte.json").write_text(
        json.dumps({"bilder": str(elsewhere), "images": None})
    )
    folder_names.carry_over(config)
    assert ort(config, "images") == elsewhere.resolve()


def _pictures_and_a_location_on_images_in_capitals(config):
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    (data / "bilder" / "a.png").write_bytes(b"x")
    (data / "speicherorte.json").write_text(json.dumps({"skripte": str(data / "Images")}))
    return data


def test_on_a_disk_that_keeps_letter_case_apart_another_spelling_blocks_nothing(
    config, monkeypatch
):
    """There ``Images`` and ``images`` are two folders: a location of the
    user's on the one does not hold up the rename into the other."""
    monkeypatch.setattr(folder_names, "_ignores_case", lambda folder: False)
    data = _pictures_and_a_location_on_images_in_capitals(config)
    folder_names.carry_over(config)
    assert (data / "images" / "a.png").is_file()


def test_on_a_disk_that_sets_letter_case_aside_another_spelling_still_blocks(
    config, monkeypatch
):
    """Silence probe: on the usual disks of macOS and Windows both
    spellings are one folder, and it is the user's."""
    monkeypatch.setattr(folder_names, "_ignores_case", lambda folder: True)
    data = _pictures_and_a_location_on_images_in_capitals(config)
    folder_names.carry_over(config)
    assert (data / "bilder" / "a.png").is_file()


def test_on_a_disk_that_keeps_letter_case_apart_a_path_in_other_case_does_not_follow(tmp_path):
    old, new = tmp_path / "data" / "chatdateien", tmp_path / "data" / "chat_files"
    follow = folder_names.following([(str(old), str(new))], ignore_case=False)
    assert follow(str(tmp_path / "data" / "CHATDATEIEN" / "c" / "x.pdf")) is None
    assert follow(str(old / "c" / "x.pdf")) == new / "c" / "x.pdf"


def test_the_disk_is_measured_on_the_folder_itself(tmp_path):
    folder = tmp_path / "Data"
    folder.mkdir()
    ignores = (tmp_path / "data").exists()
    assert folder_names._ignores_case.__wrapped__(folder) is ignores
    # A folder not made yet is measured on the nearest one that is.
    assert folder_names._ignores_case.__wrapped__(folder / "not" / "yet") is ignores


def test_two_folders_holding_files_give_one_line_naming_both_and_the_way_out(config, caplog):
    data = config.datenverzeichnis
    for name in ("bilder", "images"):
        (data / name).mkdir(parents=True)
        (data / name / "a.png").write_bytes(name.encode())
    with caplog.at_level(logging.WARNING, logger="app.folder_names"):
        folder_names.carry_over(config)
    lines = [
        record.getMessage() for record in caplog.records
        if str(data / "bilder") in record.getMessage()
    ]
    assert len(lines) == 1
    assert str(data / "images") in lines[0]
    assert "move the contents" in lines[0]


def test_the_overrides_file_is_read_once_for_pins_and_former_keys(config, monkeypatch, tmp_path):
    """The lookup of the image models folder afterwards reads the file as
    rewritten; it is left out here."""
    data = config.datenverzeichnis
    data.mkdir(parents=True)
    overrides = data / "speicherorte.json"
    overrides.write_text(json.dumps({"bilder": str(tmp_path / "pictures")}))
    monkeypatch.setattr(folder_names.speicherorte, "ort", lambda config, name: tmp_path / "models")
    reads = []
    read_text = Path.read_text

    def counting(self, *args, **kwargs):
        if self == overrides:
            reads.append(self)
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    folder_names.carry_over(config)
    assert len(reads) == 1
    assert json.loads(read_text(overrides)) == {"images": str(tmp_path / "pictures")}


def test_a_folder_that_cannot_go_back_is_used_where_it_lies(tmp_path, monkeypatch, caplog):
    """The line could not be written and the folder not moved back: this
    start reads it under the new name."""
    config_file = _old_install(tmp_path, monkeypatch)
    config = config_laden(config_file)
    monkeypatch.setattr(folder_names.configwanderung, "values_replaced", lambda *a: set())
    rename = Path.rename

    def no_way_back(self, target):
        if Path(target).name in ("modelle", "sprachmodelle"):
            raise OSError("busy")
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", no_way_back)
    with caplog.at_level(logging.WARNING, logger="app.folder_names"):
        folder_names.carry_over(config)
    data = tmp_path / "data"
    assert config.app.modelle_verzeichnis == "./data/models"
    assert ort(config, "models") == (data / "models").resolve()
    assert any(
        str(data / "models") in record.getMessage()
        and str(data / "modelle") in record.getMessage()
        and "modelle_verzeichnis" in record.getMessage()
        for record in caplog.records
    )


def test_a_location_written_decomposed_pins_the_folder_written_composed(config, tmp_path):
    data = tmp_path / unicodedata.normalize("NFC", "Müller") / "data"
    config.app.data_dir = str(data)
    (data / "bilder").mkdir(parents=True)
    decomposed = unicodedata.normalize("NFD", str(data / "bilder"))
    (data / "speicherorte.json").write_text(json.dumps({"skripte": decomposed}))
    folder_names.carry_over(config)
    assert (data / "bilder").is_dir()


def test_a_stored_path_written_decomposed_follows(tmp_path):
    base = tmp_path / unicodedata.normalize("NFC", "Müller")
    old, new = base / "chatdateien", base / "chat_files"
    follow = folder_names.following([(str(old), str(new))])
    stored = unicodedata.normalize("NFD", str(old / "c" / "x.pdf"))
    assert follow(stored) == new / "c" / "x.pdf"


def test_a_path_in_capitals_and_the_other_unicode_form_follows(tmp_path):
    # Both spellings at once, so the rule is named here as well: the two
    # forms are compared in one Unicode form, the letter case by the disk's.
    old = tmp_path / unicodedata.normalize("NFC", "ärger") / "chatdateien"
    new = old.parent / "chat_files"
    follow = folder_names.following([(str(old), str(new))], ignore_case=True)
    stored = unicodedata.normalize("NFD", str(tmp_path / "ÄRGER" / "chatdateien" / "x.pdf"))
    assert follow(stored) == new / "x.pdf"


def test_a_stored_value_that_is_not_text_is_passed_over(tmp_path):
    follow = folder_names.following([(str(tmp_path / "a"), str(tmp_path / "b"))])
    assert follow(5) is None


def test_a_measurement_that_cannot_look_sets_letter_case_aside(tmp_path, monkeypatch):
    def refused(self):
        raise PermissionError("no")

    monkeypatch.setattr(Path, "exists", refused)
    assert folder_names._ignores_case.__wrapped__(tmp_path / "Data") is True


def test_a_failure_while_paths_follow_leaves_every_row_and_the_note(config, monkeypatch):
    data = config.datenverzeichnis
    old, new = data / "chatdateien", data / "chat_files"
    for name in "abc":
        (new / name).mkdir(parents=True)
        (new / name / "n.txt").write_text(name)
    (data / folder_names.PENDING).write_text(json.dumps([[str(old), str(new)]]))
    db = Database(":memory:")
    db.schema_einrichten()
    try:
        repositories = repositories_erstellen(db)
        chat = repositories.chats.erstellen(user_id="u", title="t")
        documents = [
            repositories.documents.speichern(
                chat_id=chat.id, filename="n.txt", pfad=str(old / name / "n.txt")
            )
            for name in "abc"
        ]
        following = folder_names.following

        # The rule is not named here: the production call passes none, and
        # this stand-in must not force one — that is what it would measure.
        def failing_on_the_third(pairs, ignore_case=None):
            follow = following(pairs, ignore_case)
            calls = []

            def counted(path):
                calls.append(path)
                if len(calls) == 3:
                    raise sqlite3.OperationalError("disk I/O error")
                return follow(path)

            return counted

        monkeypatch.setattr(folder_names, "following", failing_on_the_third)
        with pytest.raises(sqlite3.OperationalError):
            folder_names.paths_carried_over(config, repositories)
        assert [repositories.documents.holen(document.id).pfad for document in documents] == [
            str(old / name / "n.txt") for name in "abc"
        ]
        assert (data / folder_names.PENDING).exists()
    finally:
        db.schliessen()


def test_a_failed_move_leaves_no_pair_behind_in_the_note(tmp_path, monkeypatch):
    """The line could not be written, so the folder was to go back — and the
    way back failed as well, leaving it under its new name. The pair of that
    failed move must not stay in the note: the note is read in BOTH
    directions, so a new → old pair sends every stored path of the new folder
    back to the folder that is no longer there, and nothing ever follows."""
    config_file = _old_install(tmp_path, monkeypatch)
    (tmp_path / "data" / "modelle" / "m.gguf").write_bytes(b"m")
    config = config_laden(config_file)
    monkeypatch.setattr(folder_names.configwanderung, "values_replaced", lambda *a: set())
    rename = Path.rename

    def no_way_back(self, target):
        if Path(target).name in ("modelle", "sprachmodelle"):
            raise OSError("busy")
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", no_way_back)
    db = Database(":memory:")
    db.schema_einrichten()
    try:
        repositories = repositories_erstellen(db)
        chat = repositories.chats.erstellen(user_id="u", title="t")
        document = repositories.documents.speichern(
            chat_id=chat.id,
            filename="m.gguf",
            pfad=str(tmp_path / "data" / "modelle" / "m.gguf"),
        )
        folder_names.carry_over(config)
        folder_names.paths_carried_over(config, repositories)
        assert repositories.documents.holen(document.id).pfad == str(
            (tmp_path / "data" / "models" / "m.gguf").resolve()
        )
    finally:
        db.schliessen()


def test_a_move_that_went_through_keeps_its_pair(tmp_path, monkeypatch):
    """Silence probe: the pair of a move that worked is untouched, and the
    pair of a rollback that worked belongs in the note — the folder is back
    under its former name, and a stored path below it lies where it always
    did."""
    config_file = _old_install(tmp_path, monkeypatch)
    config = config_laden(config_file)
    monkeypatch.setattr(folder_names.configwanderung, "values_replaced", lambda *a: set())
    folder_names.carry_over(config)
    pairs = json.loads((config.datenverzeichnis / folder_names.PENDING).read_text())
    former = str((tmp_path / "data" / "modelle").resolve())
    current = str((tmp_path / "data" / "models").resolve())
    assert [former, current] in pairs
    assert [current, former] in pairs


def _set_in_file(config, field, value):
    """Writes one field of the ``app`` section into the configuration file
    the config came from, as a user's own edit would."""
    import yaml

    source = config._source
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    raw.setdefault("app", {})[field] = value
    source.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")


def _image_models_on_a_disk_of_its_own(tmp_path, monkeypatch):
    """An installation whose image models folder is one the user pointed
    somewhere of their own — beside the data folder here, which is the shape
    of a second disk with a rule of its own about letter case. The companion
    folder inside it still carries its former name. Returns the config and
    the image models folder."""
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    data = (tmp_path / "data").resolve()
    models = (tmp_path / "models").resolve()
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"app:\n  data_dir: {data}\n  bildmodelle_verzeichnis: {models / 'image_models'}\n"
    )
    (models / "image_models" / "gesichter").mkdir(parents=True)
    (models / "image_models" / "gesichter" / "f.bin").write_bytes(b"f")
    return config_laden(config_file), models


def _share_naming_the_companion(repositories, models):
    """A chat whose shared folder names the companion folder in another
    spelling — the ordinary shape of a path on a disk that takes both
    spellings for one folder."""
    chat = repositories.chats.erstellen(user_id="u", title="t")
    repositories.chats.aktualisieren(
        chat.id, working_dirs=[str(models / "image_models" / "GESICHTER")]
    )
    return chat


def test_a_companion_path_follows_the_rule_of_its_own_disk(tmp_path, monkeypatch, repos):
    """The image models folder can lie on a disk other than the data folder's,
    and the two need not agree about letter case. A stored path below a
    companion folder is then compared by the rule of the disk it lies on;
    compared by the data folder's rule, it is not recognised at all and stays
    on a folder that is gone."""
    config, models = _image_models_on_a_disk_of_its_own(tmp_path, monkeypatch)
    monkeypatch.setattr(
        folder_names, "_ignores_case", lambda folder: Path(folder).is_relative_to(models)
    )
    chat = _share_naming_the_companion(repos, models)
    folder_names.carry_over(config)
    folder_names.paths_carried_over(config, repos)
    assert repos.chats.holen(chat.id).working_dirs == [
        str(models / "image_models" / "faces")
    ]


def test_a_companion_a_location_names_in_other_letters_is_not_moved(tmp_path, monkeypatch):
    """A location of the user's can name the companion folder in the other
    letter case — on the disk it lies on that is the same folder. Its pin is
    compared by the rule of THAT disk; compared by the data folder's rule it
    is not recognised, and the folder the location names is renamed away."""
    config, models = _image_models_on_a_disk_of_its_own(tmp_path, monkeypatch)
    monkeypatch.setattr(
        folder_names, "_ignores_case", lambda folder: Path(folder).is_relative_to(models)
    )
    # Set in the file: the move reads the folder names from there again.
    named = models / "image_models" / "GESICHTER"
    _set_in_file(config, "einbettungsmodelle_verzeichnis", str(named))
    config.app.einbettungsmodelle_verzeichnis = str(named)
    folder_names.carry_over(config)
    assert (models / "image_models" / "gesichter").is_dir()
    assert not (models / "image_models" / "faces").exists()


def test_a_pair_that_cannot_be_taken_back_is_said_out_loud(config, monkeypatch, caplog):
    """The move failed and the note cannot be written at all, so the pair
    stays in it — the one state it must not stay in. Nothing else would ever
    mention the stored paths that now follow nothing, so the line is
    written."""
    (config.datenverzeichnis / "bilder").mkdir(parents=True)
    writes = []
    real_write = folder_names._write_note

    def failing_second(pending, entries):
        writes.append(entries)
        if len(writes) > 1:
            raise OSError("no note")
        return real_write(pending, entries)

    def no_move(self, target):
        raise OSError("busy")

    monkeypatch.setattr(folder_names, "_write_note", failing_second)
    monkeypatch.setattr(Path, "rename", no_move)
    with caplog.at_level(logging.WARNING, logger="app.folder_names"):
        folder_names.carry_over(config)
    assert len(writes) == 2
    assert any("could not be taken" in record.getMessage() for record in caplog.records)
    assert (config.datenverzeichnis / "bilder").is_dir()


def test_with_one_rule_on_both_disks_a_companion_path_follows_as_before(
    tmp_path, monkeypatch, repos
):
    """Silence probe: where both folders lie on a disk that sets letter case
    aside, both rules are the same one, and the path follows as it always
    did."""
    config, models = _image_models_on_a_disk_of_its_own(tmp_path, monkeypatch)
    monkeypatch.setattr(folder_names, "_ignores_case", lambda folder: True)
    chat = _share_naming_the_companion(repos, models)
    folder_names.carry_over(config)
    folder_names.paths_carried_over(config, repos)
    assert repos.chats.holen(chat.id).working_dirs == [
        str(models / "image_models" / "faces")
    ]


def test_a_note_in_another_encoding_stops_the_move_too(config, caplog):
    """A note restored from a backup in another encoding cannot be read —
    that is the same state as a note nobody may open, and not a reason to
    give up the whole carry-over with an exception either."""
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    (data / "bilder" / "a.png").write_bytes(b"x")
    (data / folder_names.PENDING).write_bytes(b"[[\xff\xfe]]")
    with caplog.at_level(logging.WARNING, logger="app.folder_names"):
        folder_names.carry_over(config)
    assert (data / "bilder").is_dir()
    assert not (data / "images").exists()
    assert any("cannot be read" in record.getMessage() for record in caplog.records)


def test_an_unreadable_note_is_said_out_loud_where_the_paths_should_follow(config, repos, caplog):
    """The paths following the note is the other half of the move, and a note
    it cannot read is not "nothing to do": the stored paths stay on folders
    that no longer exist, and nothing else would ever mention them."""
    data = config.datenverzeichnis
    data.mkdir(parents=True, exist_ok=True)
    (data / folder_names.PENDING).mkdir(parents=True)
    with caplog.at_level(logging.WARNING, logger="app.folder_names"):
        folder_names.paths_carried_over(config, repos)
    assert any(
        "stored paths below renamed folders are left as they are" in record.getMessage()
        for record in caplog.records
    )


def test_a_pin_on_another_disk_holds_the_folder_it_names(config, monkeypatch, tmp_path):
    """A location of the user's can lie on a disk other than the folder being
    renamed — behind a mount point, or a link. The pin is compared with that
    folder as text, so both sides have to be spelled the same way: a pin
    folded by its own disk's rule and a folder by its own would never meet,
    and the folder the user named would be renamed away."""
    data = tmp_path / "Data"
    config.app.data_dir = str(data)
    mounted = data / "bilder" / "usb"
    (mounted / "Shared").mkdir(parents=True)
    (data / "bilder" / "a.png").write_bytes(b"x")
    config.app.einbettungsmodelle_verzeichnis = str(mounted / "Shared")
    # The data folder sets letter case aside; the disk behind the mount does
    # not, as a foreign disk usually does.
    monkeypatch.setattr(
        folder_names, "_ignores_case", lambda folder: not str(folder).startswith(str(mounted))
    )
    folder_names.carry_over(config)
    assert (data / "bilder").is_dir()
    assert not (data / "images").exists()


def test_a_pair_the_note_does_not_carry_is_left_alone(config, caplog):
    """``_forget`` is written for the one pair ``_note`` just added. A pair
    the note does not carry means the note is not what was expected — and
    writing back what was read would throw the pairs of every earlier rename
    away. So nothing is written, and the line says what is missing."""
    data = config.datenverzeichnis
    pending = data / folder_names.PENDING
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(json.dumps([[str(data / "a"), str(data / "b")]]))
    with caplog.at_level(logging.WARNING, logger="app.folder_names"):
        folder_names._forget(pending, data / "x", data / "y")
    assert json.loads(pending.read_text(encoding="utf-8")) == [[str(data / "a"), str(data / "b")]]
    assert any("does not carry" in record.getMessage() for record in caplog.records)


def test_a_note_that_cannot_be_read_stops_the_move_and_says_so(config, caplog):
    """The note is what makes a move survivable, and a note nobody can read
    is not an empty note. Renaming anyway would move folders whose stored
    paths nothing ever follows; writing over it would take every earlier
    rename along."""
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    (data / "bilder" / "a.png").write_bytes(b"x")
    # A note that cannot be read: a folder where the note's file belongs.
    (data / folder_names.PENDING).mkdir(parents=True)
    with caplog.at_level(logging.WARNING, logger="app.folder_names"):
        folder_names.carry_over(config)
    assert (data / "bilder").is_dir()
    assert not (data / "images").exists()
    assert any("cannot be read" in record.getMessage() for record in caplog.records)


def test_two_starts_on_two_ports_move_the_folders_once_and_the_paths_follow(
    config, monkeypatch
):
    """Two services on two ports start at the same moment against one data
    folder: neither finds the other yet, and each holds the lock of its own
    port. The second one comes up while the first is in the middle of its
    move. Only one of them may move the folders — a second mover's rename
    fails on the folder the first already took, and its pair is then taken
    back out of the note the first one's stored paths depend on.

    The second one starts on a thread of its own: it waits for the lock on
    the move, which the first gives back only once its move is over — on
    the first one's own thread that wait could never end."""
    import threading

    from app import main as main_module
    from app.events import bus
    from app.main import app_erstellen

    with _start(config) as client:
        repositories = client.app.state.repositories
        chat = repositories.chats.erstellen(user_id="u", title="t")
        folder = config.datenverzeichnis / "chatdateien" / chat.id
        folder.mkdir(parents=True)
        (folder / "note.txt").write_text("hello")
        document = repositories.documents.speichern(
            chat_id=chat.id, filename="note.txt", mime_type="text/plain",
            pfad=str(folder / "note.txt"),
        )

    # Both looks at the folder land before either service has written its
    # claim: each sees nobody else.
    monkeypatch.setattr(main_module, "_lebende_instanz", lambda _config: None)
    second = config.model_copy(deep=True)
    second.app.port = int(config.app.port) + 1
    real_note = folder_names._note
    real_carry_over = folder_names.carry_over
    noted: list[str] = []
    second_start: list[threading.Thread] = []
    failures: list[BaseException] = []

    def start_second():
        try:
            with TestClient(app_erstellen(second)):
                pass
        except BaseException as error:  # noqa: BLE001 - handed to the test below
            failures.append(error)

    def note_then_second_start(pending, old, new):
        # Every rename notes its pair first, so this counts the movers.
        noted.append(old.name)
        written = real_note(pending, old, new)
        if len(noted) == 1:
            thread = threading.Thread(target=start_second)
            second_start.append(thread)
            thread.start()
        return written

    # The second service shares this process with the first, and with it
    # the state a service keeps per process: the first one's lock, the bus's
    # subscribers and the loop it hands work back to. The first waits for
    # the second right after its own move, so the two never run on side by
    # side past it; that state is kept and put back, so the first service
    # runs on with its own and no later test inherits the second one's.
    def carry_over_then_wait_for_second(own_config, lock_path=None):
        if own_config is not config:
            return real_carry_over(own_config, lock_path)
        own_lock = main_module._schloss
        handlers = {name: list(entries) for name, entries in bus._handler.items()}
        loop = bus._schleife
        try:
            moved = real_carry_over(own_config, lock_path)
            for thread in second_start:
                thread.join(timeout=30)
                assert not thread.is_alive(), "the second start never ended"
        finally:
            main_module._schloss = own_lock
            bus._handler.clear()
            bus._handler.update(handlers)
            bus.schleife_merken(loop)
        return moved

    monkeypatch.setattr(folder_names, "_note", note_then_second_start)
    monkeypatch.setattr(folder_names, "carry_over", carry_over_then_wait_for_second)
    with _start(config) as client:
        renewed = client.app.state.repositories.documents.holen(document.id)

    assert not failures
    assert len(second_start) == 1
    assert noted == ["chatdateien"], "both services moved the folders"
    assert renewed.pfad == str(config.datenverzeichnis / "chat_files" / chat.id / "note.txt")
    assert not (config.datenverzeichnis / folder_names.PENDING).exists()


def test_a_start_that_does_not_get_the_folder_lock_moves_nothing(config, monkeypatch):
    """The lock the move runs under is held on the data folder, whatever
    port the holder serves on: while another service holds it, a start moves
    no folder and reads no note."""
    monkeypatch.setattr(folder_names, "MOVE_WAIT_SECONDS", 0.2)
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    (data / "bilder" / "a.png").write_bytes(b"x")
    holder = instanzschloss.halten(data / folder_names.MOVE_LOCK)
    assert holder is not None
    try:
        with _start(config):
            pass
    finally:
        instanzschloss.loslassen(holder)
    assert (data / "bilder" / "a.png").read_bytes() == b"x"
    assert not (data / "images").exists()


def test_a_start_alone_moves_and_gives_the_folder_lock_back(config):
    """Silence probe: one start on its own moves the folders as before, and
    the move's lock is free again once the move is over — while the service
    is still running."""
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    (data / "bilder" / "a.png").write_bytes(b"x")
    with _start(config):
        assert not instanzschloss.gehalten(data / folder_names.MOVE_LOCK)
    assert (data / "images" / "a.png").read_bytes() == b"x"
    assert not (data / "bilder").exists()


def test_a_move_another_service_holds_is_said_in_the_log(config, caplog, monkeypatch):
    """A start that does not get the lock on the move leaves the folders
    alone, and the log says so — otherwise folders under their former names
    would simply stay, with no line anywhere saying why."""
    monkeypatch.setattr(folder_names, "MOVE_WAIT_SECONDS", 0.2)
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    holder = instanzschloss.halten(data / folder_names.MOVE_LOCK)
    assert holder is not None
    try:
        with caplog.at_level(logging.INFO, logger="app.folder_names"):
            folder_names.carry_over(config)
    finally:
        instanzschloss.loslassen(holder)
    assert (data / "bilder").is_dir()
    lines = [r for r in caplog.records if "another service holds" in r.getMessage()]
    assert [r.levelno for r in lines] == [logging.INFO]


def test_a_move_lock_that_cannot_be_taken_moves_without_it_and_warns(config, caplog):
    """A lock file that cannot even be opened is no other service at work:
    waiting for it would keep the folders under their former names for
    good. They are moved without the lock, as before there was one, and the
    line is a warning."""
    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    # A folder where the lock's file belongs: it cannot be opened as a file.
    (data / folder_names.MOVE_LOCK).mkdir()
    with caplog.at_level(logging.INFO, logger="app.folder_names"):
        folder_names.carry_over(config)
    assert (data / "images").is_dir()
    assert not (data / "bilder").exists()
    lines = [r for r in caplog.records if "without the lock" in r.getMessage()]
    assert [r.levelno for r in lines] == [logging.WARNING]


def _old_models_config(tmp_path, monkeypatch):
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "app:\n"
        '  data_dir: "./data"\n'
        "  modelle_verzeichnis: ./data/modelle\n",
        encoding="utf-8",
    )
    (tmp_path / "data" / "modelle").mkdir(parents=True)
    return config_file


def test_a_start_without_the_folder_lock_reads_the_new_names_once_it_is_free(
    tmp_path, monkeypatch
):
    """A second service read its configuration at start, before the service
    holding the move wrote the new folder names into the file. Without the
    lock it moves nothing: it waits until the lock is given back and reads
    the names then, so it does not go on with the former ones and make
    those folders anew — read at once, it found the file still unwritten."""
    import threading

    config_file = _old_models_config(tmp_path, monkeypatch)
    second = config_laden(config_file)
    first = config_laden(config_file)
    holder = instanzschloss.halten(first.datenverzeichnis / folder_names.MOVE_LOCK)
    assert holder is not None

    def first_moves_then_lets_go():
        # The first service is still moving when the second asks.
        threading.Event().wait(0.3)
        folder_names._carry_over(first)
        instanzschloss.loslassen(holder)

    mover = threading.Thread(target=first_moves_then_lets_go)
    mover.start()
    try:
        folder_names.carry_over(second)
    finally:
        mover.join(timeout=30)
        instanzschloss.loslassen(holder)
    assert first.app.modelle_verzeichnis == "./data/models"
    assert second.app.modelle_verzeichnis == "./data/models"
    assert ort(second, "models") == (tmp_path / "data" / "models").resolve()
    assert not (tmp_path / "data" / "modelle").exists()
    # Taken only to see it free, and given straight back.
    assert not instanzschloss.gehalten(second.datenverzeichnis / folder_names.MOVE_LOCK)


def test_a_lock_never_given_back_holds_the_start_only_until_the_wait_ends(
    tmp_path, monkeypatch, caplog
):
    """A move hanging on a disk that does not answer keeps its lock: the
    second start waits for it only so long, then reads the names as they
    stand, says so, and goes on."""
    import time

    config_file = _old_models_config(tmp_path, monkeypatch)
    config = config_laden(config_file)
    monkeypatch.setattr(folder_names, "MOVE_WAIT_SECONDS", 0.3)
    holder = instanzschloss.halten(config.datenverzeichnis / folder_names.MOVE_LOCK)
    assert holder is not None
    # The file changes while the lock stays held.
    config_file.write_text(
        config_file.read_text(encoding="utf-8").replace("data/modelle", "data/models"),
        encoding="utf-8",
    )
    began = time.monotonic()
    try:
        with caplog.at_level(logging.WARNING, logger="app.folder_names"):
            folder_names.carry_over(config)
    finally:
        instanzschloss.loslassen(holder)
    waited = time.monotonic() - began
    assert 0.3 <= waited < 5
    assert config.app.modelle_verzeichnis == "./data/models"
    assert (tmp_path / "data" / "modelle").is_dir()
    lines = [r for r in caplog.records if "still holds" in r.getMessage()]
    assert [r.levelno for r in lines] == [logging.WARNING]


def test_a_start_without_the_folder_lock_keeps_a_name_nobody_changed(tmp_path, monkeypatch):
    """Silence probe: read again, a name the file still holds stays what it
    was — a folder of the user's own is not touched by reading it twice."""
    monkeypatch.setenv("EXE_AI_DATEN", str(tmp_path))
    own = tmp_path / "own-models"
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"app:\n  data_dir: \"./data\"\n  modelle_verzeichnis: {own}\n",
        encoding="utf-8",
    )
    config = config_laden(config_file)
    config.datenverzeichnis.mkdir(parents=True)
    monkeypatch.setattr(folder_names, "MOVE_WAIT_SECONDS", 0.2)
    holder = instanzschloss.halten(config.datenverzeichnis / folder_names.MOVE_LOCK)
    assert holder is not None
    try:
        folder_names.carry_over(config)
    finally:
        instanzschloss.loslassen(holder)
    assert config.app.modelle_verzeichnis == str(own)
    assert f"  modelle_verzeichnis: {own}\n" in config_file.read_text(encoding="utf-8")


def test_a_start_that_gets_the_folder_lock_after_a_move_takes_the_new_names(
    tmp_path, monkeypatch
):
    """Both services read their configuration at start. The first moves the
    folders and gives the lock back; only then does the second reach the
    move, and it gets the lock at once. It reads the names again before it
    moves anything: with the former name it read at start, it went on with
    a folder that is not there any more and made it anew."""
    config_file = _old_models_config(tmp_path, monkeypatch)
    second = config_laden(config_file)
    first = config_laden(config_file)
    folder_names.carry_over(first)
    assert first.app.modelle_verzeichnis == "./data/models"
    folder_names.carry_over(second)
    assert second.app.modelle_verzeichnis == "./data/models"
    assert ort(second, "models") == (tmp_path / "data" / "models").resolve()
    assert not (tmp_path / "data" / "modelle").exists()


def test_a_start_that_gets_the_folder_lock_alone_still_moves_its_folders(
    tmp_path, monkeypatch
):
    """Silence probe: read again by the start that holds the lock, an
    unchanged file still names the former folder, and that start moves it."""
    config_file = _old_models_config(tmp_path, monkeypatch)
    config = config_laden(config_file)
    folder_names.carry_over(config)
    assert config.app.modelle_verzeichnis == "./data/models"
    assert (tmp_path / "data" / "models").is_dir()
    assert not (tmp_path / "data" / "modelle").exists()


def _moved_chat_file(config):
    """A chat file under the former folder, moved by a start of its own: the
    note is written, the stored path not followed yet. Returns the open
    database, its repositories and the document."""
    folder = config.datenverzeichnis / "chatdateien" / "c1"
    folder.mkdir(parents=True)
    (folder / "n.txt").write_text("n")
    db = Database(":memory:")
    db.schema_einrichten()
    repositories = repositories_erstellen(db)
    chat = repositories.chats.erstellen(user_id="u", title="t")
    document = repositories.documents.speichern(
        chat_id=chat.id, filename="n.txt", pfad=str(folder / "n.txt")
    )
    folder_names.carry_over(config)
    assert (config.datenverzeichnis / folder_names.PENDING).exists()
    return db, repositories, document


def test_the_mover_follows_its_paths_while_a_waiting_start_holds_the_lock_a_moment(config):
    """A second service waiting for the move takes the lock again and again,
    each time for a moment, to see it free. The service that moved the
    folders comes to its stored paths right after — and where its try fell
    on one of those moments, it left the paths behind and the note in
    place. It waits for the lock the way the waiting start does."""
    import threading

    db, repositories, document = _moved_chat_file(config)
    try:
        lock_path = config.datenverzeichnis / folder_names.MOVE_LOCK
        holder = instanzschloss.halten(lock_path)
        assert holder is not None
        releaser = threading.Timer(0.3, instanzschloss.loslassen, args=(holder,))
        releaser.start()
        try:
            folder_names.paths_carried_over(config, repositories)
        finally:
            releaser.join(timeout=30)
            instanzschloss.loslassen(holder)
        assert repositories.documents.holen(document.id).pfad == str(
            config.datenverzeichnis / "chat_files" / "c1" / "n.txt"
        )
        assert not (config.datenverzeichnis / folder_names.PENDING).exists()
        assert not instanzschloss.gehalten(lock_path)
    finally:
        db.schliessen()


def test_stored_paths_wait_for_a_lock_never_given_back_only_so_long(
    config, monkeypatch, caplog
):
    """Silence probe: a lock that stays held keeps the stored paths where
    they are once the wait is over — the note stays for the next start, and
    the line says another service holds the lock."""
    import time

    db, repositories, document = _moved_chat_file(config)
    monkeypatch.setattr(folder_names, "MOVE_WAIT_SECONDS", 0.2)
    holder = instanzschloss.halten(config.datenverzeichnis / folder_names.MOVE_LOCK)
    assert holder is not None
    began = time.monotonic()
    try:
        with caplog.at_level(logging.INFO, logger="app.folder_names"):
            folder_names.paths_carried_over(config, repositories)
        waited = time.monotonic() - began
        assert 0.2 <= waited < 5
        assert repositories.documents.holen(document.id).pfad == str(
            config.datenverzeichnis / "chatdateien" / "c1" / "n.txt"
        )
        assert (config.datenverzeichnis / folder_names.PENDING).exists()
        lines = [r for r in caplog.records if "Stored paths not carried over" in r.getMessage()]
        # Once when the wait begins, once when it ends with the lock held.
        assert [r.levelno for r in lines] == [logging.INFO, logging.INFO]
    finally:
        instanzschloss.loslassen(holder)
        db.schliessen()


def test_reading_the_folder_names_again_leaves_the_file_as_it_is(tmp_path, monkeypatch):
    """The names are read again from a file the user owns: reading writes
    nothing into it. Loaded whole instead, the file was completed with every
    setting it lacked and written back — by a start that was told to leave
    the folders alone. A line the file no longer carries keeps the name
    read at start."""
    config_file = _old_models_config(tmp_path, monkeypatch)
    config = config_laden(config_file)
    # The user's own edit after the start: only two settings, and the
    # models folder at its new name.
    config_file.write_text(
        "app:\n"
        '  data_dir: "./data"\n'
        "  modelle_verzeichnis: ./data/models\n",
        encoding="utf-8",
    )
    config.app.bilder_verzeichnis = "./somewhere-read-at-start"
    before = config_file.read_bytes()
    monkeypatch.setattr(folder_names, "MOVE_WAIT_SECONDS", 0.2)
    holder = instanzschloss.halten(config.datenverzeichnis / folder_names.MOVE_LOCK)
    assert holder is not None
    try:
        folder_names.carry_over(config)
    finally:
        instanzschloss.loslassen(holder)
    assert config_file.read_bytes() == before
    assert config.app.modelle_verzeichnis == "./data/models"
    assert config.app.bilder_verzeichnis == "./somewhere-read-at-start"


def test_a_file_that_cannot_be_read_again_leaves_the_names_as_read(tmp_path, monkeypatch):
    """Silence probe: a file that is no longer readable YAML leaves every
    folder name as it was read at start, and the start goes on."""
    config_file = _old_models_config(tmp_path, monkeypatch)
    config = config_laden(config_file)
    config_file.write_text("app: [unclosed\n", encoding="utf-8")
    folder_names.names_read_again(config)
    assert config.app.modelle_verzeichnis == "./data/modelle"


def test_a_lock_file_that_cannot_be_opened_reads_nothing_again(config, monkeypatch, caplog):
    """A lock whose file cannot even be opened is no other service at work:
    nobody can have moved the folders, so there are no new names to read
    and nothing to wait for. The start says so and moves at once."""
    import time

    reads: list[object] = []
    moves: list[object] = []
    monkeypatch.setattr(folder_names, "names_read_again", lambda own: reads.append(own))
    monkeypatch.setattr(folder_names, "_carry_over", lambda own: moves.append(own))
    (config.datenverzeichnis / folder_names.MOVE_LOCK).mkdir(parents=True)
    began = time.monotonic()
    with caplog.at_level(logging.INFO, logger="app.folder_names"):
        folder_names.carry_over(config)
    assert time.monotonic() - began < folder_names.MOVE_WAIT_SECONDS
    assert reads == []
    assert moves == [config]
    lines = [r for r in caplog.records if "cannot be taken" in r.getMessage()]
    assert [r.levelno for r in lines] == [logging.WARNING]


def test_a_start_that_waited_for_the_lock_reads_the_names_again(config, monkeypatch):
    """Silence probe: a lock another service holds is a move under way, so
    the start that waited for it does read the names again."""
    reads: list[object] = []
    monkeypatch.setattr(folder_names, "names_read_again", lambda own: reads.append(own))
    monkeypatch.setattr(folder_names, "MOVE_WAIT_SECONDS", 0.1)
    config.datenverzeichnis.mkdir(parents=True)
    holder = instanzschloss.halten(config.datenverzeichnis / folder_names.MOVE_LOCK)
    assert holder is not None
    try:
        folder_names.carry_over(config)
    finally:
        instanzschloss.loslassen(holder)
    assert reads == [config]


def test_one_try_at_the_lock_opens_its_file_once(config, monkeypatch):
    """Whether another service holds the lock or its file cannot be opened
    is heard from the one try itself. Asked again by opening the file a
    second time, the answer could belong to another moment than the try."""
    import builtins

    lock_path = config.datenverzeichnis / folder_names.MOVE_LOCK
    config.datenverzeichnis.mkdir(parents=True)
    holder = instanzschloss.halten(lock_path)
    assert holder is not None
    opened: list[str] = []
    real_open = builtins.open

    def counting_open(file, *args, **kwargs):
        if str(file) == str(lock_path):
            opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(folder_names, "MOVE_WAIT_SECONDS", 0.0)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(builtins, "open", counting_open)
            folder_names.paths_carried_over(config, repositories=None)
    finally:
        instanzschloss.loslassen(holder)
    assert len(opened) == 1


def _flock_failing_with(monkeypatch, code):
    """Every try to take a lock answered by the kernel with ``code``."""
    import os

    from app import instanzschloss as module

    real_flock = module.fcntl.flock

    def flock(fd, operation):
        if operation & module.fcntl.LOCK_EX:
            raise OSError(code, os.strerror(code))
        return real_flock(fd, operation)

    monkeypatch.setattr(module.fcntl, "flock", flock)


@pytest.mark.skipif(sys.platform == "win32", reason="stands in for the POSIX lock call")
def test_a_lock_the_file_system_cannot_give_is_an_error_not_a_holder(config, monkeypatch):
    """A file system without locks answers with an error of its own, not
    with "somebody holds it". Taken for a holder, it kept every start
    waiting for a service that does not exist."""
    import errno

    config.datenverzeichnis.mkdir(parents=True)
    path = config.datenverzeichnis / folder_names.MOVE_LOCK
    _flock_failing_with(monkeypatch, errno.ENOLCK)
    lock, error = instanzschloss.try_lock(path)
    assert lock is None
    assert error is not None and error.errno == errno.ENOLCK
    # The instance lock reads it as before: not had.
    assert instanzschloss.halten(path) is None


@pytest.mark.skipif(sys.platform == "win32", reason="stands in for the POSIX lock call")
@pytest.mark.parametrize("code", ["EAGAIN", "EWOULDBLOCK", "EACCES"])
def test_each_answer_for_a_held_lock_reads_as_held(config, monkeypatch, code):
    """Silence probe: every answer the kernel gives for a lock somebody
    else holds still reads as held, not as an error."""
    import errno

    config.datenverzeichnis.mkdir(parents=True)
    _flock_failing_with(monkeypatch, getattr(errno, code))
    lock, error = instanzschloss.try_lock(config.datenverzeichnis / folder_names.MOVE_LOCK)
    assert (lock, error) == (None, None)


def test_a_really_held_lock_reads_as_held(config):
    """Silence probe without any stand-in: a lock another holder has."""
    config.datenverzeichnis.mkdir(parents=True)
    path = config.datenverzeichnis / folder_names.MOVE_LOCK
    holder = instanzschloss.halten(path)
    assert holder is not None
    try:
        assert instanzschloss.try_lock(path) == (None, None)
    finally:
        instanzschloss.loslassen(holder)


@pytest.mark.skipif(sys.platform == "win32", reason="stands in for the POSIX lock call")
def test_folders_move_without_a_lock_the_file_system_cannot_give(config, monkeypatch, caplog):
    """The lock's file opens, but the lock on it cannot be taken at all:
    the folders move without it, at once, and the log says so."""
    import errno
    import time

    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    _flock_failing_with(monkeypatch, errno.ENOLCK)
    began = time.monotonic()
    with caplog.at_level(logging.INFO, logger="app.folder_names"):
        folder_names.carry_over(config)
    assert time.monotonic() - began < folder_names.MOVE_WAIT_SECONDS
    assert (data / "images").is_dir()
    assert not (data / "bilder").exists()
    lines = [r for r in caplog.records if "without the lock" in r.getMessage()]
    assert [r.levelno for r in lines] == [logging.WARNING]


def test_stored_paths_follow_without_a_lock_that_cannot_be_taken(config, monkeypatch, caplog):
    """The folders moved without the lock, so their stored paths follow
    without it too — at once, and the log says so."""
    import time

    db, repositories, document = _moved_chat_file(config)
    try:
        lock_path = config.datenverzeichnis / folder_names.MOVE_LOCK
        lock_path.unlink(missing_ok=True)
        lock_path.mkdir()
        began = time.monotonic()
        with caplog.at_level(logging.INFO, logger="app.folder_names"):
            folder_names.paths_carried_over(config, repositories)
        assert time.monotonic() - began < folder_names.MOVE_WAIT_SECONDS
        assert repositories.documents.holen(document.id).pfad == str(
            config.datenverzeichnis / "chat_files" / "c1" / "n.txt"
        )
        assert not (config.datenverzeichnis / folder_names.PENDING).exists()
        lines = [r for r in caplog.records if "without the lock" in r.getMessage()]
        assert [r.levelno for r in lines] == [logging.WARNING]
    finally:
        db.schliessen()


def test_a_start_that_waited_reads_the_names_under_the_lock(config, monkeypatch):
    """The names are read while this start holds the lock: given back
    first, another service could begin its move between the two."""
    import threading

    lock_path = config.datenverzeichnis / folder_names.MOVE_LOCK
    config.datenverzeichnis.mkdir(parents=True)
    held_while_reading: list[bool] = []

    def reading(own):
        # Another open file asks: held by this start's lock, it cannot be had.
        held_while_reading.append(instanzschloss.gehalten(lock_path))

    monkeypatch.setattr(folder_names, "names_read_again", reading)
    holder = instanzschloss.halten(lock_path)
    assert holder is not None
    releaser = threading.Timer(0.2, instanzschloss.loslassen, args=(holder,))
    releaser.start()
    try:
        folder_names.carry_over(config)
    finally:
        releaser.join(timeout=30)
        instanzschloss.loslassen(holder)
    assert held_while_reading == [True]
    assert not instanzschloss.gehalten(lock_path)


@pytest.mark.parametrize(
    "text",
    ["", "# nothing but a comment\n", "- a\n- list\n", "app:\n  - a list\n", "other: 1\n"],
)
def test_a_file_that_names_no_folder_leaves_the_names_as_read(tmp_path, monkeypatch, text):
    """A file that is empty, no mapping, or carries no ``app`` mapping names
    no folder at all: the names read at start stay. Read as an empty
    mapping, it set every location back to its default."""
    config_file = _old_models_config(tmp_path, monkeypatch)
    config = config_laden(config_file)
    config_file.write_text(text, encoding="utf-8")
    folder_names.names_read_again(config)
    assert config.app.modelle_verzeichnis == "./data/modelle"


def test_a_file_that_leaves_a_folder_out_keeps_the_name_read_at_start(tmp_path, monkeypatch):
    """An ``app`` mapping without a folder's line says nothing about that
    folder: the name read at start stays. Read at its default instead, a
    line somebody was in the middle of writing sent the location to a
    folder nobody named."""
    config_file = _old_models_config(tmp_path, monkeypatch)
    config = config_laden(config_file)
    config_file.write_text('app:\n  data_dir: "./data"\n', encoding="utf-8")
    folder_names.names_read_again(config)
    assert config.app.modelle_verzeichnis == "./data/modelle"


def test_a_line_the_file_carries_is_read_again(tmp_path, monkeypatch):
    """Silence probe: a line the file does carry is read as written."""
    config_file = _old_models_config(tmp_path, monkeypatch)
    config = config_laden(config_file)
    config_file.write_text(
        'app:\n  data_dir: "./data"\n  modelle_verzeichnis: ./data/models\n',
        encoding="utf-8",
    )
    folder_names.names_read_again(config)
    assert config.app.modelle_verzeichnis == "./data/models"


def test_a_start_that_waited_carries_over_what_the_mover_left(config, monkeypatch):
    """The service holding the lock stops half way: one folder moved, the
    next rename failed. A start that waited for the lock and then gets it
    carries over what is left — reading the names alone, it left the rest
    under the former name until some later start."""
    import threading

    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    (data / "chatdateien").mkdir()
    lock_path = data / folder_names.MOVE_LOCK
    holder = instanzschloss.halten(lock_path)
    assert holder is not None
    real_rename = Path.rename

    def failing_on_chat_files(self, target):
        if self.name == "chatdateien":
            raise OSError("disk went away")
        return real_rename(self, target)

    # The first service, under its lock, gets as far as the pictures.
    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", failing_on_chat_files)
        folder_names._carry_over(config)
    assert (data / "images").is_dir()
    assert (data / "chatdateien").is_dir()
    releaser = threading.Timer(0.2, instanzschloss.loslassen, args=(holder,))
    releaser.start()
    try:
        folder_names.carry_over(config)
    finally:
        releaser.join(timeout=30)
        instanzschloss.loslassen(holder)
    assert (data / "chat_files").is_dir()
    assert not (data / "chatdateien").exists()
    assert not instanzschloss.gehalten(lock_path)


def test_a_lock_that_turns_unusable_while_waiting_moves_without_it(config, monkeypatch, caplog):
    """The lock was held at the first try and cannot be taken at all on a
    later one: the wait ends, the log says so, and the folders are carried
    over without the lock — after the names are read again, since somebody
    was moving a moment ago. Before, that end of the wait was silent and
    nothing moved."""
    import errno

    data = config.datenverzeichnis
    (data / "bilder").mkdir(parents=True)
    answers = iter([(None, None), (None, OSError(errno.ENOLCK, "no locks"))])
    monkeypatch.setattr(instanzschloss, "try_lock", lambda path: next(answers))
    reads: list[object] = []
    real_read = folder_names.names_read_again
    monkeypatch.setattr(
        folder_names, "names_read_again", lambda own: (reads.append(own), real_read(own))
    )
    with caplog.at_level(logging.INFO, logger="app.folder_names"):
        folder_names.carry_over(config)
    assert (data / "images").is_dir()
    assert not (data / "bilder").exists()
    assert reads == [config]
    lines = [r for r in caplog.records if "without the lock" in r.getMessage()]
    assert [r.levelno for r in lines] == [logging.WARNING]


def test_the_wait_asks_as_often_as_a_waiting_windows_lock(config, monkeypatch):
    """The wait's bounds are the ones ``msvcrt.locking`` with ``LK_LOCK``
    keeps: ten tries, one second apart. Counted on a lock that stays held,
    with a clock that moves only when the wait sleeps."""
    monkeypatch.setattr(folder_names, "MOVE_WAIT_STEP", REAL_WAIT_STEP)
    now = [0.0]
    tries: list[float] = []

    def held(path):
        tries.append(now[0])
        return None, None

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(instanzschloss, "try_lock", held)
    monkeypatch.setattr(folder_names.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(folder_names.time, "sleep", sleep)
    lock, error, waited = folder_names._lock_within_wait(
        config.datenverzeichnis / folder_names.MOVE_LOCK, "Folders"
    )
    assert (lock, error, waited) == (None, None, True)
    # One try at once, then one after every step until the bound.
    expected = round(folder_names.MOVE_WAIT_SECONDS / REAL_WAIT_STEP) + 1
    assert len(tries) == expected == 11
    assert tries[-1] == folder_names.MOVE_WAIT_SECONDS


def test_a_held_lock_is_tried_once_before_the_first_step(config, monkeypatch):
    """The start tries the lock once and then waits a step; it does not
    try twice at the same moment before waiting at all."""
    now = [0.0]
    tries: list[float] = []

    def held(path):
        tries.append(now[0])
        return None, None

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(instanzschloss, "try_lock", held)
    monkeypatch.setattr(folder_names.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(folder_names.time, "sleep", sleep)
    folder_names.carry_over(config)
    assert tries.count(0.0) == 1


def test_a_start_beside_a_running_service_reads_the_new_names(tmp_path, monkeypatch):
    """A moved the folders and wrote their new names; B read its
    configuration before that and finds A running, so B moves nothing. It
    still reads the names again — left with the former ones, it made those
    folders anew."""
    from app import main as main_module

    config_file = _old_models_config(tmp_path, monkeypatch)
    second = config_laden(config_file)
    first = config_laden(config_file)
    folder_names.carry_over(first)
    monkeypatch.setattr(main_module, "_lebende_instanz", lambda _config: 4321)
    moves: list[object] = []
    monkeypatch.setattr(folder_names, "carry_over", lambda *args: moves.append(args) or True)
    with TestClient(main_module.app_erstellen(second)):
        assert second.app.modelle_verzeichnis == "./data/models"
    assert moves == []
    assert not (tmp_path / "data" / "modelle").exists()


def test_a_lock_held_through_the_wait_is_waited_for_once(config, monkeypatch):
    """A lock on the move that stays with another service through the
    wait leaves both halves to that one: the start waits once, not again
    for the stored paths."""
    from app import main as main_module

    monkeypatch.setattr(main_module, "_lebende_instanz", lambda _config: None)
    monkeypatch.setattr(folder_names, "MOVE_WAIT_SECONDS", 0.2)
    waits: list[str] = []
    real_wait = folder_names._lock_within_wait

    def counted(path, step):
        waits.append(step)
        return real_wait(path, step)

    monkeypatch.setattr(folder_names, "_lock_within_wait", counted)
    config.datenverzeichnis.mkdir(parents=True)
    holder = instanzschloss.halten(config.datenverzeichnis / folder_names.MOVE_LOCK)
    assert holder is not None
    try:
        with _start(config):
            pass
    finally:
        instanzschloss.loslassen(holder)
    assert waits == ["Folders"]


def test_a_free_lock_lets_both_halves_run_and_works_out_its_path_once(config, monkeypatch):
    """Silence probe: with the lock free, both halves of the move run — and
    the lock's path is worked out once for both."""
    data = config.datenverzeichnis
    (data / "chatdateien" / "c1").mkdir(parents=True)
    waits: list[str] = []
    real_wait = folder_names._lock_within_wait
    monkeypatch.setattr(
        folder_names, "_lock_within_wait",
        lambda path, step: waits.append(step) or real_wait(path, step),
    )
    worked_out: list[object] = []
    real_path = folder_names.lock_path
    monkeypatch.setattr(
        folder_names, "lock_path", lambda own: worked_out.append(own) or real_path(own)
    )
    with _start(config):
        pass
    assert waits == ["Folders", "Stored paths"]
    assert len(worked_out) == 1
    assert (data / "chat_files" / "c1").is_dir()
