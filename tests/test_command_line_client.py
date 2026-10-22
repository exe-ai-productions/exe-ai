"""The command line client in the system prompt and at the gate.

The prompt names the client's command where the run can use it. A command
that starts the client is asked like a path outside the shared folders —
"exe -p" answers every question of the service with yes, and "exe settings"
switches the approval mode — and follows the mode the same way: asked in
"Manuell" and "Eingeschränkt", let through in "Auto", refused in a run with
nobody to ask.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from app import berechtigungen, command_line_client, grundprompt
from app.berechtigungsregeln import Regeldatei
from app.tools import WerkzeugRegistry, shell
from app.providers import MockProvider, mock_endpunkt
from tests.conftest import provider_setzen
from tests.test_systemprompt_stand_job import _request

SHELL = shell.WERKZEUG_NAME


@pytest.fixture
def command(tmp_path, monkeypatch) -> Path:
    """An installed command: the file the prompt names."""
    path = tmp_path / "Resources" / "bin" / "exe"
    path.parent.mkdir(parents=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(command_line_client, "path", lambda: path)
    return path


# --- Where the command lies ---------------------------------------------------------


def test_a_run_from_the_source_folder_has_no_command():
    assert command_line_client.path() is None


def test_the_command_of_an_installed_program_lies_in_the_bin_folder_beside_the_program(
    tmp_path, monkeypatch
):
    program = tmp_path / "Resources" / "exe-ai-terminal" / "Exe AI"
    program.parent.mkdir(parents=True)
    program.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(program))
    monkeypatch.setattr(sys, "platform", "darwin")
    assert command_line_client.path() is None  # the file is not there yet
    wanted = tmp_path / "Resources" / "bin" / "exe"
    wanted.parent.mkdir()
    wanted.write_text("", encoding="utf-8")
    assert command_line_client.path() == wanted.resolve()


def test_on_windows_the_command_lies_next_to_the_program(tmp_path, monkeypatch):
    program = tmp_path / "resources" / "exe-ai-terminal" / "Exe AI.exe"
    program.parent.mkdir(parents=True)
    program.write_text("", encoding="utf-8")
    (program.parent / "exe.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(program))
    monkeypatch.setattr(sys, "platform", "win32")
    assert command_line_client.path() == (program.parent / "exe.exe").resolve()


def test_on_windows_the_wrapper_of_the_installer_by_its_path_starts_the_client_too(
    tmp_path, monkeypatch
):
    program = tmp_path / "install" / "resources" / "exe-ai-terminal" / "Exe AI.exe"
    program.parent.mkdir(parents=True)
    program.write_text("", encoding="utf-8")
    (program.parent / "exe.exe").write_text("", encoding="utf-8")
    wrapper = tmp_path / "install" / "bin" / "exe.cmd"
    wrapper.parent.mkdir()
    wrapper.write_text("", encoding="utf-8")
    other = tmp_path / "tools" / "exe.cmd"
    other.parent.mkdir()
    other.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(program))
    monkeypatch.setattr(sys, "platform", "win32")
    assert command_line_client.starts(f'"{wrapper}" --help') == str(wrapper)
    assert command_line_client.starts(f'"{program.parent / "exe.exe"}" --help') is not None
    assert command_line_client.starts(f'"{other}" --help') is None


# --- The paragraph in the prompt --------------------------------------------------------


def test_the_paragraph_names_the_command_and_the_mcp_server_it_sets_up(command):
    text = grundprompt.bauen(command_line=str(command))
    assert f'Its command on this machine is "{command}"' in " ".join(text.split())
    assert f'"{command}" mcp add https://example.com/mcp' in " ".join(text.split())
    assert "Settings → Servers and connections → MCP Servers → choose the service's tile" in text
    assert "command line client" not in grundprompt.bauen()


def test_the_command_is_named_where_the_run_has_a_shell_and_may_start_programs(command):
    named = command_line_client.for_prompt
    assert named(shell_offered=True, zugriff=("ja", "fragen")) == str(command)
    assert named(shell_offered=True, zugriff=("ja", "ja")) == str(command)
    # Nothing to run it with, no folders to run commands in, or a rule that
    # refuses what lies outside the folders: no advice against a wall.
    assert named(shell_offered=False, zugriff=("ja", "fragen")) is None
    assert named(shell_offered=True, zugriff=None) is None
    assert named(shell_offered=True, zugriff=("ja", "nein")) is None


def test_a_source_run_names_no_command():
    assert command_line_client.for_prompt(shell_offered=True, zugriff=("ja", "ja")) is None


def _chat_system(client, chat_id, registry) -> str:
    """The system message of one chat request on the test endpoint, which can
    call tools once the registry is the one given."""
    client.app.state.config.features.mcp = True
    client.app.state.werkzeuge = registry
    client.app.state.discovery.zustaende["test"].endpunkt.capabilities.tool_calls = True
    provider = provider_setzen(client, MockProvider(mock_endpunkt("test"), haeppchen=["ok"]))
    client.post(
        "/api/v1/chat/completions",
        json={"chat_id": chat_id, "endpoint_id": "test", "content": "hi"},
    )
    (system,) = [n for n in provider.letzte_anfrage.nachrichten if n.role == "system"]
    return " ".join(system.content.split())


def test_a_chat_with_a_shell_reads_the_paragraph_and_one_without_does_not(
    client, chat_id, command
):
    with_shell = _chat_system(client, chat_id, WerkzeugRegistry([], shell_an=True))
    assert f'Its command on this machine is "{command}"' in with_shell
    assert "Every command of its chat also runs from outside" in with_shell

    other = client.post("/api/v1/chats", json={"title": "No shell"}).json()["id"]
    without = _chat_system(client, other, WerkzeugRegistry([], shell_an=False))
    assert "command line client" not in without


def test_a_chat_that_may_not_start_programs_outside_its_folders_is_not_told_to(
    client, chat_id, command, tmp_path
):
    rules = tmp_path / "rules.json"
    rules.write_text(
        json.dumps(
            {
                "standard": {"chat": "ja", "agent": "ja"},
                "dateien": {
                    "werkzeuge": [SHELL],
                    "innerhalb_der_ordner": {"chat": "ja", "agent": "ja"},
                    "ausserhalb_der_ordner": {"chat": "nein", "agent": "nein"},
                },
            }
        ),
        encoding="utf-8",
    )
    registry = WerkzeugRegistry([], shell_an=True, berechtigungen_pfad=rules)
    assert "command line client" not in _chat_system(client, chat_id, registry)


async def test_a_job_the_chat_sent_off_reads_it_and_one_started_by_hand_does_not(
    client, config, tmp_path, command
):
    sent_off, _folder = await _request(client, config, tmp_path, ask_in_chat=True)
    assert f'Its command on this machine is "{command}"' in " ".join(
        sent_off.nachrichten[0].content.split()
    )
    by_hand, _folder = await _request(client, config, tmp_path, ask_in_chat=False)
    assert "command line client" not in by_hand.nachrichten[0].content


# --- Which commands start it -----------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "exe --help",
        "exe",
        "exe.cmd mcp add https://mcp.example.test/mcp",
        "EXE.EXE settings",
        "cd work && exe mcp",
        "ls | exe -p hello",
        "FOO=1 exe settings",
        "time exe --version",
        "env HOME=/tmp exe settings",
        "env FOO=1 BAR=2 exe",
        'sh -c "exe --help"',
        "echo hi; exe --help",
        "$(exe --version)",
    ],
)
def test_a_command_that_starts_the_client_is_asked(line, tmp_path):
    assert shell.braucht_bestaetigung({"command": line}, [str(tmp_path)])
    assert command_line_client.starts(line) is not None


def test_the_installed_command_by_its_path_or_through_a_link_is_asked(
    command, tmp_path
):
    link = tmp_path / "bin-link"
    os.symlink(command, link)
    for line in (f'"{command}" --help', f"{link} --help", f"'{command}'"):
        assert shell.braucht_bestaetigung({"command": line}, [str(tmp_path)]), line


@pytest.mark.parametrize(
    "line",
    [
        "ls",
        "ls -la exe-notes",
        "python3 -m pytest",
        "cat exe-notes.md",
        "echo exe-notes",
        "./exe-notes.md",
        "execute --now",
        "exercise.sh",
        "git commit -m 'exe'",
    ],
)
def test_other_commands_are_not_asked_for_it(line, tmp_path):
    assert command_line_client.starts(line) is None
    assert not shell.braucht_bestaetigung({"command": line}, [str(tmp_path)])


def test_a_file_named_exe_somewhere_else_is_somebodys_own_program(command, tmp_path):
    other = tmp_path / "tools" / "exe"
    other.parent.mkdir()
    other.write_text("#!/bin/sh\n", encoding="utf-8")
    assert command_line_client.starts(f"{other} --help") is None


def test_the_reason_is_the_clients_and_a_folder_outside_still_comes_first(tmp_path):
    folders = [str(tmp_path)]
    assert shell.grundschluessel({"command": "exe --help"}, folders) == shell.GRUND_SCHLUESSEL_CLI
    # An address in the line does not hide that the client is run.
    assert (
        shell.grundschluessel({"command": "exe mcp add https://mcp.example.test/mcp"}, folders)
        == shell.GRUND_SCHLUESSEL_CLI
    )
    assert (
        shell.grundschluessel({"command": "exe --help /etc/hosts"}, folders)
        == shell.GRUND_SCHLUESSEL
    )
    assert (
        shell.grundschluessel({"command": "curl https://mcp.example.test/mcp"}, folders)
        == shell.GRUND_SCHLUESSEL_NETZ
    )


def test_the_question_names_the_command_and_the_sentence_of_the_client(tmp_path):
    registry = WerkzeugRegistry([], shell_an=True)
    reason = registry.bestaetigungsgrund(SHELL, {"command": "exe --version"}, [str(tmp_path)])
    assert reason == ("werkzeug.reason_cli", "pfad", "exe")


# --- The mode decides ---------------------------------------------------------------------------


def _judged(line: str, tmp_path, origin="chat", outside="fragen"):
    rules = Regeldatei()
    rules.ausserhalb_der_ordner["chat"] = outside
    return berechtigungen.urteil(
        SHELL, {"command": line}, [str(tmp_path)], origin, regeln=rules
    )


def test_manual_and_restricted_ask_and_auto_lets_it_run(tmp_path):
    assert _judged("exe --help", tmp_path, outside="fragen").antwort == "fragen"
    assert _judged("exe --help", tmp_path, outside="ja").antwort == "ja"
    assert _judged("exe --help", tmp_path, outside="nein").antwort == "nein"


def test_a_run_without_a_user_is_refused_with_the_clients_own_words(tmp_path):
    from app.agenten import Agent

    judgment = berechtigungen.urteil(
        SHELL, {"command": "exe --help"}, [str(tmp_path)], "agent",
        agent=Agent(name="a", prompt="p", werkzeuge=[SHELL], berechtigungen={}),
        regeln=Regeldatei(),
    )
    assert judgment.antwort == "nein"
    assert "starts Exe AI's own command line" in judgment.grund
    assert "outside the shared folders" not in judgment.grund
    assert not judgment.about_path


def test_an_ordinary_command_is_not_asked_in_the_same_modes(tmp_path):
    """The silence probe: nothing else changed."""
    assert _judged("ls", tmp_path, outside="fragen").antwort == "ja"
    assert _judged("python3 -m pytest", tmp_path, outside="fragen").antwort == "ja"
    assert _judged("cat exe-notes.md", tmp_path, outside="fragen").antwort == "ja"
