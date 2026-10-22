"""The picture wall shows the picture folder, and the scripts folder is
listed at all.

The pictures were filtered by a name pattern the server mints itself
(``^[a-f0-9]{32}\\.(png|jpg|webp)$``), so a picture a run wrote as
``diagramm.png`` sat in the user's own folder and never appeared. The
scripts had no listing of any kind: a schedule asked for the file name as
free text, and a typo became a schedule that fails at its first firing.

The pattern was doing two jobs at once, and only one was ever needed —
keeping path tricks out. That one is tested here too, because relaxing the
listing must not relax the door.
"""

from __future__ import annotations

import os

import pytest

from app.speicherorte import ort


def _bilderordner(config):
    ordner = ort(config, "images")
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def test_ein_bild_mit_sprechendem_namen_steht_auf_der_wand(client, config):
    ordner = _bilderordner(config)
    (ordner / "diagramm.png").write_bytes(b"x" * 300)

    antwort = client.get("/api/v1/bilder")
    assert antwort.status_code == 200
    assert "diagramm.png" in antwort.json()["bilder"]


def test_auch_endungen_die_es_vorher_nicht_gab(client, config):
    """`.jpeg` was invisible because the old name pattern only knew `.jpg`,
    and the folder is full of files nobody renamed for it."""
    ordner = _bilderordner(config)
    for name in ("foto.jpeg", "modern.webp"):
        (ordner / name).write_bytes(b"x" * 300)

    gezeigt = set(client.get("/api/v1/bilder").json()["bilder"])
    assert {"foto.jpeg", "modern.webp"} <= gezeigt


def test_die_wand_zeigt_nur_was_der_chat_auch_nimmt(client, config):
    """A tile the window offers and then refuses when it is dragged into the
    chat is worse than one that is not there. GIF is in the folder's world
    and in none of the three lists a picture has to pass — what may be
    uploaded, what the chat accepts, what a message carries to a model."""
    (_bilderordner(config) / "bewegt.gif").write_bytes(b"x" * 300)
    assert "bewegt.gif" not in set(client.get("/api/v1/bilder").json()["bilder"])


def test_was_kein_bild_ist_bleibt_von_der_wand_weg(client, config):
    ordner = _bilderordner(config)
    (ordner / "notiz.txt").write_bytes(b"x" * 300)
    # Markup, not pixels: served from this origin it could carry a script.
    (ordner / "zeichnung.svg").write_bytes(b"<svg/>" + b"x" * 300)
    (ordner / "leer.png").write_bytes(b"")

    gezeigt = set(client.get("/api/v1/bilder").json()["bilder"])
    assert "notiz.txt" not in gezeigt
    assert "zeichnung.svg" not in gezeigt
    assert "leer.png" not in gezeigt


def test_ein_bild_mit_sprechendem_namen_wird_auch_ausgeliefert(client, config):
    """Visible on the wall and unfetchable would be the same fault wearing
    the other face."""
    (_bilderordner(config) / "diagramm.png").write_bytes(b"x" * 300)
    assert client.get("/api/v1/images/diagramm.png").status_code == 200


def test_die_tuer_bleibt_zu(client, config):
    _bilderordner(config)
    for versuch in ("..%2F..%2Fetc%2Fpasswd", "%2Fetc%2Fpasswd", "gibtsnicht.png"):
        assert client.get(f"/api/v1/images/{versuch}").status_code == 404


def test_eine_verknuepfung_aus_dem_bilderordner_heraus_wird_abgelehnt(client, config, tmp_path):
    """What the old name pattern could never have caught: the name is
    blameless and the file is somewhere else entirely."""
    draussen = tmp_path / "geheim.png"
    draussen.write_bytes(b"x" * 300)
    (_bilderordner(config) / "harmlos.png").symlink_to(draussen)
    assert client.get("/api/v1/images/harmlos.png").status_code == 404
    # And not on the wall either: a tile the door refuses is a picture box
    # that stays broken for good.
    assert "harmlos.png" not in set(client.get("/api/v1/bilder").json()["bilder"])


# --- The scripts -----------------------------------------------------------


@pytest.mark.platforms("posix", reason="the execute bit decides")
def test_der_skriptordner_wird_aufgelistet(client, config):
    ordner = ort(config, "scripts")
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "aufraeumen.sh").write_text("#!/bin/bash\n")
    os.chmod(ordner / "aufraeumen.sh", 0o755)
    (ordner / "nicht-startbar.sh").write_text("#!/bin/bash\n")

    antwort = client.get("/api/v1/skripte")
    assert antwort.status_code == 200
    nach_name = {e["name"]: e for e in antwort.json()}
    assert set(nach_name) == {"aufraeumen.sh", "nicht-startbar.sh"}
    # Listed rather than hidden, and saying why it would be refused at
    # firing time (`geprueft`, app/skriptlauf.py).
    assert nach_name["aufraeumen.sh"]["startbar"] is True
    assert nach_name["nicht-startbar.sh"]["startbar"] is False


def test_on_windows_the_listing_says_startable_by_extension(client, config, monkeypatch):
    """The listing asks the same function as the start (app/skriptlauf.py
    `startbar`): on Windows the extension decides, the execute bit does not
    exist there — so a .bat is startable and a .sh with the bit set is not."""
    import functools

    from app import skriptlauf

    monkeypatch.setattr(skriptlauf, "startable", functools.partial(skriptlauf.startable, platform="win32"))
    ordner = ort(config, "scripts")
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "nacht.bat").write_text("echo hi\n")
    (ordner / "nacht.sh").write_text("#!/bin/bash\n")
    os.chmod(ordner / "nacht.sh", 0o755)

    nach_name = {e["name"]: e for e in client.get("/api/v1/skripte").json()}
    assert nach_name["nacht.bat"]["startbar"] is True
    assert nach_name["nacht.sh"]["startbar"] is False


def test_ein_leerer_skriptordner_ist_kein_fehler(client):
    antwort = client.get("/api/v1/skripte")
    assert antwort.status_code == 200
    assert antwort.json() == []


# --- One script's text, for its tile ---------------------------------------


def test_a_script_is_answered_as_plain_text_shown_in_place(client, config):
    ordner = ort(config, "scripts")
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "alt.rb").write_bytes(b"puts 'hello'\n")

    antwort = client.get("/api/v1/skripte/text", params={"name": "alt.rb"})
    assert antwort.status_code == 200
    assert antwort.text == "puts 'hello'\n"
    assert antwort.headers["content-type"].startswith("text/plain")
    # No file name, so no download: the text is shown where it is asked for.
    assert "content-disposition" not in antwort.headers


@pytest.mark.parametrize("name", ["../secret.txt", "/etc/passwd", "a/b.sh", "..", " "])
def test_a_name_that_spells_out_a_path_or_nothing_is_refused(client, name):
    assert client.get("/api/v1/skripte/text", params={"name": name}).status_code == 400


def test_a_script_that_is_not_there_is_not_found(client):
    assert client.get("/api/v1/skripte/text", params={"name": "weg.sh"}).status_code == 404


def test_a_link_that_leads_out_of_the_folder_is_not_served(client, config, tmp_path):
    ordner = ort(config, "scripts")
    ordner.mkdir(parents=True, exist_ok=True)
    geheim = tmp_path / "outside.txt"
    geheim.write_text("not for the wall\n", encoding="utf-8")
    (ordner / "notes.txt").symlink_to(geheim)

    antwort = client.get("/api/v1/skripte/text", params={"name": "notes.txt"})
    assert antwort.status_code == 404
    assert "not for the wall" not in antwort.text
