"""The model window's engine levers are written lever by lever.

The window sent the whole row from its own copy, so a lever a second window
or the command line had moved was put back by the next change made here. The
real windows are driven in a browser by
``test_model_windows_pending_save_chrome.py``; this file holds what does not
need one — the route the window now relies on, and the window's source.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

URL = "/api/v1/settings/global/feineinstellungen"
WINDOW = (
    Path(__file__).resolve().parent.parent / "frontend" / "src" / "teile" / "Modellserver.svelte"
)


def test_two_windows_each_move_another_lever_and_both_stay(client: TestClient):
    assert client.patch(URL, json={"wert": {"festnageln": True}}).status_code == 200
    assert client.patch(URL, json={"wert": {"kv_cache": "q8_0"}}).status_code == 200

    stored = client.get(URL).json()["wert"]
    assert stored["festnageln"] is True
    assert stored["kv_cache"] == "q8_0"


def test_a_lever_sent_alone_leaves_the_others_as_stored(client: TestClient):
    client.put(URL, json={"wert": {"kv_cache": "q8_0", "festnageln": True, "faeden": 6}})
    client.patch(URL, json={"wert": {"faeden": 4}})
    stored = client.get(URL).json()["wert"]
    assert (stored["kv_cache"], stored["festnageln"], stored["faeden"]) == ("q8_0", True, 4)


def test_the_window_writes_by_patch_not_by_put():
    quelle = WINDOW.read_text(encoding="utf-8")
    assert "einstellungSetzen('global', FEINEINSTELLUNGEN" not in quelle
    assert "einstellungMischen('global', FEINEINSTELLUNGEN, changed)" in quelle


def test_the_window_reads_the_levers_again_when_a_run_has_ended():
    quelle = WINDOW.read_text(encoding="utf-8")
    ende = quelle.split("await standLaden(true)", 1)[1].split("liefVorher = auskunft.laeuft", 1)[0]
    assert "await feinLaden()" in ende
