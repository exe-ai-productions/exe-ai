"""The named storage locations."""

from __future__ import annotations

import os

import pytest

from app.config import Config
from app.speicherorte import ORTE, ort


def test_jeder_ort_loest_zu_einem_absoluten_pfad_auf():
    """Every named location resolves, and always to an absolute folder — a
    relative one would land wherever the working directory happened to be."""
    config = Config()
    for eintrag in ORTE:
        pfad = ort(config, eintrag.name)
        assert pfad.is_absolute()


def test_jeder_ort_liegt_woanders():
    """Pictures, picture models and language models are three folders, not
    one — a name that pointed at the same place as another would let one
    kind overwrite the other's files."""
    config = Config()
    pfade = {ort(config, e.name) for e in ORTE}
    assert len(pfade) == len(ORTE)


def test_unbekannter_ort_scheitert_laut():
    """A typo must fail where it is made, not silently at a wrong folder."""
    with pytest.raises(KeyError):
        ort(Config(), "gibtsnicht")


def test_bilderort_folgt_der_konfiguration(tmp_path):
    """Change the configured path and the location follows — this is the hook
    the later move-it-elsewhere feature hangs on."""
    config = Config()
    config.app.bilder_verzeichnis = str(tmp_path / "woanders")
    assert ort(config, "images") == (tmp_path / "woanders").resolve()


def test_setzen_und_zuruecksetzen(tmp_path):
    """A set path takes hold and a reset returns to the installed default."""
    from app.speicherorte import loeschen, ort, setzen, standard
    config = Config()
    config.app.data_dir = str(tmp_path / "data")
    config.app.bilder_verzeichnis = str(tmp_path / "data" / "images")

    neu = tmp_path / "woanders"
    gesetzt = setzen(config, "images", str(neu))
    assert gesetzt == neu.resolve()
    assert ort(config, "images") == neu.resolve()

    zurueck = loeschen(config, "images")
    assert zurueck == standard(config, "images")
    assert ort(config, "images") == standard(config, "images")


def test_setzen_auf_standard_hinterlaesst_keine_ueberschreibung(tmp_path):
    """Choosing exactly the default drops the override instead of storing a
    dead line."""
    from app.speicherorte import setzen, standard, ueberschreibungen
    config = Config()
    config.app.data_dir = str(tmp_path / "data")
    config.app.bilder_verzeichnis = str(tmp_path / "data" / "images")
    setzen(config, "images", str(tmp_path / "erst"))
    setzen(config, "images", str(standard(config, "images")))
    assert "images" not in ueberschreibungen(config)


def test_das_bilderfeld_kann_nicht_auf_den_kopienordner_zeigen(tmp_path):
    """The copies' cache is no ORTE entry, so the plain overlap loop cannot
    see it — a picture folder pointing AT it (or holding it) would put the
    model's copies onto the wall."""
    from app.speicherorte import SpeicherortFehler, bildkopien_verzeichnis, setzen

    config = Config()
    config.app.data_dir = str(tmp_path / "data")
    config.app.bilder_verzeichnis = str(tmp_path / "data" / "images")

    with pytest.raises(SpeicherortFehler):
        setzen(config, "images", str(bildkopien_verzeichnis(config)))
    # The data folder as a whole would HOLD the cache — refused as well.
    with pytest.raises(SpeicherortFehler):
        setzen(config, "images", str(tmp_path / "data"))


def test_kaputte_ueberschreibungsdatei_zaehlt_als_keine(tmp_path):
    """An unreadable overrides file must not take a location down."""
    from app.speicherorte import ort, standard, _ueberschreibungen_datei
    config = Config()
    config.app.data_dir = str(tmp_path / "data")
    config.app.bilder_verzeichnis = str(tmp_path / "data" / "images")
    datei = _ueberschreibungen_datei(config)
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text("{ not json", encoding="utf-8")
    assert ort(config, "images") == standard(config, "images")


def test_leeres_bilderfeld_folgt_dem_datenordner(tmp_path):
    """An empty bilder_verzeichnis follows a moved data_dir — old pictures are
    still found, unlike a hardcoded path."""
    from app.speicherorte import standard
    config = Config()
    config.app.data_dir = str(tmp_path / "woanders")
    config.app.bilder_verzeichnis = ""
    assert standard(config, "images") == (config.datenverzeichnis / "images")


def test_zwei_orte_duerfen_sich_keinen_ordner_teilen(tmp_path):
    """Pointing a second location at another's folder is refused, so the two
    kinds of files never mix."""
    from app.speicherorte import SpeicherortFehler, setzen
    import pytest as _pytest
    config = Config()
    config.app.data_dir = str(tmp_path / "data")
    gemeinsam = tmp_path / "gemeinsam"
    setzen(config, "images", str(gemeinsam))
    with _pytest.raises(SpeicherortFehler):
        setzen(config, "models", str(gemeinsam))
    # And nesting is refused too, in both directions.
    with _pytest.raises(SpeicherortFehler):
        setzen(config, "models", str(gemeinsam / "drin"))


def test_a_relative_path_raises_its_own_key_and_creates_no_folder(tmp_path, monkeypatch):
    from app.speicherorte import SpeicherortFehler, setzen

    monkeypatch.chdir(tmp_path)
    config = Config()
    config.app.data_dir = str(tmp_path / "data")
    config.app.bilder_verzeichnis = str(tmp_path / "data" / "images")

    texts = ["relativ", "./neu", "a/b"]
    if os.name != "nt":
        # Windows has no ``~name`` for another user: it joins the name to the
        # folder of the users and keeps going.
        texts.append("~keinbenutzerdiesesnamens/x")
    for text in texts:
        with pytest.raises(SpeicherortFehler) as fehler:
            setzen(config, "images", text)
        assert fehler.value.grund == "speicherorte.not_absolute"

    assert not (tmp_path / "relativ").exists()
    assert not (tmp_path / "neu").exists()
    assert not (tmp_path / "a").exists()
