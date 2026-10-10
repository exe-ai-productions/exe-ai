"""The main model server's start choice, as a stored value.

What this has to get right is the same thing the agent slot's key had to
(test_agentenserver.py): the values a start uses come out of one place, and the
two empties stay apart — "never chosen" is not "chosen: none".
"""

from __future__ import annotations

from app import runnermodellwahl as wahl
from app.api.v1.einstellungen import PRUEFER
from app.db.repositories.einstellungen import GLOBAL
from app.feineinstellungen import Feineinstellungen


def test_der_schluessel_steht_im_pruefer():
    """Without this entry the settings route answers 400 and the whole choice
    stays in the browser it was supposed to leave."""
    assert wahl.SCHLUESSEL in PRUEFER
    assert PRUEFER[wahl.SCHLUESSEL] is wahl.wahl_pruefen


def _setzen(repos, wert):
    repos.einstellungen.setzen(GLOBAL, wahl.SCHLUESSEL, wert)


# --- what may be stored ---------------------------------------------------


def test_nur_was_geschickt_wurde_ueberlebt():
    """The window writes the numbers without resending the module memory, and
    the other way round — so a key that was not sent must not appear."""
    assert wahl.wahl_pruefen({"kontext": 8192}) == {"kontext": 8192}
    assert "modell" not in wahl.wahl_pruefen({"kontext": 8192})


def test_zahlen_werden_eingefangen_statt_abgelehnt():
    """A settings write that failed outright would take the whole choice with
    it; a number out of range is a number to bring into range."""
    assert wahl.wahl_pruefen({"kontext": 10})["kontext"] == wahl.KONTEXT_MIN
    assert wahl.wahl_pruefen({"kontext": 10**9})["kontext"] == wahl.KONTEXT_MAX
    assert wahl.wahl_pruefen({"schichten": -5})["schichten"] == 0
    assert wahl.wahl_pruefen({"kontext": "acht"})["kontext"] == wahl.KONTEXT_VORGABE


def test_der_port_bleibt_none_wenn_niemand_ihn_bewegt_hat():
    """None is a real answer here — "the server's own port" — and not a
    missing one, so it must survive the check."""
    assert wahl.wahl_pruefen({"port": None})["port"] is None
    assert wahl.wahl_pruefen({"port": 0})["port"] is None
    assert wahl.wahl_pruefen({"port": 8123})["port"] == 8123


def test_die_zwei_leeren_bleiben_verschieden():
    """`None` is "never chosen" and `""` is "chosen: none". Folding them
    together lets a pairing somebody switched off walk back in."""
    geprueft = wahl.wahl_pruefen(
        {"module": {"a.gguf": {"drafter": "", "vision": None}}}
    )
    assert geprueft["module"]["a.gguf"] == {"drafter": "", "vision": None}


def test_die_modulliste_ist_begrenzt():
    """The settings column holds JSON and cannot check anything by itself, so
    a direct call on the route must not be able to grow the row without end.
    A write that grows the row past the cap is refused, never shortened."""
    import pytest

    from app.db.repositories.einstellungen import WriteRefused

    enough = {"module": {f"m{i}.gguf": {"drafter": "d"} for i in range(wahl.MODULE_HOECHSTZAHL)}}
    wahl.row_check({}, enough)
    too_many = {"module": {**enough["module"], "zu-viel.gguf": {"drafter": "d"}}}
    with pytest.raises(WriteRefused):
        wahl.row_check(enough, too_many)
    # The value check itself shortens nothing.
    assert len(wahl.wahl_pruefen(too_many)["module"]) == wahl.MODULE_HOECHSTZAHL + 1


def test_an_old_oversized_row_just_cannot_grow():
    """A row stored larger before the cap still takes a write that adds no
    module."""
    import pytest

    from app.db.repositories.einstellungen import WriteRefused

    old = {"module": {f"m{i}.gguf": {"drafter": "d"} for i in range(600)}}
    wahl.row_check(old, {**old, "kontext": 8192})
    with pytest.raises(WriteRefused):
        wahl.row_check(old, {"module": {**old["module"], "neu.gguf": {"drafter": "d"}}})


def test_unsinn_faellt_durch():
    assert wahl.wahl_pruefen("nein") == {}
    assert wahl.wahl_pruefen({"module": "nein"})["module"] == {}
    assert wahl.wahl_pruefen({"module": {"a.gguf": 5}})["module"] == {}


# --- what a start reads back ----------------------------------------------


def test_ohne_gespeichertes_gelten_die_vorgaben(repos):
    werte = wahl.startwerte(repos, "m.gguf")
    assert werte["kontext"] == wahl.KONTEXT_VORGABE
    assert werte["schichten"] == wahl.SCHICHTEN_VORGABE
    assert werte["port"] is None
    assert werte["drafter"] is None
    assert werte["vision"] is None
    assert isinstance(werte["fein"], Feineinstellungen)
    assert wahl.modell(repos) is None


def test_ein_gespeicherter_wert_ueberlebt_die_geaenderte_vorgabe(repos):
    """Moving the default must not move anybody's setting.

    32768 is what this key used to open on. A machine that stored it stored a
    number, not an agreement with the default — and the one that was stored
    is the one a start uses, before the default is ever looked at.

    The other direction is the same test from the other side: a value that
    now equals the default is still a stored value and stays through a
    re-check, so nothing can quietly fold it back into "never chosen".
    """
    frueher = 32768
    assert wahl.KONTEXT_VORGABE != frueher

    _setzen(repos, {"modell": "m.gguf", "kontext": frueher})
    assert wahl.startwerte(repos, "m.gguf")["kontext"] == frueher

    _setzen(repos, {"modell": "m.gguf", "kontext": wahl.KONTEXT_VORGABE})
    geprueft = wahl.wahl_pruefen({"modell": "m.gguf", "kontext": wahl.KONTEXT_VORGABE})
    assert geprueft["kontext"] == wahl.KONTEXT_VORGABE
    assert wahl.startwerte(repos, "m.gguf")["kontext"] == wahl.KONTEXT_VORGABE


def test_die_gespeicherte_wahl_kommt_vollstaendig_zurueck(repos):
    _setzen(repos, {
        "modell": "gross.gguf",
        "kontext": 65536,
        "schichten": 40,
        "port": 8125,
        "module": {"gross.gguf": {"drafter": "mtp-gross.gguf", "vision": "augen.gguf"}},
    })
    assert wahl.modell(repos) == "gross.gguf"
    werte = wahl.startwerte(repos, "gross.gguf")
    assert werte["kontext"] == 65536
    assert werte["schichten"] == 40
    assert werte["port"] == 8125
    assert werte["drafter"] == "mtp-gross.gguf"
    assert werte["vision"] == "augen.gguf"


def test_das_modul_gehoert_zur_datei_und_nicht_zum_server(repos):
    """Two files, two module pairs — the projector that belongs to one is
    nonsense for the next, which is why the memory is per file."""
    _setzen(repos, {"module": {
        "a.gguf": {"drafter": "mtp-a.gguf", "vision": None},
        "b.gguf": {"drafter": None, "vision": "augen-b.gguf"},
    }})
    assert wahl.startwerte(repos, "a.gguf")["drafter"] == "mtp-a.gguf"
    assert wahl.startwerte(repos, "a.gguf")["vision"] is None
    assert wahl.startwerte(repos, "b.gguf")["drafter"] is None
    assert wahl.startwerte(repos, "b.gguf")["vision"] == "augen-b.gguf"
    # A file nobody ever chose a module for asks nothing of the runner, which
    # then falls back to the folder manifest — the behaviour that stood before
    # this key existed.
    assert wahl.startwerte(repos, "c.gguf")["drafter"] is None


def test_die_hebel_kommen_aus_ihrem_eigenen_schluessel(repos):
    """The engine levers were already on the server before this stage. They
    are read from the key that owns them, not copied in here — one place, and
    a start still gets one answer."""
    repos.einstellungen.setzen(GLOBAL, "feineinstellungen", {"kv_cache": "q8_0"})
    assert wahl.startwerte(repos, "m.gguf")["fein"].kv_cache == "q8_0"


def test_eine_gewaehlte_leere_datei_ist_kein_modell(repos):
    """"No model" is a real state of this field, and it must not turn into
    "load something"."""
    _setzen(repos, {"modell": ""})
    assert wahl.modell(repos) is None


def test_merken_laesst_den_rest_der_wahl_stehen(repos):
    """The record every start path passes writes the file and nothing else —
    a start must never quietly reset the window somebody set."""
    _setzen(repos, {"modell": "alt.gguf", "kontext": 65536, "module": {"x": {"drafter": "d"}}})
    wahl.modell_merken(repos, "neu.gguf")
    stand = wahl.wahl(repos)
    assert stand["modell"] == "neu.gguf"
    assert stand["kontext"] == 65536
    assert stand["module"] == {"x": {"drafter": "d"}}


def test_merken_auf_einer_leeren_ablage(repos):
    wahl.modell_merken(repos, "erst.gguf")
    assert wahl.modell(repos) == "erst.gguf"


def test_die_vorgaben_nennen_keine_wahl():
    """What is sent to the page is the fallback, never the answer — the choice
    is what the field says, not what a default would say."""
    assert set(wahl.vorgaben()) == {"kontext", "schichten", "port", "vorladen"}


# --- May the program start this server by itself? ---


def test_vorladen_ist_ab_werk_erlaubt(repos):
    """An installation that has never seen this key preloads exactly as it did
    before the key existed. A default that switches somebody's running program
    off underneath them is not a default, it is a regression."""
    assert wahl.vorladen_erlaubt(repos) is True


def test_vorladen_laesst_sich_abschalten(repos):
    """And back on again — the whole point of the tick box."""
    repos.einstellungen.setzen("global", wahl.SCHLUESSEL, {"vorladen": False})
    assert wahl.vorladen_erlaubt(repos) is False

    repos.einstellungen.setzen("global", wahl.SCHLUESSEL, {"vorladen": True})
    assert wahl.vorladen_erlaubt(repos) is True


def test_vorladen_ueberlebt_ein_schreiben_das_es_nicht_nennt(repos):
    """The key-by-key merge every setting in this house is read through: the
    window writes the context size without resending the tick box, and the
    tick box stays where the user put it."""
    repos.einstellungen.setzen("global", wahl.SCHLUESSEL, {"vorladen": False})
    repos.einstellungen.setzen(
        "global", wahl.SCHLUESSEL,
        {**wahl.wahl(repos), **wahl.wahl_pruefen({"kontext": 4096})},
    )
    assert wahl.wahl(repos)["kontext"] == 4096
    assert wahl.vorladen_erlaubt(repos) is False


def test_vorladen_wird_beim_pruefen_zu_einem_ja_oder_nein(repos):
    """A tick box is a tick box, whatever the route was sent."""
    assert wahl.wahl_pruefen({"vorladen": 0})["vorladen"] is False
    assert wahl.wahl_pruefen({"vorladen": "ja"})["vorladen"] is True
    assert "vorladen" not in wahl.wahl_pruefen({"kontext": 4096})


# --- A default does not freeze into a choice ------------------------------


def test_eine_vorgabe_friert_nicht_als_wahl_ein():
    """"Nobody has chosen" and "today's default" are different answers.

    A write that carries `kontext: null` says the first; storing 32768 for it
    says the second, and tomorrow's default would then be wrong for everybody
    who was here today. It is the same nailing-down the port is spared from
    (see the module header) — what an unset value RUNS as is decided in
    `startwerte`, which is a fallback and not a choice anybody made.
    """
    assert wahl.wahl_pruefen({"kontext": None})["kontext"] is None
    assert wahl.wahl_pruefen({"schichten": None})["schichten"] is None
    # Nonsense is still brought into range rather than refused.
    assert wahl.wahl_pruefen({"kontext": "acht"})["kontext"] == wahl.KONTEXT_VORGABE


def test_ein_ungewaehlter_wert_startet_trotzdem_auf_der_vorgabe(repos):
    """The stored `None` must not travel to the command line as a hole."""
    _setzen(repos, {"kontext": None, "schichten": None})
    werte = wahl.startwerte(repos, "m.gguf")
    assert werte["kontext"] == wahl.KONTEXT_VORGABE
    assert werte["schichten"] == wahl.SCHICHTEN_VORGABE


def test_null_schichten_bleiben_null(repos):
    """0 GPU layers is "run this on the processor alone" — a thing people set
    on purpose, and the one number a falsy test silently turns into 99."""
    assert wahl.wahl_pruefen({"schichten": 0})["schichten"] == 0
    _setzen(repos, {"schichten": 0})
    assert wahl.startwerte(repos, "m.gguf")["schichten"] == 0


def test_ein_gewaehltes_kein_modul_erreicht_den_start(repos):
    """`""` is "chosen: none" and has to arrive as `""`.

    Turned into `None` on the last step it means "nobody said", and the
    runner then attaches what the folder manifest or the name heuristic
    declares — so "explicitly without a projector" showed as "none" in the
    window and as `--mmproj …` on the command line.
    """
    _setzen(repos, {"module": {"a.gguf": {"drafter": "", "vision": ""}}})
    werte = wahl.startwerte(repos, "a.gguf")
    assert werte["drafter"] == ""
    assert werte["vision"] == ""


def test_im_modul_ueberlebt_nur_die_gesendete_rolle():
    """Inside an entry the same rule as at the top of the key.

    A row writes one of the two. Filling the other in with `None` would read
    as "projector never chosen" the moment the write is merged into what is
    stored rather than replacing it — and merging is what keeps two windows
    from undoing each other.
    """
    geprueft = wahl.wahl_pruefen({"module": {"a.gguf": {"vision": "augen.gguf"}}})
    assert geprueft["module"]["a.gguf"] == {"vision": "augen.gguf"}
