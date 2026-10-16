"""On a small machine the voice is not kept loaded unless somebody says so.

"Keep model loaded" shipped on everywhere. On a MacBook Air with 8 GB the
speech model and the kept voice filled the memory and the Mac stalled in the
middle of a conversation. The works answer is now off on a machine with 8 GB
or less, and on everywhere else, also where the memory cannot be read. A choice
the person stored beats the works answer either way, and the window shows what
the service says.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import diktatsprachewahl

ROOT = Path(__file__).resolve().parent.parent


class _Settings:
    def __init__(self, stored: dict) -> None:
        self._stored = stored

    def zusammengefuehrt(self, key, vorgabe=None):
        return dict(self._stored)


class _Repositories:
    def __init__(self, stored: dict | None = None) -> None:
        self.einstellungen = _Settings(stored or {})


@pytest.mark.parametrize(
    ("gb", "expected"),
    [(8.0, False), (4.0, False), (7.5, False), (8.1, True), (16.0, True), (64.0, True), (None, True)],
)
def test_the_works_answer_follows_the_memory_of_the_machine(monkeypatch, gb, expected):
    monkeypatch.setattr(diktatsprachewahl, "gesamt_gb", lambda: gb)
    assert diktatsprachewahl.keep_model_default() is expected
    assert diktatsprachewahl.vorgaben()["keep_model_in_memory"] is expected
    assert diktatsprachewahl.keep_model_in_memory(_Repositories()) is expected


def test_the_limit_is_eight_gigabytes():
    assert diktatsprachewahl.SMALL_MACHINE_GB == 8


def test_silence_a_stored_choice_beats_the_works_answer_on_both_sides(monkeypatch):
    monkeypatch.setattr(diktatsprachewahl, "gesamt_gb", lambda: 8.0)
    assert diktatsprachewahl.keep_model_in_memory(_Repositories({"keep_model_in_memory": True})) is True
    monkeypatch.setattr(diktatsprachewahl, "gesamt_gb", lambda: 64.0)
    assert diktatsprachewahl.keep_model_in_memory(_Repositories({"keep_model_in_memory": False})) is False


def test_the_window_is_told_the_works_answer_of_the_service(client: TestClient, monkeypatch):
    monkeypatch.setattr(diktatsprachewahl, "gesamt_gb", lambda: 8.0)
    shown = client.get("/api/v1/sprachserver").json()["diktat_vorgaben"]
    assert shown["keep_model_in_memory"] is False
    monkeypatch.setattr(diktatsprachewahl, "gesamt_gb", lambda: 16.0)
    shown = client.get("/api/v1/sprachserver").json()["diktat_vorgaben"]
    assert shown["keep_model_in_memory"] is True


def test_the_window_assumes_nothing_where_the_service_names_a_works_answer():
    panel = (ROOT / "frontend/src/teile/Sprachserver.svelte").read_text(encoding="utf-8")
    assert "diktat.keep_model_in_memory ?? werk.keep_model_in_memory ?? false" in panel
    assert "keep_model_in_memory ?? true" not in panel
