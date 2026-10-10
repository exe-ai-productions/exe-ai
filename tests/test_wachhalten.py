"""Keeping the machine awake for a job's duration (app/wachhalten.py).
``subprocess.Popen`` is faked — no real caffeinate
process is ever started by these tests."""

from __future__ import annotations

import pytest

from app import wachhalten


@pytest.fixture(autouse=True)
def sauberer_zustand():
    """The module holds global state (one caffeinate process for the whole
    service) — a test must start from and leave a known-clean count, or an
    unbalanced call elsewhere in the suite would silently skew this file's
    own assertions."""
    wachhalten._prozess = None
    wachhalten._laeufende_auftraege = 0
    yield
    wachhalten._prozess = None
    wachhalten._laeufende_auftraege = 0


class GefaelschterProzess:
    def __init__(self):
        self.beendet = False

    def terminate(self):
        self.beendet = True


def test_erster_lauf_startet_caffeinate(monkeypatch):
    prozesse = []

    def gefaelschtes_popen(befehl):
        prozess = GefaelschterProzess()
        prozesse.append(prozess)
        return prozess

    monkeypatch.setattr(wachhalten.sys, "platform", "darwin")
    monkeypatch.setattr(wachhalten, "Popen", gefaelschtes_popen)

    wachhalten.sicherstellen()
    try:
        assert len(prozesse) == 1
        assert prozesse[0].beendet is False
    finally:
        wachhalten.freigeben()

    assert prozesse[0].beendet is True


def test_zwei_ueberlappende_laeufe_teilen_sich_einen_prozess(monkeypatch):
    prozesse = []

    def gefaelschtes_popen(befehl):
        prozess = GefaelschterProzess()
        prozesse.append(prozess)
        return prozess

    monkeypatch.setattr(wachhalten.sys, "platform", "darwin")
    monkeypatch.setattr(wachhalten, "Popen", gefaelschtes_popen)

    wachhalten.sicherstellen()
    wachhalten.sicherstellen()
    assert len(prozesse) == 1  # not started twice

    wachhalten.freigeben()
    assert prozesse[0].beendet is False  # the other run still needs it

    wachhalten.freigeben()
    assert prozesse[0].beendet is True


def test_ausserhalb_von_macos_wird_nichts_gestartet(monkeypatch):
    aufrufe = []
    monkeypatch.setattr(wachhalten.sys, "platform", "win32")
    monkeypatch.setattr(wachhalten, "Popen", lambda befehl: aufrufe.append(befehl))

    wachhalten.sicherstellen()
    try:
        assert aufrufe == []
    finally:
        wachhalten.freigeben()


def test_fehlendes_caffeinate_wirft_nicht(monkeypatch):
    def platzt(befehl):
        raise OSError("nicht gefunden")

    monkeypatch.setattr(wachhalten.sys, "platform", "darwin")
    monkeypatch.setattr(wachhalten, "Popen", platzt)

    wachhalten.sicherstellen()  # must not raise
    wachhalten.freigeben()
