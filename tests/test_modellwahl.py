"""What the user picked among the models — and that it actually gets stored.

The switch in the model window looked like it worked and stored nothing: the
settings route only vouched for `parameter`, so every write came back 400, and
the interface quietly put its own state back. These tests are there so that
cannot happen again silently.
"""

from __future__ import annotations

from app import modellwahl
from app.modellwahl import aus_pruefen, wahl_pruefen


# --- What gets through ------------------------------------------------------


def test_aus_liste_nimmt_nur_saubere_kennungen():
    assert aus_pruefen(["a", " b ", "", None, 7, "a"]) == ["a", "b"]


def test_aus_liste_haelt_die_reihenfolge():
    assert aus_pruefen(["z", "a", "m"]) == ["z", "a", "m"]


def test_aus_liste_lehnt_alles_ab_was_keine_liste_ist():
    assert aus_pruefen({"a": 1}) == []
    assert aus_pruefen("a") == []
    assert aus_pruefen(None) == []


def test_wahl_nimmt_je_anbieter_die_modelle():
    assert wahl_pruefen({"openai": ["gpt-5.5", "gpt-5.5"], "anthropic": ["claude-opus-5"]}) == {
        "openai": ["gpt-5.5"],
        "anthropic": ["claude-opus-5"],
    }


def test_ein_anbieter_ohne_wahl_faellt_weg():
    """An empty entry says nothing its absence does not."""
    assert wahl_pruefen({"openai": [], "anthropic": ["x"]}) == {"anthropic": ["x"]}


def test_wahl_lehnt_alles_ab_was_kein_objekt_ist():
    assert wahl_pruefen(["openai"]) == {}
    assert wahl_pruefen(None) == {}


# --- And that the route really stores them ----------------------------------


def test_die_schnellwahl_laesst_sich_wirklich_abschalten(client):
    antwort = client.put(
        "/api/v1/settings/global/modelle_aus", json={"wert": ["qwen-mac"]}
    )
    assert antwort.status_code == 200
    assert antwort.json()["wert"] == ["qwen-mac"]

    # And it comes back — a list travels whole, there is nothing to merge.
    gelesen = client.get("/api/v1/settings/resolved/modelle_aus").json()
    assert gelesen["wert"] == ["qwen-mac"]


def test_die_katalogwahl_laesst_sich_wirklich_sichern(client):
    antwort = client.put(
        "/api/v1/settings/global/katalog_wahl",
        json={"wert": {"openai": ["gpt-5.5", "gpt-4o-mini"]}},
    )
    assert antwort.status_code == 200

    gelesen = client.get("/api/v1/settings/resolved/katalog_wahl").json()
    assert gelesen["wert"] == {"openai": ["gpt-5.5", "gpt-4o-mini"]}


def test_leere_wahl_loescht_den_eintrag(client):
    client.put("/api/v1/settings/global/modelle_aus", json={"wert": ["a"]})
    client.put("/api/v1/settings/global/modelle_aus", json={"wert": []})
    # Nothing set means the scope above applies — here there is none, so {}.
    assert client.get("/api/v1/settings/resolved/modelle_aus").json()["wert"] == {}


def test_eine_unbekannte_einstellung_kommt_nicht_durch(client):
    """The JSON column cannot check anything itself — whoever is not vouched
    for does not get in."""
    antwort = client.put("/api/v1/settings/global/irgendwas", json={"wert": [1]})
    assert antwort.status_code == 400


def test_das_zuletzt_benutzte_modell_kommt_durch():
    assert modellwahl.zuletzt_pruefen({"id": " lokal/qwen "}) == {"id": "lokal/qwen"}


def test_kein_modellname_wird_nicht_gespeichert():
    assert modellwahl.zuletzt_pruefen({"id": ""}) is None
    assert modellwahl.zuletzt_pruefen({"id": "   "}) is None
    assert modellwahl.zuletzt_pruefen({"id": 7}) is None
    assert modellwahl.zuletzt_pruefen("lokal/qwen") is None
    assert modellwahl.zuletzt_pruefen({"id": "x" * 401}) is None


def test_das_zuletzt_benutzte_modell_ueberlebt_die_route(client):
    """It used to sit in browser storage, so a second window on the same
    service opened on whatever came first in the list."""
    antwort = client.put(
        "/api/v1/settings/global/modell_zuletzt", json={"wert": {"id": "lokal/qwen"}}
    )
    assert antwort.status_code == 200, antwort.text
    gelesen = client.get("/api/v1/settings/resolved/modell_zuletzt").json()
    assert gelesen["wert"] == {"id": "lokal/qwen"}


# --- A name above the limit ---------------------------------------------------


def test_a_name_is_cut_to_the_limit_the_stored_choice_keeps():
    assert modellwahl.name_kuerzen("x" * 401) == "x" * modellwahl.MAX_LAENGE
    # Blanks around the cut are not part of the name either.
    assert modellwahl.name_kuerzen("  " + "x" * 399 + " tail") == "x" * 399
    # Silence probe: a name below the limit is only trimmed.
    assert modellwahl.name_kuerzen("  Beta 9B ") == "Beta 9B"


def test_a_listed_name_above_the_limit_is_kept_with_the_choice_and_equals_it_again(client):
    """Falls over without the cut: the list handed out the whole name, the
    stored choice refused it as too long and kept the id alone, so a client
    following the listed name found the stored one missing at every start."""
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.gemeldeter_name = "n" * 401

    listed = client.get("/api/v1/models").json()[0]
    assert len(listed["name"]) == modellwahl.MAX_LAENGE

    stored = client.put(
        "/api/v1/settings/global/modell_zuletzt",
        json={"wert": {"id": listed["id"], "name": listed["name"]}},
    )
    assert stored.status_code == 200, stored.text
    kept = client.get("/api/v1/settings/resolved/modell_zuletzt").json()["wert"]
    assert kept == {"id": listed["id"], "name": listed["name"]}


def test_silence_probe_a_listed_name_below_the_limit_is_handed_out_whole(client):
    zustand = client.app.state.discovery.zustaende["test"]
    zustand.gemeldeter_name = "Beta 9B"
    assert client.get("/api/v1/models").json()[0]["name"] == "Beta 9B"
