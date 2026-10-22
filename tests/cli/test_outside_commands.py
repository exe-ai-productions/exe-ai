"""A command of the chat from outside it: ``exe theme pearl`` is what
``/theme pearl`` is — the same handler, the result written out and the
program ended. Where a word is missing, the selection opens at a terminal;
without one the program says what to give and ends. What is not a command
is refused with the sentence for an unknown word, before anything is asked
of the service."""

from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from cli import commands, main as main_module, outside, prefs, themes
from cli.main import main
from cli.texts import Texts
from test_commands import ENTER, SAFETY_NET_SECONDS, Lines, Service, context

WORDS = Texts("en")


@pytest.fixture(autouse=True)
def the_default_look():
    yield
    themes.set_look(themes.DEFAULT_LOOK)


def run(
    *arguments: str,
    service: Service,
    tmp_path: Path,
    typed: str = "",
    terminal: bool = False,
    monkeypatch: pytest.MonkeyPatch,
) -> int:
    """The program with ``arguments`` against the stand-in service; ``typed``
    waits in its input, and ``terminal`` says whether there is one to pick
    in."""
    monkeypatch.setattr(outside, "has_terminal", lambda: terminal)
    with create_pipe_input() as pipe:
        pipe.send_text(typed)
        net = threading.Timer(SAFETY_NET_SECONDS, pipe.close)
        net.start()
        try:
            with create_app_session(input=pipe, output=DummyOutput()):
                return main(
                    [*arguments, "--lang", "en"],
                    http=httpx.Client(transport=httpx.MockTransport(service)),
                    prefs_path=tmp_path / "cli.json",
                )
        finally:
            net.cancel()


def test_a_theme_with_its_word_is_set_written_out_and_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = Service()
    assert run("theme", "pearl", service=service, tmp_path=tmp_path, monkeypatch=monkeypatch) == 0

    # What the handler says in the chat is what stands here: the same one.
    inside = context(Service(), tmp_path / "inside")
    inside.commands.run("/theme pearl")
    assert isinstance(inside.renderer, Lines)
    assert capsys.readouterr().out.splitlines() == inside.renderer.notices
    assert prefs.load(tmp_path / "cli.json").get("look") == "pearl"
    # No chat was made, none was opened.
    assert not service.asked("POST", "/chats")
    assert not service.asked("POST", "/chat/completions")


def test_a_model_with_its_number_is_chosen_the_way_the_chat_chooses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = Service()
    assert run("model", "2", service=service, tmp_path=tmp_path, monkeypatch=monkeypatch) == 0

    assert service.bodies("PUT", f"/settings/global/{commands.LAST_MODEL_KEY}") == [
        {"wert": {"id": "remote", "name": "Remote Model"}}
    ]
    # No chat is open outside the chat: nothing is kept with one.
    assert not service.asked("PATCH", "/chats/chat-1")
    assert capsys.readouterr().out == WORDS.t("cli.modell_gewaehlt", name="Remote Model") + "\n"


def test_a_word_behind_the_command_may_be_several(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = Service()
    assert run("model", "Remote", "Model", service=service, tmp_path=tmp_path, monkeypatch=monkeypatch) == 0
    assert service.bodies("PUT", f"/settings/global/{commands.LAST_MODEL_KEY}") == [
        {"wert": {"id": "remote", "name": "Remote Model"}}
    ]


def test_without_its_word_and_without_a_terminal_the_program_says_what_to_give(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = Service()
    assert run("model", service=service, tmp_path=tmp_path, monkeypatch=monkeypatch) == 2

    shown = capsys.readouterr()
    assert shown.out == ""
    assert shown.err == WORDS.t("cli.needs_terminal", program="exe") + "\n"
    # Nothing was chosen.
    assert not service.asked("PUT", f"/settings/global/{commands.LAST_MODEL_KEY}")


def test_without_its_word_and_at_a_terminal_the_selection_opens_and_the_choice_is_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = Service()
    code = run(
        "model", service=service, tmp_path=tmp_path, typed="2" + ENTER, terminal=True,
        monkeypatch=monkeypatch,
    )
    assert code == 0
    assert service.bodies("PUT", f"/settings/global/{commands.LAST_MODEL_KEY}") == [
        {"wert": {"id": "remote", "name": "Remote Model"}}
    ]
    assert WORDS.t("cli.modell_gewaehlt", name="Remote Model") in capsys.readouterr().out


def test_a_selection_that_is_closed_chooses_nothing_and_still_ends_well(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = Service()
    code = run(
        "model", service=service, tmp_path=tmp_path, typed="\x1b", terminal=True,
        monkeypatch=monkeypatch,
    )
    assert code == 0
    assert not service.asked("PUT", f"/settings/global/{commands.LAST_MODEL_KEY}")


def test_what_the_command_refuses_is_said_and_the_code_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("model", "99", service=Service(), tmp_path=tmp_path, monkeypatch=monkeypatch) == 1
    assert capsys.readouterr().err == WORDS.t("cli.modell_unbekannt", name="99") + "\n"


def test_new_goes_on_in_a_new_chat_and_writes_nothing_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = Service()
    code = run(
        "new", service=service, tmp_path=tmp_path, typed=f"/quit{ENTER}", monkeypatch=monkeypatch
    )
    assert code == 0
    # The client ran after the command: the models were read once for the
    # command and once more for the chat's head, as `exe` reads them.
    assert len(service.asked("GET", "/models")) >= 2
    # A new chat is made when something is written into it, not before.
    assert not service.asked("POST", "/chats")


def test_a_command_that_opens_a_chat_goes_on_in_the_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = Service()
    code = run(
        "chats", "2", service=service, tmp_path=tmp_path, typed=f"/quit{ENTER}",
        monkeypatch=monkeypatch,
    )
    assert code == 0
    # The history of the chat that was named was read: the client opened it.
    assert service.asked("GET", "/chats/chat-2/messages")


@pytest.mark.parametrize("name", sorted({name for name, _ in commands.outside_entries(Texts("en"))}))
def test_every_command_of_the_chat_but_stop_is_a_word_of_the_command_line(name: str) -> None:
    assert main_module._unknown_word(name, [], Texts("en")) is None


@pytest.mark.parametrize("name", sorted({name for name, _ in commands.outside_entries(Texts("en"))}))
def test_every_command_of_the_chat_runs_from_outside_without_a_failure_of_its_own(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each handler is run through the outside screen, asker and renderer:
    it ends well, or it ends where a selection needs a terminal — never in
    a traceback. The chat that ``new`` and ``chats`` open is left at once."""
    code = run(
        name, service=Service(), tmp_path=tmp_path, typed=f"/quit{ENTER}", monkeypatch=monkeypatch
    )
    assert code in (0, 1, 2)


def test_the_words_of_the_command_line_are_the_registered_commands_but_stop(
    tmp_path: Path,
) -> None:
    registry = context(Service(), tmp_path).commands
    assert isinstance(registry, commands.Commands)
    registered = set(registry.names())
    named = {name for name, _ in commands.outside_entries(Texts("en"))}
    assert named == registered - {"stop"}


@pytest.mark.parametrize("word", ["serve", "stop"])
def test_the_two_words_that_went_are_unknown_and_nothing_is_asked_of_the_service(
    word: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    service = Service()
    assert run(word, service=service, tmp_path=tmp_path, monkeypatch=monkeypatch) == 2

    assert capsys.readouterr().err == WORDS.t("cli.unknown_outside_command", name=word, program="exe") + "\n"
    assert service.seen == []


def test_the_first_word_that_is_none_is_the_one_that_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("modell", "foo", service=Service(), tmp_path=tmp_path, monkeypatch=monkeypatch) == 2
    assert "modell" in capsys.readouterr().err


def test_service_alone_and_service_with_another_word_are_said_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("service", service=Service(), tmp_path=tmp_path, monkeypatch=monkeypatch) == 2
    said = capsys.readouterr().err
    for word in ("start", "run", "stop", "status"):
        assert f"service {word}" in said

    assert run("service", "foo", service=Service(), tmp_path=tmp_path, monkeypatch=monkeypatch) == 2
    assert capsys.readouterr().err == (
        WORDS.t("cli.unknown_outside_command", name="service foo", program="exe") + "\n"
    )


def test_install_takes_no_word_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("install", "now", service=Service(), tmp_path=tmp_path, monkeypatch=monkeypatch) == 2
    assert "now" in capsys.readouterr().err


def test_the_command_line_without_a_word_still_opens_the_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silence probe: no word, the chat — as before."""
    service = Service()
    assert run(
        service=service, tmp_path=tmp_path, typed=f"/quit{ENTER}", terminal=True,
        monkeypatch=monkeypatch,
    ) == 0
    assert service.asked("GET", "/models")



# --- the servers and the overview, from outside ----------------------------------------------


def _run_at_the_stand_in(
    *arguments: str, stub_http: httpx.Client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setattr(outside, "has_terminal", lambda: False)
    with create_pipe_input() as pipe:
        with create_app_session(input=pipe, output=DummyOutput()):
            return main([*arguments, "--lang", "en"], http=stub_http, prefs_path=tmp_path / "cli.json")


def test_server_stop_from_outside_writes_the_servers_line_and_ends_with_code_zero(
    stub, stub_http, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    agent = stub.servers["/agentenmodell"]
    agent.running, agent.model = True, "agent.gguf"
    code = _run_at_the_stand_in(
        "server", "stop", "agent", stub_http=stub_http, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    assert code == 0
    assert agent.stops == 1
    assert capsys.readouterr().out == (
        f"{WORDS.t('agentserver.titel')}  {WORDS.t('status.inaktiv')}\n"
    )


def test_server_without_a_word_and_without_a_terminal_names_what_to_give(
    stub, stub_http, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_at_the_stand_in(
        "server", stub_http=stub_http, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    assert code == 2
    assert capsys.readouterr().err == WORDS.t("cli.needs_terminal", program="exe") + "\n"


def test_status_from_outside_writes_the_lines_of_the_overview_and_ends_with_code_zero(
    stub, stub_http, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub.memory = {"belegt_gb": 25.2, "gesamt_gb": 64.0, "anteil": 0.39}
    code = _run_at_the_stand_in(
        "status", stub_http=stub_http, tmp_path=tmp_path, monkeypatch=monkeypatch
    )
    assert code == 0
    lines = [" ".join(line.split()) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0].startswith(WORDS.t("cli.titel"))
    assert f"{WORDS.t('kopf.speicher')} 25/64 GB" in lines
    assert sum(1 for line in lines if WORDS.t("status.inaktiv") in line) == 6
    # Nothing was changed on the way.
    assert all(request.split()[0] == "GET" for request in stub.requests if "/api/v1/" in request)
