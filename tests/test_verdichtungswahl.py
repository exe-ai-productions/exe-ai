"""The compaction threshold: what counts as a usable share, and the fallback.

Built after the tool-round setting next door, and for the same reason it
exists: a number baked into the source has to be wrong for somebody. A chat
of short questions can run most of the way full before folding anything is
worth the request it costs; one that reads large files wants the room long
before that.
"""

from __future__ import annotations

from pathlib import Path

from app import verdichtungswahl as vw

# The repository root, so these source-text guards read the checkout they
# live in and not a path from one particular machine.
WURZEL = Path(__file__).resolve().parent.parent


def test_ein_anteil_im_band_wird_genommen():
    assert vw.wahl_pruefen(50) == 50.0
    assert vw.wahl_pruefen(vw.KLEINSTE) == vw.KLEINSTE
    assert vw.wahl_pruefen(vw.GROESSTE) == vw.GROESSTE
    # A whole number is a share too, and comes back as one.
    assert isinstance(vw.wahl_pruefen(70), float)


def test_alles_unbrauchbare_zaehlt_als_ungesetzt():
    for wert in (0, -3, "50", None, [], {}):
        assert vw.wahl_pruefen(wert) is None


def test_ausserhalb_des_bandes_wird_nicht_zurechtgebogen():
    """Not clamped, refused.

    A number somebody typed and a number this module invented from it are
    different things, and only the first should decide anything. Silently
    turning 95 into 85 would leave a setting on screen that says one thing
    while the program does another.
    """
    assert vw.wahl_pruefen(vw.KLEINSTE - 0.1) is None
    assert vw.wahl_pruefen(vw.GROESSTE + 0.1) is None
    assert vw.wahl_pruefen(200) is None


def test_die_notbremse_bleibt_ausser_reichweite():
    """The handoff at 90% is the last moment a run can still ask for a
    status report and have it fit. A threshold that could be pushed above it
    would be a setting able to break the safety net it sits under."""
    from app import zwischenstand

    assert vw.GROESSTE < zwischenstand.SCHWELLE_PROZENT
    assert vw.wahl_pruefen(zwischenstand.SCHWELLE_PROZENT) is None


def test_bool_ist_kein_anteil():
    # True would pass isinstance(_, int) and silently mean 1 — refuse it.
    assert vw.wahl_pruefen(True) is None
    assert vw.wahl_pruefen(False) is None


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


def test_schwelle_faellt_auf_die_vorgabe_zurueck():
    assert vw.schwelle(_FakeRepos(None)) == vw.VORGABE


def test_schwelle_nimmt_den_gesetzten_wert():
    assert vw.schwelle(_FakeRepos(70)) == 70.0


def test_schwelle_haelt_die_vorgabe_bei_muellwert():
    # A stored value that is not a usable share must not become the threshold.
    assert vw.schwelle(_FakeRepos(0)) == vw.VORGABE
    assert vw.schwelle(_FakeRepos("frueh")) == vw.VORGABE
    assert vw.schwelle(_FakeRepos(99)) == vw.VORGABE


def test_die_verdichtung_hat_keine_eigene_schwelle_mehr():
    """One number for the whole house.

    A chat and a job compacting at different moments, for no reason anybody
    chose, is what two constants for one decision produce. `verdichtung.py`
    used to carry its own 50; the job path read that one and the chat read
    the cascade. Now both ask here.
    """
    from app import verdichtung

    assert not hasattr(verdichtung, "SCHWELLE_PROZENT"), (
        "compaction has a number of its own again -- then it drifts apart from the "
        "setting"
    )


def test_der_auftrag_liest_dieselbe_schwelle():
    """Source-text guard: the job path must go through the cascade, not
    through a number of its own."""

    quelle = (WURZEL / "app/api/v1/auftraege.py").read_text(encoding="utf-8")
    assert "verdichtungswahl.schwelle(" in quelle, (
        "the job does not ask the setting"
    )


def test_die_vorgabe_bleibt_unter_der_notbremse():
    """The handoff is the net this sits under; a default at or above it
    would mean the net never gets its turn."""
    from app import zwischenstand

    assert vw.VORGABE < zwischenstand.SCHWELLE_PROZENT
