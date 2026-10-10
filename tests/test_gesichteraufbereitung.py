"""Getting ID photos into a safe shape before either painter sees them
 — the 223-pixel rounding gap, the untouched originals,
skipping a folder that has not actually changed, and an unreadable photo
never quietly standing in for "no photos at all".

Runs the picture library for real rather than faking image handling — the
actual crop-and-resize behaviour is the point.
Fixture photos are hand-built PNGs (struct + zlib, same approach as
app/bildmetadaten.py), not files borrowed from the system, so a test never
depends on what happens to exist on the machine running it.
"""

from __future__ import annotations

import struct
import time
import zlib
from pathlib import Path

import pytest

from app import gesichteraufbereitung

pytestmark = pytest.mark.skipif(
    not gesichteraufbereitung.verfuegbar(), reason="no picture library on this machine"
)


def _png_erzeugen(pfad: Path, breite: int, hoehe: int, farbe=(200, 120, 60)) -> None:
    def chunk(typ: bytes, daten: bytes) -> bytes:
        return (
            struct.pack(">I", len(daten)) + typ + daten
            + struct.pack(">I", zlib.crc32(typ + daten))
        )

    ihdr = struct.pack(">IIBBBBB", breite, hoehe, 8, 2, 0, 0, 0)  # 8-bit RGB
    zeile = bytes([0]) + bytes(farbe) * breite  # filter "none" + one pixel row
    idat = zlib.compress(zeile * hoehe)
    pfad.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


@pytest.fixture
def gesichter(tmp_path: Path) -> Path:
    ordner = tmp_path / "gesichter"
    ordner.mkdir()
    return ordner


def test_ungueste_masse_landen_alle_auf_der_kante(gesichter, tmp_path):
    """The exact table from the Auftrag: three sizes that made sd-cli's own
    internal scale-to-224 round down to 223 and skip the whole batch."""
    for name, breite, hoehe in (
        ("quadrat", 447, 447), ("breit", 738, 414), ("hoch", 365, 547),
    ):
        _png_erzeugen(gesichter / f"{name}.png", breite, hoehe)

    aufbereitet = gesichteraufbereitung.aufbereiten(gesichter, tmp_path / "arbeit")

    ergebnisse = sorted(p.stem for p in aufbereitet.iterdir() if p.suffix == ".jpeg")
    assert ergebnisse == ["breit-png", "hoch-png", "quadrat-png"]
    for stamm in ergebnisse:
        breite, hoehe = gesichteraufbereitung._masse(aufbereitet / f"{stamm}.jpeg")
        assert (breite, hoehe) == (gesichteraufbereitung.ZIEL_KANTE,) * 2


def test_eine_kleinere_kante_funktioniert_auch(gesichter, tmp_path):
    _png_erzeugen(gesichter / "eins.png", 738, 414)
    aufbereitet = gesichteraufbereitung.aufbereiten(gesichter, tmp_path / "arbeit", kante=224)
    assert gesichteraufbereitung._masse(aufbereitet / "eins-png.jpeg") == (224, 224)


def test_originale_bleiben_unangetastet(gesichter, tmp_path):
    quelle = gesichter / "ich.png"
    _png_erzeugen(quelle, 738, 414)
    vorher_bytes = quelle.read_bytes()
    vorher_zeit = quelle.stat().st_mtime

    gesichteraufbereitung.aufbereiten(gesichter, tmp_path / "arbeit")

    assert quelle.read_bytes() == vorher_bytes
    assert quelle.stat().st_mtime == vorher_zeit
    # Still exactly the size it was drawn at — nothing cropped it in place.
    assert gesichteraufbereitung._masse(quelle) == (738, 414)


def test_unterordner_werden_ignoriert(gesichter, tmp_path):
    """sd-cli itself only reads the top level — an old set kept in a
    subfolder must not end up in the prepared copy either."""
    _png_erzeugen(gesichter / "oben.png", 480, 640)
    alt = gesichter / "altes_set"
    alt.mkdir()
    _png_erzeugen(alt / "unten.png", 480, 640)

    aufbereitet = gesichteraufbereitung.aufbereiten(gesichter, tmp_path / "arbeit")

    assert [p.stem for p in aufbereitet.glob("*.jpeg")] == ["oben-png"]


def test_nicht_bild_dateien_werden_uebersprungen(gesichter, tmp_path):
    _png_erzeugen(gesichter / "ich.png", 480, 640)
    (gesichter / "notiz.txt").write_text("kein Foto")

    aufbereitet = gesichteraufbereitung.aufbereiten(gesichter, tmp_path / "arbeit")

    assert [p.stem for p in aufbereitet.glob("*.jpeg")] == ["ich-png"]


def test_unveraenderte_fotos_werden_nicht_neu_gebaut(gesichter, tmp_path):
    """The fingerprint of this folder must stay stable across
    repeated draws with the same photos — a rebuild on every call would
    give every file a fresh mtime and restart Image-Turbo's server for
    nothing."""
    _png_erzeugen(gesichter / "ich.png", 480, 640)
    arbeitsordner = tmp_path / "arbeit"

    gesichteraufbereitung.aufbereiten(gesichter, arbeitsordner)
    erste_zeit = (arbeitsordner / "ich-png.jpeg").stat().st_mtime
    time.sleep(0.05)
    gesichteraufbereitung.aufbereiten(gesichter, arbeitsordner)

    assert (arbeitsordner / "ich-png.jpeg").stat().st_mtime == erste_zeit


def test_geaenderte_fotos_werden_neu_aufbereitet(gesichter, tmp_path):
    _png_erzeugen(gesichter / "ich.png", 480, 640)
    arbeitsordner = tmp_path / "arbeit"
    gesichteraufbereitung.aufbereiten(gesichter, arbeitsordner)

    _png_erzeugen(gesichter / "zwei.png", 738, 414)
    aufbereitet = gesichteraufbereitung.aufbereiten(gesichter, arbeitsordner)

    assert sorted(p.stem for p in aufbereitet.glob("*.jpeg")) == ["ich-png", "zwei-png"]


# --- Two findings from a review of the face photos ---------------------------


def test_ein_gleicher_stamm_mit_verschiedener_endung_ueberschreibt_sich_nicht(gesichter, tmp_path):
    """The second finding: portrait.jpg and portrait.png used to collide on
    the same output name and one photo silently vanished from the batch."""
    _png_erzeugen(gesichter / "portrait.png", 480, 640)
    (gesichter / "portrait.jpg").write_bytes((gesichter / "portrait.png").read_bytes())

    aufbereitet = gesichteraufbereitung.aufbereiten(gesichter, tmp_path / "arbeit")

    assert sorted(p.stem for p in aufbereitet.glob("*.jpeg")) == [
        "portrait-jpg", "portrait-png",
    ]


def test_ein_unlesbares_foto_gibt_none_wenn_es_das_einzige_ist(gesichter, tmp_path):
    """The first finding: a photo misnamed with a readable extension (a
    phone's HEIC saved as ".jpg", in the reported case) that the library
    cannot actually open must not leave an EMPTY prepared folder standing in for
    "no photos" — the exact silent gap photomaker.gesichter() itself
    already guards against for an empty gesichter/."""
    (gesichter / "eigentlich-heic.jpg").write_bytes(b"kein echtes Bild")

    assert gesichteraufbereitung.aufbereiten(gesichter, tmp_path / "arbeit") is None


def test_ein_unlesbares_foto_neben_einem_guten_wird_nur_uebersprungen(gesichter, tmp_path):
    _png_erzeugen(gesichter / "gut.png", 480, 640)
    (gesichter / "kaputt.jpg").write_bytes(b"kein echtes Bild")

    aufbereitet = gesichteraufbereitung.aufbereiten(gesichter, tmp_path / "arbeit")

    assert aufbereitet is not None
    assert [p.stem for p in aufbereitet.glob("*.jpeg")] == ["gut-png"]


def test_masse_einer_unlesbaren_datei_stuerzt_nicht_ab(tmp_path):
    """A file that is no picture answers (None, None), not an exception.
    The tool that stood here before answered such a file with exit code 0
    and the literal text "<nil>" for both dimensions; the library raises
    instead, and the answer has to stay the same."""
    datei = tmp_path / "kaputt.jpg"
    datei.write_bytes(b"kein echtes Bild")
    assert gesichteraufbereitung._masse(datei) == (None, None)
