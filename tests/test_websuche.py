"""The shipped web search: what it offers, and where it must not reach.

Two servers can serve the search — the bundled library and a self-hosted
SearXNG. The point of the tests below is that swapping one for the other
stays invisible: same tool names, same guard.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

from app.tools import server_lesen

# The servers live next to each other in mcp/ and import each other by plain
# name, exactly as they do when started as a subprocess from the project root.
MCP_ORDNER = Path(__file__).resolve().parent.parent / "mcp"
if str(MCP_ORDNER) not in sys.path:
    sys.path.insert(0, str(MCP_ORDNER))

ddgs_server = importlib.import_module("ddgs_server")
searxng_server = importlib.import_module("searxng_server")
webseite_lesen = importlib.import_module("webseite_lesen")


# --- What is shipped ------------------------------------------------------


def test_die_suche_wird_angeschaltet_ausgeliefert():
    eintraege = server_lesen(Path("mcp_servers.json"))
    suche = next(e for e in eintraege if e.name == "websuche")
    # A search that ships switched off is a search nobody finds.
    assert suche.enabled is True
    assert suche.allowed_tools == ["web_search", "read_webpage"]


def test_die_suche_braucht_keine_geheimnisse():
    eintraege = server_lesen(Path("mcp_servers.json"))
    suche = next(e for e in eintraege if e.name == "websuche")
    # No placeholder in the environment means nothing to fill in before the
    # first search — that is the whole reason this variant is the shipped one.
    assert not any("${" in wert for wert in (suche.env or {}).values())


# --- The swap has to stay invisible ---------------------------------------


def test_beide_server_bieten_dieselben_werkzeuge():
    namen = ["web_search", "read_webpage"]
    assert [w["name"] for w in ddgs_server.WERKZEUGE] == namen
    assert [w["name"] for w in searxng_server.WERKZEUGE] == namen


def test_beide_server_teilen_sich_dieselbe_sperre():
    # Not two copies that drift apart: one module, used twice.
    assert ddgs_server.webseite_lesen is searxng_server.webseite_lesen


# --- Where read_webpage must not reach ------------------------------------


@pytest.mark.parametrize(
    "adresse",
    [
        "http://127.0.0.1:8090/api/v1/chats",
        "http://localhost:8090/",
        "http://[::1]:8090/",
        "http://192.168.1.1/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data/",  # the cloud metadata address
        "http://100.80.1.3:8770/",  # a tailnet, outside is_private
    ],
)
def test_innen_bleibt_innen(adresse: str):
    assert webseite_lesen.zeigt_nach_innen(adresse) is True


def test_ein_name_der_nicht_aufloest_gilt_als_verdaechtig():
    assert webseite_lesen.zeigt_nach_innen("http://gibtsganzsicherhiernicht.invalid/") is True


def test_ohne_wirt_gilt_als_innen():
    assert webseite_lesen.zeigt_nach_innen("http:///pfad") is True


@pytest.mark.parametrize("adresse", ["ftp://example.org/datei", "file:///etc/passwd", "beispiel.de"])
def test_nur_http_und_https_werden_gelesen(adresse: str):
    antwort = asyncio.run(webseite_lesen.lesen(adresse))
    assert antwort.startswith("Error:")


# --- No address of its own ------------------------------------------------


def test_the_self_run_search_asks_nothing_without_an_address(monkeypatch):
    """An instance on this machine used to be assumed (127.0.0.1:8888) — a
    search that answered from whatever happened to listen there. Without an
    address the server says so and sends no request at all."""
    sent = []

    class Client:
        def __init__(self, *a, **k):
            sent.append("opened")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *a, **k):
            sent.append("asked")
            raise AssertionError("nothing may be asked without an address")

    monkeypatch.setattr(searxng_server, "SEARXNG_URL", "")
    monkeypatch.setattr(searxng_server.httpx, "AsyncClient", Client)
    with pytest.raises(ValueError, match="SEARXNG_URL"):
        asyncio.run(searxng_server.websuche("anything"))
    assert sent == []


def test_silence_with_an_address_the_search_goes_there(monkeypatch):
    seen = []

    class Answer:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"title": "A", "url": "https://a.example", "content": "x"}]}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **k):
            seen.append(url)
            return Answer()

    monkeypatch.setattr(searxng_server, "SEARXNG_URL", "https://suche.example.org")
    monkeypatch.setattr(searxng_server.httpx, "AsyncClient", Client)
    text = asyncio.run(searxng_server.websuche("anything"))
    assert seen == ["https://suche.example.org/search"] and "https://a.example" in text


# --- Every engine down is not an empty result ------------------------------


def _ask_with(monkeypatch, answer: dict):
    class Reply:
        def raise_for_status(self):
            return None

        def json(self):
            return answer

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **k):
            return Reply()

    monkeypatch.setattr(searxng_server, "SEARXNG_URL", "https://suche.example.org")
    monkeypatch.setattr(searxng_server.httpx, "AsyncClient", Client)
    return asyncio.run(searxng_server.websuche("newest release"))


def test_a_search_with_every_engine_down_says_so(monkeypatch):
    text = _ask_with(monkeypatch, {
        "results": [],
        "unresponsive_engines": [["google", "Suspended: too many requests"], ["duckduckgo", "timeout"]],
    })
    assert not text.startswith("No results for")
    assert "google (Suspended: too many requests)" in text and "duckduckgo (timeout)" in text
    assert "not an empty result" in text and "unavailable" in text


def test_the_web_search_says_searching_again_will_not_help_right_now(monkeypatch):
    text = _ask_with(monkeypatch, {"results": [], "unresponsive_engines": [["google", "timeout"]]})
    assert "will not help right now" in text
    assert "will not help now" not in text


def test_silence_no_hits_and_no_engine_down_stays_no_results(monkeypatch):
    assert _ask_with(monkeypatch, {"results": [], "unresponsive_engines": []}) == "No results for: newest release"
    assert _ask_with(monkeypatch, {"results": []}) == "No results for: newest release"


def test_silence_hits_with_an_engine_down_keep_the_list_as_it_was(monkeypatch):
    text = _ask_with(monkeypatch, {
        "results": [{"title": "A", "url": "https://a.example", "content": "x"}],
        "unresponsive_engines": [["google", "timeout"]],
    })
    assert text.startswith("Results for") and "https://a.example" in text
    assert "google" not in text and "unavailable" not in text


def test_an_engine_without_a_reason_stands_by_its_name(monkeypatch):
    text = _ask_with(monkeypatch, {"results": [], "unresponsive_engines": [["brave"]]})
    assert "answered: brave." in text
