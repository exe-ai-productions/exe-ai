"""The architecture a server's build does not know is named on the page of
every server, not only on the chat server's.

The runner says it with its state (tests/test_modellrunner.py), the live line
carries it (tests/test_ereignisstrom.py), and each server's answer repeats it
so a page opened afterwards finds it there. Here: the four answers, and the
four pages that read them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"

# (route of the answer, runner on app.state, page of the window)
SERVERS = [
    ("/api/v1/agentenmodell", "agentenrunner", "Agentserver.svelte"),
    ("/api/v1/einbettungsserver", "einbettungsrunner", "Einbettungsserver.svelte"),
    ("/api/v1/sprachserver", "sprachrunner", "Sprachserver.svelte"),
    ("/api/v1/bereinigungsserver", "sprachputzrunner", "Bereinigungsserver.svelte"),
]


@pytest.mark.parametrize(("route", "runner_name", "_page"), SERVERS)
def test_the_answer_names_the_architecture_the_last_start_failed_on(
    client: TestClient, monkeypatch, route, runner_name, _page
):
    runner = getattr(client.app.state, runner_name)
    monkeypatch.setattr(runner, "unknown_architecture", lambda: "diffusion-gemma")
    assert client.get(route).json()["unknown_architecture"] == "diffusion-gemma"


@pytest.mark.parametrize(("route", "_runner_name", "_page"), SERVERS)
def test_a_server_that_never_failed_names_no_architecture(
    client: TestClient, route, _runner_name, _page
):
    """Silence: nothing failed, so the field is there and says nothing."""
    daten = client.get(route).json()
    assert "unknown_architecture" in daten
    assert daten["unknown_architecture"] is None


@pytest.mark.parametrize(("_route", "_runner_name", "page"), SERVERS)
def test_each_page_shows_the_sentence_from_its_own_answer(_route, _runner_name, page):
    quelle = (FRONTEND / "teile" / page).read_text(encoding="utf-8")
    assert "import Startfehler from './Startfehler.svelte'" in quelle
    assert "<Startfehler arch={auskunft?.unknown_architecture} />" in quelle


def test_the_shared_line_uses_the_existing_sentence():
    quelle = (FRONTEND / "teile" / "Startfehler.svelte").read_text(encoding="utf-8")
    assert "t('modell.unknown_architecture', { arch })" in quelle
    # Nothing to say, nothing drawn.
    assert re.search(r"\{#if arch\}", quelle)


def test_the_embedding_page_reads_again_when_its_server_speaks():
    """It keeps no beat of its own, so the announcement of its server is the
    only thing that can tell it a start failed while nobody watched."""
    seite = (FRONTEND / "teile" / "Einbettungsserver.svelte").read_text(encoding="utf-8")
    assert "neuigkeit.einbettung" in seite
    leitung = (FRONTEND / "lib" / "ereignisstrom.svelte.js").read_text(encoding="utf-8")
    # The name is one word in two files: what the service sends is what the
    # window listens for.
    from app import runnerzustand

    assert f"ereignis?.runner === '{runnerzustand.EMBEDDING}'" in leitung
    assert "neuigkeit.einbettung += 1" in leitung


def test_the_runner_names_of_the_line_match_the_server():
    from app import agentenserver, einbettungsserver, runnerzustand, sprachserver

    # Every server builds its runner with a reporter under its own name.
    for modul, name in (
        (agentenserver, "AGENT"),
        (einbettungsserver, "EMBEDDING"),
    ):
        assert f"runnerzustand.melder(runnerzustand.{name})" in Path(modul.__file__).read_text(
            encoding="utf-8"
        )
    quelle = Path(sprachserver.__file__).read_text(encoding="utf-8")
    assert "runnerzustand.melder(runnerzustand.SPEECH)" in quelle
    assert "runnerzustand.melder(runnerzustand.CLEANUP)" in quelle
