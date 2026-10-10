"""The language the service speaks in (app/api/abhaengigkeiten.py, hole_sprache)."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.abhaengigkeiten import hole_sprache


def _client(configured: str = "de") -> TestClient:
    app = FastAPI()
    app.state.config = SimpleNamespace(app=SimpleNamespace(language=configured))

    @app.get("/language")
    def language(sprache: str = Depends(hole_sprache)) -> str:
        return sprache

    return TestClient(app)


def test_the_interface_language_wins_over_the_systems_accept_language():
    # A German Mac, the interface set to English.
    answer = _client().get("/language", headers={"X-Ui-Language": "en", "Accept-Language": "de-DE,de;q=0.9"})
    assert answer.json() == "en"


def test_silence_probe_without_the_interface_language_the_header_decides_as_before():
    assert _client().get("/language", headers={"Accept-Language": "en-GB,en;q=0.9"}).json() == "en"
    assert _client().get("/language", headers={"Accept-Language": "de-DE"}).json() == "de"


def test_the_interface_language_is_read_like_the_header():
    assert _client().get("/language", headers={"X-Ui-Language": "EN-gb"}).json() == "en"


def test_silence_probe_an_unknown_interface_language_falls_back_to_the_rest():
    headers = {"X-Ui-Language": "xx", "Accept-Language": "en-US"}
    assert _client().get("/language", headers=headers).json() == "en"
    # Neither header: the configured language, or the standard one (English)
    # for an unknown one.
    assert _client("en").get("/language").json() == "en"
    assert _client("xx").get("/language").json() == "en"
    assert _client("de").get("/language").json() == "de"


def test_every_fetch_of_the_page_carries_the_interface_language():
    """Source text only: the chat stream once went out without the language
    while every other request had it. Each fetch in api.js is found by what
    it is, a call to fetch, and must pass the language header along."""
    quelle = (Path(__file__).resolve().parent.parent / "frontend/src/lib/api.js").read_text()
    aufrufe = re.findall(r"await fetch\(.*?\n  \}\)", quelle, re.S)
    assert len(aufrufe) >= 3, aufrufe
    for aufruf in aufrufe:
        assert "sprachkopf()" in aufruf, aufruf
