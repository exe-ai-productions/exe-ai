"""The section "llama.cpp" stands in the window of every server that starts
that program, as one piece.

Before, the check for a newer build, the fetch and the way back to the tested
build stood only in the model server's window; the agent, embedding, speech
and cleaning servers start the same program and had no button. Now
`LlamaCppSection.svelte` draws the section once and each window places it
above its log. Its routes are the program's (`/runner/programm`), so a press
in one window is a press for all; what differs per window is only where its
four fields come from, and they come from the one function
`app.api.v1.runner.program_state`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import runner as runner_module

SOURCE = Path(__file__).resolve().parent.parent / "frontend" / "src"
TEILE = SOURCE / "teile"

# (route of the answer, window)
SERVERS = [
    ("/api/v1/runner", "Modellserver.svelte"),
    ("/api/v1/agentenmodell", "Agentserver.svelte"),
    ("/api/v1/einbettungsserver", "Einbettungsserver.svelte"),
    ("/api/v1/sprachserver", "Sprachserver.svelte"),
    ("/api/v1/bereinigungsserver", "Bereinigungsserver.svelte"),
]
FIELDS = ("programm", "version", "updatable", "restorable")


@pytest.mark.parametrize(("route", "_page"), SERVERS)
def test_every_answer_carries_the_four_fields_of_the_program(client: TestClient, route, _page):
    answer = client.get(route).json()
    for field in FIELDS:
        assert field in answer, (route, field)


@pytest.mark.parametrize(("route", "_page"), SERVERS)
def test_every_answer_reads_the_program_through_the_one_function(
    client: TestClient, monkeypatch, route, _page
):
    """The build, whether it can be updated and whether it can be taken back
    are read once, in one place — five answers, the same words."""
    program = runner_module._Program(
        path=Path("/opt/test/llama-server"),
        version="b9999",
        fetched="b9999",
        own_first=True,
    )
    monkeypatch.setattr(runner_module, "_program", lambda runner, config: program)
    answer = client.get(route).json()
    assert answer["programm"] == str(program.path)
    assert answer["version"] == "b9999"
    assert answer["updatable"] is True
    assert answer["restorable"] is True


@pytest.mark.parametrize(("route", "_page"), SERVERS)
def test_a_program_the_settings_name_offers_nothing_in_any_window(
    client: TestClient, monkeypatch, route, _page
):
    """The silence check: where a program named by hand comes first, a
    fetched build would never run — no window offers a check or a way back."""
    program = runner_module._Program(
        path=Path("/usr/local/bin/llama-server"),
        version="b100",
        fetched=None,
        own_first=False,
    )
    monkeypatch.setattr(runner_module, "_program", lambda runner, config: program)
    answer = client.get(route).json()
    assert answer["version"] == "b100"
    assert answer["updatable"] is False
    assert answer["restorable"] is False


@pytest.mark.parametrize(("_route", "page"), SERVERS)
def test_each_window_places_the_section_and_does_not_draw_it(_route, page):
    source = (TEILE / page).read_text(encoding="utf-8")
    assert "import LlamaCppSection from './LlamaCppSection.svelte'" in source
    assert "<LlamaCppSection {auskunft} onrefresh={laden} />" in source
    # The section is the component's; no window carries its own head line or
    # its own buttons any more.
    assert 'titel="llama.cpp"' not in source
    for key in (
        "bildserver.nach_updates_suchen",
        "bildserver.generator_aktualisieren",
        "bildserver.restore_tested_build",
    ):
        assert key not in source, (page, key)


def test_the_check_for_updates_is_drawn_only_by_the_section_and_the_picture_server():
    carriers = sorted(
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*")
        if path.suffix in {".svelte", ".js"}
        and "bildserver.nach_updates_suchen" in path.read_text(encoding="utf-8")
    )
    assert carriers == [
        # The phone pages draw the same two buttons in their own shape.
        "phone/servers/ImageServerView.svelte",
        "phone/servers/ProgramSection.svelte",
    ]
    # The desktop draws the check as one sign, the piece both programs share.
    updaters = sorted(
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*")
        if path.suffix in {".svelte", ".js"}
        and "<UpdateButton" in path.read_text(encoding="utf-8")
    )
    assert updaters == ["teile/Bildserver.svelte", "teile/LlamaCppSection.svelte"]


def test_the_section_stands_above_the_log_in_every_window():
    for _route, page in SERVERS:
        source = (TEILE / page).read_text(encoding="utf-8")
        assert source.index("<LlamaCppSection {auskunft} onrefresh={laden} />") < source.index("{#snippet unten()}"), page


def test_the_picture_servers_block_is_unchanged():
    """The silence check: the section "sd.cpp" is still the picture server's
    own, with its own routes."""
    source = (TEILE / "Bildserver.svelte").read_text(encoding="utf-8")
    assert 'titel="sd.cpp"' in source
    assert "LlamaCppSection" not in source
    assert "<UpdateButton" in source


def test_a_window_reads_again_when_a_fetch_ends():
    """The embedding window keeps no beat of its own: without being asked it
    would name the old build after an update. The section asks, once, at the
    end of a fetch — and not when it merely opens."""
    section = (TEILE / "LlamaCppSection.svelte").read_text(encoding="utf-8")
    assert section.count("onrefresh?.()") == 1
    ended = section.index("if (fetchingBefore && !fetching) {")
    assert ended < section.index("onrefresh?.()") < section.index("fetchingBefore = fetching")
