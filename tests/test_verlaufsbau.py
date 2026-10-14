"""``app/verlaufsbau.py``: the history as the model sees it, in a module of
its own.

It lived in the request route, and every module that needed the reading
had to be handed a function instead of importing one — the route imports
them, and importing back would have closed a circle. Compaction was
therefore called with ``zeilentext=...`` at every site, and a caller that
passed a different reader would have reintroduced the measurement fault
the parameter was added to prevent. The reading is importable now, and the
guard is that it stays where every reader can reach it.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.verlaufsbau import _verlauf_bauen

WURZEL = Path(__file__).resolve().parent.parent


def test_das_modul_haengt_nicht_an_der_route():
    """Importing the reading must not pull the request route in with it —
    that is the circle the hand-over existed to avoid.

    Asked in a Python process of its own: taking the two modules out of
    this run's ``sys.modules`` and importing them afresh left the rest of
    the run with two copies of the route, and a later test that read the
    route's state looked at the new copy while the app still used the old
    one."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, app.verlaufsbau; "
            "sys.exit(3 if 'app.api.v1.generierung' in sys.modules else 0)",
        ],
        cwd=WURZEL,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                filter(None, [str(WURZEL), os.environ.get("PYTHONPATH")])
            ),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 3, "the reading pulled the route in"
    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr}"


def test_die_lesung_hat_einen_ort_und_die_route_keinen_zweiten():
    route = (WURZEL / "app/api/v1/generierung.py").read_text(encoding="utf-8")
    for name in ("_ersatzsatz", "_zeilenworte", "zeilentext", "_verlauf_bauen"):
        assert not re.search(rf"^def {name}\(", route, re.M), f"{name} is defined in the route again"
    assert "from app.verlaufsbau import _verlauf_bauen" in route
    faltung = (WURZEL / "app/chatverdichtung.py").read_text(encoding="utf-8")
    assert re.search(r"from app\.verlaufsbau import [\w, ]*\bzeilentext\b", faltung), (
        "compaction no longer imports the one reading"
    )
    assert "zeilentext," not in faltung.split("def vielleicht_verdichten")[1].split(")")[0], (
        "compaction is handed the reading again instead of importing it"
    )


def test_die_gespraechsanweisung_uebergeht_eine_spaeter_gespeicherte_werkzeugmeldung(
    client, chat_id
):
    """A finished background run's report is stored as an assistant row and
    travels as ``role="user"`` too (the swap a few lines above in
    ``_verlauf_bauen``) — and can sort after the turn the instruction
    actually belongs to. Scanning backward for the first ``role == "user"``
    would catch that report instead of the sentence that was actually
    spoken."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", content="Wie spät ist es?")
    repositories.messages.speichern(
        chat_id=chat_id, role="assistant", content="[report]", art="werkzeugmeldung"
    )
    chat = repositories.chats.holen(chat_id)
    verlauf = _verlauf_bauen(chat, repositories, "SYS", gespraechsanweisung="ANWEISUNG")
    assert [n.role for n in verlauf] == ["system", "user", "user"]
    assert verlauf[1].content == "ANWEISUNG\n\nWie spät ist es?"
    assert verlauf[2].content == "[report]"


# --- The row with an attachment the model cannot see -----------------------


def _letzte_nachricht(client, chat_id, **zeile):
    """One stored row, read by a model without vision, as the last message.

    The setup the four tests below share: store the row, build the history
    for a model that cannot see, and hand back what the model would get.
    """
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, **zeile)
    chat = repositories.chats.holen(chat_id)
    verlauf = _verlauf_bauen(chat, repositories, "SYS", vision=False)
    return [n for n in verlauf if n.role != "system"][-1]


def test_die_pruefung_erkennt_einen_bericht_und_keine_andere_art():
    """`ist_dienstbericht` is the named check beside `ARTEN`.

    The word stood in that set and was compared by hand in more than one
    place; a typo in one of them would have switched the rule off without a
    sound, and the report would have gone to the model as its own answer
    again. One name, one place, and every art of the set that is not it stays
    what it is."""
    from app.db.repositories.messages import ARTEN, ist_dienstbericht

    # The word has to be IN the set as well: without this line a rename that
    # leaves the literal behind would keep `is True` green while no writer
    # produces the value any more — the rule would be off without a sound,
    # which is the very drift this check is for.
    assert "werkzeugmeldung" in ARTEN
    assert ist_dienstbericht("werkzeugmeldung") is True
    for art in sorted(ARTEN - {"werkzeugmeldung"}):
        assert ist_dienstbericht(art) is False
    # And a row that claims nothing at all is no report either.
    assert ist_dienstbericht(None) is False


def test_eine_berichtszeile_mit_anhang_bleibt_die_stimme_des_dienstes(client, chat_id):
    """A report is the SERVICE talking, with or without a picture beside it.

    The report row carries an attachment, so it lands in the picture branch
    — `speichern` mirrors the first attachment into the scalar `bild`
    (app/db/repositories/messages.py:131), and a row with a picture is read
    as a picture row. That branch hard-coded `role="assistant"`, so a report
    with an attachment would have reached the model as its own earlier words
    — the shape it then copies (asked to "wait and see", a 27B model wrote
    "[background run #2 finished: …]" of its own making). Both branches ask
    `_als_modellnachricht` now, so the two cannot drift apart.
    """
    nachricht = _letzte_nachricht(
        client,
        chat_id,
        role="assistant",
        content="[report]",
        art="werkzeugmeldung",
        anhaenge=["bild.png"],
    )

    assert nachricht.content == "[report]"
    assert nachricht.role == "user"
    assert nachricht.service_report is True


def test_eine_nutzerzeile_mit_anhang_bleibt_wie_sie_war(client, chat_id):
    """Silence probe: a turn the USER wrote does not change. It keeps its
    role, it stays no service report, and the notice about the unseen
    picture still goes in front of what they wrote."""
    nachricht = _letzte_nachricht(
        client, chat_id, role="user", content="Was ist auf dem Bild?", anhaenge=["bild.png"]
    )

    assert nachricht.content.startswith("Was ist auf dem Bild?")
    assert nachricht.role == "user"
    assert nachricht.service_report is False


def test_eine_berichtszeile_ohne_anhang_bleibt_wie_sie_war(client, chat_id):
    """Silence probe for the branch below the picture branch: without an
    attachment the report row reaches the model exactly as before — same
    role, same flag, content unchanged."""
    nachricht = _letzte_nachricht(
        client, chat_id, role="assistant", content="[report]", art="werkzeugmeldung"
    )

    assert nachricht.content == "[report]"
    assert nachricht.role == "user"
    assert nachricht.service_report is True


def test_ein_eigenes_bild_des_modells_bleibt_das_bild_des_modells(client, chat_id):
    """Silence probe for the picture branch: an answer with its own picture
    is a picture the model drew, and keeps travelling as its own answer —
    `role="assistant"`, no service report. Only a REPORT row turns into the
    service's voice there."""
    nachricht = _letzte_nachricht(
        client, chat_id, role="assistant", content="", bild="gezeichnet.png"
    )

    assert nachricht.role == "assistant"
    assert nachricht.service_report is False


# --- What the model sees of a picture ---------------------------------------


def _png(
    breite: int,
    hoehe: int,
    *,
    farbe: tuple[int, int, int] = (40, 90, 160),
    rauschen: bool = False,
) -> bytes:
    """A one-colour PNG of the wanted size, written by hand — or a noisy one
    (``rauschen``), which does not compress: the picture the byte threshold
    is measured against (2100×2100, about 13 MB)."""
    import random
    import struct
    import zlib

    rng = random.Random(619)
    if rauschen:
        zeilen = b"".join(b"\x00" + rng.randbytes(breite * 3) for _ in range(hoehe))
    else:
        zeilen = b"".join(b"\x00" + bytes(farbe) * breite for _ in range(hoehe))

    def stueck(art: bytes, daten: bytes) -> bytes:
        return (
            struct.pack(">I", len(daten)) + art + daten
            + struct.pack(">I", zlib.crc32(art + daten))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + stueck(b"IHDR", struct.pack(">IIBBBBB", breite, hoehe, 8, 2, 0, 0, 0))
        + stueck(b"IDAT", zlib.compress(zeilen, 6))
        + stueck(b"IEND", b"")
    )


def _bild_ablegen(config, name: str, daten: bytes) -> None:
    from app.api.v1.bilder import bilder_verzeichnis

    ordner = bilder_verzeichnis(config)
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / name).write_bytes(daten)


def _messen_verboten(monkeypatch) -> None:
    """Forbids measuring for the rest of the test: on the second call the
    answer has to come from the work folder, and every way of measuring
    starts a process."""
    from app import model_image

    def _nie() -> bool:
        raise AssertionError("it was measured again instead of looked up")

    monkeypatch.setattr(model_image, "verfuegbar", _nie)


def test_das_werkzeug_ist_da_wo_es_da_sein_muss():
    """The library travels with the package, and the module says so on
    every system. Without this pin the whole shrinking can be dead in the
    field — the content tests skip where the tool is missing, so a broken
    answer reads as "not needed here" instead of "broken"."""
    from app import model_image

    assert model_image.verfuegbar() is True


def test_ein_grosses_bild_geht_verkleinert_an_das_modell(client, config, monkeypatch):
    """Over 1920 pixels on the longest side a copy is built: JPEG with 1920
    on its longest side, the ratio untouched (app/model_image.py). The second
    call hands out the same bytes — anything else would leave the provider's
    prompt cache cold in every round."""
    import base64

    from app import model_image, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    _bild_ablegen(config, "gross.png", _png(4000, 2500))

    # The route's own order: the warm-up BUILDS (off the event loop), the
    # stretch only looks up — the second call below cannot build at all
    # (`model_image.nachschlag`), so the picture is warmed here first.
    verlaufsbau.bilder_vorbereiten(config, ["gross.png"])
    erste = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "gross.png")
    # The second round is forbidden to measure: were the copy not looked up,
    # this call would try to build it again and the assertion below would see
    # the original instead of the copy.
    _messen_verboten(monkeypatch)
    zweite = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "gross.png")

    assert erste == zweite, "the second round sends other bytes"
    assert erste.startswith("data:image/jpeg;base64,"), erste[:40]
    roh = base64.b64decode(erste.split(",", 1)[1])
    assert roh[:2] == b"\xff\xd8", "no JPEG"

    import tempfile

    with tempfile.TemporaryDirectory() as ordner:
        kopie = Path(ordner) / "kopie.jpg"
        kopie.write_bytes(roh)
        breite, hoehe = model_image.masse(kopie)
    assert max(breite, hoehe) == 1920, (breite, hoehe)
    assert (breite, hoehe) == (1920, 1200), (breite, hoehe)


def test_die_kopie_steht_nicht_auf_der_bilderwand(client, config):
    """The work folder lies in the DATA folder, never in the picture folder:
    the wall shows the original, never its smaller twin."""
    from app import model_image, speicherorte, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    _bild_ablegen(config, "gross.png", _png(3000, 2000))
    verlaufsbau.bilder_vorbereiten(config, ["gross.png"])

    from app.api.v1.bilder import bilder_verzeichnis

    kopien = speicherorte.bildkopien_verzeichnis(config)
    # A copy really was built — a test that only looks at the wall stays green
    # when nothing happened at all.
    assert list(kopien.glob("*.jpg")), "no copy was built at all"
    # And it lies outside the picture folder: inside it the wall would still
    # not list it (folders are skipped), so the wall alone cannot tell.
    assert bilder_verzeichnis(config) not in kopien.parents
    assert kopien.parent == config.datenverzeichnis

    namen = client.get("/api/v1/bilder").json()["bilder"]
    assert "gross.png" in namen
    assert not [n for n in namen if n.endswith(".jpg")], namen


def test_ein_kleines_bild_kommt_unveraendert_heraus(client, config):
    """Silence probe: under both thresholds the file travels byte-identical."""
    import base64

    from app import verlaufsbau

    daten = _png(800, 600)
    _bild_ablegen(config, "klein.png", daten)

    verlaufsbau.bilder_vorbereiten(config, ["klein.png"])
    url = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "klein.png")
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == daten


def test_ein_kleines_bild_wird_nicht_zweimal_gemessen(client, config, monkeypatch):
    """A picture under both thresholds leaves the answer "no copy needed" in
    the work folder. Without it every round would measure it anew — and
    measuring is a process start, per attachment, in every round, for exactly
    the pictures that need nothing done to them."""
    import base64

    from app import speicherorte, verlaufsbau

    daten = _png(800, 600)
    _bild_ablegen(config, "klein2.png", daten)
    verlaufsbau.bilder_vorbereiten(config, ["klein2.png"])
    erste = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "klein2.png")
    kopien = speicherorte.bildkopien_verzeichnis(config)
    assert list(kopien.glob("*-ganz")), "the answer is not on disk"

    _messen_verboten(monkeypatch)
    zweite = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "klein2.png")

    assert erste == zweite
    assert base64.b64decode(zweite.split(",", 1)[1]) == daten


def test_ohne_werkzeug_geht_das_original_hinaus(client, config, monkeypatch):
    """Partial failure: without the tool the original goes out — no crash,
    no empty message.

    Really without it: the shrink itself is made to throw, not only reported
    as missing, so a call into it anywhere on this path would throw the way
    it would throw on a machine that has no library — which is exactly what
    a chat request must never do (measured once before this was fixed: the
    history could not be built at all)."""
    import base64

    from app import model_image, verlaufsbau

    def wirft(quelle, ziel):
        raise RuntimeError("no library on this machine")

    monkeypatch.setattr(model_image, "verfuegbar", lambda: False)
    monkeypatch.setattr(model_image, "_verkleinern", wirft)
    daten = _png(4000, 2500)
    _bild_ablegen(config, "ohne-werkzeug.png", daten)

    # The warm-up asks for the tool first and finds none — off the loop;
    # the stretch then looks up, finds nothing on record and takes the
    # original. Nothing on this path may throw.
    verlaufsbau.bilder_vorbereiten(config, ["ohne-werkzeug.png"])
    url = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "ohne-werkzeug.png")
    assert base64.b64decode(url.split(",", 1)[1]) == daten


def test_zwei_gleiche_staemme_bekommen_zwei_kopien(client, config):
    """`foto.png` and `foto.jpg` of the same size and second are two
    pictures: the extension travels into the name of the copy, or the model
    would be shown the first one under the second one's name."""
    from app import model_image, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    from app.api.v1.bilder import bilder_verzeichnis

    # Two DIFFERENT pictures sharing a stem: with only size and second in the
    # copy's name they would collide, and the model would be shown the first
    # one under the second one's name.
    _bild_ablegen(config, "foto.png", _png(4000, 2500, farbe=(30, 90, 160)))
    _bild_ablegen(config, "foto.jpg", _png(4000, 2500, farbe=(200, 40, 40)))

    # The key itself, on two files carrying the SAME bytes: size and time
    # agree exactly there, so whatever still separates them is the part that
    # has to. Two one-colour PNGs differ in length (measured: 35.860 against
    # 35.245 bytes), which would let the size part carry the test alone and
    # leave the extension unproven.
    bilder = bilder_verzeichnis(config)
    gleich = _png(4000, 2500, farbe=(30, 90, 160))
    for name in ("gleich.png", "gleich.jpg"):
        _bild_ablegen(config, name, gleich)
    stand = os.stat(bilder / "gleich.png")
    os.utime(bilder / "gleich.jpg", ns=(stand.st_atime_ns, stand.st_mtime_ns))
    schluessel = {n: model_image._kennung(bilder / n) for n in ("gleich.png", "gleich.jpg")}
    assert schluessel["gleich.png"] != schluessel["gleich.jpg"], schluessel
    assert schluessel["gleich.png"].endswith("-png"), schluessel
    assert schluessel["gleich.jpg"].endswith("-jpg"), schluessel

    verlaufsbau.bilder_vorbereiten(config, ["foto.png", "foto.jpg"])
    eins = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "foto.png")
    zwei = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "foto.jpg")
    assert eins != zwei, "both pictures get the same copy"

    from app import speicherorte

    kopien_ordner = speicherorte.bildkopien_verzeichnis(config)
    kopien = sorted(p.name for p in kopien_ordner.glob("*.jpg"))
    assert len(kopien) == 2, kopien
    assert len({p.read_bytes() for p in kopien_ordner.glob("*.jpg")}) == 2, "the two copies are the same"


# --- The copy: under the threshold, in a named place, off the loop


def test_ein_rauschbild_kommt_unter_die_byte_schwelle(client, config, monkeypatch):
    """A picture over both thresholds comes out under ``BYTES_MAX``: the
    noise picture that once left the copy at 3.84 MB — one pass, and the
    threshold the module names was never reached — arrives under it, and
    the second call hands out the same bytes: the ladder writes one file,
    and every later round finds it. (The rungs below the first, every step
    the longest side times 0.8 down to 100 pixels, are forced in
    tests/test_model_image.py — this picture no longer needs them.)"""
    import base64
    import tempfile

    from app import model_image, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    daten = _png(2100, 2100, rauschen=True)
    assert len(daten) > model_image.BYTES_MAX, "the noise picture came out too small"
    _bild_ablegen(config, "rausch.png", daten)

    verlaufsbau.bilder_vorbereiten(config, ["rausch.png"])
    erste = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "rausch.png")
    _messen_verboten(monkeypatch)
    zweite = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "rausch.png")
    assert erste == zweite, "the second round sends other bytes"

    roh = base64.b64decode(erste.split(",", 1)[1])
    assert roh[:2] == b"\xff\xd8", "no JPEG"
    assert len(roh) <= model_image.BYTES_MAX, f"{len(roh)} bytes above the threshold"

    with tempfile.TemporaryDirectory() as ordner:
        kopie = Path(ordner) / "kopie.jpg"
        kopie.write_bytes(roh)
        breite, hoehe = model_image.masse(kopie)
    # The first rung already fits: the library's encoder writes this noise
    # at 1920 in about 2.5 MB (measured; the system tool that stood here
    # before needed a second rung) — square in, square out, at the edge.
    # The rungs below are forced in tests/test_model_image.py.
    assert (breite, hoehe) == (model_image.KANTE_MAX, model_image.KANTE_MAX), (breite, hoehe)


def test_die_kopien_haengen_nicht_am_bilderordner(client, config, tmp_path):
    """A moved picture folder neither takes the copy folder along nor raises
    a new one beside itself: the copies' place is asked for by name and sits
    under the DATA folder. With the old hand-built path the
    copies of a moved folder appeared right next to the new one —
    ``<folder>/model-images`` beside ``<folder>/Bilder``."""
    from app import model_image, speicherorte, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    neu = tmp_path / "bilder-neu"
    speicherorte.setzen(config, "images", neu)
    try:
        _bild_ablegen(config, "gross.png", _png(3000, 2000))
        verlaufsbau.bilder_vorbereiten(config, ["gross.png"])
        url = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "gross.png")
        assert url.startswith("data:image/jpeg;base64,")

        kopien = speicherorte.bildkopien_verzeichnis(config)
        assert list(kopien.glob("*.jpg")), "no copy was built at all"
        assert kopien.parent == config.datenverzeichnis
        # No second folder appears beside the new pictures folder.
        assert not (neu.parent / speicherorte.MODELLBILDER_ORDNER).exists(), "a folder beside the new pictures folder"
        assert not (neu / speicherorte.MODELLBILDER_ORDNER).exists(), "a folder inside the new pictures folder"
    finally:
        speicherorte.loeschen(config, "images")


def test_der_start_raeumt_kopien_ohne_ihr_bild_weg(client, config, monkeypatch):
    """Copies and markers whose picture is gone are removed when the service
    starts — the work folder is a cache: it may only carry what
    a picture can still be answered with. A copy whose picture IS there
    stays, byte for byte; a removal that fails does not stop the rest."""
    import pathlib

    from app import model_image, speicherorte, verlaufsbau
    from app.api.v1.bilder import bilder_verzeichnis

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    for name in ("bleibt.png", "geht.png", "stur.png"):
        _bild_ablegen(config, name, _png(3000, 2000))
    _bild_ablegen(config, "klein.png", _png(800, 600))
    verlaufsbau.bilder_vorbereiten(config, ["bleibt.png", "geht.png", "stur.png", "klein.png"])

    kopien = speicherorte.bildkopien_verzeichnis(config)
    bleibt = list(kopien.glob("bleibt-*.jpg"))
    assert len(bleibt) == 1, sorted(p.name for p in kopien.iterdir())
    vorher = bleibt[0].read_bytes()
    assert list(kopien.glob("klein-*-ganz")), "the marker is missing even before the cleanup"

    bilder = bilder_verzeichnis(config)
    for name in ("geht.png", "stur.png", "klein.png"):
        (bilder / name).unlink()

    # One copy cannot be removed — the start takes the others and goes on.
    echt = pathlib.Path.unlink

    def stur(self, *a, **k):
        if self.name.startswith("stur-"):
            raise OSError("gesperrt")
        return echt(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "unlink", stur)
    entfernt = model_image.aufraeumen(bilder, kopien)

    assert entfernt == 2, "the orphaned copy and the orphaned marker did not go"
    assert not list(kopien.glob("geht-*")), "the copy without a picture is still there"
    assert not list(kopien.glob("klein-*")), "the marker without a picture is still there"
    # The locked one stayed behind — and it did not hold the run up.
    assert list(kopien.glob("stur-*.jpg")), "the locked copy is gone anyway"
    # The copy WITH its picture is untouched, byte for byte.
    assert bleibt[0].read_bytes() == vorher


def test_die_kopien_haengen_an_einer_stelle():
    """Where the copies live is asked for by name, and the tool processes sit
    in a thread — the shape no reader may quietly undo: no
    caller builds the copy folder out of the picture folder any more, the
    start cleans orphaned copies, and the answer route warms the pictures
    through ``asyncio.to_thread``. A source guard, in the house's form."""
    from app.api.v1 import generierung as generierungsmodul

    for datei in (WURZEL / "app").rglob("*.py"):
        text = datei.read_text(encoding="utf-8")
        assert "model_image.arbeitsordner" not in text, f"hand-built path in {datei}"
        assert '.parent / "model-images"' not in text, f"hand-built path in {datei}"
    assert "model_image.aufraeumen(" in (WURZEL / "app/main.py").read_text(encoding="utf-8"), (
        "the start does not clean up the copies"
    )
    assert "asyncio.to_thread(verlaufsbau.bilder_vorbereiten" in Path(
        generierungsmodul.__file__
    ).read_text(encoding="utf-8"), "the route does not warm the pictures off the loop"


def test_ein_alter_grosser_rest_wird_neu_geleitert(client, config):
    """A copy from the old one-pass version can sit ABOVE the threshold
    (exactly the noisy pictures that motivated the
    ladder). The building door takes it as "not on record" and replaces it
    with a leathered one; the lookup door — the stretch's — hands it out
    instead of starting a tool."""
    from app import model_image, speicherorte, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    daten = _png(2100, 2100, rauschen=True)
    _bild_ablegen(config, "alt.png", daten)
    kennung = model_image._kennung(speicherorte.ort(config, "images") / "alt.png")
    kopien = speicherorte.bildkopien_verzeichnis(config)
    kopien.mkdir(parents=True, exist_ok=True)
    alt = kopien / f"alt-{kennung}.jpg"
    alt.write_bytes(b"\xff\xd8" + b"x" * (model_image.BYTES_MAX + 1))  # the old over-sized rest
    alt_roh = alt.read_bytes()

    # Lookup door: the big old copy goes out as it lies — no tool.
    assert model_image.nachschlag(
        speicherorte.ort(config, "images") / "alt.png", kopien
    ) == alt
    assert alt.read_bytes() == alt_roh

    # Building door: the ladder replaces it.
    verlaufsbau.bilder_vorbereiten(config, ["alt.png"])
    assert alt.stat().st_size <= model_image.BYTES_MAX, alt.stat().st_size
    assert alt.read_bytes() != alt_roh


def test_der_aufraeumer_laesst_fremde_namen_liegen(client, config):
    """The reaper only takes what carries a record EXACTLY: an ordinary dashed name, a half-written -teil file and a
    foreign file stay; the genuine orphan still goes."""
    from app import model_image, speicherorte, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    _bild_ablegen(config, "geht9.png", _png(3000, 2000))
    verlaufsbau.bilder_vorbereiten(config, ["geht9.png"])
    kopien = speicherorte.bildkopien_verzeichnis(config)
    (speicherorte.ort(config, "images") / "geht9.png").unlink()

    fremd = {
        "urlaub-2024-08-01-12-30.jpg",
        "foto-100-200-300-png-a1b2c3-t-eil.jpg",
        "notizen.txt",
    }
    for name in fremd:
        (kopien / name).write_bytes(b"nicht unsere Sache")
    teil = kopien / "geht9-1-2-3-png-abcdef-1234567890abcdef1234567890abcdef-teil.jpg"
    teil.write_bytes(b"\xff\xd8halb")

    entfernt = model_image.aufraeumen(speicherorte.ort(config, "images"), kopien)

    assert entfernt == 1, "exactly the orphan should go"
    for name in fremd | {teil.name}:
        assert (kopien / name).exists(), f"{name} was touched"


def test_ein_umbenanntes_bild_verliert_seine_alte_kopie(client, config):
    """Renaming in place keeps size, time and inode — the key is unchanged,
    only the stem differs. Matched by stem AND key, the reaper takes the old
    record; with the key alone the cache would grow by one entry per rename."""
    from app import model_image, speicherorte, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    bilder = speicherorte.ort(config, "images")
    _bild_ablegen(config, "vorher9.png", _png(3000, 2000))
    verlaufsbau.bilder_vorbereiten(config, ["vorher9.png"])
    kopien = speicherorte.bildkopien_verzeichnis(config)
    assert len(list(kopien.glob("vorher9-*.jpg"))) == 1

    os.rename(bilder / "vorher9.png", bilder / "nachher9.png")

    entfernt = model_image.aufraeumen(bilder, kopien)

    assert entfernt == 1, "the old copy stayed behind"
    assert not list(kopien.glob("vorher9-*.jpg"))
    assert not list(kopien.glob("nachher9-*.jpg"))  # no new one yet


def test_ein_unlesbares_bild_zaehlt_nicht_als_verschwunden(client, config, monkeypatch):
    """A stat failure is UNREADABLE, not gone: a folder the walk cannot look
    into must not widen the list of the deceased (a
    chmod-0400 picture folder used to wipe the whole cache). Nothing is
    removed when the list cannot be completed."""
    from app import model_image, speicherorte, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    _bild_ablegen(config, "gesperrt9.png", _png(3000, 2000))
    verlaufsbau.bilder_vorbereiten(config, ["gesperrt9.png"])
    kopien = speicherorte.bildkopien_verzeichnis(config)
    assert list(kopien.glob("gesperrt9-*"))

    echt = model_image._kennung

    def stur(pfad):
        raise OSError("kein Zugriff")

    monkeypatch.setattr(model_image, "_kennung", stur)
    entfernt = model_image.aufraeumen(speicherorte.ort(config, "images"), kopien)
    monkeypatch.setattr(model_image, "_kennung", echt)

    assert entfernt == 0, "cleaned up despite an unreadable list"
    assert list(kopien.glob("gesperrt9-*")), "the copy fell victim to the unreadable walk"


def test_eine_nur_andere_schreibweise_behaelt_die_kopie(client, config):
    """A rename that only changes case keeps size, time and inode — and one
    file, on this platform's volumes. The reaper compares stems case-folded,
    or such a copy would fall at every start."""
    from app import model_image, speicherorte, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    bilder = speicherorte.ort(config, "images")
    _bild_ablegen(config, "foto9.png", _png(3000, 2000))
    verlaufsbau.bilder_vorbereiten(config, ["foto9.png"])
    kopien = speicherorte.bildkopien_verzeichnis(config)
    assert len(list(kopien.glob("foto9-*.jpg"))) == 1

    os.rename(bilder / "foto9.png", bilder / "Foto9.png")
    entfernt = model_image.aufraeumen(bilder, kopien)

    assert entfernt == 0, "the copy fell victim to the spelling"
    assert list(kopien.glob("foto9-*.jpg"))


def test_bei_gleichem_ordner_wird_nichts_geraeumt(client, config):
    """Pictures and copies in the SAME folder (a hand-written config value):
    cleaning would compare the cache to itself and unlink everything, at
    every start. The guard refuses."""
    from app import model_image, speicherorte, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    _bild_ablegen(config, "zwei9.png", _png(3000, 2000))
    verlaufsbau.bilder_vorbereiten(config, ["zwei9.png"])
    kopien = speicherorte.bildkopien_verzeichnis(config)
    assert list(kopien.glob("zwei9-*.jpg"))

    entfernt = model_image.aufraeumen(kopien, kopien)

    assert entfernt == 0
    assert list(kopien.glob("zwei9-*.jpg"))


def test_ein_fehlgeschlagenes_verkleinern_laesst_kein_werkzeug_nachlaufen(client, config, monkeypatch):
    """Partial failure, the second half of the demand on the copies: a shrink that
    FAILS writes no record — and the stretch must still not start a tool
    again on the event loop. The warm-up burns the
    failure off the loop; the send path then hands out the original."""
    import base64

    from app import model_image, speicherorte, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    daten = _png(4000, 2500)
    _bild_ablegen(config, "kaputt9.png", daten)

    monkeypatch.setattr(model_image, "_verkleinern", lambda quelle, ziel: False)
    verlaufsbau.bilder_vorbereiten(config, ["kaputt9.png"])
    kopien = speicherorte.bildkopien_verzeichnis(config)
    assert not list(kopien.glob("kaputt9-*")), "something lies on disk despite the failure"

    # The stretch's way: forbidden to measure — and it hands out the original.
    _messen_verboten(monkeypatch)
    url = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "kaputt9.png")
    assert base64.b64decode(url.split(",", 1)[1]) == daten


def test_ein_verschwundenes_bild_stuerzt_die_antwort_nicht(client, config, monkeypatch):
    """Gone between the lookup and the read — deleted, a volume dropped: no
    crash, no image (this used to raise into a 500 and the
    chat got no answer at all)."""
    from app import model_image, verlaufsbau

    _bild_ablegen(config, "weg9.png", _png(800, 600))
    echt = model_image.nachschlag

    def verschwunden(quelle, ziel_ordner):
        pfad = echt(quelle, ziel_ordner)
        return pfad.with_name("gibt-es-nicht-mehr.png")

    monkeypatch.setattr(model_image, "nachschlag", verschwunden)
    assert verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "weg9.png") is None


def test_die_namensliste_laesst_leere_assistentenzeilen_aus(client, config):
    """The warm-up's light pass answers what the history will really carry:
    an empty assistant row — where a drawing lands — is
    answered with a replacement sentence before its picture is ever asked
    for, so its name is not in the list."""
    repositories = client.app.state.repositories
    chat = repositories.chats.erstellen(user_id="standard", title="Bilder", endpoint_id="test")
    repositories.messages.speichern(
        chat_id=chat.id, role="user", content="Was ist das?", anhaenge=["frage.png"]
    )
    repositories.messages.speichern(
        chat_id=chat.id, role="assistant", content="", bild="gezeichnet.png"
    )
    repositories.messages.speichern(chat_id=chat.id, role="assistant", content="Antwort.")

    namen = repositories.messages.bildanhaenge(chat_id=chat.id)

    assert namen == ["frage.png"], namen


def test_ein_name_mit_klammern_bekommt_seine_kopie(client, config):
    """The silence probe for a name a shell tool would read as a pattern:
    ``[1]`` in a name is a wildcard to a PowerShell lookup, and the copy's
    size check used to fail silently on it. The library reads the name as
    a name; the copy is built and found again."""
    from app import model_image, speicherorte, verlaufsbau

    _bild_ablegen(config, "foto[1].png", _png(3000, 2000))
    verlaufsbau.bilder_vorbereiten(config, ["foto[1].png"])
    kopien = speicherorte.bildkopien_verzeichnis(config)
    gebaut = [p for p in kopien.iterdir() if p.name.startswith("foto[1]-") and p.suffix == ".jpg"]
    assert len(gebaut) == 1, sorted(p.name for p in kopien.iterdir())
    assert model_image.masse(gebaut[0]) == (1920, 1280)


# --- The warm-up's place in the answer route --------------------------------


@pytest.fixture
async def dienst(config):
    """A real app whose lifespan has run (the form of
    tests/test_hintergrundwecken.py)."""
    from app.main import app_erstellen

    app = app_erstellen(config)
    async with app.router.lifespan_context(app):
        yield app


async def test_das_erste_verkleinern_haelt_die_schleife_nicht_an(dienst, monkeypatch):
    """The FIRST look at a large picture starts a tool process of its own —
    and it runs off the event loop: while it works, the service
    goes on answering. Measured as the largest gap between two ticks of a
    clock task; before the fix the route called the shrink synchronously,
    and the loop stood for the whole tool run."""
    import time

    from app import model_image
    from app.api.v1 import generierung as generierungsmodul
    from app.api.v1.schemas import GenerierungAnfrage
    from app.providers import MockProvider
    from tests.test_hintergrundwecken import _antwort_abwarten, _mitschreiben

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    app = dienst
    _bild_ablegen(app.state.config, "gross.png", _png(4000, 2500))
    chat = app.state.repositories.chats.erstellen(
        user_id="standard", title="Bild", endpoint_id="test"
    )
    # The user turn is saved by the ROUTE itself (generierung.py, `saved_turn`)
    # — the picture goes along in the request.
    provider = MockProvider(haeppchen=["ok"])
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True
    # A model that can SEE: without it the history build replaces the
    # picture with its notice sentence, and nothing ever gets shrunk.
    zustand.faehigkeiten_erkannt = {**(zustand.faehigkeiten_erkannt or {}), "vision": True}
    gestartet = _mitschreiben(app)

    # The shrink is made artificially slow: the sleep stands for the work
    # the library really does on a large photo in the field.
    echt = model_image._verkleinern
    geschlafen: list[float] = []

    def langsam(quelle, ziel):
        time.sleep(0.6)
        geschlafen.append(1.0)
        return echt(quelle, ziel)

    monkeypatch.setattr(model_image, "_verkleinern", langsam)

    luecken: list[float] = []
    laeuft = True
    letzte = time.monotonic()

    async def uhr():
        nonlocal letzte
        while laeuft:
            await asyncio.sleep(0.01)
            jetzt = time.monotonic()
            luecken.append(jetzt - letzte)
            letzte = jetzt

    uhr_aufgabe = asyncio.create_task(uhr())
    try:
        await generierungsmodul.antwort_anstossen(
            app=app,
            daten=GenerierungAnfrage(
                chat_id=chat.id, content="Was ist auf dem Bild?", bilder=["gross.png"]
            ),
            repositories=app.state.repositories,
            discovery=app.state.discovery,
            generierungen=app.state.generierungen,
            user_id="standard",
            sprache="de",
        )
        await _antwort_abwarten(gestartet)
    finally:
        laeuft = False
        # The LAST gap up to here counts too: when the loop stands until
        # the end, the clock never got its last tick in — without this
        # line exactly the block this test is about would go unmeasured.
        luecken.append(time.monotonic() - letzte)
        await asyncio.gather(uhr_aufgabe, return_exceptions=True)

    assert gestartet, "no answer was started at all"
    assert provider.durchlaeufe >= 1, "the answer did not get as far as the model"
    # The measurement first: it IS the point of this test.
    assert luecken, "the clock did not run"
    groesste = max(luecken)
    assert groesste < 0.4, f"the loop stood for {groesste:.2f}s — the shrinking ran on it"
    # And the shrink really ran: without this proof the test would be green
    # because nothing happened at all.
    from app import speicherorte

    assert geschlafen, "the tool did not run at all"
    assert list(speicherorte.bildkopien_verzeichnis(app.state.config).glob("*.jpg")), (
        "no copy was built at all"
    )


async def test_ein_stopp_waehrend_des_verkleinerns_wird_gehoert(dienst, monkeypatch):
    """A stop pressed while the warm-up's tool runs is honoured right after
    it: no answer begins, no placeholder is written (the
    first version put its await in a stretch that had none, and a stop that
    landed in it was lost)."""
    import time

    from app import model_image
    from app.api.v1 import generierung as generierungsmodul
    from app.api.v1.schemas import GenerierungAnfrage
    from app.providers import MockProvider
    from tests.test_hintergrundwecken import _mitschreiben

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    app = dienst
    _bild_ablegen(app.state.config, "stopp9.png", _png(4000, 2500))
    chat = app.state.repositories.chats.erstellen(
        user_id="standard", title="Stopp", endpoint_id="test"
    )
    # The user turn is saved by the ROUTE itself (generierung.py, `saved_turn`)
    # — that is where its picture names come from for the warm-up.
    provider = MockProvider(haeppchen=["ok"])
    zustand = app.state.discovery.zustaende["test"]
    zustand.provider = provider
    zustand.erreichbar = True
    zustand.faehigkeiten_erkannt = {**(zustand.faehigkeiten_erkannt or {}), "vision": True}
    gestartet = _mitschreiben(app)

    gedrungen: list[bool] = []
    echt = model_image._verkleinern

    def langsam(quelle, ziel):
        gedrungen.append(True)
        time.sleep(0.5)
        return echt(quelle, ziel)

    monkeypatch.setattr(model_image, "_verkleinern", langsam)

    antwort = asyncio.ensure_future(
        generierungsmodul.antwort_anstossen(
            app=app,
            daten=GenerierungAnfrage(
                chat_id=chat.id, content="Was ist das?", bilder=["stopp9.png"]
            ),
            repositories=app.state.repositories,
            discovery=app.state.discovery,
            generierungen=app.state.generierungen,
            user_id="standard",
            sprache="de",
        )
    )
    try:
        for _ in range(2000):
            if gedrungen:
                break
            await asyncio.sleep(0.01)
        assert gedrungen, "the warming did not run at all"
        gestoppt = app.state.generierungen.alle_im_chat_abbrechen(chat.id)
        ergebnis = await asyncio.wait_for(antwort, timeout=30)
    finally:
        if not antwort.done():
            antwort.cancel()

    assert gestoppt >= 1, "the stop did not reach the claim"
    assert ergebnis is None, "the answer began despite the stop"
    assert not gestartet, "a run was started despite the stop"
    nachrichten = app.state.repositories.messages.auflisten(chat_id=chat.id)
    assert [n.role for n in nachrichten] == ["user"], "a placeholder was written"


def test_a_jpeg_under_a_png_name_is_announced_as_jpeg(client, config):
    """The media type comes from the bytes, not from the name: a JPEG lying
    under ``.png`` travels as ``image/jpeg``. Announced by the name, it went
    out as ``image/png``, and a provider that checks the announcement
    refuses the request."""
    from app import verlaufsbau

    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    _bild_ablegen(config, "wrong.png", jpeg)

    url = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "wrong.png")
    assert url is not None and url.startswith("data:image/jpeg;base64,"), (url or "")[:40]


def test_bytes_that_are_no_picture_get_no_jpeg_label(client, config):
    """A file named like a picture whose bytes are none is left out — never
    sent as ``image/jpeg``, which is what an unknown type silently became."""
    from app import verlaufsbau

    _bild_ablegen(config, "no-picture.webp", b"plain text, not a picture")

    assert verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "no-picture.webp") is None


def test_one_data_url_for_chat_and_read_file():
    """One place writes the data URL; it announces what the bytes are and
    refuses bytes of no known kind instead of assuming one."""
    import base64

    from app import model_image

    png = _png(4, 4)
    assert model_image.data_url(png) == "data:image/png;base64," + base64.b64encode(png).decode()
    with pytest.raises(ValueError):
        model_image.data_url(b"GIF89a")


def test_the_picture_places_are_read_once_per_warm_up_and_per_build(
    client, chat_id, config, monkeypatch,
):
    """Several pictures read the picture folder's location once — in the
    warm-up and in the history build alike, not once per picture."""
    from app import verlaufsbau

    names = ("a.png", "b.png", "c.png")
    for name in names:
        _bild_ablegen(config, name, _png(8, 8))
    reads = []
    real = verlaufsbau._picture_places

    def count(cfg):
        reads.append(1)
        return real(cfg)

    monkeypatch.setattr(verlaufsbau, "_picture_places", count)
    verlaufsbau.bilder_vorbereiten(config, list(names))
    assert len(reads) == 1

    repositories = client.app.state.repositories
    for name in names:
        repositories.messages.speichern(chat_id=chat_id, role="user", content="look", anhaenge=[name])
    chat = repositories.chats.holen(chat_id)
    reads.clear()
    history = _verlauf_bauen(chat, repositories, "SYS", config=config)
    assert len(reads) == 1
    assert sum(len(n.bild_urls or []) for n in history) == 3


def _last_user_message(client, chat_id, config, **row):
    """Store one user row and build the history for a model that sees; hand
    back the message that row became."""
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", **row)
    chat = repositories.chats.holen(chat_id)
    history = _verlauf_bauen(chat, repositories, "SYS", config=config)
    return [n for n in history if n.role != "system"][-1]


def test_a_missing_attachment_is_said_to_the_model(client, chat_id, config):
    """Fails without the fix: the message went out with no image and no word,
    and the model, asked about the picture, guessed."""
    message = _last_user_message(
        client, chat_id, config, content="What is this?", anhaenge=["gone.png"]
    )
    assert not message.bild_urls
    assert message.content.endswith("\n[An image was attached here that cannot be read.]")
    assert message.content.startswith("What is this?")


def test_an_attachment_with_no_picture_bytes_is_counted_among_the_unreadable(
    client, chat_id, config
):
    """Fails without the fix: two pictures travel, the third is dropped
    without a sentence."""
    _bild_ablegen(config, "one.png", _png(8, 8))
    _bild_ablegen(config, "two.png", _png(8, 8))
    _bild_ablegen(config, "text.png", b"plain text, not a picture")
    message = _last_user_message(
        client,
        chat_id,
        config,
        content="Look",
        anhaenge=["one.png", "text.png", "two.png"],
    )
    assert len(message.bild_urls) == 2
    assert message.content.endswith("\n[An image was attached here that cannot be read.]")


def test_several_unreadable_attachments_are_counted(client, chat_id, config):
    _bild_ablegen(config, "one.png", _png(8, 8))
    message = _last_user_message(
        client,
        chat_id,
        config,
        content="Look",
        anhaenge=["gone.png", "one.png", "also-gone.png"],
    )
    assert len(message.bild_urls) == 1
    assert message.content.endswith("\n[2 images were attached here that cannot be read.]")


def test_an_attachment_without_words_still_carries_the_sentence(client, chat_id, config):
    message = _last_user_message(client, chat_id, config, content="", anhaenge=["gone.png"])
    assert "[An image was attached here that cannot be read.]" in message.content
    assert not message.bild_urls


def test_schweigeprobe_readable_attachments_get_no_sentence(client, chat_id, config):
    """Every attachment can be read: images go along as before, no sentence."""
    _bild_ablegen(config, "one.png", _png(8, 8))
    _bild_ablegen(config, "two.png", _png(8, 8))
    message = _last_user_message(
        client, chat_id, config, content="Look", anhaenge=["one.png", "two.png"]
    )
    assert len(message.bild_urls) == 2
    assert "cannot be read" not in message.content


def test_schweigeprobe_a_message_without_attachment_is_unchanged(client, chat_id, config):
    message = _last_user_message(client, chat_id, config, content="Just words.")
    assert message.content == "Just words."
    assert not message.bild_urls


def test_schweigeprobe_a_model_that_cannot_see_gets_only_its_own_sentence(client, chat_id):
    """No second sentence for the same attachment."""
    message = _letzte_nachricht(
        client, chat_id, role="user", content="Look", anhaenge=["gone.png"]
    )
    assert "cannot see" in message.content
    assert "cannot be read" not in message.content


def test_a_picture_under_the_edge_but_over_the_bytes_is_too_large(tmp_path, monkeypatch):
    """The byte branch of the threshold on its own: a picture well under
    1920 pixels that is still over 3 MB gets a copy. Every other test uses
    small one-colour pictures, where only the edge decides."""
    from app import model_image

    monkeypatch.setattr(model_image, "masse", lambda datei: (1100, 1100))
    large = tmp_path / "noise.png"
    large.write_bytes(b"\x00" * (model_image.BYTES_MAX + 1))
    assert model_image._zu_gross(large) is True
    # Silence probe: exactly at the byte threshold and under the edge, nothing.
    exact = tmp_path / "exact.png"
    exact.write_bytes(b"\x00" * model_image.BYTES_MAX)
    assert model_image._zu_gross(exact) is False


def test_a_noisy_picture_under_the_edge_travels_as_a_smaller_copy(client, config):
    """The same branch on a real picture: 1100 by 1100 pixels of noise is
    over 3 MB, and what goes to the model is a JPEG copy under the
    threshold, still 1100 pixels on its longest side."""
    import base64
    import tempfile

    from app import model_image, verlaufsbau

    if not model_image.verfuegbar():
        pytest.skip("no tool to shrink pictures on this machine")

    noise = _png(1100, 1100, rauschen=True)
    assert len(noise) > model_image.BYTES_MAX
    _bild_ablegen(config, "noise.png", noise)

    verlaufsbau.bilder_vorbereiten(config, ["noise.png"])
    url = verlaufsbau._bild_daten_url(verlaufsbau._picture_places(config), "noise.png")
    assert url.startswith("data:image/jpeg;base64,"), url[:40]
    sent = base64.b64decode(url.split(",", 1)[1])
    assert len(sent) <= model_image.BYTES_MAX
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / "copy.jpg"
        copy.write_bytes(sent)
        assert model_image.masse(copy) == (1100, 1100)


# --- The place of an attached picture ---------------------------------------


def _user_row(client, chat_id, *, vision, **row):
    repositories = client.app.state.repositories
    repositories.messages.speichern(chat_id=chat_id, role="user", **row)
    chat = repositories.chats.holen(chat_id)
    history = _verlauf_bauen(
        chat, repositories, "SYS", config=client.app.state.config, vision=vision
    )
    return [n for n in history if n.role != "system"][-1]


@pytest.mark.parametrize("vision", [True, False])
def test_an_attached_picture_names_its_place(client, chat_id, vision):
    """The picture travels without a name; the model gets its place in the
    picture folder, so it can hand it to a job or a tool — whether it can
    see the picture or not."""
    from app.api.v1.bilder import bilder_verzeichnis

    _bild_ablegen(client.app.state.config, "shot.png", _png(4, 4))
    message = _user_row(
        client, chat_id, vision=vision, content="What is this?", anhaenge=["shot.png"]
    )

    place = (bilder_verzeichnis(client.app.state.config) / "shot.png").resolve()
    assert message.content.startswith("What is this?")
    assert f"stored in the image folder as {place}" in message.content


def test_a_row_without_a_picture_names_no_place(client, chat_id):
    """Silence probe: no attachment, no sentence."""
    message = _user_row(client, chat_id, vision=True, content="Just words.")

    assert message.content == "Just words."


def test_a_picture_that_is_gone_names_no_place(client, chat_id):
    """A sentence about a file that is not there would send the model at a
    refusal."""
    message = _user_row(
        client, chat_id, vision=False, content="And this?", anhaenge=["gone.png"]
    )

    assert "image folder" not in message.content


# --- The sentence for a document the request leaves out -------------------


def test_a_document_over_half_the_window_is_not_said_to_exceed_the_window(tmp_path):
    """A document that fits the model's window and is left out because it is
    over the half of it a request may give to documents is not "too large for
    this model's context": the head names the request, not the window."""
    from app import dokumentbudget, tokenmass
    from app.db import Database, repositories_erstellen
    from app.verlaufsbau import zeilentext

    db = Database(tmp_path / "d.db")
    db.schema_einrichten()
    repos = repositories_erstellen(db)
    chat = repos.chats.erstellen(user_id="u1", title="c")
    text = "wort " * 5_000
    dokument = repos.documents.speichern(
        chat_id=chat.id, filename="bericht.pdf", mime_type="application/pdf",
        size_bytes=len(text), extracted_text=text, pages=3, pfad=None,
    )
    repos.messages.speichern(
        chat_id=chat.id, role="user", content="Fasse zusammen.", dokumente=[dokument.id]
    )
    zeile = repos.messages.auflisten(chat_id=chat.id)[-1]
    window = 8_192
    # It fits the window and is over half of it.
    assert tokenmass.tokens(text) < window
    assert tokenmass.tokens(text) > window // 2
    plan = dokumentbudget.verteilen([dokument], dokumentbudget.budget_tokens(window, 1_000))
    assert plan[dokument.id].ganz is False

    kopf = zeilentext(zeile, repos, dokumentplan=plan)

    assert 'contains 25000 characters, is too large to be sent with this request' in kopf
    assert "context" not in kopf
    assert "wort wort" not in kopf


def test_silence_a_document_that_fits_goes_whole(tmp_path):
    from app import dokumentbudget
    from app.db import Database, repositories_erstellen
    from app.verlaufsbau import zeilentext

    db = Database(tmp_path / "d.db")
    db.schema_einrichten()
    repos = repositories_erstellen(db)
    chat = repos.chats.erstellen(user_id="u1", title="c")
    dokument = repos.documents.speichern(
        chat_id=chat.id, filename="notiz.md", mime_type="text/markdown",
        size_bytes=20, extracted_text="kurze Notiz", pages=1, pfad=None,
    )
    repos.messages.speichern(
        chat_id=chat.id, role="user", content="Und?", dokumente=[dokument.id]
    )
    zeile = repos.messages.auflisten(chat_id=chat.id)[-1]
    plan = dokumentbudget.verteilen([dokument], dokumentbudget.budget_tokens(8_192, 1_000))

    kopf = zeilentext(zeile, repos, dokumentplan=plan)

    assert '[Attached document "notiz.md"]\nkurze Notiz\n[End of document]' in kopf


# --- A generated video is told as a video ------------------------------------


def _run_row_words(client, chat_id, names):
    """The words a run row of several generated files goes out with: every
    file is stored into the one row of its run, then the history is built for
    a model that cannot see."""
    repositories = client.app.state.repositories
    for name in names:
        repositories.messages.lauf_bild_speichern(
            chat_id=chat_id, lauf_kennung="lauf-1", nr=None, von=0, bild=name, seed=None
        )
    chat = repositories.chats.holen(chat_id)
    history = _verlauf_bauen(chat, repositories, "SYS", vision=False)
    return [n for n in history if n.role != "system"][-1].content


def test_a_generated_video_row_says_video(client, chat_id):
    """A video rides in the same field as a picture; the sentence for a row
    that says nothing in words names what it was, and what the gallery plays
    is a video."""
    message = _letzte_nachricht(
        client, chat_id, role="assistant", content="", bild="clip.webm"
    )

    assert message.content == "[A generated video was shown here.]"


def test_two_generated_videos_say_the_number(client, chat_id):
    words = _run_row_words(client, chat_id, ["eins.webm", "two.avi"])

    assert words == "[2 generated videos were shown here.]"


def test_a_video_suffix_in_capitals_is_a_video(client, chat_id):
    message = _letzte_nachricht(
        client, chat_id, role="assistant", content="", bild="CLIP.WEBM"
    )

    assert message.content == "[A generated video was shown here.]"


def test_a_row_of_pictures_and_a_video_names_both(client, chat_id):
    words = _run_row_words(client, chat_id, ["bild.png", "clip.webm"])

    assert words == "[2 generated images and videos were shown here.]"


def test_silence_a_picture_row_keeps_its_sentence(client, chat_id):
    """A picture stays an image, one or several; an animated WebP is a
    picture to the gallery and stays one here."""
    one = _letzte_nachricht(
        client, chat_id, role="assistant", content="", bild="bild.png"
    )
    assert one.content == "[A generated image was shown here.]"

    two = _run_row_words(client, chat_id, ["eins.png", "two.webp"])
    assert two == "[2 generated images were shown here.]"
