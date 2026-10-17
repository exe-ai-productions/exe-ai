"""The built-in file tools: read_file, write_file, edit_file, list_dir.

What matters here is the boundary and the refusals, not the happy path:

* inside a shared folder nothing asks, outside it the confirmation appears,
  and without any shared folder the tools stay shut,
* edit_file refuses both the passage it cannot find and the one it finds
  twice — a silent guess would change the wrong line,
* read_file refuses a binary file instead of handing back replacement
  characters,
* and the listings stop before they fill the whole context.
"""

from __future__ import annotations

import asyncio

import pytest

from app.tools import (
    datei_aendern,
    datei_lesen,
    datei_schreiben,
    dateiwerkzeuge,
    grenzen,
    ordner_lesen,
)
from tests.conftest import pdf_mit_seiten, png_bytes


def lauf(coro):
    return asyncio.run(coro)


@pytest.fixture()
def ordner(tmp_path):
    (tmp_path / "notizen").mkdir()
    # As bytes: in text mode Windows would write the lines with \r\n, and
    # the edit tool keeps a file's own line ends — the LF file this fixture
    # promises would be a CRLF file there (measured).
    (tmp_path / "notizen" / "liste.md").write_bytes(b"eins\nzwei\ndrei\n")
    return [str(tmp_path)]


@pytest.fixture()
def daten(tmp_path):
    """The data folder of the run, carried along into the read tool: the
    model's picture copies (and their markers) land under it — the tool path
    hands it over (app/tools/dateiwerkzeuge.py) — so these tests never write
    into the installed folder."""
    return str(tmp_path / "data")


# --- The boundary ----------------------------------------------------------


@pytest.mark.parametrize("modul", dateiwerkzeuge.MODULE)
def test_ohne_freigabe_bleibt_alles_zu(modul):
    with pytest.raises(grenzen.GrenzeVerletzt):
        lauf(modul.ausfuehren({"path": "irgendwas.txt", "content": "x", "old_text": "a", "new_text": "b"}, []))


@pytest.mark.parametrize("modul", dateiwerkzeuge.MODULE)
def test_innerhalb_fragt_nichts(modul, ordner):
    assert modul.braucht_bestaetigung({"path": "notizen/liste.md"}, ordner) is False


@pytest.mark.parametrize("modul", dateiwerkzeuge.MODULE)
def test_ausserhalb_fragt_nach(modul, ordner):
    assert modul.braucht_bestaetigung({"path": "/etc/hosts"}, ordner) is True
    assert modul.aussenpfad({"path": "../draussen.txt"}, ordner) is not None


def test_ohne_freigabe_wird_nicht_gefragt(ordner):
    """No folder means the tool does not run at all — there is nothing to
    confirm either."""
    assert datei_lesen.braucht_bestaetigung({"path": "/etc/hosts"}, []) is False


# --- read_file -------------------------------------------------------------


def test_lesen_gibt_die_kopfzeile_mit(ordner):
    text = lauf(datei_lesen.ausfuehren({"path": "notizen/liste.md"}, ordner))
    assert text.startswith("lines 1–3 of 3")
    assert "zwei" in text


def test_lesen_mit_ausschnitt(ordner):
    text = lauf(datei_lesen.ausfuehren({"path": "notizen/liste.md", "offset": 2, "limit": 1}, ordner))
    assert text.splitlines() == ["lines 2–2 of 3", "zwei"]


def test_lesen_kappt_lange_dateien(ordner, tmp_path):
    """The cap holds for the WHOLE answer, the continuation hint included.

    Header and hint are counted into it (the way the shell tool counts its
    exit note). Added on top, the answer grew past the ceiling it is cut to
    on its way out and the line that says how to read on was the first thing
    lost — measured with this test's own file: 20,076 characters against a
    ceiling of 20,000.
    """
    (tmp_path / "lang.txt").write_text(("x" * 100 + "\n") * 500, encoding="utf-8")
    text = lauf(datei_lesen.ausfuehren({"path": "lang.txt"}, ordner))
    assert "continue with offset" in text
    assert len(text) <= datei_lesen.MAX_ZEICHEN
    letzte = text.splitlines()[-1]
    assert letzte.startswith("… [truncated at") and letzte.endswith("]"), letzte


def test_lesen_lehnt_binaerdateien_ab(ordner, tmp_path):
    (tmp_path / "bild.bin").write_bytes(b"\x89PNG\x00\x01\x02")
    with pytest.raises(grenzen.GrenzeVerletzt) as fehler:
        lauf(datei_lesen.ausfuehren({"path": "bild.bin"}, ordner))
    assert "binary" in str(fehler.value)


def test_lesen_verweist_bei_ordnern_weiter(ordner):
    with pytest.raises(grenzen.GrenzeVerletzt) as fehler:
        lauf(datei_lesen.ausfuehren({"path": "notizen"}, ordner))
    assert "list_dir" in str(fehler.value)


# --- read_file on a PDF ----------------------------------------------------
#
# A PDF used to come back as replacement characters or, once the binary guard
# was in place, as a refusal — while the very same reader had been pulling
# text out of uploaded PDFs all along. It is the reason uploaded files are
# kept at all: a document too large to travel inside a request is read here,
# a page or a stretch at a time.


@pytest.fixture()
def pdf_ordner(tmp_path, ordner):
    (tmp_path / "bericht.pdf").write_bytes(
        pdf_mit_seiten(["Page one alpha", "Page two beta", "Page three gamma"])
    )
    return ordner


def test_pdf_wird_ganz_mit_seitenmarken_gelesen(pdf_ordner):
    text = lauf(datei_lesen.ausfuehren({"path": "bericht.pdf"}, pdf_ordner))
    assert "3 pages" in text.splitlines()[0]
    assert "[page 1]" in text and "[page 3]" in text
    assert "Page two beta" in text


def test_pdf_einzelne_seite(pdf_ordner):
    text = lauf(datei_lesen.ausfuehren({"path": "bericht.pdf", "page": 2}, pdf_ordner))
    assert "page 2 of 3" in text.splitlines()[0]
    assert "Page two beta" in text
    assert "Page one alpha" not in text


def test_ein_gang_durch_die_seiten_zerlegt_die_datei_einmal(pdf_ordner, monkeypatch):
    """A model walking a report page by page reads the same file again for
    every page. Measured on a 300-page file, taking it apart costs 87 ms —
    so `page 1` through `page 300` cost 26 seconds of pure re-reading, all
    of it behind a tool call the user waits on.
    """
    from app import pdfseiten

    # Through monkeypatch, so the memory of this test does not travel into
    # the next one.
    monkeypatch.setattr(pdfseiten, "_ZULETZT", None)
    zerlegt = []
    echt = pdfseiten._zerlegen
    monkeypatch.setattr(
        pdfseiten, "_zerlegen", lambda daten: (zerlegt.append(1), echt(daten))[1]
    )

    for seite in (1, 2, 3, 2, 1):
        lauf(datei_lesen.ausfuehren({"path": "bericht.pdf", "page": seite}, pdf_ordner))

    assert len(zerlegt) == 1


def test_eine_andere_datei_wird_neu_zerlegt(pdf_ordner, tmp_path, monkeypatch):
    """The silence probe: the memory holds ONE file, and it is keyed on the
    bytes. A second document must not be answered out of the first one's
    pages, and the first must be read again when it comes back."""
    from app import pdfseiten

    (tmp_path / "zweiter.pdf").write_bytes(pdf_mit_seiten(["Ganz was anderes"]))
    # Through monkeypatch, so the memory of this test does not travel into
    # the next one.
    monkeypatch.setattr(pdfseiten, "_ZULETZT", None)
    zerlegt = []
    echt = pdfseiten._zerlegen
    monkeypatch.setattr(
        pdfseiten, "_zerlegen", lambda daten: (zerlegt.append(1), echt(daten))[1]
    )

    erst = lauf(datei_lesen.ausfuehren({"path": "bericht.pdf", "page": 1}, pdf_ordner))
    zweit = lauf(datei_lesen.ausfuehren({"path": "zweiter.pdf", "page": 1}, pdf_ordner))
    nochmal = lauf(datei_lesen.ausfuehren({"path": "bericht.pdf", "page": 1}, pdf_ordner))

    assert "Page one alpha" in erst
    assert "Ganz was anderes" in zweit
    assert "Page one alpha" in nochmal
    assert len(zerlegt) == 3


def test_wer_nicht_wiederkommt_merkt_sich_nichts(monkeypatch):
    """The upload route reads a document exactly once and stores its text
    itself. Pinning that text in memory for the rest of the process buys
    nothing — and a 20 MB document's pages are not a small nothing."""
    from app import pdfseiten

    monkeypatch.setattr(pdfseiten, "_ZULETZT", None)
    daten = pdf_mit_seiten(["Nur einmal gelesen"])

    assert pdfseiten.seiten(daten, merken=False) == ["Nur einmal gelesen"]
    assert pdfseiten._ZULETZT is None

    assert pdfseiten.seiten(daten) == ["Nur einmal gelesen"]
    assert pdfseiten._ZULETZT is not None


def test_pdf_bereich_ueber_zeilen(pdf_ordner):
    """A stretch instead of a page: the same offset/limit window the text
    path has, so one way of reading covers both."""
    text = lauf(
        datei_lesen.ausfuehren({"path": "bericht.pdf", "offset": 3, "limit": 2}, pdf_ordner)
    )
    assert text.startswith("lines 3–4 of 6")
    assert "Page two beta" in text
    assert "Page one alpha" not in text


def test_pdf_seite_die_es_nicht_gibt(pdf_ordner):
    with pytest.raises(grenzen.GrenzeVerletzt) as fehler:
        lauf(datei_lesen.ausfuehren({"path": "bericht.pdf", "page": 9}, pdf_ordner))
    assert "3 pages" in str(fehler.value)


def test_pdf_ohne_textebene_sagt_es(ordner, tmp_path):
    """A scan: no text layer. The empty answer has to say what it is, or the
    model reads it as an empty page."""
    from pypdf import PdfWriter

    schreiber = PdfWriter()
    schreiber.add_blank_page(width=300, height=200)
    with (tmp_path / "scan.pdf").open("wb") as datei:
        schreiber.write(datei)

    text = lauf(datei_lesen.ausfuehren({"path": "scan.pdf"}, ordner))
    assert "no text" in text
    text = lauf(datei_lesen.ausfuehren({"path": "scan.pdf", "page": 1}, ordner))
    assert "no text layer" in text


def test_datei_die_nur_pdf_heisst_wird_als_text_gelesen(ordner, tmp_path):
    (tmp_path / "falsch.pdf").write_text("eins\nzwei\n", encoding="utf-8")
    text = lauf(datei_lesen.ausfuehren({"path": "falsch.pdf"}, ordner))
    assert text.startswith("lines 1–2 of 2")
    assert "zwei" in text


# --- read_file on an image -------------------------------------------------


def test_bild_geht_als_bild_an_das_modell(ordner, tmp_path, daten):
    (tmp_path / "foto.png").write_bytes(png_bytes())
    gereicht: list[tuple[str, str]] = []

    text = lauf(
        datei_lesen.ausfuehren(
            {"path": "foto.png"},
            ordner,
            modellbild=lambda name, url, pfad="": gereicht.append((name, url, pfad)),
            data_dir=daten,
        )
    )
    assert len(gereicht) == 1
    assert gereicht[0][0] == "foto.png"
    assert gereicht[0][1].startswith("data:image/png;base64,")
    # The whole path travels too, so a request that retires the picture later
    # can say where to read it again (app/werkzeugbild.py).
    assert gereicht[0][2].endswith("foto.png")
    assert gereicht[0][2] != "foto.png"
    assert "attached below for THIS response only" in text


def test_bild_ohne_bildsicht_sagt_es_ehrlich(ordner, tmp_path):
    """A model that cannot see is told so. Anything else invites a
    description of a picture nobody looked at."""
    (tmp_path / "foto.png").write_bytes(png_bytes())
    text = lauf(datei_lesen.ausfuehren({"path": "foto.png"}, ordner))
    assert "does not support image input" in text
    assert "Nothing was read" in text


def test_bild_reist_ohne_seine_metadaten(ordner, tmp_path, daten):
    """A photo carries EXIF — camera, time, place. Every other way a picture
    reaches a model strips that first, and the copy handed over here must not
    be the exception. The file on disk stays as it was."""
    import base64

    from tests.conftest import jpeg_mit_exif

    roh = jpeg_mit_exif(b"GPS 51.5074 N, 0.1278 W")
    (tmp_path / "foto.jpg").write_bytes(roh)
    gereicht: list[tuple[str, str]] = []
    lauf(
        datei_lesen.ausfuehren(
            {"path": "foto.jpg"},
            ordner,
            modellbild=lambda name, url, pfad="": gereicht.append((name, url, pfad)),
            data_dir=daten,
        )
    )
    gereichte_bytes = base64.b64decode(gereicht[0][1].split(",", 1)[1])
    assert b"GPS 51.5074" in roh
    assert b"GPS 51.5074" not in gereichte_bytes
    # And the user's own file is untouched.
    assert (tmp_path / "foto.jpg").read_bytes() == roh


def test_bild_wird_an_seinen_bytes_erkannt(ordner, tmp_path, daten):
    """A JPEG called .png is announced as the JPEG it is — the extension says
    WHETHER to look, the bytes say what it is."""
    from tests.conftest import jpeg_mit_exif

    (tmp_path / "falsch.png").write_bytes(jpeg_mit_exif(b""))
    gereicht: list[tuple[str, str]] = []
    lauf(
        datei_lesen.ausfuehren(
            {"path": "falsch.png"},
            ordner,
            modellbild=lambda name, url, pfad="": gereicht.append((name, url, pfad)),
            data_dir=daten,
        )
    )
    assert gereicht[0][1].startswith("data:image/jpeg;base64,")


def test_kein_bild_hinter_dem_bildnamen(ordner, tmp_path):
    """Named like a picture, made of text: read as the text it is — the same
    fall-through a file named .pdf and holding text gets."""
    (tmp_path / "kein.png").write_text("eins\nzwei\n", encoding="utf-8")
    gereicht: list[tuple[str, str]] = []
    text = lauf(
        datei_lesen.ausfuehren(
            {"path": "kein.png"},
            ordner,
            modellbild=lambda name, url, pfad="": gereicht.append((name, url, pfad)),
        )
    )
    assert gereicht == []
    assert text.startswith("lines 1–2 of 2")
    assert "zwei" in text


def test_zu_grosse_datei_wird_gar_nicht_erst_geoeffnet(ordner, tmp_path, monkeypatch):
    """The ceiling stands BEFORE the read: a whole file goes into memory here,
    and a raw scan dump must not take the service with it."""
    from app.api.v1 import dokumente

    monkeypatch.setattr(dokumente, "MAX_BYTES", 10)
    (tmp_path / "dick.pdf").write_bytes(pdf_mit_seiten(["alpha", "beta"]))
    with pytest.raises(grenzen.GrenzeVerletzt) as fehler:
        lauf(datei_lesen.ausfuehren({"path": "dick.pdf"}, ordner))
    assert "exceeding the limit of" in str(fehler.value)


def test_schnitt_auf_einer_seite_nennt_die_seite_weiter(ordner, tmp_path, monkeypatch):
    """Cut inside page N, the hint has to carry N — an offset alone reads the
    whole document again and answers with its beginning."""
    monkeypatch.setattr(datei_lesen, "MAX_ZEICHEN", 200)
    lange_seite = "\n".join(f"Line {nr} of a very long page." for nr in range(1, 60))
    (tmp_path / "lang.pdf").write_bytes(pdf_mit_seiten(["kurz", lange_seite]))
    text = lauf(datei_lesen.ausfuehren({"path": "lang.pdf", "page": 2}, ordner))
    assert "truncated at" in text
    assert "and page 2" in text


# --- Every real picture goes in, as the smaller copy -----------------------


def _gereicht():
    gesehen: list[tuple[str, str, str]] = []
    return gesehen, lambda name, url, pfad="": gesehen.append((name, url, pfad))


def _daten(url: str) -> bytes:
    import base64

    return base64.b64decode(url.split(",", 1)[1])


def test_ein_bild_ueber_20_mb_geht_als_kleinere_kopie_hinein(ordner, tmp_path, daten):
    """A real picture goes in whatever its size — before, this one
    was refused with 'exceeding the limit of'."""
    from app import model_image
    from tests.test_verlaufsbau import _png

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    daten_bytes = _png(2700, 2700, rauschen=True)
    assert len(daten_bytes) > 20 * 1024 * 1024, len(daten_bytes)
    (tmp_path / "foto.png").write_bytes(daten_bytes)
    gesehen, merken = _gereicht()
    text = lauf(
        datei_lesen.ausfuehren({"path": "foto.png"}, ordner, modellbild=merken, data_dir=daten)
    )

    assert len(gesehen) == 1, gesehen
    name, url, pfad = gesehen[0]
    assert name == "foto.png" and pfad.endswith("foto.png")
    assert url.startswith("data:image/jpeg;base64,"), url[:40]  # the copy travels as JPEG
    assert _daten(url) != daten_bytes
    assert "too large" not in text
    # The number names the file's own bytes (after the metadata came off),
    # not the copy's.
    assert f"is an image of {len(daten_bytes):,} bytes" in text, text


def test_ein_bild_mit_11_mb_geht_auch_hinein(ordner, tmp_path, daten):
    """The 10 MB limit is gone for real pictures — this one used
    to be refused with 'too large to attach'."""
    from app import model_image
    from tests.test_verlaufsbau import _png

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    daten_bytes = _png(1950, 1950, rauschen=True)
    assert 10 * 1024 * 1024 < len(daten_bytes) < 20 * 1024 * 1024, len(daten_bytes)
    (tmp_path / "elf.png").write_bytes(daten_bytes)
    gesehen, merken = _gereicht()
    text = lauf(
        datei_lesen.ausfuehren({"path": "elf.png"}, ordner, modellbild=merken, data_dir=daten)
    )

    assert len(gesehen) == 1, gesehen
    assert gesehen[0][1].startswith("data:image/")
    assert "too large" not in text


def test_die_gereichte_daten_url_traegt_die_verkleinerte_kopie(ordner, tmp_path, daten):
    """A picture of 4000 pixels arrives as a JPEG with 1920 on its longest
    side — before, the full-size file went out."""
    from app import model_image
    from tests.test_verlaufsbau import _png

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    (tmp_path / "gross.png").write_bytes(_png(4000, 2500))
    gesehen, merken = _gereicht()
    lauf(
        datei_lesen.ausfuehren({"path": "gross.png"}, ordner, modellbild=merken, data_dir=daten)
    )

    assert len(gesehen) == 1, gesehen
    kopie = tmp_path / "kopie.jpg"
    kopie.write_bytes(_daten(gesehen[0][1]))
    assert model_image.masse(kopie) == (1920, 1200)


def test_zweimal_gelesen_dieselben_bytes(ordner, tmp_path, daten, monkeypatch):
    """The copy is FOUND again, not built again — the same bytes reach the
    model in every round. The bytes alone prove nothing (a freshly built
    copy is byte-identical, the library being deterministic), so the second round
    is forbidden to measure: every building step starts a process."""
    from app import model_image
    from tests.test_verlaufsbau import _messen_verboten, _png

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    (tmp_path / "zweimal.png").write_bytes(_png(4000, 2500))
    gesehen, merken = _gereicht()
    lauf(
        datei_lesen.ausfuehren({"path": "zweimal.png"}, ordner, modellbild=merken, data_dir=daten)
    )
    _messen_verboten(monkeypatch)
    lauf(
        datei_lesen.ausfuehren({"path": "zweimal.png"}, ordner, modellbild=merken, data_dir=daten)
    )

    assert len(gesehen) == 2
    assert gesehen[0][1] == gesehen[1][1], "the second round sends other bytes"


def test_ein_ueberschriebenes_bild_wird_neu_gelesen(ordner, tmp_path, daten):
    """The folder file may change: the changed file gets a new key (which
    carries size, time and inode — their own test below), so the next read
    sees the NEW picture — and the file itself was never touched by the
    tool."""
    from app import model_image
    from tests.test_verlaufsbau import _png

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    ziel = tmp_path / "wechsel.png"
    ziel.write_bytes(_png(4000, 2500, farbe=(30, 90, 160)))
    gesehen, merken = _gereicht()
    lauf(
        datei_lesen.ausfuehren({"path": "wechsel.png"}, ordner, modellbild=merken, data_dir=daten)
    )
    neu = _png(4000, 2500, farbe=(200, 40, 40))
    ziel.write_bytes(neu)
    lauf(
        datei_lesen.ausfuehren({"path": "wechsel.png"}, ordner, modellbild=merken, data_dir=daten)
    )

    assert len(gesehen) == 2
    assert gesehen[0][1] != gesehen[1][1], "the new picture did not arrive"
    # The tool never touches the file itself, before or after reading.
    assert ziel.read_bytes() == neu


def test_der_schluessel_traegt_zeit_und_inode_der_quelle(ordner, tmp_path, daten):
    """The copy recognises its picture by the key in its own
    name. Same bytes, same size — a NEW timestamp alone (by ONE nanosecond,
    the granularity the key names) must lead to a new key, or a file
    rewritten within the same second with the same byte count keeps being
    answered with the copy of the PREVIOUS picture. And two different files
    that agree in stem, size and time must not share one copy — the inode
    separates them."""
    import os

    from app import model_image, speicherorte
    from tests.test_verlaufsbau import _png

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    kopien = speicherorte.bildkopien_verzeichnis_fuer(daten)
    ziel = tmp_path / "zeit.png"
    ziel.write_bytes(_png(4000, 2500))
    gesehen, merken = _gereicht()
    lauf(
        datei_lesen.ausfuehren({"path": "zeit.png"}, ordner, modellbild=merken, data_dir=daten)
    )
    vorher = {p.name for p in kopien.iterdir()}

    stand = ziel.stat()
    # One microsecond, not one nanosecond: NTFS keeps hundreds of
    # nanoseconds, and a step smaller than that is not stored at all.
    os.utime(ziel, ns=(stand.st_atime_ns + 1_000, stand.st_mtime_ns + 1_000))
    lauf(
        datei_lesen.ausfuehren({"path": "zeit.png"}, ordner, modellbild=merken, data_dir=daten)
    )
    nachher = {p.name for p in kopien.iterdir()}
    assert nachher - vorher, "the new time was not in the key — no new copy"

    # Two folders, one name, the very same bytes and times: only the inode
    # separates the two files — and so it must be in the key.
    eine = tmp_path / "eins"
    zwei = tmp_path / "zwei"
    eine.mkdir()
    zwei.mkdir()
    roh = _png(4000, 2500)
    (eine / "doppelt.png").write_bytes(roh)
    (zwei / "doppelt.png").write_bytes(roh)
    st = os.stat(eine / "doppelt.png")
    os.utime(zwei / "doppelt.png", ns=(st.st_atime_ns, st.st_mtime_ns))
    gesehen, merken = _gereicht()
    lauf(
        datei_lesen.ausfuehren(
            {"path": "eins/doppelt.png"}, ordner, modellbild=merken, data_dir=daten
        )
    )
    lauf(
        datei_lesen.ausfuehren(
            {"path": "zwei/doppelt.png"}, ordner, modellbild=merken, data_dir=daten
        )
    )
    doppelt = [p.name for p in kopien.iterdir() if p.name.startswith("doppelt-")]
    assert len(doppelt) == 2, f"without the inode in the key they would be one: {doppelt}"


def test_die_kopie_reist_ohne_metadaten(ordner, tmp_path, daten):
    """The COPY, too, travels without metadata. The operating
    system's tool can carry EXIF over into it (measured: on this system the
    copy of a JPEG with EXIF still held it), so what is handed over is the
    STRIPPED copy — not simply the file the tool wrote, whose metadata
    habits may differ from system to system."""
    import io

    from app import model_image, speicherorte
    from app.bildmetadaten import metadaten_entfernen
    from PIL import Image

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    # Noise does not compress: 2400 pixels of it stay far above both
    # thresholds, and the edge alone (over 1920) already needs a copy.
    bild = Image.effect_noise((2400, 2400), 100).convert("RGB")
    exif = Image.Exif()
    exif[0x010E] = "EXIF 51.5074 N, 0.1278 W"
    puffer = io.BytesIO()
    bild.save(puffer, format="JPEG", quality=90, exif=exif)
    roh = puffer.getvalue()
    assert b"Exif" in roh, "the sample carries no metadata at all"
    (tmp_path / "exif.jpg").write_bytes(roh)
    gesehen, merken = _gereicht()
    lauf(
        datei_lesen.ausfuehren({"path": "exif.jpg"}, ordner, modellbild=merken, data_dir=daten)
    )

    kopie = next(speicherorte.bildkopien_verzeichnis_fuer(daten).glob("exif-*"))
    gesendet = _daten(gesehen[0][1])
    assert b"Exif" not in gesendet, "the metadata travels along"
    assert gesendet == metadaten_entfernen(kopie.read_bytes()), "it is not the copy that travels"
    assert (tmp_path / "exif.jpg").read_bytes() == roh


def test_der_weg_durch_die_werkzeugtuer_traegt_den_datenordner(ordner, tmp_path, daten):
    """The one line that hands the run's data folder from the dispatcher to
    the read tool (app/tools/dateiwerkzeuge.py): a picture read through it
    must put its copy under THAT folder. A test calling the read tool
    directly would not notice the line going missing."""
    from app import model_image, speicherorte
    from tests.test_verlaufsbau import _png

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    (tmp_path / "tuer.png").write_bytes(_png(4000, 2500))
    gesehen, merken = _gereicht()
    lauf(
        dateiwerkzeuge.ausfuehren(
            "read_file", {"path": "tuer.png"}, ordner, modellbild=merken, data_dir=daten
        )
    )

    kopien = speicherorte.bildkopien_verzeichnis_fuer(daten)
    assert list(kopien.glob("tuer-*")), "the copy does not lie in the data folder handed over"


def test_ein_pdf_ueber_20_mb_bekommt_weiter_die_absage(ordner, tmp_path):
    """Silence probe 613: the 20 MB ceiling stays for PDFs."""
    (tmp_path / "gross.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * (21 * 1024 * 1024))
    with pytest.raises(grenzen.GrenzeVerletzt) as fehler:
        lauf(datei_lesen.ausfuehren({"path": "gross.pdf"}, ordner))
    assert "exceeding the limit of" in str(fehler.value)


def test_a_text_file_with_a_picture_name_over_20_mb_is_read_in_pieces(ordner, tmp_path):
    """The bytes decide, not the name: a 25 MB text file called .png is read
    like the same file called .txt — in pieces, with no refusal, and nothing
    handed to the model as a picture."""
    seen, hand_over = _gereicht()
    content = b"no picture, only text\n" * (1200 * 1024)
    assert len(content) > 25 * 1024 * 1024
    (tmp_path / "dump.png").write_bytes(content)
    (tmp_path / "dump.txt").write_bytes(content)
    as_picture = lauf(
        datei_lesen.ausfuehren({"path": "dump.png", "limit": 5}, ordner, modellbild=hand_over)
    )
    as_text = lauf(datei_lesen.ausfuehren({"path": "dump.txt", "limit": 5}, ordner))
    assert seen == []
    assert "exceeding the limit" not in as_picture
    assert as_picture.startswith("lines 1–5 of "), as_picture[:80]
    assert as_picture == as_text


def test_a_text_file_with_a_pdf_name_over_20_mb_is_read_in_pieces(ordner, tmp_path):
    (tmp_path / "dump.pdf").write_bytes(b"no pdf, only text\n" * (1500 * 1024))
    text = lauf(datei_lesen.ausfuehren({"path": "dump.pdf", "limit": 5}, ordner))
    assert "exceeding the limit" not in text
    assert text.startswith("lines 1–5 of "), text[:80]


def test_a_file_with_a_picture_name_is_read_once(ordner, tmp_path, monkeypatch):
    """The whole-file read is for a PDF only; a text file with a picture name
    used to be read whole, and then once more as text."""
    import pathlib

    (tmp_path / "note.png").write_text("plain words\n", encoding="utf-8")
    real = pathlib.Path.read_bytes
    whole_reads: list[str] = []

    def counting(self):
        whole_reads.append(self.name)
        return real(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", counting)
    text = lauf(datei_lesen.ausfuehren({"path": "note.png"}, ordner))
    assert "plain words" in text
    assert whole_reads == []


def test_a_real_pdf_with_a_picture_name_is_not_read_as_pages(ordner, tmp_path):
    """Silence probe: only the .pdf name opens the page reading, and only
    when the bytes are a PDF."""
    (tmp_path / "scan.png").write_bytes(pdf_mit_seiten(["alpha", "beta"]))
    try:
        text = lauf(datei_lesen.ausfuehren({"path": "scan.png"}, ordner))
    except grenzen.GrenzeVerletzt as refusal:
        text = str(refusal)
    # Neither the page marks nor the page count of the PDF reading.
    assert "[page 1]" not in text
    assert "pages, each marked" not in text


def test_a_text_file_over_20_mb_is_read_as_before(ordner, tmp_path):
    """Silence probe: the plain text file never had a ceiling."""
    (tmp_path / "dump.txt").write_bytes(b"no picture, only text\n" * (1200 * 1024))
    text = lauf(datei_lesen.ausfuehren({"path": "dump.txt", "limit": 5}, ordner))
    assert text.startswith("lines 1–5 of "), text[:80]


def test_ohne_werkzeug_geht_das_original_hinein(ordner, tmp_path, daten, monkeypatch):
    """Partial failure: without the tool a VERY large picture goes out as it
    is — no crash, no ceiling of our own."""
    from app import model_image
    from tests.test_verlaufsbau import _png

    monkeypatch.setattr(model_image, "verfuegbar", lambda: False)
    daten_bytes = _png(2600, 2600, rauschen=True)
    (tmp_path / "ohne.png").write_bytes(daten_bytes)
    gesehen, merken = _gereicht()
    text = lauf(
        datei_lesen.ausfuehren({"path": "ohne.png"}, ordner, modellbild=merken, data_dir=daten)
    )

    assert len(gesehen) == 1, gesehen
    assert _daten(gesehen[0][1]) == daten_bytes, "the original did not arrive byte for byte"
    assert "too large" not in text


def test_eine_textdatei_mit_bildendung_wird_als_text_gelesen(ordner, tmp_path):
    """The bytes decide, not the name: a text file called .png is read as the
    text it is. (The picture limit it once carried is gone — the signature
    check now stands in its place.)"""
    (tmp_path / "note.png").write_text(
        "plain words in a file with a picture name\n", encoding="utf-8"
    )
    handed: list[tuple[str, str, str]] = []
    text = lauf(
        datei_lesen.ausfuehren(
            {"path": "note.png"},
            ordner,
            modellbild=lambda name, url, pfad="": handed.append((name, url, pfad)),
        )
    )
    assert handed == []
    assert "plain words in a file with a picture name" in text
    assert "too large" not in text


def test_text_named_like_a_picture_without_vision_is_read_as_text(ordner, tmp_path):
    (tmp_path / "note.png").write_text(
        "plain words in a file with a picture name\n", encoding="utf-8"
    )
    text = lauf(datei_lesen.ausfuehren({"path": "note.png"}, ordner))
    assert text.startswith("lines 1–1 of 1")
    assert "plain words in a file with a picture name" in text
    assert "does not support image input" not in text


def test_binary_named_like_a_picture_without_vision_is_a_binary_file(ordner, tmp_path):
    """No picture signature and not text either: it is answered like any
    other binary file, not as a picture the model cannot see."""
    (tmp_path / "blob.png").write_bytes(b"\x00\x01\x02 not a picture \x00" * 8)
    with pytest.raises(grenzen.GrenzeVerletzt, match="is a binary file"):
        lauf(datei_lesen.ausfuehren({"path": "blob.png"}, ordner))


# --- write_file ------------------------------------------------------------


def test_schreiben_legt_elternordner_an(ordner, tmp_path):
    antwort = lauf(
        datei_schreiben.ausfuehren({"path": "neu/tief/datei.txt", "content": "hallo\n"}, ordner)
    )
    assert (tmp_path / "neu" / "tief" / "datei.txt").read_text(encoding="utf-8") == "hallo\n"
    assert antwort.startswith("Created")


def test_schreiben_sagt_wenn_es_ueberschreibt(ordner):
    lauf(datei_schreiben.ausfuehren({"path": "a.txt", "content": "eins"}, ordner))
    antwort = lauf(datei_schreiben.ausfuehren({"path": "a.txt", "content": "zwei"}, ordner))
    assert antwort.startswith("Overwrote")


def test_schreiben_einer_neuen_datei_traegt_keinen_leeren_aenderungsblock(ordner):
    antwort = lauf(datei_schreiben.ausfuehren({"path": "neu.txt", "content": "hallo\n"}, ordner))
    assert "@@" not in antwort


def test_ueberschreiben_haengt_den_aenderungsblock_an(ordner):
    lauf(datei_schreiben.ausfuehren({"path": "a.txt", "content": "eins\n"}, ordner))
    antwort = lauf(datei_schreiben.ausfuehren({"path": "a.txt", "content": "zwei\n"}, ordner))
    assert "@@" in antwort
    assert "-eins" in antwort
    assert "+zwei" in antwort


# --- write_file · a .pdf path gets a PDF -----------------------------------
#
# read_file has long read PDFs, and write_file could only ever
# write text. A model asked for a report could name one and hand back a text
# file under a .pdf name — something no reader opens.


def test_schreiben_auf_pdf_erzeugt_ein_echtes_pdf(ordner, tmp_path):
    """Read back with pypdf, the same library read_file uses: the file really
    is a PDF and the page carries the text."""
    from pypdf import PdfReader

    antwort = lauf(datei_schreiben.ausfuehren(
        {"path": "bericht.pdf", "content": "Zeile eins\nZeile zwei\n"}, ordner))

    ziel = tmp_path / "bericht.pdf"
    assert ziel.read_bytes()[:5] == b"%PDF-"
    seitentext = PdfReader(str(ziel)).pages[0].extract_text()
    assert "Zeile eins" in seitentext
    assert "Zeile zwei" in seitentext
    assert antwort.startswith("Created")
    # The answer says which of the two it wrote — a caller that asked for a
    # PDF and got text back would otherwise not know.
    assert "Saved as a PDF." in antwort


# --- write_file · a slow PDF does not stall the event loop -----------------
#
# Reportlab lays out and draws synchronously. Called directly from the async
# handler, a slow PDF blocks the whole event loop: nothing else this server
# is doing can make progress until it returns.


def test_ein_langsames_pdf_laesst_eine_gleichzeitige_aufgabe_zuerst_fertig_werden(
    ordner, tmp_path, monkeypatch
):
    """A short concurrent task must finish before the slow write does. If the
    write still blocks the loop, the short task cannot even start running
    until the write's synchronous call returns, so it finishes after it."""
    import time

    def langsames_schreiben(ziel, inhalt):
        time.sleep(0.15)
        ziel.write_bytes(b"%PDF-1.4\n%%EOF")

    monkeypatch.setattr(datei_schreiben, "_pdf_schreiben", langsames_schreiben)

    async def szenario():
        reihenfolge = []

        async def schreib_aufgabe():
            await datei_schreiben.ausfuehren({"path": "bericht.pdf", "content": "x"}, ordner)
            reihenfolge.append("pdf")

        async def kurze_aufgabe():
            await asyncio.sleep(0.02)
            reihenfolge.append("kurz")

        await asyncio.gather(schreib_aufgabe(), kurze_aufgabe())
        return reihenfolge

    assert lauf(szenario()) == ["kurz", "pdf"]


# --- write_file · two PDF writes never run at the same time -----------------
#
# Off the event loop, two PDF writes run as real OS threads and could
# genuinely overlap: both racing the font cache's lazy, unlocked init, or
# both racing a write to the same path. The dedicated single-worker pool
# they now run on keeps them serialized relative to each other while the
# event loop itself stays free.


def test_zwei_pdf_schreibvorgaenge_ueberlappen_sich_nie(ordner, tmp_path, monkeypatch):
    """Two concurrent write_file(...pdf) calls must never have their
    _pdf_schreiben calls running at the same time."""
    import threading
    import time

    gleichzeitig = 0
    hoechststand = 0
    zaehler_schleuse = threading.Lock()

    def gezaehltes_schreiben(ziel, inhalt):
        nonlocal gleichzeitig, hoechststand
        with zaehler_schleuse:
            gleichzeitig += 1
            hoechststand = max(hoechststand, gleichzeitig)
        time.sleep(0.05)
        with zaehler_schleuse:
            gleichzeitig -= 1
        ziel.write_bytes(b"%PDF-1.4\n%%EOF")

    monkeypatch.setattr(datei_schreiben, "_pdf_schreiben", gezaehltes_schreiben)

    async def szenario():
        await asyncio.gather(
            datei_schreiben.ausfuehren({"path": "eins.pdf", "content": "a"}, ordner),
            datei_schreiben.ausfuehren({"path": "zwei.pdf", "content": "b"}, ordner),
        )

    lauf(szenario())
    assert hoechststand == 1


def test_zwei_gleichzeitige_schreibvorgaenge_auf_denselben_pfad_melden_beide_richtig(
    ordner, tmp_path, monkeypatch
):
    """Both calls target the same path and both start before either has
    written anything. Exactly one may say "Created" — the other must see
    the first one's file once its own turn on the pool comes and say
    "Overwrote", not repeat the stale answer from before either write."""
    import time

    def langsames_schreiben(ziel, inhalt):
        time.sleep(0.05)
        ziel.write_bytes(b"%PDF-1.4\n%%EOF")

    monkeypatch.setattr(datei_schreiben, "_pdf_schreiben", langsames_schreiben)

    async def szenario():
        return await asyncio.gather(
            datei_schreiben.ausfuehren({"path": "gleich.pdf", "content": "a"}, ordner),
            datei_schreiben.ausfuehren({"path": "gleich.pdf", "content": "b"}, ordner),
        )

    antworten = lauf(szenario())
    erstellt = sum(1 for antwort in antworten if antwort.startswith("Created"))
    ueberschrieben = sum(1 for antwort in antworten if antwort.startswith("Overwrote"))
    assert (erstellt, ueberschrieben) == (1, 1)


# --- write_file · PDF font coverage -----------------------------------------
#
# Base-14 Helvetica is Latin-1/WinAnsi only: Cyrillic, Greek, CJK and emoji
# all drew as boxes while write_file still reported success. Noto Sans and
# Noto Emoji (both shipped under app/daten) replace it.


def test_lateinischer_text_mit_umlauten_bleibt_unveraendert(ordner, tmp_path):
    """Silence test for the font switch: plain Latin text with umlauts is
    the overwhelming common case, and it reads back exactly as before —
    only the glyph shapes now come from Noto Sans instead of Helvetica."""
    from pypdf import PdfReader

    text = "Über die Wärme können Straßen später glühen."
    lauf(datei_schreiben.ausfuehren({"path": "umlaute.pdf", "content": text}, ordner))

    gelesen = PdfReader(str(tmp_path / "umlaute.pdf")).pages[0].extract_text()
    assert text in gelesen


def test_kyrillisch_griechisch_und_emoji_werden_gezeichnet(ordner, tmp_path):
    """Cyrillic and Greek sit inside the Basic Multilingual Plane, so
    pypdf's ToUnicode map reads them back exactly. Emoji such as U+1F600
    sit above it — pypdf cannot resolve a reportlab-generated ToUnicode
    entry for a code point that wide (a pypdf/reportlab limitation, not
    this tool's), so the emoji is checked the way the coverage check
    itself checks it: by glyph, not by round-tripped text. Only the rendered
    page actually shows the glyph.
    """
    from pypdf import PdfReader

    inhalt = "Привет мир\nΚαλημέρα\n😀"
    antwort = lauf(datei_schreiben.ausfuehren({"path": "welt.pdf", "content": inhalt}, ordner))

    assert antwort.startswith("Created")
    assert "Saved as a PDF." in antwort
    ziel = tmp_path / "welt.pdf"
    assert ziel.read_bytes()[:5] == b"%PDF-"
    text = PdfReader(str(ziel)).pages[0].extract_text()
    assert "Привет мир" in text
    assert "Καλημέρα" in text

    gesichter = datei_schreiben._schriften_laden()
    assert datei_schreiben._schrift_fuer_zeichen("😀", gesichter) == datei_schreiben.SCHRIFT_EMOJI


def test_ein_zeichen_ohne_glyph_wird_abgelehnt_statt_stumm_verloren(ordner, tmp_path):
    """Neither shipped font has CJK. write_file used to report success while
    the content silently vanished into boxes; now it refuses before any page
    exists, in English, naming the character — and nothing is written."""
    with pytest.raises(grenzen.GrenzeVerletzt) as fehler:
        lauf(datei_schreiben.ausfuehren({"path": "chinesisch.pdf", "content": "你好"}, ordner))

    # Both unknown characters are named, not just the first one found.
    assert "你" in str(fehler.value)
    assert "好" in str(fehler.value)
    assert "different file extension" in str(fehler.value)
    assert not (tmp_path / "chinesisch.pdf").exists()


def test_ein_formularvorschub_wird_auch_abgelehnt(ordner, tmp_path):
    """A form feed has no glyph either, but `str.splitlines()` treats it as
    a line break — the coverage scan used to run on text already split that
    way, so the character slipped past the scan and vanished from the page
    silently instead of triggering the refusal this tool promises."""
    with pytest.raises(grenzen.GrenzeVerletzt) as fehler:
        lauf(datei_schreiben.ausfuehren({"path": "vorschub.pdf", "content": "vor\x0cnach"}, ordner))

    assert "\x0c" in str(fehler.value)
    assert not (tmp_path / "vorschub.pdf").exists()


# --- write_file · a tab becomes four spaces ---------------------------------


def test_ein_tabulator_wird_zu_vier_leerzeichen(ordner, tmp_path):
    """A tab has no glyph in either shipped font, and stringWidth has no
    notion of a tab stop, so it used to draw as a box; now it is four spaces
    before anything else runs, the same as most editors already show one."""
    from pypdf import PdfReader

    lauf(datei_schreiben.ausfuehren({"path": "tab.pdf", "content": "start\tende"}, ordner))

    text = PdfReader(str(tmp_path / "tab.pdf")).pages[0].extract_text()
    assert "start    ende" in text


# --- write_file · the underscore is a fourth break mark --------------------


def test_ein_zu_breiter_dateiname_trennt_auch_hinter_dem_unterstrich(ordner, tmp_path):
    """File names built from underscore-joined parts are common —
    without `_` as a break mark, a long one was cut between characters."""
    from pypdf import PdfReader

    name = "2025-01-15_notes042_pdf_font_and_underscore_picture_twenty_three_long_enough_for_two_full_lines"
    lauf(datei_schreiben.ausfuehren({"path": "name.pdf", "content": name}, ordner))

    zeilen = [z for z in PdfReader(str(tmp_path / "name.pdf")).pages[0].extract_text().splitlines() if z.strip()]
    platz = datei_schreiben.SEITE[0] - 2 * datei_schreiben.RAND
    assert len(zeilen) > 1, zeilen
    for zeile in zeilen[:-1]:
        assert zeile.endswith("_"), zeilen
    assert "".join(zeilen) == name, zeilen
    assert _breiteste(zeilen) <= platz, zeilen


def test_eine_zu_breite_adresse_trennt_hinter_dem_bindestrich(ordner, tmp_path):
    """A word with no space in it breaks where it says so itself.

    The marks `/`, `-` and `.` are what an address and a file name are built
    from: read in order, the pieces are the same string again. Cut between
    characters instead, the reader gets `…/add` / `ress-t` and has to put
    the thing back together from letter groups.
    """
    adresse = (
        "https://example.org/eine-sehr-lange-adresse-mit-vielen-bindestrichen-"
        "und-keinem-leerzeichen-darin/bericht-zusammenfassung.html"
    )
    lauf(datei_schreiben.ausfuehren({"path": "adresse.pdf", "content": adresse}, ordner))

    zeilen = _pdf_zeilen(tmp_path / "adresse.pdf")
    platz = datei_schreiben.SEITE[0] - 2 * datei_schreiben.RAND
    assert len(zeilen) > 1, zeilen
    # Every line but the last one ends on a mark — that is the whole point.
    for zeile in zeilen[:-1]:
        assert zeile.endswith(("/", "-", ".")), zeilen
    # And read in order the pieces are the address again: nothing lost, no
    # piece invented.
    assert "".join(zeilen) == adresse, zeilen
    # None of it runs past the margin — the promise this whole function makes.
    assert _breiteste(zeilen) <= platz, zeilen


def test_ein_zu_breiter_pfad_trennt_hinter_dem_schraegstrich(ordner, tmp_path):
    """The same rule for a path: the slash is a break, the dots are breaks."""
    pfad = (
        "ordner/ein-ziemlich-langer-name/zwei/really-final/report.v2.final.FINAL.docx"
        "-und-noch-ein-ganzes-stueck-hinten-dran/und/weiter"
    )
    lauf(datei_schreiben.ausfuehren({"path": "pfad.pdf", "content": pfad}, ordner))

    zeilen = _pdf_zeilen(tmp_path / "pfad.pdf")
    platz = datei_schreiben.SEITE[0] - 2 * datei_schreiben.RAND
    assert len(zeilen) > 1, zeilen
    for zeile in zeilen[:-1]:
        assert zeile.endswith(("/", "-", ".")), zeilen
    assert "".join(zeilen) == pfad, zeilen
    assert _breiteste(zeilen) <= platz, zeilen


def test_ein_satz_aus_kurzen_woertern_bricht_nur_an_den_leerzeichen(ordner, tmp_path):
    """Silence test: the new rule must not touch ordinary prose.

    Every line but the last ends on a word and starts with one; a sentence of
    short words never reaches for the marks or for `zeichenweise`.
    """
    satz = (
        "Der Bericht liegt im Ordner und wartet dort auf den naechsten Blick, "
        "denn niemand liest ihn heute noch einmal."
    )
    lauf(datei_schreiben.ausfuehren({"path": "satz.pdf", "content": satz}, ordner))

    seiten = _pdf_zeilen(tmp_path / "satz.pdf")
    platz = datei_schreiben.SEITE[0] - 2 * datei_schreiben.RAND
    assert len(seiten) > 1, seiten
    assert _breiteste(seiten) <= platz, seiten
    assert " ".join(seiten) == satz, seiten
    for zeile in seiten[:-1]:
        assert not zeile.endswith(("/", "-", ".")), seiten


def test_ein_langer_text_wird_auf_mehrere_seiten_verteilt(ordner, tmp_path):
    """More lines than one A4 page holds: the rest goes on the next page
    instead of off the paper."""
    from pypdf import PdfReader

    viele = "\n".join(f"Zeile {n}" for n in range(1, 200))
    lauf(datei_schreiben.ausfuehren({"path": "lang.pdf", "content": viele}, ordner))

    leser = PdfReader(str(tmp_path / "lang.pdf"))
    assert len(leser.pages) > 1
    ganz = "".join(seite.extract_text() for seite in leser.pages)
    assert "Zeile 1" in ganz and "Zeile 199" in ganz


def _pdf_zeilen(ziel):
    """The drawn lines of a PDF, one string each.

    pypdf hands back text that was drawn outside the page as readily as text
    inside it, so `"wort59" in text` proves nothing about the wrap. The width
    of each line does — measured with the same font and size the writer used.
    """
    from pypdf import PdfReader

    zeilen = []
    for seite in PdfReader(str(ziel)).pages:
        zeilen.extend(z for z in seite.extract_text().splitlines() if z.strip())
    return zeilen


def _breiteste(zeilen):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    return max(
        stringWidth(z, datei_schreiben.SCHRIFT, datei_schreiben.SCHRIFTGROESSE)
        for z in zeilen
    )


def test_eine_zeile_breiter_als_die_seite_wird_umbrochen(ordner, tmp_path):
    """A line that would run off the right margin is wrapped into several
    lines, and none of them is wider than the text area."""
    lang = " ".join(f"wort{n}" for n in range(1, 60))
    lauf(datei_schreiben.ausfuehren({"path": "breit.pdf", "content": lang}, ordner))

    zeilen = _pdf_zeilen(tmp_path / "breit.pdf")
    platz = datei_schreiben.SEITE[0] - 2 * datei_schreiben.RAND
    # One input line became several drawn lines — without the wrap it stays one.
    assert len(zeilen) > 3
    assert _breiteste(zeilen) <= platz
    assert "wort1" in zeilen[0] and "wort59" in zeilen[-1]


def test_ein_wort_breiter_als_die_seite_wird_zwischen_zeichen_getrennt(ordner, tmp_path):
    """A long URL or path holds no space to break at. Cut between characters
    it stays on the paper; drawn whole it would run past the right margin."""
    wort = "A" * 300
    lauf(datei_schreiben.ausfuehren({"path": "wort.pdf", "content": wort}, ordner))

    zeilen = _pdf_zeilen(tmp_path / "wort.pdf")
    platz = datei_schreiben.SEITE[0] - 2 * datei_schreiben.RAND
    assert len(zeilen) > 1
    assert _breiteste(zeilen) <= platz
    # Nothing was dropped on the way: all 300 characters are still there.
    assert sum(z.count("A") for z in zeilen) == 300


def test_eine_pdf_endung_in_grossbuchstaben_zaehlt_auch(ordner, tmp_path):
    """The extension is compared in lower case — .PDF is the same wish."""
    antwort = lauf(datei_schreiben.ausfuehren(
        {"path": "GROSS.PDF", "content": "Zeile eins"}, ordner))

    assert (tmp_path / "GROSS.PDF").read_bytes()[:5] == b"%PDF-"
    assert "Saved as a PDF." in antwort


def test_ein_leerer_text_bekommt_trotzdem_eine_seite(ordner, tmp_path):
    """A PDF with no pages is a file no reader opens, and the tool reported
    success."""
    from pypdf import PdfReader

    lauf(datei_schreiben.ausfuehren({"path": "leer.pdf", "content": ""}, ordner))

    assert len(PdfReader(str(tmp_path / "leer.pdf")).pages) == 1


def test_ohne_pdf_endung_bleibt_alles_wie_vorher(ordner, tmp_path):
    """The silence check: any other extension writes the text byte for byte,
    and the change block still comes with it."""
    inhalt = "Zeile eins\nZeile zwei\n"
    lauf(datei_schreiben.ausfuehren({"path": "a.txt", "content": inhalt}, ordner))

    assert (tmp_path / "a.txt").read_bytes() == inhalt.encode("utf-8")

    antwort = lauf(datei_schreiben.ausfuehren(
        {"path": "a.txt", "content": "Zeile eins\nZeile drei\n"}, ordner))
    assert "@@" in antwort
    assert "Saved as a PDF." not in antwort


def test_ein_ueberschriebenes_pdf_traegt_keinen_aenderungsblock(ordner):
    """A PDF is not text: diffing the bytes of the old one against the new
    text would print noise."""
    lauf(datei_schreiben.ausfuehren({"path": "b.pdf", "content": "eins"}, ordner))
    antwort = lauf(datei_schreiben.ausfuehren({"path": "b.pdf", "content": "zwei"}, ordner))

    assert antwort.startswith("Overwrote")
    assert "@@" not in antwort


def test_die_werkzeugbeschreibung_nennt_das_pdf(ordner):
    """The model only knows what the description tells it — including that
    edit_file is no way to correct a PDF."""
    beschreibung = datei_schreiben.werkzeug_beschreibung().beschreibung

    assert ".pdf" in beschreibung
    assert "PDF" in beschreibung
    assert "edit_file cannot change one" in beschreibung


# --- the bytes as the model gave them ---------------------------------------
#
# Windows turns every \n into \r\n in text mode unless the write says
# ``newline=""``. On the Mac the bytes come out right either way, so the
# byte checks here are the silence side; the spies on the write calls are
# what falls over without the fix on every system.


@pytest.fixture()
def write_text_spy(monkeypatch):
    """Records the keywords of every Path.write_text and lets it write."""
    from pathlib import Path

    seen: list[dict] = []
    real = Path.write_text

    def spy(self, data, *args, **kwargs):
        seen.append(dict(kwargs))
        return real(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", spy)
    return seen


def test_write_file_keeps_the_line_feeds_as_given(ordner, tmp_path, write_text_spy):
    lauf(datei_schreiben.ausfuehren({"path": "lf.txt", "content": "a\nb\n"}, ordner))
    assert (tmp_path / "lf.txt").read_bytes() == b"a\nb\n"
    assert write_text_spy[-1].get("newline") == ""


def test_write_file_keeps_a_carriage_return_the_model_gave(ordner, tmp_path, write_text_spy):
    """The silence side: nothing is normalised — \r\n in the text stays
    \r\n in the file."""
    lauf(datei_schreiben.ausfuehren({"path": "crlf.txt", "content": "a\r\nb\r\n"}, ordner))
    assert (tmp_path / "crlf.txt").read_bytes() == b"a\r\nb\r\n"


def test_edit_file_leaves_every_line_feed_a_line_feed(ordner, tmp_path, write_text_spy):
    lauf(datei_aendern.ausfuehren(
        {"path": "notizen/liste.md", "old_text": "zwei", "new_text": "ZWEI"}, ordner
    ))
    assert (tmp_path / "notizen" / "liste.md").read_bytes() == b"eins\nZWEI\ndrei\n"
    assert write_text_spy[-1].get("newline") == ""


def test_edit_file_keeps_the_crlf_of_the_file_on_every_line(ordner, tmp_path, write_text_spy):
    """A file with Windows line ends stays one: the untouched lines, the
    changed line and the lines the edit adds all end in \\r\\n, and no lone
    \\n is left anywhere. The sentence and the change block are those of an
    LF file."""
    (tmp_path / "crlf.md").write_bytes(b"eins\r\nzwei\r\ndrei\r\n")
    antwort = lauf(datei_aendern.ausfuehren(
        {"path": "crlf.md", "old_text": "zwei\n", "new_text": "zwei-a\nzwei-b\n"}, ordner
    ))
    roh = (tmp_path / "crlf.md").read_bytes()
    assert roh == b"eins\r\nzwei-a\r\nzwei-b\r\ndrei\r\n"
    assert roh.count(b"\n") == roh.count(b"\r\n") == 4
    assert antwort.startswith("Changed ") and "line 2" in antwort.splitlines()[0]
    assert "-zwei" in antwort and "+zwei-a" in antwort and "\r" not in antwort
    assert write_text_spy[-1].get("newline") == ""


def test_edit_file_matches_old_text_given_with_crlf(ordner, tmp_path):
    """The model may copy the passage with the file's own \\r\\n: it is
    found all the same, and the result is the same bytes."""
    (tmp_path / "crlf.md").write_bytes(b"eins\r\nzwei\r\ndrei\r\n")
    lauf(datei_aendern.ausfuehren(
        {"path": "crlf.md", "old_text": "zwei\r\n", "new_text": "ZWEI\r\n"}, ordner
    ))
    assert (tmp_path / "crlf.md").read_bytes() == b"eins\r\nZWEI\r\ndrei\r\n"


def test_edit_file_keeps_an_lf_file_lf(ordner, tmp_path):
    """The silence side: a file with \\n stays one, the new lines too."""
    (tmp_path / "lf.md").write_bytes(b"eins\nzwei\ndrei\n")
    lauf(datei_aendern.ausfuehren(
        {"path": "lf.md", "old_text": "zwei\n", "new_text": "zwei-a\r\nzwei-b\n"}, ordner
    ))
    assert (tmp_path / "lf.md").read_bytes() == b"eins\nzwei-a\nzwei-b\ndrei\n"


def test_edit_file_takes_the_majority_ending(ordner, tmp_path):
    """Two \\n and one \\r\\n: the file is an LF file, and the one stray
    \\r\\n goes the way the editor would take it."""
    (tmp_path / "gemischt.md").write_bytes(b"eins\nzwei\r\ndrei\n")
    lauf(datei_aendern.ausfuehren(
        {"path": "gemischt.md", "old_text": "eins", "new_text": "EINS"}, ordner
    ))
    assert (tmp_path / "gemischt.md").read_bytes() == b"EINS\nzwei\ndrei\n"


def test_edit_file_leaves_a_last_line_without_an_ending_as_it_was(ordner, tmp_path):
    """A CRLF file whose last line has no ending: the ending goes onto the
    lines that had one, and the last line stays without."""
    (tmp_path / "offen.md").write_bytes(b"eins\r\nzwei\r\ndrei")
    lauf(datei_aendern.ausfuehren(
        {"path": "offen.md", "old_text": "drei", "new_text": "DREI"}, ordner
    ))
    assert (tmp_path / "offen.md").read_bytes() == b"eins\r\nzwei\r\nDREI"


def test_the_line_ending_is_read_off_the_majority():
    assert datei_aendern.line_ending("a\r\nb\r\nc\n") == "\r\n"
    assert datei_aendern.line_ending("a\nb\nc\r\n") == "\n"
    assert datei_aendern.line_ending("a\r\nb\n") == "\n"  # a tie is not "more than half"
    assert datei_aendern.line_ending("kein Zeilenende") == "\n"


@pytest.fixture()
def atomic_write_spy(monkeypatch):
    """Records the keywords of every whole-or-nothing write and lets it
    write (app/atomic_file.py is the one way the skill and the memory
    take)."""
    from app import atomic_file

    seen: list[dict] = []
    real = atomic_file.write

    def spy(path, data, **kwargs):
        seen.append(dict(kwargs))
        return real(path, data, **kwargs)

    monkeypatch.setattr(atomic_file, "write", spy)
    return seen


async def test_a_skill_is_written_with_line_feeds_only(tmp_path, atomic_write_spy):
    from app import skills
    from app.tools import skill

    mein = tmp_path / "mein"
    mein.mkdir()
    await skill.schreiben(
        {"name": "release", "description": "Vor dem Ausliefern", "instruction": "Erst Tests."}, mein
    )
    roh = (mein / "release" / skills.SKILL_DATEI).read_bytes()
    assert b"\n" in roh and b"\r" not in roh
    assert atomic_write_spy[-1].get("newline") == ""


async def test_the_memory_is_written_with_line_feeds_only(tmp_path, atomic_write_spy):
    from app.tools import memory

    pfad = tmp_path / "memory.md"
    await memory.ausfuehren({"text": "Mag Tee.", "kind": "fact"}, pfad)
    roh = pfad.read_bytes()
    assert b"\n" in roh and b"\r" not in roh
    assert atomic_write_spy[-1].get("newline") == ""


# --- edit_file -------------------------------------------------------------


def test_aendern_trifft_genau_einmal(ordner, tmp_path):
    antwort = lauf(
        datei_aendern.ausfuehren(
            {"path": "notizen/liste.md", "old_text": "zwei", "new_text": "ZWEI"}, ordner
        )
    )
    assert "line 2" in antwort
    assert (tmp_path / "notizen" / "liste.md").read_text(encoding="utf-8") == "eins\nZWEI\ndrei\n"


def test_aendern_haengt_den_aenderungsblock_an(ordner):
    antwort = lauf(
        datei_aendern.ausfuehren(
            {"path": "notizen/liste.md", "old_text": "zwei", "new_text": "ZWEI"}, ordner
        )
    )
    zeilen = antwort.splitlines()
    # The sentence stays the first line — the short form, per the summary.
    assert zeilen[0].startswith("Changed ") and "line 2" in zeilen[0]
    assert "@@" in antwort
    assert "-zwei" in antwort
    assert "+ZWEI" in antwort


def test_aendern_ohne_treffer(ordner):
    with pytest.raises(grenzen.GrenzeVerletzt) as fehler:
        lauf(
            datei_aendern.ausfuehren(
                {"path": "notizen/liste.md", "old_text": "vier", "new_text": "x"}, ordner
            )
        )
    assert "not found" in str(fehler.value)


def test_aendern_bei_mehreren_treffern(ordner, tmp_path):
    (tmp_path / "doppelt.txt").write_text("a\na\n", encoding="utf-8")
    with pytest.raises(grenzen.GrenzeVerletzt) as fehler:
        lauf(datei_aendern.ausfuehren({"path": "doppelt.txt", "old_text": "a", "new_text": "b"}, ordner))
    assert "2 times" in str(fehler.value)
    assert (tmp_path / "doppelt.txt").read_text(encoding="utf-8") == "a\na\n"


# --- list_dir --------------------------------------------------------------


def test_ordner_lesen_nimmt_den_ersten_freigegebenen(ordner):
    text = lauf(ordner_lesen.ausfuehren({}, ordner))
    assert "notizen/" in text


def test_ordner_lesen_zeigt_verstecktes_und_groessen(ordner, tmp_path):
    (tmp_path / ".versteckt").write_text("x", encoding="utf-8")
    text = lauf(ordner_lesen.ausfuehren({}, ordner))
    assert ".versteckt" in text
    assert "1 B" in text


def test_ordner_lesen_geht_in_die_tiefe(ordner):
    flach = lauf(ordner_lesen.ausfuehren({}, ordner))
    tief = lauf(ordner_lesen.ausfuehren({"depth": 2}, ordner))
    assert "liste.md" not in flach
    assert "liste.md" in tief


def test_ordner_lesen_kappt_lange_listen(ordner, tmp_path):
    for nummer in range(ordner_lesen.MAX_EINTRAEGE + 20):
        (tmp_path / f"datei-{nummer:04}.txt").write_text("x", encoding="utf-8")
    text = lauf(ordner_lesen.ausfuehren({}, ordner))
    assert "stopped at" in text


def test_eine_unlesbare_seite_kostet_nicht_das_ganze_pdf(ordner, tmp_path, monkeypatch):
    """499 readable pages must not be lost over the five hundredth. Page-wise
    access to a document too large to travel is the point of this whole path,
    so only a file that cannot be OPENED is refused."""
    import pypdf

    from app import pdfseiten

    (tmp_path / "bericht.pdf").write_bytes(
        pdf_mit_seiten(["Page one alpha", "Page two beta", "Page three gamma"])
    )

    class KaputteSeite:
        def extract_text(self):
            raise ValueError("this page cannot be extracted")

    echter_leser = pypdf.PdfReader

    class LeserMitKaputterSeite:
        def __init__(self, strom):
            self._echt = echter_leser(strom)

        @property
        def pages(self):
            seiten = list(self._echt.pages)
            seiten[1] = KaputteSeite()
            return seiten

    monkeypatch.setattr(pypdf, "PdfReader", LeserMitKaputterSeite)

    daten = (tmp_path / "bericht.pdf").read_bytes()
    assert pdfseiten.seiten(daten) == ["Page one alpha", "", "Page three gamma"]

    # And through the tool: the readable pages stay readable.
    text = lauf(datei_lesen.ausfuehren({"path": "bericht.pdf", "page": 3}, ordner))
    assert "Page three gamma" in text


def test_bytes_that_stop_being_a_picture_are_refused_not_labelled(tmp_path, monkeypatch):
    """When what travels after the metadata strip is no known picture any
    more, ``read_file`` refuses with a clear sentence instead of announcing
    a type the bytes do not have."""
    from app import bildmetadaten
    from app.tools import grenzen
    from tests.test_verlaufsbau import _png

    picture = tmp_path / "small.png"
    picture.write_bytes(_png(8, 8))
    monkeypatch.setattr(bildmetadaten, "metadaten_entfernen", lambda raw: b"not a picture")
    with pytest.raises(grenzen.GrenzeVerletzt, match="could not be prepared as an image"):
        datei_lesen._bild_bereiten(picture, tmp_path / "data")


def test_a_copy_that_is_no_picture_falls_back_to_the_source(tmp_path, monkeypatch):
    """A copy whose bytes are no known picture is not sent: the source's own
    stripped bytes go instead, as when the copy cannot be read at all."""
    import base64

    from app import model_image
    from tests.test_verlaufsbau import _png

    picture = tmp_path / "small.png"
    source = _png(8, 8)
    picture.write_bytes(source)
    broken = tmp_path / "broken-copy.jpg"
    broken.write_bytes(b"not a picture")
    monkeypatch.setattr(model_image, "kopie", lambda quelle, ziel: broken)
    url, _ = datei_lesen._bild_bereiten(picture, tmp_path / "data")
    assert url.startswith("data:image/png;base64,"), url[:40]
    assert base64.b64decode(url.split(",", 1)[1])[:8] == source[:8]
