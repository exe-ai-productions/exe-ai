"""The window page tells the service which look and which language it shows
now, and the service passes them on to whoever watches its event stream
(`POST /api/v1/events/window-theme`, `app/api/v1/ereignisse.py`). The
terminal client inside the window is the one that listens
(`tests/cli/test_window_theme.py`)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ereignisstrom
from app.api.v1.ereignisse import FensterThema, fenster_thema

WURZEL = Path(__file__).resolve().parent.parent


async def test_the_name_goes_to_the_watchers_of_the_stream_once():
    lauscher = ereignisstrom.strom.zuschauen()
    erste = asyncio.ensure_future(asyncio.wait_for(lauscher.__anext__(), timeout=2.0))
    schluss = asyncio.get_running_loop().time() + 2.0
    while ereignisstrom.strom.zuschauer < 1:
        assert asyncio.get_running_loop().time() < schluss, "watcher never arrived"
        await asyncio.sleep(0.005)
    answer = await fenster_thema(FensterThema(theme="pearl"))
    assert answer == {"theme": "pearl"}
    assert await erste == {"typ": "window_theme", "theme": "pearl"}
    await lauscher.aclose()


@pytest.mark.parametrize("name", ["pearl", "darkmatter", "exe", "a"])
def test_a_short_lower_case_name_is_taken(client: TestClient, name: str):
    answer = client.post("/api/v1/events/window-theme", json={"theme": name})
    assert answer.status_code == 200
    assert answer.json() == {"theme": name}


@pytest.mark.parametrize(
    "body",
    [
        {"theme": ""},
        {"theme": "Pearl"},
        {"theme": "../etc"},
        {"theme": "x" * 17},
        {"theme": "two words"},
        {"theme": 7},
        {},
    ],
)
def test_a_name_outside_the_pattern_is_refused_and_announces_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, body: dict
):
    """The silence probe: anything but a short lower-case word is 422 and
    nothing goes over the stream."""
    announced: list[tuple] = []
    monkeypatch.setattr(
        ereignisstrom.strom, "melden", lambda typ, **daten: announced.append((typ, daten))
    )
    answer = client.post("/api/v1/events/window-theme", json=body)
    assert answer.status_code == 422
    assert announced == []


async def test_a_language_goes_over_the_stream_with_or_without_a_look():
    lauscher = ereignisstrom.strom.zuschauen()
    erste = asyncio.ensure_future(asyncio.wait_for(lauscher.__anext__(), timeout=2.0))
    schluss = asyncio.get_running_loop().time() + 2.0
    while ereignisstrom.strom.zuschauer < 1:
        assert asyncio.get_running_loop().time() < schluss, "watcher never arrived"
        await asyncio.sleep(0.005)
    answer = await fenster_thema(FensterThema(language="en"))
    assert answer == {"language": "en"}
    assert await erste == {"typ": "window_theme", "language": "en"}
    zweite = asyncio.ensure_future(asyncio.wait_for(lauscher.__anext__(), timeout=2.0))
    answer = await fenster_thema(FensterThema(theme="pearl", language="de"))
    assert answer == {"theme": "pearl", "language": "de"}
    assert await zweite == {"typ": "window_theme", "theme": "pearl", "language": "de"}
    await lauscher.aclose()


def test_a_known_language_is_taken(client: TestClient):
    answer = client.post("/api/v1/events/window-theme", json={"language": "en"})
    assert answer.status_code == 200
    assert answer.json() == {"language": "en"}


@pytest.mark.parametrize(
    "body",
    [{"language": "xx"}, {"language": ""}, {"language": "EN"}, {"language": 7}, {"theme": None, "language": None}],
)
def test_an_unknown_language_is_refused_and_announces_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, body: dict
):
    """The silence probe: a language without a catalogue is 422, and so is a
    request that names nothing; nothing goes over the stream."""
    announced: list[tuple] = []
    monkeypatch.setattr(
        ereignisstrom.strom, "melden", lambda typ, **daten: announced.append((typ, daten))
    )
    answer = client.post("/api/v1/events/window-theme", json=body)
    assert answer.status_code == 422
    assert announced == []


def test_the_window_page_tells_the_service_what_changed_and_only_while_the_client_runs():
    """The page's side, read from its source (the page has no test of its
    own): a change of the look's attributes, of the document's language and
    of the device's own preference all recolour the drawing and tell the
    service — only while a client runs and only what is another than the
    one it was given last."""
    source = (WURZEL / "frontend/src/lib/windowTerminal.js").read_text(encoding="utf-8")
    assert "if (told.theme || told.language) api.fensterMelden(told).catch(() => {})" in source
    assert "if (!session.running) return" in source
    assert "if (look !== session.look) {" in source
    assert "if (texte.sprache !== session.lang) {" in source
    assert "new MutationObserver(windowChanged).observe(document.documentElement, {" in source
    assert "attributeFilter: ['data-modus', 'data-eigen', 'lang']," in source
    assert "window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', windowChanged)" in source
    # What it starts with is what later changes are measured against.
    assert "session.look = currentLook()" in source
    assert "session.lang = texte.sprache" in source
    assert "look: session.look," in source
    assert "lang: session.lang," in source
    api = (WURZEL / "frontend/src/lib/api.js").read_text(encoding="utf-8")
    assert "ruf('/events/window-theme', { method: 'POST', body: alsText(felder) })" in api
