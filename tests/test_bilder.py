"""Vision input: upload, delivery, lockdown."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.providers import ChatNachricht
from app.providers.openai_kompatibel import OpenAIKompatiblerProvider

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"testbild"


def test_bild_rundreise(client):
    antwort = client.post(
        "/api/v1/images", content=PNG_BYTES, headers={"Content-Type": "image/png"}
    )
    assert antwort.status_code == 201
    name = antwort.json()["bild"]
    assert name.endswith(".png")

    geholt = client.get(f"/api/v1/images/{name}")
    assert geholt.status_code == 200
    assert geholt.content == PNG_BYTES
    assert geholt.headers["content-type"].startswith("image/png")


def test_falscher_typ_wird_abgewiesen(client):
    antwort = client.post(
        "/api/v1/images", content=b"GIF89a", headers={"Content-Type": "image/gif"}
    )
    assert antwort.status_code == 415


def test_fremde_namen_erreichen_das_dateisystem_nicht(client):
    assert client.get("/api/v1/images/../../config.yaml").status_code in (404, 422)
    assert client.get("/api/v1/images/boese.png").status_code == 404


def test_bild_ohne_vision_gibt_400(client):
    chat = client.post("/api/v1/chats", json={"title": "Vision"}).json()
    hochgeladen = client.post(
        "/api/v1/images", content=PNG_BYTES, headers={"Content-Type": "image/png"}
    ).json()["bild"]
    antwort = client.post(
        "/api/v1/chat/completions",
        json={
            "chat_id": chat["id"],
            "endpoint_id": "test",
            "content": "Was ist auf dem Bild?",
            "bild": hochgeladen,
        },
    )
    # The test endpoint has no vision — the API is the outer boundary.
    assert antwort.status_code == 400


def test_provider_baut_das_bildformat():
    nachricht = ChatNachricht(
        role="user", content="Was ist das?", bild_url="data:image/png;base64,QUJD"
    )
    eintrag = OpenAIKompatiblerProvider._nachricht_bauen(nachricht)
    assert eintrag["content"] == [
        {"type": "text", "text": "Was ist das?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ]

    ohne_text = ChatNachricht(role="user", content="", bild_url="data:image/png;base64,QUJD")
    eintrag = OpenAIKompatiblerProvider._nachricht_bauen(ohne_text)
    assert eintrag["content"] == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}
    ]


def _png(breite: int, hoehe: int, *, zufall: bool = False) -> bytes:
    """A PNG of the given size, written by hand: 8-bit RGB, one filter byte
    per row, zlib over the rows. Random rows are incompressible, which is how
    a picture of a few hundred kilobytes becomes one of eleven megabytes."""
    import os
    import struct
    import zlib

    zeilen = bytearray()
    for _ in range(hoehe):
        zeilen.append(0)
        zeilen += os.urandom(breite * 3) if zufall else bytes([40, 90, 160]) * breite

    def stueck(art: bytes, daten: bytes) -> bytes:
        return (
            struct.pack(">I", len(daten)) + art + daten
            + struct.pack(">I", zlib.crc32(art + daten))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + stueck(b"IHDR", struct.pack(">IIBBBBB", breite, hoehe, 8, 2, 0, 0, 0))
        + stueck(b"IDAT", zlib.compress(bytes(zeilen), 6))
        + stueck(b"IEND", b"")
    )


def test_ein_bild_ueber_zehn_megabyte_wird_angenommen(client):
    """The ceiling is gone: the upload keeps the file exactly as it came.
    What the MODEL gets is worked out when the request is built
    (app/model_image.py), not here."""
    daten = _png(2100, 2100, zufall=True)
    assert len(daten) > 11 * 1024 * 1024, len(daten)

    antwort = client.post(
        "/api/v1/images", content=daten, headers={"Content-Type": "image/png"}
    )
    assert antwort.status_code == 201, antwort.text
    name = antwort.json()["bild"]

    geholt = client.get(f"/api/v1/images/{name}")
    assert geholt.content == daten, "the stored file is not the uploaded one"


def test_bild_info_weist_ein_grosses_bild_nicht_mehr_ab(client):
    """The same ceiling in ``/bild/info``: reading what a picture says about
    how it was made does not depend on how big it is. Whether the program is
    there is a different question — it may answer 503 here — but never 413
    for the size.

    Named outright, not only "not 413": every other failure — 500 for a crash
    while reading the bytes, 404 for a route that moved away, 422 — would
    read as "accepted" and the test would carry nothing."""
    daten = _png(2100, 2100, zufall=True)
    assert len(daten) > 11 * 1024 * 1024, len(daten)

    antwort = client.post(
        "/api/v1/bild/info", content=daten, headers={"Content-Type": "image/png"}
    )
    assert antwort.status_code in (200, 503), antwort.text


def _bild_hochladen(client, extra: bytes = b"") -> str:
    return client.post(
        "/api/v1/images", content=PNG_BYTES + extra, headers={"Content-Type": "image/png"}
    ).json()["bild"]


def test_bilder_eines_chats_und_eines_projekts(client):
    """The studio's picture rail: with a chat only that chat's pictures, with
    a project those of every chat in it, never a stranger's; newest first."""
    projekt = client.post("/api/v1/projects", json={"name": "P"}).json()["id"]
    chat_a = client.post("/api/v1/chats", json={"title": "A"}).json()["id"]
    chat_b = client.post("/api/v1/chats", json={"title": "B"}).json()["id"]
    fremd = client.post("/api/v1/chats", json={"title": "C"}).json()["id"]
    for chat in (chat_a, chat_b):
        assert client.patch(f"/api/v1/chats/{chat}", json={"project_id": projekt}).status_code == 200
    # Four pictures of their own: the same bytes would be one file.
    a1, a2, b1, c1 = (_bild_hochladen(client, bytes([i])) for i in range(4))
    nachrichten = client.app.state.repositories.messages
    nachrichten.speichern(chat_id=chat_a, role="user", content="x", bild=a1)
    nachrichten.speichern(chat_id=chat_a, role="assistant", content="", art="bild", bild=a2)
    nachrichten.speichern(chat_id=chat_b, role="assistant", content="", art="bild", bild=b1)
    nachrichten.speichern(chat_id=fremd, role="assistant", content="", art="bild", bild=c1)

    assert client.get(f"/api/v1/bilder?chat={chat_a}").json()["bilder"] == [a2, a1]
    assert client.get(f"/api/v1/bilder?projekt={projekt}").json()["bilder"] == [b1, a2, a1]
    # The silence probe: without either, the whole folder as before.
    alle = client.get("/api/v1/bilder").json()["bilder"]
    assert {a1, a2, b1, c1} <= set(alle)


# --- The picture studio's working pictures -------------------------------

ROOT = Path(__file__).resolve().parent.parent


def _folders(config):
    from app.api.v1.bilder import bilder_verzeichnis
    from app.speicherorte import scratch_pictures_dir

    return bilder_verzeichnis(config), scratch_pictures_dir(config)


def _upload(client, *, scratch: bool = False, extra: bytes = b"") -> str:
    answer = client.post(
        "/api/v1/images" + ("?scratch=true" if scratch else ""),
        content=PNG_BYTES + extra, headers={"Content-Type": "image/png"},
    )
    assert answer.status_code == 201
    return answer.json()["bild"]


def test_a_working_picture_lies_outside_the_picture_folder(client):
    """A frame of a control video, or what the drawing surface put together,
    goes up as a working picture: it lies in its own folder, not in the
    picture folder, is on no wall — and the draw still finds it by name."""
    from app.api.v1.bild import _startbild

    config = client.app.state.config
    pictures, scratch = _folders(config)
    frame = _upload(client, scratch=True)

    assert (scratch / frame).read_bytes() == PNG_BYTES
    assert not (pictures / frame).exists()
    assert frame not in client.get("/api/v1/bilder").json()["bilder"]
    assert _startbild(config, frame, "en") == scratch / frame

    # Silence probe: an ordinary picture lies in the picture folder as
    # before, on the wall, and is read from there. Other bytes, so that it
    # is not the file of the frame: the same bytes are one name.
    ordinary = _upload(client, extra=b"-ordinary")
    assert (pictures / ordinary).is_file()
    assert not (scratch / ordinary).exists()
    assert ordinary in client.get("/api/v1/bilder").json()["bilder"]
    assert _startbild(config, ordinary, "en") == pictures / ordinary


def test_the_start_of_the_service_empties_the_working_pictures(config, request):
    """What lay among the working pictures before the service started is
    gone once it is up; a picture of the picture folder stays."""
    pictures, scratch = _folders(config)
    for folder in (pictures, scratch):
        folder.mkdir(parents=True)
    (scratch / "frame.png").write_bytes(PNG_BYTES)
    (pictures / "kept.png").write_bytes(PNG_BYTES)

    request.getfixturevalue("client")

    assert not (scratch / "frame.png").exists()
    assert (pictures / "kept.png").is_file()


def test_beside_a_second_service_the_working_pictures_stay(client):
    """A second service still alive on the same data folder may have a draw
    reading them: this start leaves them alone."""
    from app.main import _startbereinigung

    config = client.app.state.config
    _pictures, scratch = _folders(config)
    frame = _upload(client, scratch=True)

    _startbereinigung(client.app, config, nur_eigene=True)
    assert (scratch / frame).is_file()
    _startbereinigung(client.app, config)
    assert not (scratch / frame).exists()


def test_the_picture_folder_cannot_be_laid_into_the_working_pictures(config):
    """The folder is emptied at every start: a location pointing at it, or
    into it, would lose its files."""
    from app import speicherorte

    scratch = speicherorte.scratch_pictures_dir(config)
    for target in (scratch, scratch / "inside"):
        with pytest.raises(speicherorte.SpeicherortFehler):
            speicherorte._pruefen(config, "images", target)


def test_the_studio_sends_its_working_pictures_as_such():
    """Source text: the frames of a video and what the drawing surface puts
    together go up as working pictures; a starting image the surface hands
    on as it is keeps its name and its place in the picture folder."""
    draw = (ROOT / "frontend/src/lib/studiozeichnen.svelte.js").read_text("utf-8")
    canvas = (ROOT / "frontend/src/teile/StudioCanvas.svelte").read_text("utf-8")
    api = (ROOT / "frontend/src/lib/api.js").read_text("utf-8")

    assert "ruf(`/images${scratch ? '?scratch=true' : ''}`" in api
    assert "api.bildHochladen(frame, true)" in draw
    assert "api.bildHochladen(frame)" not in draw
    assert "{ type: 'image/png' }), true)).bild" in canvas
    # Kept while file, rate and count stay the same.
    assert "last.file === file && last.rate === rate && last.count === count" in draw
    # Silence probe: the surface uploads nothing for a picture it hands on
    # as it is, and a picture dropped into the studio is an ordinary one.
    assert "const cut = wieEs ? null : aufDenBereich(bildKnoten, place)" in canvas
    assert "const startbild = cut ? await hochladen(cut, 'startbild.png') : name" in canvas
    assert "await api.bildHochladen(datei)" in canvas


# --- The same bytes are one file ------------------------------------------


def _png_with_text(text: bytes) -> bytes:
    """A real, parseable PNG with a text chunk the metadata switch strips."""
    import struct
    import zlib

    from tests.test_bildschutz import _block

    ihdr = _block(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = _block(b"IDAT", zlib.compress(b"\x00\x11\x22\x33"))
    return b"\x89PNG\r\n\x1a\n" + ihdr + _block(b"tEXt", b"parameters\x00" + text) + idat + _block(
        b"IEND", b""
    )


def _files(folder: Path) -> int:
    return len(list(folder.iterdir())) if folder.exists() else 0


def test_the_same_bytes_twice_are_one_file(client):
    """A message the service refused goes up again with the same pictures:
    the second upload names the first file and writes nothing."""
    from app.bildfensterwahl import BILDNAME

    pictures, _ = _folders(client.app.state.config)
    before = _files(pictures)

    first, second = _upload(client), _upload(client)

    assert first == second
    assert BILDNAME.fullmatch(first)
    assert _files(pictures) == before + 1
    assert (pictures / first).read_bytes() == PNG_BYTES


def test_other_bytes_are_another_file_and_every_name_has_the_shape(client):
    from app.bildfensterwahl import BILDNAME

    jpeg = client.post(
        "/api/v1/images", content=b"\xff\xd8\xff" + b"jpeg", headers={"Content-Type": "image/jpeg"}
    ).json()["bild"]
    first, second = _upload(client), _upload(client, extra=b"-other")

    assert len({first, second, jpeg}) == 3
    assert all(BILDNAME.fullmatch(name) for name in (first, second, jpeg))
    assert jpeg.endswith(".jpg")


def test_two_photos_that_differ_only_in_metadata_are_one_file_once_it_is_stripped(client):
    """The name comes from the bytes as they are stored: with the switch on,
    the text chunk is gone before the name is made."""
    from app.bildschutz import SCHLUESSEL

    settings = client.app.state.repositories.einstellungen
    one, other = _png_with_text(b"first-prompt"), _png_with_text(b"another-prompt!!")
    assert one != other

    def up(content: bytes) -> str:
        answer = client.post("/api/v1/images", content=content, headers={"Content-Type": "image/png"})
        assert answer.status_code == 201
        return answer.json()["bild"]

    settings.setzen("global", SCHLUESSEL, {"an": True})
    assert up(one) == up(other)
    # Silence probe: with the switch off the pictures are stored as they
    # came, so two different files stay two.
    settings.setzen("global", SCHLUESSEL, {"an": False})
    assert up(one) != up(other)


def test_a_picture_two_chats_name_stays_when_one_of_them_goes(client):
    """Two sends of the same picture are one file, named by a row of each
    chat: the delete of one chat leaves it to the other."""
    pictures, _ = _folders(client.app.state.config)
    name = _upload(client)
    assert _upload(client) == name
    chat_a = client.post("/api/v1/chats", json={"title": "A"}).json()["id"]
    chat_b = client.post("/api/v1/chats", json={"title": "B"}).json()["id"]
    messages = client.app.state.repositories.messages
    messages.speichern(chat_id=chat_a, role="user", content="x", bild=name)
    messages.speichern(chat_id=chat_b, role="user", content="x", bild=name)

    assert client.delete(f"/api/v1/chats/{chat_a}").status_code == 204
    assert (pictures / name).is_file()
    # Silence probe: the last chat that names it takes it along.
    assert client.delete(f"/api/v1/chats/{chat_b}").status_code == 204
    assert not (pictures / name).exists()


def test_a_cut_off_file_of_the_same_name_is_written_again(client):
    pictures, _ = _folders(client.app.state.config)
    name = _upload(client)
    (pictures / name).write_bytes(PNG_BYTES[:5])

    assert _upload(client) == name
    assert (pictures / name).read_bytes() == PNG_BYTES
