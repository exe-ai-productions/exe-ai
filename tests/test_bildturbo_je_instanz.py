"""Two instances of the program, two picture servers — not one killed by the other.

Port and note were the same for every instance, and every start reads the
note and signals whatever it names. So a second instance of the program read
the FIRST one's process id and ended a picture server that was drawing for
somebody else. The data folder is shared between instances; the app's own
port is the one thing they cannot share, so it is what tells them apart.
"""

from __future__ import annotations

from app import bildturbo
from app.bildturbo import Bildturbo


def test_die_ausgelieferte_lage_bleibt_wie_sie_war():
    """An ordinary installation must not move. The shipped app port keeps the
    shipped picture port, and the note keeps the name it already has on
    disk — or the first start after an update would not find its own
    orphan."""
    assert bildturbo.port_fuer(8090) == bildturbo.PORT
    assert bildturbo.port_fuer(None) == bildturbo.PORT
    assert bildturbo.pid_dateiname(None) == bildturbo.PID_DATEI


def test_zwei_instanzen_teilen_weder_port_noch_notiz(tmp_path):
    echt = Bildturbo(tmp_path, 8090)
    pruef = Bildturbo(tmp_path, 8091)
    # The same data folder, deliberately: that is the case that used to bite.
    assert echt._pid_datei != pruef._pid_datei
    assert echt._port != pruef._port


def test_der_abstand_traegt_die_kennung():
    """A trial run beside the running program lands beside it here too,
    rather than on a number somebody has to remember."""
    assert bildturbo.port_fuer(8091) == bildturbo.PORT + 1
    assert bildturbo.port_fuer(8089) == bildturbo.PORT - 1


def test_ohne_port_bleibt_alles_beim_alten(tmp_path):
    """Every caller that knows nothing of instances still works, and gets
    exactly what it got before."""
    ohne = Bildturbo(tmp_path)
    assert ohne._port == bildturbo.PORT
    assert ohne._pid_datei.name == bildturbo.PID_DATEI
