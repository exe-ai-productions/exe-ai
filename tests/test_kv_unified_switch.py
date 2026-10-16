"""The switch "Dynamisches Kontextfenster" ("KV - Unified"): with several
slots (`--parallel N`) either all of them share the one cache of the
window's size (`--kv-unified`) or each gets the window divided by N
(`--no-kv-unified`).

Before, a slot count went out alone: llama.cpp then gave every request the
window divided by the count while the page went on showing the whole window.
Shipped on; with the slot count on Auto the engine switches it on itself, so
no flag goes out.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import agentenmodellwahl, feineinstellungenwahl
from app.feineinstellungen import Feineinstellungen, context_per_request, flags
from tests.conftest import agentenmodell_setzen
from tests.test_runner_api import StummerRunner

LEVERS = "/api/v1/settings/global/feineinstellungen"
LEVERS_RESOLVED = "/api/v1/settings/resolved/feineinstellungen"


# --- the command -------------------------------------------------------------


def test_on_with_a_count_says_kv_unified():
    assert flags(Feineinstellungen(parallel=2, kv_unified=True)) == ["--parallel", "2", "--kv-unified"]


def test_off_with_a_count_says_no_kv_unified():
    assert flags(Feineinstellungen(parallel=2, kv_unified=False)) == [
        "--parallel", "2", "--no-kv-unified",
    ]


@pytest.mark.parametrize("switch", [True, False])
def test_auto_slots_say_nothing_either_way(switch):
    """The engine turns it on itself when it picks the slot count."""
    assert flags(Feineinstellungen(parallel=None, kv_unified=switch)) == []


def test_it_is_on_where_nothing_says_otherwise():
    assert Feineinstellungen().kv_unified is True
    assert Feineinstellungen.aus_daten(None).kv_unified is True
    assert Feineinstellungen.aus_daten({"parallel": 3}).kv_unified is True
    assert Feineinstellungen.aus_daten({"kv_unified": False}).kv_unified is False
    assert Feineinstellungen().als_daten()["kv_unified"] is True


def test_it_survives_the_round_trip_through_the_levers():
    daten = Feineinstellungen(parallel=4, kv_unified=False).als_daten()
    assert Feineinstellungen.aus_daten(daten) == Feineinstellungen(parallel=4, kv_unified=False)


# --- the context one request gets --------------------------------------------


def test_the_window_divides_by_the_slots_when_the_cache_is_not_shared():
    assert context_per_request(16384, Feineinstellungen(parallel=2, kv_unified=False)) == 8192
    assert context_per_request(16384, Feineinstellungen(parallel=4, kv_unified=False)) == 4096


@pytest.mark.parametrize(
    "fein",
    [
        Feineinstellungen(parallel=2, kv_unified=True),
        Feineinstellungen(parallel=None, kv_unified=False),
        Feineinstellungen(parallel=1, kv_unified=False),
        None,
    ],
)
def test_otherwise_every_request_may_use_the_whole_window(fein):
    assert context_per_request(16384, fein) is None


# --- stored with the levers --------------------------------------------------


def test_the_switch_stays_stored(client: TestClient):
    assert client.patch(LEVERS, json={"wert": {"kv_unified": False}}).status_code == 200
    stored = client.get(LEVERS_RESOLVED).json()["wert"]
    assert stored["kv_unified"] is False
    assert feineinstellungenwahl.gewaehlt(client.app.state.repositories).kv_unified is False


def test_the_shipped_levers_name_it_on(client: TestClient):
    assert feineinstellungenwahl.VORGABE["kv_unified"] is True
    assert feineinstellungenwahl.gewaehlt(client.app.state.repositories).kv_unified is True


# --- what the servers tell ---------------------------------------------------


class _RunnerWithLevers(StummerRunner):
    """Keeps the levers the way the real runner does."""

    def starten(self, modell, **kw):
        lauf = super().starten(modell, **kw)
        lauf.fein = kw.get("fein")
        return lauf


def test_the_model_server_names_the_context_per_request(client: TestClient):
    runner = _RunnerWithLevers()
    client.app.state.modellrunner = runner
    client.patch(LEVERS, json={"wert": {"parallel": 2, "kv_unified": False}})
    client.patch("/api/v1/settings/global/runnermodell", json={"wert": {"kontext": 16384}})
    client.post("/api/v1/runner/start", json={"modell": "m.gguf"})
    answer = client.get("/api/v1/runner").json()
    assert answer["kontext"] == 16384
    assert answer["kontext_je_anfrage"] == 8192
    assert answer["fein"]["kv_unified"] is False


def test_the_model_server_names_nothing_while_the_cache_is_shared(client: TestClient):
    client.app.state.modellrunner = _RunnerWithLevers()
    client.patch(LEVERS, json={"wert": {"parallel": 2, "kv_unified": True}})
    client.post("/api/v1/runner/start", json={"modell": "m.gguf"})
    assert client.get("/api/v1/runner").json()["kontext_je_anfrage"] is None


def test_the_idle_model_server_names_nothing(client: TestClient):
    client.app.state.modellrunner = _RunnerWithLevers()
    assert client.get("/api/v1/runner").json()["kontext_je_anfrage"] is None


def test_the_agent_slot_names_the_context_per_request(client: TestClient, monkeypatch):
    from app.modellrunner import Lauf

    agentenmodell_setzen(client, "klein.gguf", sorte="slot")
    runner = client.app.state.agentenrunner
    fein = Feineinstellungen(parallel=4, kv_unified=False)
    lauf = Lauf(modell="klein.gguf", kontext=32768, schichten=None, port=8083, fein=fein)
    monkeypatch.setattr(runner, "lauf", lambda: lauf)
    monkeypatch.setattr(runner, "laeuft", lambda: True)
    answer = client.get("/api/v1/agentenmodell").json()
    assert answer["kontext_je_anfrage"] == 8192
    assert answer["fein"]["kv_unified"] is False


def test_the_slots_stored_levers_carry_the_switch(client: TestClient):
    client.put(
        "/api/v1/settings/global/agentenmodell",
        json={"wert": {"sorte": "slot", "wert": "klein.gguf",
                       "fein": {"parallel": 2, "kv_unified": False}}},
    )
    fein = agentenmodellwahl.slot_startwerte(client.app.state.repositories)["fein"]
    assert fein.kv_unified is False
    assert "--no-kv-unified" in flags(fein)


def test_both_windows_hand_the_storage_half_the_slots_and_the_levers():
    """The context one request gets is named beside the context field — in the
    storage half of the sheet, which only reads the slot count and the
    levers. A window that did not pass them would never show it."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "frontend" / "src" / "teile"
    for name in ("Modellserver.svelte", "Agentserver.svelte"):
        source = (root / name).read_text(encoding="utf-8")
        match = re.search(r'<Serverregler\s+kennung="\w+"\s+teil="speicher".*?/>', source, re.S)
        assert match, name
        assert "{parallel}" in match.group(0) and "{fein}" in match.group(0), name
