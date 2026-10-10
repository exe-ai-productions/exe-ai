"""The tool-round setting: what counts as a usable round limit, and the fallback."""

from __future__ import annotations

from app import werkzeugrundenwahl as wr


def test_ganze_zahl_ab_eins_wird_genommen():
    assert wr.wahl_pruefen(1) == 1
    assert wr.wahl_pruefen(50) == 50
    assert wr.wahl_pruefen(10_000) == 10_000


def test_alles_unbrauchbare_zaehlt_als_ungesetzt():
    for wert in (0, -3, 2.5, "50", None, [], {}):
        assert wr.wahl_pruefen(wert) is None


def test_bool_ist_keine_rundenzahl():
    # True would pass isinstance(_, int) and silently mean 1 — refuse it.
    assert wr.wahl_pruefen(True) is None
    assert wr.wahl_pruefen(False) is None


class _FakeEinstellungen:
    def __init__(self, wert):
        self._wert = wert

    def kette(self, schluessel, *, modell=None, chat=None):
        # One scope is enough for these fakes: the single stored value.
        return ["global"]

    def holen(self, bereich, schluessel):
        return self._wert

    def aufgeloest(self, schluessel, *, modell=None, chat=None, vorgabe=None):
        return self._wert if self._wert is not None else vorgabe


class _FakeRepos:
    def __init__(self, wert):
        self.einstellungen = _FakeEinstellungen(wert)


def test_runden_faellt_auf_die_vorgabe_zurueck():
    assert wr.runden(_FakeRepos(None)) == wr.VORGABE


def test_runden_nimmt_den_gesetzten_wert():
    assert wr.runden(_FakeRepos(120)) == 120


def test_runden_haelt_die_vorgabe_bei_muellwert():
    # A stored value that is not a usable count must not become the limit.
    assert wr.runden(_FakeRepos(0)) == wr.VORGABE
    assert wr.runden(_FakeRepos("viele")) == wr.VORGABE
