"""The embedding server starts with the values stored beside its file and port:
the window (context), the batch size, the pooling kind, the layers on the
graphics card, the CPU threads, the memory lock and the parallel requests.

Before, every start ran with a window of 2048, a batch of 2048, `--pooling mean`
and 99 layers, whatever was stored. A model with a pooling kind of its own
answered with other vectors than it should, a text over 2048 tokens was
refused, and neither the layers nor the threads, the memory lock or the
parallel requests could be set. Shipped, nothing named is said on the command
line except what the server has always been given: the window and the batch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

EMBEDDING = "/api/v1/settings/global/embedding"
START = "/api/v1/einbettungsserver/start"
STATE = "/api/v1/einbettungsserver"


def _command(client: TestClient, monkeypatch, stored: dict | None = None) -> list[str]:
    """The command line a start with these stored values runs."""
    if stored is not None:
        assert client.patch(EMBEDDING, json={"wert": stored}).status_code == 200
    seen: dict = {}
    runner = client.app.state.einbettungsrunner
    monkeypatch.setattr(runner, "starten", lambda modell, **kw: seen.update(kw))
    assert client.post(START, json={"modell": "e.gguf"}).status_code == 200
    return runner.befehl(
        "e.gguf",
        seen["kontext"],
        seen["schichten"],
        8081,
        fein=seen["fein"],
        extra_flags=seen["extra_flags"],
    )


def _value_after(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def test_with_nothing_stored_the_start_says_what_it_always_said_and_no_more(client, monkeypatch):
    command = _command(client, monkeypatch)
    assert "--embedding" in command
    assert _value_after(command, "--ctx-size") == "2048"
    assert _value_after(command, "--batch-size") == "2048"
    assert _value_after(command, "--ubatch-size") == "2048"
    for flag in ("--pooling", "--n-gpu-layers", "--threads", "-t", "--load-mode", "--parallel"):
        assert flag not in command, (flag, command)


def test_every_stored_value_stands_on_the_command_line(client, monkeypatch):
    command = _command(
        client,
        monkeypatch,
        {
            "context": 8192, "batch": 4096, "pooling": "cls", "layers": 20,
            "threads": 6, "mlock": True, "parallel": 4,
        },
    )
    assert _value_after(command, "--ctx-size") == "8192"
    assert _value_after(command, "--batch-size") == "4096"
    assert _value_after(command, "--ubatch-size") == "4096"
    assert _value_after(command, "--pooling") == "cls"
    assert _value_after(command, "--n-gpu-layers") == "20"
    assert _value_after(command, "--threads") == "6"
    assert _value_after(command, "--load-mode") == "mmap+mlock"
    assert _value_after(command, "--parallel") == "4"
    assert command.count("--ctx-size") == 1


@pytest.mark.parametrize("kind", ["mean", "cls", "last"])
def test_each_named_pooling_kind_travels_and_the_standard_says_nothing(client, monkeypatch, kind):
    assert _value_after(_command(client, monkeypatch, {"pooling": kind}), "--pooling") == kind
    assert "--pooling" not in _command(client, monkeypatch, {"pooling": ""})


def test_an_unknown_pooling_kind_falls_back_to_the_standard(client, monkeypatch):
    assert "--pooling" not in _command(client, monkeypatch, {"pooling": "banana"})


def test_a_batch_over_the_window_is_set_to_the_window(client, monkeypatch):
    command = _command(client, monkeypatch, {"context": 4096, "batch": 16384})
    assert _value_after(command, "--batch-size") == "4096"
    assert _value_after(command, "--ubatch-size") == "4096"


def test_a_batch_stored_before_the_window_was_lowered_is_held_to_the_window(client, monkeypatch):
    client.patch(EMBEDDING, json={"wert": {"context": 16384, "batch": 8192}})
    command = _command(client, monkeypatch, {"context": 2048})
    assert _value_after(command, "--batch-size") == "2048"


@pytest.mark.parametrize(("sent", "expected"), [(100, "2048"), (99999, "32768"), (3000, "3000")])
def test_a_window_outside_its_bounds_is_brought_in(client, monkeypatch, sent, expected):
    assert _value_after(_command(client, monkeypatch, {"context": sent}), "--ctx-size") == expected


def test_threads_zero_and_parallel_empty_say_nothing_and_the_numbers_are_bounded(client, monkeypatch):
    command = _command(client, monkeypatch, {"threads": 0, "parallel": None, "mlock": False})
    for flag in ("--threads", "--parallel", "--load-mode"):
        assert flag not in command
    command = _command(client, monkeypatch, {"threads": 99999, "parallel": 999})
    assert _value_after(command, "--threads") == "256"
    assert _value_after(command, "--parallel") == "64"


def test_a_value_that_is_no_number_is_not_stored_and_a_word_for_no_says_no(client: TestClient):
    """NaN and Infinity are no numbers; a stored value stays where a bad one
    arrives; the string "false" is not a yes."""
    client.patch(EMBEDDING, json={"wert": {"layers": 20, "threads": 3}})
    answer = client.patch(
        EMBEDDING,
        content='{"wert": {"context": NaN, "threads": Infinity, "layers": "abc", "mlock": "false"}}',
        headers={"Content-Type": "application/json"},
    )
    assert answer.status_code == 200, answer.text
    stored = client.get(STATE).json()
    assert stored["layers"] == 20 and stored["threads"] == 3
    assert stored["context"] == 2048 and stored["mlock"] is False


def test_the_state_answer_carries_the_shipped_values_and_the_stored_ones(client: TestClient):
    shipped = client.get(STATE).json()
    assert {key: shipped[key] for key in (
        "context", "batch", "pooling", "layers", "threads", "mlock", "parallel")} == {
        "context": 2048, "batch": 2048, "pooling": "", "layers": None,
        "threads": 0, "mlock": False, "parallel": None,
    }
    client.patch(EMBEDDING, json={"wert": {
        "context": 8192, "batch": 4096, "pooling": "last", "layers": 12,
        "threads": 3, "mlock": True, "parallel": 2,
    }})
    stored = client.get(STATE).json()
    assert {key: stored[key] for key in (
        "context", "batch", "pooling", "layers", "threads", "mlock", "parallel")} == {
        "context": 8192, "batch": 4096, "pooling": "last", "layers": 12,
        "threads": 3, "mlock": True, "parallel": 2,
    }


def test_silence_the_file_and_the_port_are_stored_and_used_as_before(client: TestClient, monkeypatch):
    folder = Path(client.get(STATE).json()["ordner"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "e.gguf").write_bytes(b"GGUF")
    client.patch(EMBEDDING, json={"wert": {"model": "e.gguf", "port": 8188}})
    seen: dict = {}
    monkeypatch.setattr(
        client.app.state.einbettungsrunner, "starten", lambda modell, **kw: seen.update(kw)
    )
    client.post(START, json={"modell": "e.gguf"})
    assert seen["port"] == 8188
    answer = client.get(STATE).json()
    assert answer["modell"] == "e.gguf" and answer["port"] == 8188


def test_silence_the_command_lines_of_the_model_and_agent_servers_stay_the_same(client: TestClient):
    """Nothing here says `--embedding` or `--pooling`, and the extra words of
    one start are empty where nobody passes any."""
    for runner in (client.app.state.modellrunner, client.app.state.agentenrunner):
        plain = runner.befehl("m.gguf", 16384, None, 8080)
        assert plain == runner.befehl("m.gguf", 16384, None, 8080, extra_flags=())
        for word in ("--embedding", "--pooling", "--batch-size", "--ubatch-size"):
            assert word not in plain, (word, plain)
