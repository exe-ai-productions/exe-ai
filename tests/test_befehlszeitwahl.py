"""The command time-limit setting: what counts as usable, and the fallback.

The half worth guarding hardest is the silent one: whoever sets NOTHING must
get exactly the 120 seconds the code always had. Without that guard,
"configurable" cannot be told apart from "broken".
"""

from __future__ import annotations

from app import befehlszeitwahl as bz
from app.tools import shell


def test_vorgabe_ist_die_alte_konstante():
    # The silent half: no setting anywhere means the shipped 120 — the very
    # constant the shell always had, imported, not copied.
    assert bz.VORGABE == shell.ZEITGRENZE_SEKUNDEN == 120


def test_ganze_zahl_ab_eins_wird_genommen():
    assert bz.wahl_pruefen(1) == 1
    assert bz.wahl_pruefen(120) == 120
    assert bz.wahl_pruefen(86_400) == 86_400


def test_alles_unbrauchbare_zaehlt_als_ungesetzt():
    for wert in (0, -3, 2.5, "300", None, [], {}):
        assert bz.wahl_pruefen(wert) is None


def test_bool_ist_keine_sekundenzahl():
    # True would pass isinstance(_, int) and silently mean 1 — refuse it.
    assert bz.wahl_pruefen(True) is None
    assert bz.wahl_pruefen(False) is None


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


def test_sekunden_fallen_auf_die_vorgabe_zurueck():
    assert bz.sekunden(_FakeRepos(None)) == bz.VORGABE == 120


def test_sekunden_nehmen_den_gesetzten_wert():
    assert bz.sekunden(_FakeRepos(600)) == 600


def test_sekunden_halten_die_vorgabe_bei_muellwert():
    # A stored value that is not a usable count must not become the limit.
    assert bz.sekunden(_FakeRepos(0)) == bz.VORGABE
    assert bz.sekunden(_FakeRepos("lange")) == bz.VORGABE


def test_agentenkopf_gewinnt_ueber_die_kaskade():
    # The head is the most specific layer a job has — same rule as the
    # token budget (app/auftragtokenwahl.py).
    assert bz.sekunden(_FakeRepos(600), agent_wert=90) == 90


def test_unbrauchbarer_agentenwert_tritt_beiseite():
    # A head value that is no usable count steps aside for the cascade —
    # and with nothing set anywhere, for the shipped default.
    assert bz.sekunden(_FakeRepos(600), agent_wert=0) == 600
    assert bz.sekunden(_FakeRepos(None), agent_wert=None) == bz.VORGABE
