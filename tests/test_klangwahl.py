"""The sound switch and its volume in the settings cascade.

The route only writes what somebody vouches for. Without an entry the window
saved into nothing: the slider moved, the service answered 400, and the level
was back at the default on the next start. So the round trip through the real
route is the test that matters here.
"""

from __future__ import annotations

from app import klangwahl


def test_beides_kommt_durch():
    assert klangwahl.wahl_pruefen({"an": False, "pegel": 30}) == {"an": False, "pegel": 30}


def test_der_pegel_bleibt_zwischen_null_und_hundert():
    assert klangwahl.wahl_pruefen({"pegel": 400}) == {"pegel": 100}
    assert klangwahl.wahl_pruefen({"pegel": -5}) == {"pegel": 0}


def test_muell_faellt_raus():
    assert klangwahl.wahl_pruefen({"an": "ja", "pegel": "laut"}) is None
    assert klangwahl.wahl_pruefen("an") is None
    # A boolean is not a level — otherwise True would land as 1.
    assert klangwahl.wahl_pruefen({"pegel": True}) is None


def test_die_vorgabe_steht_dahinter():
    # Against the constant, not against a copy of it: the key grew by four
    # switches and every such addition used to break this test pointlessly.
    assert klangwahl.aufgeloest(None) == klangwahl.VORGABE
    assert klangwahl.aufgeloest({"pegel": 10}) == {**klangwahl.VORGABE, "pegel": 10}


def test_every_occurrence_has_a_sound_switch_of_its_own():
    """One sound switch per occurrence, all shipped on; the popup of the
    same occurrence is another key (app/meldewahl.py) and not answered here."""
    assert klangwahl.wahl_pruefen({"fertig": False}) is None
    assert klangwahl.wahl_pruefen({"melde_fertig": False}) is None
    assert set(klangwahl.VORGABE) == {
        "an", "pegel", "nur_hintergrund",
        "ton_fertig", "ton_wartet", "ton_fehler", "ton_agent_cronjob",
    }
    assert all(klangwahl.VORGABE[name] is True for name in klangwahl.SOUND_FIELDS)


def test_a_switched_off_sound_survives_storing():
    """A bare False must not read as nothing set and let the shipped value
    switch the sound back on."""
    gespeichert = klangwahl.wahl_pruefen({"ton_agent_cronjob": False})
    assert gespeichert == {"ton_agent_cronjob": False}
    aufgeloest = klangwahl.aufgeloest(gespeichert)
    assert aufgeloest["ton_agent_cronjob"] is False
    assert aufgeloest["ton_fertig"] is True
    assert klangwahl.wahl_pruefen({"ton_fehler": "nein"}) is None


def test_nur_im_hintergrund_ist_eine_einstellung():
    assert klangwahl.aufgeloest(None)["nur_hintergrund"] is True
    aus = klangwahl.wahl_pruefen({"nur_hintergrund": False})
    assert klangwahl.aufgeloest(aus)["nur_hintergrund"] is False


def test_die_route_speichert_und_gibt_zurueck(client):
    antwort = client.put(
        "/api/v1/settings/global/klaenge", json={"wert": {"an": True, "pegel": 42}}
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["wert"] == {"an": True, "pegel": 42}

    gelesen = client.get("/api/v1/settings/resolved/klaenge").json()
    assert gelesen["wert"] == {"an": True, "pegel": 42}


def test_aus_bleibt_aus(client):
    """The switch is stored as an object because the route reads a falsy
    value as "nothing set" — a bare false could never switch anything off."""
    client.put("/api/v1/settings/global/klaenge", json={"wert": {"an": False, "pegel": 0}})
    gelesen = client.get("/api/v1/settings/resolved/klaenge").json()
    assert gelesen["wert"]["an"] is False
    assert gelesen["wert"]["pegel"] == 0
