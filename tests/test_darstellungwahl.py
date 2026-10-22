"""The look of the interface in the settings cascade.

These values lived in browser storage, which meant a different truth on
every device and none at all for the program itself. The round trip through
the real route is what matters here: without an entry in PRUEFER the window
would appear to save and the value would be gone on the next start.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import darstellungwahl

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"


def test_alles_kommt_durch():
    assert darstellungwahl.wahl_pruefen(
        {
            "codefarben": "tokyo",
            "blasenfarbe": "#123abc",
        }
    ) == {
        "codefarben": "tokyo",
        "blasenfarbe": "#123abc",
    }


@pytest.mark.parametrize(
    "pack", ["github", "githubdark", "dracula", "nord", "solarizedlight", "solarizeddark"]
)
def test_the_six_new_code_packs_are_accepted(pack):
    assert darstellungwahl.wahl_pruefen({"codefarben": pack}) == {"codefarben": pack}


def test_the_three_lists_of_code_packs_agree():
    """The packs are named in three places: the server's checker, the list
    in the settings and the style sheet. A pack missing from the checker
    looks saved and is back at `exe` after the next start; one missing from
    the style sheet is chosen and changes nothing."""
    offered = re.findall(
        r"\['(\w+)', 'einstellungen\.codefarben_\w+'\]",
        (FRONTEND / "lib" / "darstellungswerte.js").read_text(encoding="utf-8"),
    )
    styled = set(
        re.findall(
            r"data-codefarben='(\w+)'",
            (FRONTEND / "stil" / "codefarben.css").read_text(encoding="utf-8"),
        )
    )
    assert tuple(offered) == darstellungwahl.CODEFARBEN
    # `exe` has no rule of its own: it is the house pack, the variables' defaults.
    assert styled == set(darstellungwahl.CODEFARBEN) - {"exe"}


def test_an_unknown_code_pack_is_not():
    assert darstellungwahl.wahl_pruefen({"codefarben": "monokai"}) is None
    assert darstellungwahl.wahl_pruefen({"codefarben": 2}) is None


def test_old_outline_and_size_values_are_passed_over():
    """A value stored while the outline switch and the two size steps
    existed still carries them. They are dropped without an error, and what
    the value holds besides them stays."""
    assert darstellungwahl.wahl_pruefen(
        {
            "kontur": True,
            "schrift": "gross",
            "oberflaeche": "groesser",
            "blasenfarbe": "#aabbcc",
        }
    ) == {"blasenfarbe": "#aabbcc"}
    assert darstellungwahl.aufgeloest({"kontur": True, "schrift": "gross"}) == {
        "codefarben": "exe",
        "blasenfarbe": "",
        "verlauf": {},
        "chat": {},
    }


def test_die_blasenfarbe_ist_sechsstelliges_hex():
    assert darstellungwahl.wahl_pruefen({"blasenfarbe": "#ABC"}) is None
    assert darstellungwahl.wahl_pruefen({"blasenfarbe": "rot"}) is None
    # Lower case, so what comes back matches what the colour input hands out.
    assert darstellungwahl.wahl_pruefen({"blasenfarbe": "#AABBCC"})["blasenfarbe"] == "#aabbcc"
    # A trailing line break is no colour field's output — full match only.
    assert darstellungwahl.wahl_pruefen({"blasenfarbe": "#aabbcc\n"}) is None
    assert (
        darstellungwahl.wahl_pruefen(
            {"verlauf": {"eigen": {"farben": ["#aabbcc\n", "#112233", "#445566", "#778899"]}}}
        )
        is None
    )


def test_leere_blasenfarbe_heisst_hausfarbe():
    """Empty is a choice — "no colour of my own" — and has to survive
    storing, or clearing the colour could never be remembered."""
    assert darstellungwahl.wahl_pruefen({"blasenfarbe": ""}) == {"blasenfarbe": ""}


def test_muell_faellt_raus():
    assert darstellungwahl.wahl_pruefen("dunkel") is None
    assert darstellungwahl.wahl_pruefen({"kontur": "an"}) is None
    assert darstellungwahl.wahl_pruefen({}) is None


def test_die_vorgabe_steht_dahinter():
    assert darstellungwahl.aufgeloest(None) == {
        "codefarben": "exe",
        "blasenfarbe": "",
        "verlauf": {},
        "chat": {},
    }
    assert darstellungwahl.aufgeloest({"blasenfarbe": "#aabbcc"})["codefarben"] == "exe"
    # The nested map is a copy: a caller's write must never land in the
    # module's default.
    assert darstellungwahl.aufgeloest(None)["verlauf"] is not darstellungwahl.VORGABE["verlauf"]
    assert darstellungwahl.aufgeloest(None)["chat"] is not darstellungwahl.VORGABE["chat"]


def test_das_chatlayout_kommt_durch():
    werte = {
        "schrift": 19,
        "breite": 1200,
        "blase_eigen": 70,
        "blase_ki": 100,
        "anker_eigen": 50,
        "anker_ki": 0,
        "abstand": 40,
        "bildkachel": 300,
    }
    assert darstellungwahl.wahl_pruefen({"chat": werte}) == {"chat": werte}


def test_falsches_im_chatlayout_faellt_einzeln_weg():
    assert darstellungwahl.wahl_pruefen(
        {
            "chat": {
                "schrift": 9,
                "breite": 2001,
                "blase_eigen": 55.5,
                "blase_ki": True,
                "anker_eigen": "50",
                "abstand": 30,
                "zoom": 2,
            }
        }
    ) == {"chat": {"abstand": 30}}


def test_ein_leeres_chatlayout_bleibt_stehen():
    """"Standard" stores an empty map; it must reach the row, or a layout
    stored before would stay in force."""
    assert darstellungwahl.wahl_pruefen({"chat": {}}) == {"chat": {}}
    assert darstellungwahl.wahl_pruefen({"chat": "unfug"}) is None


def test_die_grenzen_des_chatlayouts_stimmen_mit_dem_fenster_ueberein():
    """The route vouches for the ranges, the layout mode draws them. A range
    that differs between the two lets the window offer a value the route
    then throws away on the next start."""
    quelle = (FRONTEND / "lib" / "chatlayout.js").read_text(encoding="utf-8")
    fenster = {
        name: (int(von), int(bis))
        for name, von, bis in re.findall(
            r"\{\s*id:\s*'(\w+)',[^}]*?von:\s*(\d+),\s*bis:\s*(\d+)", quelle
        )
    }
    assert fenster == darstellungwahl.CHAT_GRENZEN


def test_the_factory_values_of_the_chat_layout():
    """What the program ships before anybody touched the layout mode, and
    what "Standard" there goes back to. Only what differs from these is
    stored, so moving one of them moves every chat that never set it."""
    source = (FRONTEND / "lib" / "chatlayout.js").read_text(encoding="utf-8")
    factory = {
        name: int(value)
        for name, value in re.findall(r"\{\s*id:\s*'(\w+)',[^}]*?standard:\s*(\d+)", source)
    }
    assert factory == {
        "schrift": 16,
        "breite": 900,
        "blase_eigen": 80,
        "blase_ki": 100,
        "anker_eigen": 100,
        "anker_ki": 0,
        "abstand": 24,
        "bildkachel": 512,
    }


def test_the_fallbacks_in_the_stylesheets_are_the_factory_values():
    """The components carry a fallback for the moment before the first
    layout is applied. A fallback that differs from the factory value draws
    the chat in one shape and then jumps to the other — so every fallback of
    every layout variable, wherever it stands, says what the table says."""
    source = (FRONTEND / "lib" / "chatlayout.js").read_text(encoding="utf-8")
    factory = {
        name: int(value)
        for name, value in re.findall(r"\{\s*id:\s*'(\w+)',[^}]*?standard:\s*(\d+)", source)
    }
    expected = {
        "--chat-schrift": f"{factory['schrift']}px",
        "--chat-breite": f"{factory['breite']}px",
        "--blase-eigen-breite": f"{factory['blase_eigen']}%",
        "--blase-ki-breite": f"{factory['blase_ki']}%",
        # The anchors run from 0 to 1 in the components.
        "--blase-eigen-stelle": f"{factory['anker_eigen'] / 100:g}",
        "--blase-ki-stelle": f"{factory['anker_ki'] / 100:g}",
        "--chat-abstand": f"{factory['abstand']}px",
    }
    sheets = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(FRONTEND.rglob("*"))
        if path.suffix in {".svelte", ".css"}
    )
    for variable, value in expected.items():
        found = set(re.findall(rf"var\({re.escape(variable)},\s*([^)]+?)\s*\)", sheets))
        assert found == {value}, f"{variable}: the stylesheets fall back to {sorted(found)}, the table says {value}"


def test_die_route_speichert_und_gibt_zurueck(client):
    antwort = client.put(
        "/api/v1/settings/global/darstellung",
        json={"wert": {"kontur": True, "codefarben": "onelight", "schrift": "unfug"}},
    )
    assert antwort.status_code == 200, antwort.text
    # The old outline switch and the step are passed over, the rest is kept.
    assert antwort.json()["wert"] == {"codefarben": "onelight"}

    gelesen = client.get("/api/v1/settings/resolved/darstellung").json()
    assert gelesen["wert"] == {"codefarben": "onelight"}


def test_der_eigene_rahmen_verlauf_kommt_durch():
    """Colours, hue and angle of the own gradient go through; colours come
    back lower case, so the stored value matches what the colour fields
    hand out."""
    assert darstellungwahl.wahl_pruefen(
        {
            "verlauf": {
                "eigen": {
                    "farben": ["#AABBCC", "#112233", "#445566", "#778899"],
                    "ton": -30,
                    "winkel": 200,
                },
            }
        }
    ) == {
        "verlauf": {
            "eigen": {
                "farben": ["#aabbcc", "#112233", "#445566", "#778899"],
                "ton": -30,
                "winkel": 200,
            },
        }
    }


def test_nur_der_eigene_verlauf_wird_gespeichert():
    """The fixed looks keep their design's gradient: a choice stored for one
    of them before falls away, the own gradient's stays."""
    assert darstellungwahl.wahl_pruefen(
        {
            "verlauf": {
                "hell": {"winkel": 90},
                "dunkel": {"farben": ["#112233", "#445566", "#778899"]},
                "darkmatter": {"ton": 20},
                "heaven": {"winkel": 10},
                "eigen": {"winkel": 90},
            }
        }
    ) == {"verlauf": {"eigen": {"winkel": 90}}}
    assert darstellungwahl.wahl_pruefen({"verlauf": {"hell": {"winkel": 90}}}) is None


def test_ein_farbton_null_ist_beim_eigenen_verlauf_eine_wahl():
    """The own gradient starts turned, so a hue of zero is a change and is
    kept; out of range still falls away."""
    assert darstellungwahl.wahl_pruefen({"verlauf": {"eigen": {"ton": 0}}}) == {
        "verlauf": {"eigen": {"ton": 0}}
    }
    assert darstellungwahl.wahl_pruefen({"verlauf": {"eigen": {"ton": 181}}}) is None


def test_verlauf_falsches_faellt_weg():
    """A wrong count for the look, a colour that is no six-digit hex, an
    angle or hue out of range, a bool, an unknown look — each falls away."""
    assert (
        darstellungwahl.wahl_pruefen(
            {"verlauf": {"eigen": {"farben": ["#aabbcc", "#112233", "#445566"]}}}
        )
        is None
    )
    assert (
        darstellungwahl.wahl_pruefen(
            {"verlauf": {"eigen": {"farben": ["aabbcc", "#112233", "#445566", "#778899"]}}}
        )
        is None
    )
    assert darstellungwahl.wahl_pruefen({"verlauf": {"eigen": {"winkel": 400}}}) is None
    assert darstellungwahl.wahl_pruefen({"verlauf": {"eigen": {"winkel": -1}}}) is None
    assert darstellungwahl.wahl_pruefen({"verlauf": {"eigen": {"ton": -181}}}) is None
    assert darstellungwahl.wahl_pruefen({"verlauf": {"eigen": {"ton": True}}}) is None
    assert darstellungwahl.wahl_pruefen({"verlauf": {"blau": {"ton": 10}}}) is None
    # The edges are real angles and hues, not refusals.
    assert darstellungwahl.wahl_pruefen({"verlauf": {"eigen": {"winkel": 0}}}) == {
        "verlauf": {"eigen": {"winkel": 0}}
    }
    assert darstellungwahl.wahl_pruefen({"verlauf": {"eigen": {"ton": 180}}}) == {
        "verlauf": {"eigen": {"ton": 180}}
    }


def test_ein_leerer_verlaufseintrag_loescht_sich():
    """An entry that holds no usable choice at all disappears — also the
    one look among several — and every untouched look keeps the look's own
    gradient (the silence probe)."""
    assert darstellungwahl.wahl_pruefen({"verlauf": {"eigen": {}}}) is None
    assert darstellungwahl.wahl_pruefen({"verlauf": {"eigen": {"farbe": "rot"}}}) is None
    assert darstellungwahl.wahl_pruefen(
        {"blasenfarbe": "#aabbcc", "verlauf": {"eigen": {"ton": "viel"}}}
    ) == {"blasenfarbe": "#aabbcc"}
    assert darstellungwahl.wahl_pruefen(
        {"verlauf": {"eigen": {"ton": 12}, "blau": {"ton": 5}}}
    ) == {"verlauf": {"eigen": {"ton": 12}}}
    assert darstellungwahl.aufgeloest({"verlauf": {"eigen": {}}})["verlauf"] == {}


def test_die_verlauf_anzahl_stimmt_mit_dem_stilblatt_ueberein():
    """The route vouches for how many colours a look's frame carries; the
    style sheet draws them. A look that gains or loses a colour in one place
    only would be refused or drawn short — the two must not drift."""
    css = (FRONTEND / "stil" / "global.css").read_text(encoding="utf-8")
    bloecke = {
        "eigen": r"\[data-modus='eigen'\]\s*\{([^}]*)\}",
    }
    assert set(bloecke) == set(darstellungwahl.VERLAUF_ANZAHL)
    for schema, muster in bloecke.items():
        treffer = re.search(muster, css)
        assert treffer, f"kein Block für {schema}"
        block = treffer.group(1)
        vorgaben = re.findall(r"--rahmen-vorgabe-(\d+):\s*#", block)
        assert len(vorgaben) == darstellungwahl.VERLAUF_ANZAHL[schema], schema
        # Numbered without gaps: the setters write --rahmen-farbe-1…n.
        assert sorted(vorgaben) == [str(n) for n in range(1, len(vorgaben) + 1)], schema
        assert set(re.findall(r"--rahmen-farbe-(\d+)", block)) == set(vorgaben), schema
        # A three-colour look marks the fourth absent, or the root block's
        # fourth leaks into the field count.
        if len(vorgaben) < 4:
            assert f"--rahmen-vorgabe-{len(vorgaben) + 1}: initial" in block, schema
    # The auto look follows the dark sheet while the device is dark — the
    # whole block, value for value: the mirror the auto resolution rests on.
    auto = re.search(
        r":root:not\(\[data-modus='hell'\], \[data-modus='snow'\], \[data-eigen='hell'\]\)\s*\{([^}]*)\}", css
    )
    assert auto, "kein Block für den Auto-Dunkel-Fall"
    dunkel_treffer = re.search(r"\[data-modus='dunkel'\]\s*\{([^}]*)\}", css)
    assert dunkel_treffer
    auto_block, dunkel_block = auto.group(1), dunkel_treffer.group(1)
    farbmuster = r"--rahmen-vorgabe-\d+:\s*(#[0-9a-fA-F]{6})"
    assert re.findall(farbmuster, auto_block) == re.findall(farbmuster, dunkel_block)
    assert len(re.findall(r"--rahmen-vorgabe-(\d+):\s*#", auto_block)) == 3
    assert "--rahmen-vorgabe-4: initial" in auto_block
    winkel_auto = re.search(r"--rahmen-winkel-vorgabe:\s*(\d+)deg", auto_block)
    winkel_dunkel = re.search(r"--rahmen-winkel-vorgabe:\s*(\d+)deg", dunkel_block)
    assert winkel_auto and winkel_dunkel and winkel_auto.group(1) == winkel_dunkel.group(1)
