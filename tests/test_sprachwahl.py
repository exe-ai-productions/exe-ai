"""The interface language in the settings cascade.

It sat in browser storage, which is the one place the program itself cannot
look — so a service that had to write a text for its user had no way of
knowing which language that user reads.
"""

from __future__ import annotations

from app import sprachwahl


def test_die_kataloge_auf_der_platte_sind_die_liste():
    """A hard-coded list here would let the route accept a language nobody
    can serve, or refuse one that was just added."""
    from app.i18n import verfuegbare_sprachen

    assert sprachwahl.erlaubt() == ("auto", *verfuegbare_sprachen())
    for sprache in verfuegbare_sprachen():
        assert sprachwahl.wahl_pruefen({"sprache": sprache}) == {"sprache": sprache}


def test_auto_ist_ein_wert_keine_leere():
    """Going back to automatic is a decision. A cleared entry could not be
    told apart from never having chosen."""
    assert sprachwahl.wahl_pruefen({"sprache": "auto"}) == {"sprache": "auto"}


def test_muell_faellt_raus():
    assert sprachwahl.wahl_pruefen({"sprache": "kli"}) is None
    assert sprachwahl.wahl_pruefen("de") is None
    assert sprachwahl.wahl_pruefen({}) is None


def test_die_vorgabe_steht_dahinter():
    assert sprachwahl.aufgeloest(None) == {"sprache": "auto"}
    assert sprachwahl.aufgeloest({"sprache": "en"}) == {"sprache": "en"}


def test_die_route_speichert_und_gibt_zurueck(client):
    antwort = client.put("/api/v1/settings/global/sprache", json={"wert": {"sprache": "en"}})
    assert antwort.status_code == 200, antwort.text
    assert client.get("/api/v1/settings/resolved/sprache").json()["wert"] == {"sprache": "en"}

    client.put("/api/v1/settings/global/sprache", json={"wert": {"sprache": "auto"}})
    assert client.get("/api/v1/settings/resolved/sprache").json()["wert"] == {"sprache": "auto"}
