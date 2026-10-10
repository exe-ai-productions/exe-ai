"""The folder is what is shown.

Three walls in this program stand over a folder the user owns, and every one
of them used to show something narrower than the folder: the pictures only
names the server had minted itself, the agents' shelf only what its record
knew about, the scripts nothing at all. What they share now lives in
``app/ordnerinhalt.py``, and the dangerous half of it is the second
question — handing a file back by the name a browser sent.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.ordnerinhalt import auflisten, sicherer_pfad


def test_ein_ordner_der_nicht_existiert_ist_leer(tmp_path):
    """The state before the first file, and after a folder was moved away.
    Both are answered with an empty wall, never with an error."""
    assert auflisten(tmp_path / "gibtsnicht") == []


def test_was_drin_liegt_wird_gezeigt(ordner_mit_dateien):
    namen = {p.name for p in auflisten(ordner_mit_dateien)}
    assert namen == {"diagramm.png", "bericht.md", "winzig.png"}


def test_endungen_grenzen_ein(ordner_mit_dateien):
    namen = {p.name for p in auflisten(ordner_mit_dateien, endungen=frozenset({".png"}))}
    assert namen == {"diagramm.png", "winzig.png"}


def test_zu_kleines_faellt_raus(ordner_mit_dateien):
    namen = {p.name for p in auflisten(ordner_mit_dateien, mindestgroesse=100)}
    assert "winzig.png" not in namen
    assert "diagramm.png" in namen


def test_eigene_buchhaltung_bleibt_draussen(ordner_mit_dateien):
    (ordner_mit_dateien / "verzeichnis.json").write_text("[]")
    namen = {p.name for p in auflisten(
        ordner_mit_dateien, auslassen=frozenset({"verzeichnis.json"})
    )}
    assert "verzeichnis.json" not in namen


def test_ordner_darin_stehen_nicht_auf_der_wand(ordner_mit_dateien):
    """None of the three walls can open one, and an unopenable tile is worse
    than no tile."""
    (ordner_mit_dateien / "unterordner").mkdir()
    assert "unterordner" not in {p.name for p in auflisten(ordner_mit_dateien)}


def test_eine_verknuepfung_aus_dem_ordner_heraus_wird_nicht_aufgelistet(tmp_path):
    """Listing answers by the same rule as handing back. ``is_file`` follows
    a link and says yes, ``sicherer_pfad`` resolves it and says no — and
    everything after a listing goes through ``sicherer_pfad``. Listed and
    refused was a tile that did nothing, a picture box that stayed broken,
    and a script the wall called runnable while the runner refused it."""
    draussen = tmp_path / "geheim.png"
    draussen.write_bytes(b"x" * 200)
    ordner = tmp_path / "bilder"
    ordner.mkdir()
    (ordner / "echt.png").write_bytes(b"x" * 200)
    (ordner / "harmlos.png").symlink_to(draussen)
    # A link that stays inside the folder is as good as the file it names.
    (ordner / "zweitname.png").symlink_to("echt.png")

    namen = {p.name for p in auflisten(ordner)}
    assert namen == {"echt.png", "zweitname.png"}
    # The claim itself: whatever is listed, the guard hands back.
    for pfad in auflisten(ordner):
        assert sicherer_pfad(ordner, pfad.name) is not None, pfad.name


def test_das_neueste_steht_oben(ordner_mit_dateien):
    alt = ordner_mit_dateien / "bericht.md"
    neu = ordner_mit_dateien / "diagramm.png"
    os.utime(alt, (1_000_000, 1_000_000))
    os.utime(neu, (2_000_000, 2_000_000))
    reihe = [p.name for p in auflisten(ordner_mit_dateien)]
    assert reihe.index("diagramm.png") < reihe.index("bericht.md")


# --- The guard -------------------------------------------------------------


def test_ein_name_im_ordner_wird_gefunden(ordner_mit_dateien):
    assert sicherer_pfad(ordner_mit_dateien, "diagramm.png") is not None


def test_ein_name_ist_nie_ein_pfad(ordner_mit_dateien):
    for versuch in ("../../etc/passwd", "/etc/passwd", "unter/datei.png", "..", ".", ""):
        assert sicherer_pfad(ordner_mit_dateien, versuch) is None, versuch


def test_eine_verknuepfung_aus_dem_ordner_heraus_wird_abgelehnt(tmp_path):
    """The trick a name pattern can never catch: the name is blameless, the
    file it resolves to is somewhere else entirely."""
    draussen = tmp_path / "geheim.png"
    draussen.write_bytes(b"x" * 200)
    ordner = tmp_path / "bilder"
    ordner.mkdir()
    (ordner / "harmlos.png").symlink_to(draussen)
    assert sicherer_pfad(ordner, "harmlos.png") is None


def test_ein_ordner_ist_keine_datei(ordner_mit_dateien):
    (ordner_mit_dateien / "unterordner").mkdir()
    assert sicherer_pfad(ordner_mit_dateien, "unterordner") is None


import pytest


@pytest.fixture
def ordner_mit_dateien(tmp_path: Path) -> Path:
    (tmp_path / "diagramm.png").write_bytes(b"x" * 300)
    (tmp_path / "bericht.md").write_text("# Bericht\n")
    (tmp_path / "winzig.png").write_bytes(b"x" * 5)
    return tmp_path


# --- What the three walls now show -----------------------------------------


def test_die_ablage_nimmt_auf_was_jemand_hineingelegt_hat(tmp_path):
    """The case this was built for, measured on a real installation: a file
    lay in the shelf's folder and the wall said "nothing delivered yet",
    because it had not come through the delivery tool."""
    from app.agentendock import AgentenDock

    dock = AgentenDock(tmp_path)
    dock.ablegen("bericht.md", b"# Bericht\n", agent="recherche")
    (tmp_path / "counter-script.sh").write_text("#!/bin/bash\n")

    nach_name = {e["name"]: e for e in dock.alle()}
    assert set(nach_name) == {"bericht.md", "counter-script.sh"}
    # Nobody delivered the straggler, so nobody is named for it.
    assert nach_name["counter-script.sh"]["agent"] == ""
    assert nach_name["bericht.md"]["agent"] == "recherche"


def test_eine_aufgenommene_datei_behaelt_ihre_kennung(tmp_path):
    """The id is what a tile clicks with. One that changed between two
    listings would break the very next click."""
    from app.agentendock import AgentenDock

    dock = AgentenDock(tmp_path)
    (tmp_path / "diagramm.png").write_bytes(b"x" * 200)
    erste = {e["name"]: e["id"] for e in dock.alle()}
    zweite = {e["name"]: e["id"] for e in dock.alle()}
    assert erste == zweite


def test_ein_kaputtes_verzeichnis_nimmt_nichts_auf(tmp_path):
    """Writing stragglers over a record we could not read is the silent loss
    the strict read exists to prevent — it would cost the names of
    everything already on the shelf."""
    from app.agentendock import AgentenDock

    dock = AgentenDock(tmp_path)
    dock.ablegen("bericht.md", b"# Bericht\n", agent="recherche")
    (tmp_path / "agentendock.json").write_text("{kaputt")
    (tmp_path / "counter-script.sh").write_text("#!/bin/bash\n")

    assert dock.alle() == []
    # And nothing was touched: the record is repairable, the file is there.
    assert (tmp_path / "agentendock.json").read_text() == "{kaputt"
    assert (tmp_path / "counter-script.sh").is_file()


def test_eine_verknuepfung_auf_sich_selbst_ist_nur_nichts(tmp_path):
    """`resolve` gives up on a link pointing at itself with a RuntimeError,
    not an OSError. Unguarded that reached the route as a 500 where the
    honest answer is the 404 every other name that leads nowhere gets."""
    (tmp_path / "schleife.png").symlink_to(tmp_path / "schleife.png")
    assert sicherer_pfad(tmp_path, "schleife.png") is None
    # And it never reaches the wall either — `is_file` already says no.
    assert auflisten(tmp_path) == []
