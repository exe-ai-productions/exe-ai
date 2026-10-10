"""``app/einstellungswahl.py``: the two steps every cascade setting shares.

Five modules had written check-and-fall-back by hand; the copy nobody
remembers is the one that keeps refusing what the others learned to
accept. The routine lives once now, and the five keep only their key,
their default and their idea of a usable value.
"""

from __future__ import annotations

from app import (
    auftragtokenwahl,
    befehlszeitwahl,
    einstellungswahl,
    verdichtungswahl,
    weckrundenwahl,
    werkzeugrundenwahl,
)


def test_ganze_zahl_ab_eins():
    assert einstellungswahl.ganze_zahl_ab_eins(1) == 1
    assert einstellungswahl.ganze_zahl_ab_eins(50) == 50
    for wert in (0, -3, 1.5, "5", True, False, None, [], {}):
        assert einstellungswahl.ganze_zahl_ab_eins(wert) is None, wert


class _Einstellungen:
    """Stands in for the cascade: one stored value per scope."""

    def __init__(self, je_bereich):
        self.je_bereich = je_bereich
        self.gefragt = []

    def kette(self, schluessel, *, modell, chat):
        # Least specific first, exactly like the real chain.
        bereiche = ["global"]
        if modell:
            bereiche.append(f"modell:{modell}")
        if chat:
            bereiche.append(f"chat:{chat}")
        return bereiche

    def holen(self, bereich, schluessel):
        self.gefragt.append((bereich, schluessel))
        return self.je_bereich.get(bereich)


class _Repos:
    def __init__(self, je_bereich):
        # A plain value means "stored globally"; a dict maps scope to value.
        if not isinstance(je_bereich, dict):
            je_bereich = {"global": je_bereich} if je_bereich is not None else {}
        self.einstellungen = _Einstellungen(je_bereich)


def test_aufgeloest_nimmt_den_gesetzten_wert_und_faellt_sonst_zurueck():
    repos = _Repos({"chat:c": 7})
    assert einstellungswahl.aufgeloest(
        repos, "x", einstellungswahl.ganze_zahl_ab_eins, 50, modell="m", chat="c"
    ) == 7
    assert repos.einstellungen.gefragt[0] == ("chat:c", "x"), (
        "the most specific level is not asked first"
    )
    assert einstellungswahl.aufgeloest(
        _Repos({"global": "sieben"}), "x", einstellungswahl.ganze_zahl_ab_eins, 50
    ) == 50
    assert einstellungswahl.aufgeloest(
        _Repos({"global": 0}), "x", einstellungswahl.ganze_zahl_ab_eins, 50
    ) == 50


def test_ein_abgelehnter_wert_faellt_auf_die_naechste_ebene_nicht_auf_die_vorgabe():
    """The defect this rewrite ends: a chat value the checker refuses used
    to skip the global value entirely and land on the shipped default."""
    repos = _Repos({"chat:c": 0, "global": 40})
    assert einstellungswahl.aufgeloest(
        repos, "x", einstellungswahl.ganze_zahl_ab_eins, 80, chat="c"
    ) == 40


def test_die_fuenf_module_gehen_durch_den_einen_helfer():
    """Same shape, same answers, one routine: what a module refuses it
    refuses the way the others do."""
    for modul in (werkzeugrundenwahl, weckrundenwahl, befehlszeitwahl):
        assert modul.wahl_pruefen(3) == 3
        assert modul.wahl_pruefen(0) is None
        assert modul.wahl_pruefen("3") is None
        assert modul.wahl_pruefen(True) is None
    assert auftragtokenwahl.wahl_pruefen(auftragtokenwahl.OBERGRENZE + 1) is None
    assert auftragtokenwahl.wahl_pruefen(3) == 3
    assert verdichtungswahl.schwelle(_Repos(None)) == verdichtungswahl.VORGABE
    assert verdichtungswahl.schwelle(_Repos(40)) == 40.0
    assert werkzeugrundenwahl.runden(_Repos("x")) == werkzeugrundenwahl.VORGABE
    assert weckrundenwahl.runden(_Repos(9)) == 9
