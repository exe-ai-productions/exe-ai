"""The name setting: checked on the way in, one line on the way out."""

from app import anrede


def test_pruefer_behaelt_nur_bekanntes():
    sauber = anrede.schalter_pruefen({"name": "  Max  ", "an": 1, "x": "y"})
    assert sauber == {"name": "Max", "an": True}


def test_pruefer_verwirft_unbrauchbares():
    assert anrede.schalter_pruefen("Max") == {}
    assert anrede.schalter_pruefen(None) == {}


def test_pruefer_begrenzt_die_laenge():
    lang = anrede.schalter_pruefen({"name": "x" * 200})
    assert len(lang["name"]) == anrede.NAME_HOECHSTLAENGE


def test_anhaengen_mit_namen():
    ergebnis = anrede.anhaengen("Grund.", {"name": "Max", "an": True})
    assert ergebnis.startswith("Grund.")
    assert '"Max"' in ergebnis


def test_anhaengen_aus_oder_leer_aendert_nichts():
    assert anrede.anhaengen("Grund.", {"name": "Max", "an": False}) == "Grund."
    assert anrede.anhaengen("Grund.", {"name": "", "an": True}) == "Grund."


def test_anhaengen_ohne_grundprompt():
    ergebnis = anrede.anhaengen("", {"name": "Max", "an": True})
    assert ergebnis.startswith('The user goes by "Max".')
    # The program is not only a terminal; it also answers on a phone.
    assert "terminal" not in ergebnis


def test_der_erststart_reist_im_selben_eintrag_mit():
    """The first-start window is what asks for the name, so it is the same
    act. It used to be a mark in browser storage and came back in every new
    browser profile, on an installation long since set up."""
    assert anrede.schalter_pruefen({"erststart": True}) == {"erststart": True}
    assert anrede.schalter_pruefen({"erststart": 0}) == {"erststart": False}


def test_der_erststart_steht_nicht_im_systemprompt(repos):
    """`lesen` is what the system prompt is built from — whether a window
    was once answered has no business in it."""
    repos.einstellungen.setzen(
        "global", anrede.SCHLUESSEL, {"name": "Max", "an": True, "erststart": True}
    )
    stand = anrede.lesen(repos)
    assert "erststart" not in stand
    assert anrede.anhaengen("", stand).count("erststart") == 0


def test_name_und_erststart_ueberleben_gemeinsam(client):
    """Writing a scope replaces its whole row — all three keys have to go
    out together, or saving the name would take the answered window with
    it."""
    client.put(
        "/api/v1/settings/global/anrede",
        json={"wert": {"name": "Max", "an": True, "erststart": True}},
    )
    gelesen = client.get("/api/v1/settings/resolved/anrede").json()["wert"]
    assert gelesen == {"name": "Max", "an": True, "erststart": True}
