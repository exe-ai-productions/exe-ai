"""The program's roles at its door: called plainly it serves and opens the
interface; called with ``--serve`` it serves and opens nothing."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn

import start
from app import config


class Threads:
    """Keeps every thread the program would have started, and starts none:
    the one that opens the window polls the port for half a minute."""

    def __init__(self) -> None:
        self.targets: list[Any] = []

    def __call__(self, *, target: Any, args: tuple = (), daemon: bool = False) -> Any:
        self.targets.append(target)
        return SimpleNamespace(start=lambda: None)


@pytest.fixture
def door(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The program's surroundings, every one of them a stand-in: the
    configuration names a port, nothing listens on it, serving is kept
    instead of done, and no thread runs."""
    served: list[dict[str, Any]] = []
    threads = Threads()
    monkeypatch.setattr(
        config, "get_config", lambda: SimpleNamespace(app=SimpleNamespace(host="127.0.0.1", port=8123))
    )
    monkeypatch.setattr(start, "_antwortet", lambda port, host="127.0.0.1": False)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: served.append(kwargs))
    monkeypatch.setattr(threading, "Thread", threads)
    return {"served": served, "threads": threads}


def test_serve_serves_without_opening_the_interface(door: dict[str, Any]) -> None:
    assert start.main(["--serve"]) == 0

    assert [entry["port"] for entry in door["served"]] == [8123]
    assert door["served"][0]["host"] == "127.0.0.1"
    assert door["threads"].targets == []


def test_called_plainly_the_program_opens_the_interface_beside_serving(door: dict[str, Any]) -> None:
    assert start.main([]) == 0

    assert [entry["port"] for entry in door["served"]] == [8123]
    assert door["threads"].targets == [start._browser_oeffnen]


def test_serve_with_a_service_already_on_the_port_serves_nothing(
    door: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(start, "_antwortet", lambda port, host="127.0.0.1": True)

    assert start.main(["--serve"]) == 1

    assert door["served"] == []
    assert door["threads"].targets == []
    assert "A service is already listening on port 8123" in capsys.readouterr().err
