"""What the program does before any service is involved: ``--version``,
``--help`` — and ``stop``, which ends a service by the note it left."""

from __future__ import annotations

import json
import re
import signal
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from cli import service, themes
from cli.main import VERSION_FILE, help_text, main
from cli.texts import Texts
from test_texts import _catalogue as catalogue_of
from test_texts import _sentences as sentences_below

OWN_ADDRESS = "http://127.0.0.1:8123"
PORT = 8123


def refusing(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"a request went out: {request.method} {request.url}")


def run(*arguments: str, tmp_path: Path) -> int:
    """The program with ``arguments``, against an outside that must never be
    asked anything."""
    return main(
        [*arguments, "--lang", "en"],
        http=httpx.Client(transport=httpx.MockTransport(refusing)),
        prefs_path=tmp_path / "cli.json",
    )


# --- --version and --help -----------------------------------------------------


def test_version_prints_the_version_the_service_carries_and_asks_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    carried = re.search(r'^__version__ = "([^"]+)"', VERSION_FILE.read_text("utf-8"), re.M)
    assert carried is not None

    assert run("--version", tmp_path=tmp_path) == 0

    assert capsys.readouterr().out == carried.group(1) + "\n"


def test_help_names_the_commands_and_the_switches_and_asks_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("--help", tmp_path=tmp_path) == 0

    out = capsys.readouterr().out
    # The program's own name stands wherever the sentence names it.
    assert out.splitlines()[0] == (
        "Run exe on its own or with options, a command, or both. Example: exe --theme pearl"
    )
    for word in (
        "service start", "service run", "service stop", "service status", "install",
        "model", "theme", "--url", "--lang", "--theme", "--chat", "--password-file",
        "--version", "--help",
    ):
        assert re.search(rf"^  {re.escape(word)}\s", out, re.M), word
    # The two words that went are not listed, and neither is the command
    # that stops an answer: from outside none runs.
    for word in ("serve", "stop"):
        assert not re.search(rf"^  {word}\s", out, re.M), word
    assert "http://127.0.0.1:8090" in out
    assert "de, en" in out
    assert "exe, darkmatter, moune, heaven, pearl" in out
    # The switch is not listed under its old name as well.
    assert "--look" not in out


def test_the_help_command_writes_what_the_help_switch_writes_and_asks_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("--help", tmp_path=tmp_path) == 0
    switch = capsys.readouterr().out

    assert run("help", tmp_path=tmp_path) == 0

    command = capsys.readouterr()
    assert command.out == switch
    assert command.err == ""
    # Not the chat's list, whose commands stand with a slash.
    assert "/model" not in command.out


@pytest.mark.parametrize(
    ("language", "sentence"),
    [("en", "Set the theme: "), ("de", "Erscheinungsbild festlegen: ")],
)
def test_help_names_the_theme_switch_with_every_theme_it_takes(language: str, sentence: str) -> None:
    lines = [line for line in help_text(Texts(language)).splitlines() if line.startswith("  --theme ")]
    assert len(lines) == 1
    assert lines[0].split(None, 1)[1] == sentence + ", ".join(themes.available())


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_help_names_the_themes_the_client_has_and_keeps_no_list_of_its_own(
    language: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(themes, "available", lambda: ("auto", "exe", "neon"))
    lines = [line for line in help_text(Texts(language)).splitlines() if line.startswith("  --theme ")]
    assert len(lines) == 1 and lines[0].endswith(": auto, exe, neon")


def asked_nothing(*arguments: str, tmp_path: Path) -> int:
    """The program with ``arguments`` exactly as given, against an outside
    that must never be asked anything."""
    return main(
        list(arguments),
        http=httpx.Client(transport=httpx.MockTransport(refusing)),
        prefs_path=tmp_path / "cli.json",
    )


@pytest.mark.parametrize(
    ("typed", "name"),
    [
        # The parser reads a word behind a switch it does not know as the
        # command; the switch is what is wrong, not the word.
        (("--look", "pearl"), "--look"),
        (("--look=pearl",), "--look"),
        (("--look",), "--look"),
    ],
)
@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("en", "Unknown option: {name}. Use exe --help to list available options."),
        ("de", "Unbekannte Option: {name}. exe --help zeigt die verfügbaren Optionen."),
    ],
)
def test_a_switch_the_client_does_not_have_is_named_in_the_catalogues_words(
    typed: tuple[str, ...],
    name: str,
    language: str,
    sentence: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The outside of ``asked_nothing`` fails the test on any request.
    assert asked_nothing(*typed, "--lang", language, tmp_path=tmp_path) == 2
    shown = capsys.readouterr()
    assert shown.out == ""
    # The parser's own usage line and its sentence are not in the output.
    assert shown.err == sentence.format(name=name) + "\n"
    assert not (tmp_path / "cli.json").exists()


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("en", "Unknown command: modell. Use exe --help to list available commands."),
        ("de", "Unbekannter Befehl: modell. exe --help zeigt die verfügbaren Befehle."),
    ],
)
def test_a_command_the_client_does_not_have_is_named_in_the_catalogues_words(
    language: str, sentence: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert asked_nothing("modell", "--lang", language, tmp_path=tmp_path) == 2
    shown = capsys.readouterr()
    assert shown.out == "" and shown.err == sentence + "\n"
    assert not (tmp_path / "cli.json").exists()


def test_a_word_behind_a_known_command_is_a_command_the_client_does_not_have(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert asked_nothing("install", "extra", "--lang", "en", tmp_path=tmp_path) == 2
    assert capsys.readouterr().err == (
        "Unknown command: extra. Use exe --help to list available commands.\n"
    )


@pytest.mark.parametrize(
    ("switch", "value", "language", "sentence"),
    [
        ("--theme", "neon", "en", "“neon” is not available."),
        ("--theme", "neon", "de", "„neon“ ist nicht verfügbar."),
        ("--lang", "xx", "en", "“xx” is not available."),
    ],
)
def test_a_value_a_switch_does_not_take_gets_the_sentence_and_the_switchs_help_line(
    switch: str,
    value: str,
    language: str,
    sentence: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The switch still takes only the names of the themes and the codes of
    the languages — and now says so in the catalogue's words."""
    arguments = [switch, value] if switch == "--lang" else [switch, value, "--lang", language]
    assert asked_nothing(*arguments, tmp_path=tmp_path) == 2
    lines = capsys.readouterr().err.splitlines()
    assert lines[0] == sentence
    wanted = [line for line in help_text(Texts("en" if switch == "--lang" else language)).splitlines()
              if line.startswith(f"  {switch} ")]
    assert lines[1:] == wanted
    assert not (tmp_path / "cli.json").exists()


@pytest.mark.parametrize("typed", [("--l", "de"), ("--t", "pearl"), ("--pass", "file"), ("--ver",)])
def test_a_beginning_of_a_switch_is_a_switch_the_client_does_not_have(
    typed: tuple[str, ...], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The help names a switch in full, and only that spelling counts."""
    assert asked_nothing(*typed, "--lang", "en", tmp_path=tmp_path) == 2
    assert capsys.readouterr().err == (
        f"Unknown option: {typed[0]}. Use exe --help to list available options.\n"
    )
    # Nothing was taken from it: no language, no theme, nothing remembered.
    assert not (tmp_path / "cli.json").exists()


@pytest.mark.parametrize(
    "switch", ["--url", "--lang", "--theme", "--chat", "--password-file", "--version", "--help"]
)
def test_every_switch_the_help_names_is_taken_as_it_is_spelled_out(
    switch: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Silence probe: the switches of the help are no unknown options. The
    ones that do something before any service is asked end at once."""
    if switch in ("--version", "--help"):
        assert asked_nothing(switch, tmp_path=tmp_path) == 0
        assert "Unknown" not in capsys.readouterr().err
    else:
        # A switch that wants a value and is given none says what it takes;
        # that is its own line, not the sentence of an unknown option.
        assert asked_nothing(switch, tmp_path=tmp_path) == 2
        err = capsys.readouterr().err
        assert err.startswith(f"  {switch} ") and "Unknown" not in err


def test_the_short_help_switch_is_still_taken(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert asked_nothing("-h", "--lang", "en", tmp_path=tmp_path) == 0
    assert capsys.readouterr().out.startswith("Run exe on its own")


@pytest.mark.parametrize("language", ["en", "de"])
def test_no_sentence_of_the_client_says_look_any_more(language: str) -> None:
    client = catalogue_of(language)["cli"]
    sentences = sentences_below(client, "cli")
    assert len(sentences) > 70
    assert [key for key, sentence in sentences if "look" in sentence.lower()] == []
    # And the key of the old sentence is gone with it.
    assert "help_look" not in client and "help_theme" in client


def test_help_speaks_the_language_asked_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            ["--lang", "de", "-h"],
            http=httpx.Client(transport=httpx.MockTransport(refusing)),
            prefs_path=tmp_path / "cli.json",
        )
        == 0
    )

    out = capsys.readouterr().out
    assert out.startswith("exe allein oder mit Optionen, einem Befehl oder beidem aufrufen.")
    assert "\nBefehle\n" in out
    assert "\nOptionen\n" in out


# --- stop ---------------------------------------------------------------------


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A data folder of this test's own, the way the service would be given
    one."""
    root = tmp_path / "daten"
    monkeypatch.setenv(service.DATA_VARIABLE, str(root))
    monkeypatch.setattr(service, "STOP_POLL_SECONDS", 0.0)
    return root


def note(root: Path, pid: int = 4242, port: int = PORT) -> Path:
    file = service.note_file(port)
    assert file == root / "data" / f".dienst-{port}.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"pid": pid, "port": port}), encoding="utf-8")
    return file


class Listening:
    """Whether the port answers: it does until the process was signalled —
    the way a service lets go of its port when asked to end."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, ends: bool = True) -> None:
        self.answering = True
        self.signals: list[tuple[int, Any]] = []
        self.ends = ends
        monkeypatch.setattr(service, "answering", lambda host, port: self.answering)
        monkeypatch.setattr(service.os, "kill", self.kill)
        # The process the note names has been there since long before the
        # note was written: it is the one that wrote it.
        monkeypatch.setattr(service, "began", lambda pid: 0.0)
        # The way these tests follow is the one that signals the process;
        # on Windows the service is asked through a marker file and only
        # then ended from outside, which test_service_windows_stop.py holds.
        monkeypatch.setattr(service, "_on_windows", lambda: False)

    def kill(self, pid: int, number: Any) -> None:
        self.signals.append((pid, number))
        if self.ends:
            self.answering = False


def test_stop_asks_the_process_from_the_note_to_end_and_waits_for_the_port(
    data_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    note(data_root)
    listening = Listening(monkeypatch)

    assert run("service", "stop", "--url", OWN_ADDRESS, tmp_path=tmp_path) == 0

    assert listening.signals == [(4242, signal.SIGTERM)]
    assert capsys.readouterr().out == Texts("en").t("cli.service_stopped", port=8123) + "\n"


def test_stop_without_a_note_says_so_and_does_nothing(
    data_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listening = Listening(monkeypatch)

    assert run("service", "stop", "--url", OWN_ADDRESS, tmp_path=tmp_path) == 0

    assert listening.signals == []
    assert capsys.readouterr().out == Texts("en").t("cli.service_not_running", port=8123) + "\n"


def test_stop_with_a_note_but_a_silent_port_signals_nobody(
    data_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    note(data_root)
    listening = Listening(monkeypatch)
    listening.answering = False

    assert run("service", "stop", "--url", OWN_ADDRESS, tmp_path=tmp_path) == 0

    assert listening.signals == []
    assert Texts("en").t("cli.service_not_running", port=8123) in capsys.readouterr().out


def test_stop_with_a_process_that_is_gone_already_says_none_is_running(
    data_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    note(data_root)
    listening = Listening(monkeypatch)

    def gone(pid: int, number: Any) -> None:
        raise ProcessLookupError(pid)

    monkeypatch.setattr(service.os, "kill", gone)

    assert run("service", "stop", "--url", OWN_ADDRESS, tmp_path=tmp_path) == 0

    assert listening.signals == []
    assert Texts("en").t("cli.service_not_running", port=8123) in capsys.readouterr().out


def test_stop_says_when_the_service_keeps_its_port_past_the_wait(
    data_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    note(data_root)
    listening = Listening(monkeypatch, ends=False)
    monkeypatch.setattr(service, "STOP_WAIT_SECONDS", 0.0)

    assert run("service", "stop", "--url", OWN_ADDRESS, tmp_path=tmp_path) == 1

    assert listening.signals == [(4242, signal.SIGTERM)]
    assert Texts("en").t("cli.service_not_stopped", port=8123) in capsys.readouterr().err


def test_stop_of_a_process_that_is_not_ours_says_the_systems_words(
    data_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    note(data_root)
    Listening(monkeypatch)

    def refused(pid: int, number: Any) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(service.os, "kill", refused)

    assert run("service", "stop", "--url", OWN_ADDRESS, tmp_path=tmp_path) == 1

    assert "Operation not permitted" in capsys.readouterr().err


def test_stop_at_a_network_address_goes_by_the_note_in_this_machines_folder(
    data_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A service of this machine may listen at a network address: the note
    under its port says so, and it is stopped like any other. Without a
    note, the address is another machine's — nothing is signalled."""
    listening = Listening(monkeypatch)
    assert run("service", "stop", "--url", "http://100.100.0.9:8123", tmp_path=tmp_path) == 0
    assert listening.signals == []
    assert Texts("en").t("cli.service_not_running", port=8123) in capsys.readouterr().out

    note(data_root)
    assert run("service", "stop", "--url", "http://100.100.0.9:8123", tmp_path=tmp_path) == 0
    assert listening.signals == [(4242, signal.SIGTERM)]
    assert Texts("en").t("cli.service_stopped", port=8123) in capsys.readouterr().out


def test_stop_at_the_unspecified_address_probes_the_loopback_one(
    data_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    note(data_root)
    probed: list[str] = []
    listening = Listening(monkeypatch)

    def answering(host: str, port: int) -> bool:
        probed.append(host)
        return listening.answering

    monkeypatch.setattr(service, "answering", answering)
    assert run("service", "stop", "--url", "http://0.0.0.0:8123", tmp_path=tmp_path) == 0
    assert probed and set(probed) == {"127.0.0.1"}
    assert listening.signals == [(4242, signal.SIGTERM)]


def test_stop_at_an_address_without_a_port_says_what_url_takes(
    data_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listening = Listening(monkeypatch)
    assert run("service", "stop", "--url", "http://localhost", tmp_path=tmp_path) == 2
    assert listening.signals == []
    assert "http://127.0.0.1:8090" in capsys.readouterr().err


def test_a_half_written_or_foreign_note_names_nobody(data_root: Path) -> None:
    file = service.note_file(PORT)
    file.parent.mkdir(parents=True)
    file.write_text('{"pid": 42', encoding="utf-8")
    assert service.read_note(file) is None
    file.write_text('{"port": 8123}', encoding="utf-8")
    assert service.read_note(file) is None
    file.write_text('"just a string"', encoding="utf-8")
    assert service.read_note(file) is None
    assert service.read_note(file.with_name("missing.json")) is None


def test_the_data_root_follows_the_services_own_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(service.DATA_VARIABLE, raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert service.data_root() == service.START_SCRIPT.parent
    monkeypatch.setenv(service.DATA_VARIABLE, "/somewhere/else")
    assert service.data_root() == Path("/somewhere/else")
