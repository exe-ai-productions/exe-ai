"""The private places of the program are shut to every tool call.

The data folder holds the chats, the notes and the folders of other chats; the
settings folder holds the keys and the rules of the permission gate. A model
that works in a chat which shares no folder must not read or write them in
any mode — not in "Auto", where everything outside the shared folders runs,
and not in "Manuell" either. What it needs to work stays open: its own chat
folder, the dock, the pictures, the scripts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import berechtigungen
from app.berechtigungsregeln import Regeldatei
from app.tools import WerkzeugRegistry, WerkzeugVerboten, grenzen


class _Share:
    """Stands in for the folder share the program builds: only the data
    folder is read from it by the gate."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir


@pytest.fixture
def layout(tmp_path):
    """A settings folder with its files, and a data folder with the places a
    run meets in it."""
    settings = tmp_path / "app"
    data = settings / "data"
    for name in ("config.yaml", ".env", "berechtigungen.json", "mcp_servers.json"):
        settings.mkdir(exist_ok=True)
        (settings / name).write_text("secret", encoding="utf-8")
    (data / "chat_files" / "mine").mkdir(parents=True)
    (data / "chat_files" / "other").mkdir(parents=True)
    (data / "agent_dock").mkdir()
    (data / "images").mkdir()
    (data / "scripts").mkdir()
    (data / "exe-ai-terminal.db").write_text("chats", encoding="utf-8")
    (data / "ordnerwissen.json").write_text("notes", encoding="utf-8")
    (data / "chat_files" / "mine" / "upload.txt").write_text("mine", encoding="utf-8")
    (data / "chat_files" / "other" / "private.txt").write_text("other", encoding="utf-8")
    (data / "agent_dock" / "delivery.txt").write_text("delivery", encoding="utf-8")
    (data / "images" / "picture.txt").write_text("picture", encoding="utf-8")
    (data / "scripts" / "run.sh").write_text("script", encoding="utf-8")
    own = [
        str(data / "chat_files" / "mine"), str(data / "agent_dock"), str(data / "images"),
    ]
    return {"settings": settings, "data": data, "own": own}


def _check(layout, ordner=None):
    return grenzen.private_check(
        ordner if ordner is not None else layout["own"], layout["data"], layout["settings"]
    )


# --- The test itself --------------------------------------------------------


@pytest.mark.parametrize(
    "relative",
    [
        "exe-ai-terminal.db", "ordnerwissen.json", "chat_files/other/private.txt",
        "chat_files/other", "chat_files",
    ],
)
def test_the_data_folder_is_private(layout, relative):
    assert _check(layout)(layout["data"] / relative) is True


@pytest.mark.parametrize("name", ["config.yaml", ".env", "berechtigungen.json", "mcp_servers.json"])
def test_the_files_with_keys_and_rules_are_private(layout, name):
    assert _check(layout)(layout["settings"] / name) is True


@pytest.mark.parametrize(
    "relative",
    [
        "chat_files/mine/upload.txt", "chat_files/mine", "agent_dock/delivery.txt",
        "images/picture.txt", "scripts/run.sh", "scripts",
    ],
)
def test_what_a_run_works_in_stays_open(layout, relative):
    """Silence: the own chat folder, the dock, the pictures and the scripts."""
    assert _check(layout)(layout["data"] / relative) is False


def test_the_other_files_beside_the_settings_are_not_private(layout):
    assert _check(layout)(layout["settings"] / "readme.txt") is False


def test_a_folder_outside_is_not_private(layout, tmp_path):
    assert _check(layout)(tmp_path / "somewhere" / "file.txt") is False


def test_sharing_the_data_folder_opens_nothing_of_it(layout):
    """A share that is the data folder, or lies above it, is no permission to
    read the chats in it."""
    for shared in (layout["data"], layout["settings"], layout["settings"].parent):
        check = _check(layout, [str(shared)])
        assert check(layout["data"] / "exe-ai-terminal.db") is True
        assert check(layout["data"] / "chat_files" / "other" / "private.txt") is True


def test_a_subfolder_of_the_data_folder_that_was_shared_is_open(layout):
    check = _check(layout, [str(layout["data"] / "chat_files" / "other")])
    assert check(layout["data"] / "chat_files" / "other" / "private.txt") is False
    assert check(layout["data"] / "chat_files" / "mine" / "upload.txt") is True


def test_a_spelling_in_other_letter_case_is_the_same_place(layout):
    upper = Path(str(layout["data"] / "exe-ai-terminal.db").upper())
    assert _check(layout)(upper) is True


def test_a_link_to_a_private_file_is_private(layout):
    link = layout["data"] / "chat_files" / "mine" / "link.txt"
    link.symlink_to(layout["data"] / "exe-ai-terminal.db")
    target = grenzen.private_target({"path": str(link)}, layout["own"], _check(layout))
    assert target is not None and target.endswith("exe-ai-terminal.db")


def test_without_a_data_folder_and_settings_there_is_no_test():
    assert grenzen.private_check([], None, None) is None


# --- The gate ---------------------------------------------------------------


def _judge(layout, name, argumente, mode="auto", herkunft="chat"):
    regeln = Regeldatei()
    if mode == "auto":
        regeln.standard[herkunft] = "ja"
        regeln.ausserhalb_der_ordner[herkunft] = "ja"
    elif mode == "manuell":
        regeln.ausserhalb_der_ordner[herkunft] = "fragen"
    return berechtigungen.urteil(
        name, argumente, layout["own"], herkunft, regeln=regeln, private=_check(layout),
    )


@pytest.mark.parametrize("mode", ["auto", "manuell"])
def test_read_file_of_the_database_is_refused_in_every_mode(layout, mode):
    path = str(layout["data"] / "exe-ai-terminal.db")
    judgment = _judge(layout, "read_file", {"path": path}, mode)
    assert judgment.antwort == "nein"
    assert path in judgment.grund and "private place" in judgment.grund
    assert judgment.about_path is False


@pytest.mark.parametrize("mode", ["auto", "manuell"])
def test_write_file_into_the_settings_is_refused_in_every_mode(layout, mode):
    path = str(layout["settings"] / "config.yaml")
    judgment = _judge(layout, "write_file", {"path": path, "content": "x"}, mode)
    assert judgment.antwort == "nein"


def test_the_notes_are_refused_and_so_is_the_folder_of_another_chat(layout):
    for relative in ("ordnerwissen.json", "chat_files/other/private.txt"):
        judgment = _judge(layout, "read_file", {"path": str(layout["data"] / relative)})
        assert judgment.antwort == "nein", relative


def test_a_relative_path_out_of_the_own_folder_is_refused(layout):
    judgment = _judge(layout, "read_file", {"path": "../../exe-ai-terminal.db"})
    assert judgment.antwort == "nein"


def test_a_search_without_a_path_in_a_shared_data_folder_is_refused(layout):
    regeln = Regeldatei()
    regeln.ausserhalb_der_ordner["chat"] = "ja"
    ordner = [str(layout["data"])]
    judgment = berechtigungen.urteil(
        "search_files", {"pattern": "chat"}, ordner, "chat", regeln=regeln,
        private=_check(layout, ordner),
    )
    assert judgment.antwort == "nein"


def test_an_agent_is_refused_too_and_a_rule_that_always_allows_does_not_open_it(layout):
    regeln = Regeldatei()
    regeln.regeln["read_file"] = "ja"
    judgment = berechtigungen.urteil(
        "read_file", {"path": str(layout["data"] / "exe-ai-terminal.db")}, layout["own"],
        "agent", regeln=regeln, private=_check(layout),
    )
    assert judgment.antwort == "nein"


@pytest.mark.parametrize(
    "relative",
    ["chat_files/mine/upload.txt", "agent_dock/delivery.txt", "images/picture.txt", "scripts/run.sh"],
)
def test_the_open_places_are_judged_as_before(layout, relative):
    """Silence: reading and writing in the own chat folder, the dock, the
    pictures and the scripts."""
    path = str(layout["data"] / relative)
    judgment = _judge(layout, "read_file", {"path": path}, "auto")
    assert judgment.antwort == "ja"
    writing = _judge(layout, "write_file", {"path": path, "content": "x"}, "auto")
    assert writing.antwort == "ja"


def test_without_the_test_nothing_changes(layout):
    judgment = berechtigungen.urteil(
        "read_file", {"path": str(layout["data"] / "exe-ai-terminal.db")}, layout["own"],
        "chat", regeln=Regeldatei(),
    )
    assert judgment.antwort == "fragen"


# --- Commands ---------------------------------------------------------------


@pytest.mark.parametrize("mode", ["auto", "manuell"])
def test_a_command_with_the_path_of_the_database_is_refused(layout, mode):
    command = f"cat '{layout['data'] / 'exe-ai-terminal.db'}'"
    judgment = _judge(layout, "run_command", {"command": command}, mode)
    assert judgment.antwort == "nein"
    assert "exe-ai-terminal.db" in judgment.grund


def test_a_command_with_a_relative_path_into_the_data_folder_is_refused(layout):
    judgment = _judge(layout, "run_command", {"command": "sqlite3 ../../exe-ai-terminal.db .dump"})
    assert judgment.antwort == "nein"


def test_a_command_that_names_the_settings_is_refused(layout):
    command = f"grep key {layout['settings'] / '.env'}"
    assert _judge(layout, "run_command", {"command": command}).antwort == "nein"


def test_a_command_in_the_open_places_is_judged_as_before(layout):
    for command in (
        "ls", f"cat {layout['data'] / 'chat_files' / 'mine' / 'upload.txt'}",
        f"cp x {layout['data'] / 'agent_dock' / 'out.txt'}", "echo hello > note.txt",
    ):
        assert _judge(layout, "run_command", {"command": command}, "auto").antwort == "ja", command


def test_a_command_with_a_bare_file_name_beside_the_database_is_not_refused(layout):
    """The heuristic reads the paths a command names; a name that resolves in
    the first shared folder is that folder's file."""
    assert _judge(layout, "run_command", {"command": "cat upload.txt"}).antwort == "ja"


# --- Through the registry ---------------------------------------------------


@pytest.mark.asyncio
async def test_the_registry_refuses_the_database_in_auto(layout):
    (layout["settings"] / "berechtigungen.json").write_text(
        json.dumps({"standard": {"chat": "ja"}, "dateien": {
            "innerhalb_der_ordner": {"chat": "ja"}, "ausserhalb_der_ordner": {"chat": "ja"},
        }}),
        encoding="utf-8",
    )
    registry = WerkzeugRegistry(
        [], shell_an=True, berechtigungen_pfad=layout["settings"] / "berechtigungen.json",
        folder_share=_Share(layout["data"]),
    )
    with pytest.raises(WerkzeugVerboten) as refused:
        await registry.ausfuehren(
            "read_file", {"path": str(layout["data"] / "exe-ai-terminal.db")},
            ordner=layout["own"],
        )
    assert "private place" in str(refused.value)
    assert registry.braucht_bestaetigung(
        "read_file", {"path": str(layout["data"] / "exe-ai-terminal.db")}, layout["own"]
    ) is False
    ergebnis = await registry.ausfuehren(
        "read_file", {"path": str(layout["data"] / "chat_files" / "mine" / "upload.txt")},
        ordner=layout["own"],
    )
    assert "mine" in ergebnis


@pytest.mark.asyncio
async def test_the_registry_refuses_a_command_naming_the_database(layout):
    registry = WerkzeugRegistry(
        [], shell_an=True, berechtigungen_pfad=layout["settings"] / "berechtigungen.json",
        folder_share=_Share(layout["data"]),
    )
    with pytest.raises(WerkzeugVerboten) as refused:
        await registry.ausfuehren(
            "run_command", {"command": f"cat {layout['data'] / 'exe-ai-terminal.db'}"},
            ordner=layout["own"],
        )
    assert "private place" in str(refused.value)


# --- The search walks past ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_search_over_a_folder_above_the_data_folder_skips_it(layout):
    from app.tools import datei_suchen

    (layout["settings"] / "readme.txt").write_text("chats are here", encoding="utf-8")
    out = await datei_suchen.ausfuehren(
        {"pattern": "chats", "path": str(layout["settings"])},
        [str(layout["settings"])], data_dir=layout["data"],
    )
    assert "readme.txt" in out
    assert "exe-ai-terminal.db" not in out
    assert "ordnerwissen.json" not in out


@pytest.mark.asyncio
async def test_a_search_in_the_own_folder_finds_its_files_as_before(layout):
    from app.tools import datei_suchen

    out = await datei_suchen.ausfuehren(
        {"pattern": "mine"}, layout["own"], data_dir=layout["data"],
    )
    assert "upload.txt" in out


@pytest.mark.asyncio
async def test_a_search_over_the_settings_folder_skips_the_files_with_keys(layout):
    from app.tools import datei_suchen

    (layout["settings"] / "config.yaml").write_text("api_key: hunter2", encoding="utf-8")
    (layout["settings"] / "readme.txt").write_text("api_key is explained here", encoding="utf-8")
    out = await datei_suchen.ausfuehren(
        {"pattern": "api_key", "path": str(layout["settings"])},
        [str(layout["settings"])], data_dir=layout["data"], private=_check(layout),
    )
    assert "readme.txt" in out
    assert "hunter2" not in out
    assert "config.yaml" not in out


def test_a_variable_in_a_command_is_read_like_the_shell_reads_it(layout, monkeypatch):
    monkeypatch.setenv("A929_DATA", str(layout["data"]))
    judgment = _judge(layout, "run_command", {"command": "cat $A929_DATA/exe-ai-terminal.db"})
    assert judgment.antwort == "nein"
