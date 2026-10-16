"""The agent server remembers the speed module and the projector per model
file, as the model server does.

The slot's choice held one pair for every file, and the window set it back to
nothing at every switch of the model — so switching away and back cost both,
and a projector chosen for one file was on the command line of the next.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import agentenmodellwahl as wahl
from app.api.v1.einstellungen import ROW_CHECKS
from app.db.repositories.einstellungen import WriteRefused

REPO = Path(__file__).resolve().parent.parent
STORE = REPO / "frontend" / "src" / "lib" / "agentenserver.svelte.js"
WINDOW = REPO / "frontend" / "src" / "teile" / "Agentserver.svelte"
URL = "/api/v1/settings/global/agentenmodell"


def _patch(client: TestClient, **werte) -> None:
    antwort = client.patch(URL, json={"wert": werte})
    assert antwort.status_code == 200, antwort.text


def test_the_modules_of_two_files_are_kept_apart(client: TestClient):
    _patch(client, sorte="slot", wert="a.gguf", module={"a.gguf": {"drafter": "mtp-a.gguf"}})
    _patch(client, module={"b.gguf": {"vision": "b-mmproj.gguf"}})
    repositories = client.app.state.repositories

    a = wahl.slot_startwerte(repositories, "a.gguf")
    b = wahl.slot_startwerte(repositories, "b.gguf")
    assert (a["drafter"], a["vision"]) == ("mtp-a.gguf", None)
    assert (b["drafter"], b["vision"]) == (None, "b-mmproj.gguf")


def test_switching_to_another_file_and_back_brings_the_modules_back(client: TestClient):
    _patch(client, sorte="slot", wert="a.gguf",
           module={"a.gguf": {"drafter": "mtp-a.gguf", "vision": ""}})
    _patch(client, wert="b.gguf")
    repositories = client.app.state.repositories
    # The autostart has no request: it asks for the file the field names.
    assert wahl.slot_startwerte(repositories)["drafter"] is None
    _patch(client, wert="a.gguf")
    werte = wahl.slot_startwerte(repositories)
    assert (werte["drafter"], werte["vision"]) == ("mtp-a.gguf", "")


def test_an_entry_written_for_one_role_keeps_the_other(client: TestClient):
    _patch(client, sorte="slot", wert="a.gguf",
           module={"a.gguf": {"drafter": "mtp-a.gguf", "vision": "a-mmproj.gguf"}})
    _patch(client, module={"a.gguf": {"vision": ""}})
    werte = wahl.slot_startwerte(client.app.state.repositories, "a.gguf")
    assert (werte["drafter"], werte["vision"]) == ("mtp-a.gguf", "")


def test_the_check_keeps_only_the_role_that_was_sent():
    sauber = wahl.wahl_pruefen({"module": {"a.gguf": {"vision": ""}, "b.gguf": "no set"}})
    assert sauber == {"module": {"a.gguf": {"vision": ""}}}


def test_the_row_check_refuses_growth_past_the_cap():
    assert ROW_CHECKS[wahl.SCHLUESSEL] is wahl.row_check
    voll = {"module": {f"{n}.gguf": {} for n in range(wahl.MODULE_PAIR_LIMIT + 1)}}
    with pytest.raises(WriteRefused):
        wahl.row_check({"module": {}}, voll)
    # A row stored larger before the cap keeps taking writes that add none.
    wahl.row_check(voll, voll)


def test_silence_the_defaults_say_nobody_chose(client: TestClient):
    _patch(client, sorte="slot", wert="a.gguf")
    werte = wahl.slot_startwerte(client.app.state.repositories, "a.gguf")
    assert werte["drafter"] is None and werte["vision"] is None
    assert "module" in wahl.VORGABE and "drafter" not in wahl.VORGABE


def test_the_window_no_longer_wipes_the_pair_at_a_switch():
    fenster = WINDOW.read_text(encoding="utf-8")
    assert "drafter: null, vision: null" not in fenster
    assert "setModules(agentenmodell.wert" in fenster
    speicher = STORE.read_text(encoding="utf-8")
    assert "export function setModules(" in speicher
    assert "export function modulesFor(" in speicher
