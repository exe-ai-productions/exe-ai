"""Light, dark and the four that are neither, in the settings cascade."""

from __future__ import annotations

import re
from pathlib import Path

from app import moduswahl


def test_jeder_angebotene_modus_kommt_durch():
    """The list mirrors MODI in the settings window and the first-start
    screen — eight, not the three the mode looks like from outside; the
    own gradient among them."""
    for modus in ("auto", "hell", "dunkel", "darkmatter", "heaven", "moune", "snow", "eigen"):
        assert moduswahl.wahl_pruefen({"modus": modus}) == {"modus": modus}


def test_muell_faellt_raus():
    assert moduswahl.wahl_pruefen({"modus": "gruen"}) is None
    assert moduswahl.wahl_pruefen("dunkel") is None
    assert moduswahl.wahl_pruefen({"modus": True}) is None
    assert moduswahl.wahl_pruefen({}) is None


def test_die_vorgabe_steht_dahinter():
    assert moduswahl.aufgeloest(None) == {"modus": "auto"}
    assert moduswahl.aufgeloest({"modus": "heaven"}) == {"modus": "heaven"}


def test_die_route_speichert_und_gibt_zurueck(client):
    antwort = client.put("/api/v1/settings/global/modus", json={"wert": {"modus": "darkmatter"}})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["wert"] == {"modus": "darkmatter"}

    gelesen = client.get("/api/v1/settings/resolved/modus").json()
    assert gelesen["wert"] == {"modus": "darkmatter"}


def test_unfug_speichert_nichts(client):
    client.put("/api/v1/settings/global/modus", json={"wert": {"modus": "gruen"}})
    gelesen = client.get("/api/v1/settings/resolved/modus").json()
    assert gelesen["wert"] == {}


def test_die_drei_listen_bleiben_dieselben():
    """The modes stand in three lists — the route's tuple and the two
    screens that offer them — and they must not drift apart: a mode the
    route refuses never reaches the screen, one a row misses cannot be
    picked at all. Silence probe in both directions."""
    wurzel = Path(__file__).resolve().parent.parent
    for name in ("SystemPrompt.svelte", "Erststart.svelte"):
        quelle = (wurzel / "frontend" / "src" / "teile" / name).read_text(
            encoding="utf-8"
        )
        block = re.search(r"const MODI = \[([\s\S]*?)\n  \]", quelle)
        assert block, f"{name} has no MODI list"
        gefunden = tuple(re.findall(r"\['([a-z]+)'", block.group(1)))
        assert gefunden == moduswahl.MODI, (name, gefunden)
