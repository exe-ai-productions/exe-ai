"""Ends a run when the model keeps hitting the same wall.
"""

from __future__ import annotations

from app.schleifenwaechter import Schleifenwaechter


def test_drei_gleiche_ablehnungen_hintereinander_beenden():
    waechter = Schleifenwaechter()
    assert waechter.aufruf("shell", {"befehl": "rm -rf /"}, abgelehnt=True) is False
    assert waechter.aufruf("shell", {"befehl": "rm -rf /"}, abgelehnt=True) is False
    assert waechter.aufruf("shell", {"befehl": "rm -rf /"}, abgelehnt=True) is True


def test_zwei_ablehnungen_beenden_noch_nicht():
    waechter = Schleifenwaechter()
    assert waechter.aufruf("shell", {"befehl": "x"}, abgelehnt=True) is False
    assert waechter.aufruf("shell", {"befehl": "x"}, abgelehnt=True) is False


def test_ein_erlaubter_aufruf_dazwischen_setzt_zurueck():
    waechter = Schleifenwaechter()
    waechter.aufruf("shell", {"befehl": "x"}, abgelehnt=True)
    waechter.aufruf("shell", {"befehl": "x"}, abgelehnt=True)
    assert waechter.aufruf("shell", {"befehl": "x"}, abgelehnt=False) is False
    # The streak is gone — two more identical rejections are not the third.
    assert waechter.aufruf("shell", {"befehl": "x"}, abgelehnt=True) is False
    assert waechter.aufruf("shell", {"befehl": "x"}, abgelehnt=True) is False


def test_ein_abgewandelter_aufruf_dazwischen_setzt_zurueck():
    """Different arguments are a different call — the model tried
    something else, even if that attempt was rejected too."""
    waechter = Schleifenwaechter()
    waechter.aufruf("shell", {"befehl": "a"}, abgelehnt=True)
    waechter.aufruf("shell", {"befehl": "a"}, abgelehnt=True)
    assert waechter.aufruf("shell", {"befehl": "b"}, abgelehnt=True) is False
    assert waechter.aufruf("shell", {"befehl": "b"}, abgelehnt=True) is False
    assert waechter.aufruf("shell", {"befehl": "b"}, abgelehnt=True) is True


def test_ein_anderes_werkzeug_mit_denselben_argumenten_ist_ein_anderer_aufruf():
    waechter = Schleifenwaechter()
    waechter.aufruf("shell", {"pfad": "x"}, abgelehnt=True)
    waechter.aufruf("shell", {"pfad": "x"}, abgelehnt=True)
    assert waechter.aufruf("read_file", {"pfad": "x"}, abgelehnt=True) is False


def test_argument_reihenfolge_spielt_keine_rolle():
    """The same call, the keys just written in a different order — still
    the same rejection, not a fresh one."""
    waechter = Schleifenwaechter()
    waechter.aufruf("shell", {"a": 1, "b": 2}, abgelehnt=True)
    waechter.aufruf("shell", {"b": 2, "a": 1}, abgelehnt=True)
    assert waechter.aufruf("shell", {"a": 1, "b": 2}, abgelehnt=True) is True


def test_ein_fehlgeschlagener_aber_nicht_abgelehnter_aufruf_zaehlt_nicht():
    """Only a Tor 3 refusal counts — a tool that ran and genuinely failed
    is a different problem with a different shape."""
    waechter = Schleifenwaechter()
    for _ in range(5):
        assert waechter.aufruf("shell", {"befehl": "x"}, abgelehnt=False) is False
