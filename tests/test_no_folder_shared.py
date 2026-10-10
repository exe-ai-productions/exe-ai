"""File tools in a chat that shares no folder of the user's.

Such a chat works in its private folder under the program's data
(app/dokumentablage.py), so a bare name the model gives lands there. A
refusal that only named the path left the model nothing to go on: it tried
the same call again and then searched the whole disk. Every file tool that
refuses such a path now says the same thing — that no folder is shared, and
that the model should ask the user for one or ask them to share one via the
folder icon in the input bar (``grenzen.NO_FOLDER_SHARED``).

Silence probe throughout: with a folder of the user's shared, every refusal
reads as it did before.
"""

from __future__ import annotations

import asyncio

import pytest

from app import dokumentablage
from app.tools import create_folder, dateiwerkzeuge, grenzen
from app.tools.registry import WerkzeugRegistry, WerkzeugVerboten


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def data_dir(tmp_path):
    return tmp_path / "data"


def _private_folders(data_dir, chat_id: str) -> list[str]:
    """The folders a chat sharing nothing hands its tools — built the way
    the run builds them, the private folder created as the run creates it."""
    folders = dokumentablage.ordner_dieses_chats(data_dir, [], chat_id)
    assert grenzen.prepare_folders(folders, data_dir) is None
    return folders


def _create_folder(repos, data_dir, path: str, folders: list[str], chat_id: str) -> str:
    registry = WerkzeugRegistry(
        [], shell_an=True, folder_share=create_folder.ChatFolderShare(repos, data_dir)
    )
    return run(registry.ausfuehren(
        create_folder.WERKZEUG_NAME, {"path": path}, ordner=folders, chat_id=chat_id,
        herkunft="chat",
    ))


# --- create_folder ---------------------------------------------------------


def test_create_folder_with_a_bare_name_and_no_folder_shared_names_the_way_out(repos, data_dir):
    chat = repos.chats.erstellen(user_id="u", title="t")
    folders = _private_folders(data_dir, chat.id)

    with pytest.raises(WerkzeugVerboten) as refusal:
        _create_folder(repos, data_dir, "work", folders, chat.id)

    text = str(refusal.value)
    assert grenzen.NO_FOLDER_SHARED in text
    assert "own data folder" in text
    assert "Give a full path to a folder of the user's instead" not in text
    assert not (dokumentablage.chatordner(data_dir, chat.id) / "work").exists()
    assert repos.chats.holen(chat.id).working_dirs == []


def test_silence_probe_create_folder_with_a_folder_shared_refuses_as_before(
    repos, data_dir, tmp_path
):
    shared = tmp_path / "shared"
    shared.mkdir()
    chat = repos.chats.erstellen(user_id="u", title="t")
    repos.chats.aktualisieren(chat.id, working_dirs=[str(shared)])
    folders = dokumentablage.ordner_dieses_chats(data_dir, [str(shared)], chat.id)
    inside_data = str(data_dir / "anything")

    with pytest.raises(WerkzeugVerboten) as refusal:
        _create_folder(repos, data_dir, inside_data, folders, chat.id)

    text = str(refusal.value)
    assert text.endswith("Give a full path to a folder of the user's instead.")
    assert grenzen.NO_FOLDER_SHARED not in text
    # And a bare name still goes into the shared folder.
    assert "Created" in _create_folder(repos, data_dir, "work", folders, chat.id)
    assert (shared / "work").is_dir()


# --- the tools that refuse a missing path ----------------------------------

MISSING = [
    ("read_file", {"path": "exe.md"}),
    ("edit_file", {"path": "exe.md", "old_text": "a", "new_text": "b"}),
    ("list_dir", {"path": "work"}),
    ("search_files", {"pattern": "x", "path": "work"}),
]


@pytest.mark.parametrize(("name", "arguments"), MISSING)
def test_a_missing_bare_name_with_no_folder_shared_names_the_way_out(name, arguments, data_dir):
    folders = _private_folders(data_dir, "c1")

    with pytest.raises(grenzen.GrenzeVerletzt) as refusal:
        run(dateiwerkzeuge.ausfuehren(name, arguments, folders, data_dir=data_dir))

    text = str(refusal.value)
    assert "does not exist." in text
    assert text.endswith(grenzen.NO_FOLDER_SHARED)


@pytest.mark.parametrize(("name", "arguments"), MISSING)
def test_silence_probe_a_missing_name_in_a_shared_folder_only_does_not_exist(
    name, arguments, data_dir, tmp_path
):
    shared = tmp_path / "shared"
    shared.mkdir()
    folders = dokumentablage.ordner_dieses_chats(data_dir, [str(shared)], "c1")

    with pytest.raises(grenzen.GrenzeVerletzt) as refusal:
        run(dateiwerkzeuge.ausfuehren(name, arguments, folders, data_dir=data_dir))

    target = (shared / arguments["path"]).resolve()
    assert str(refusal.value) == f"'{target}' does not exist."


def test_read_file_through_the_registry_carries_the_way_out(repos, data_dir):
    """The registry hands the data folder over from the chat's folder share —
    the one line that makes the sentence reach a real run."""
    chat = repos.chats.erstellen(user_id="u", title="t")
    folders = _private_folders(data_dir, chat.id)
    registry = WerkzeugRegistry(
        [], shell_an=True, folder_share=create_folder.ChatFolderShare(repos, data_dir)
    )

    with pytest.raises(WerkzeugVerboten, match="folder icon in the input bar"):
        run(registry.ausfuehren(
            "read_file", {"path": "exe.md"}, ordner=folders, chat_id=chat.id, herkunft="chat",
        ))


def test_write_file_with_no_folder_shared_still_writes_into_the_private_folder(data_dir):
    """Not a refusal, so nothing to add: the file is made where the name
    points, as before."""
    folders = _private_folders(data_dir, "c1")

    result = run(dateiwerkzeuge.ausfuehren(
        "write_file", {"path": "note.txt", "content": "x"}, folders, data_dir=data_dir
    ))

    assert grenzen.NO_FOLDER_SHARED not in result
    assert (dokumentablage.chatordner(data_dir, "c1") / "note.txt").read_text() == "x"
