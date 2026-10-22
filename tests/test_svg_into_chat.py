"""An SVG file dragged into the chat field is a document: read as text,
carried by a card, opened like any file — and still no picture."""

from __future__ import annotations

import re

from tests.fensterquelle import BAR_SOURCE

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">'
    '<rect width="8" height="8" fill="#ff0000"/></svg>'
)


def _chat(client):
    return client.post("/api/v1/chats", json={"title": "Svg"}).json()


def _window_endings() -> set[str]:
    source = BAR_SOURCE.read_text(encoding="utf-8")
    source = re.sub(r"//[^\n]*", "", source)
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    found = re.search(r"DOKUMENT_ENDUNGEN\s*=\s*\[(.*?)\]", source, re.S)
    assert found, "DOKUMENT_ENDUNGEN not found"
    return set(re.findall(r"['\"]([^'\"]+)['\"]", found.group(1)))


def test_svg_is_a_document_ending_in_window_and_service():
    from app.api.v1.dokumente import ERLAUBTE_ENDUNGEN

    assert ".svg" in _window_endings()
    assert ERLAUBTE_ENDUNGEN[".svg"] == "text/plain"


def test_the_file_field_offers_svg():
    """The picker's `accept` is built from the same list, so an ending in
    the list is an ending the field offers."""
    source = BAR_SOURCE.read_text(encoding="utf-8")
    assert "...(zustand.features.document_upload ? DOKUMENT_ENDUNGEN : [])" in source


def test_an_svg_upload_is_stored_as_text_and_comes_back_as_text(client):
    chat = _chat(client)
    answer = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=logo.svg", content=SVG.encode()
    )
    assert answer.status_code == 201
    meta = answer.json()["dokument"]
    assert meta["typ"] == "svg"
    stored = client.app.state.repositories.documents.holen(meta["id"])
    assert stored.mime_type == "text/plain"
    assert stored.extracted_text == SVG


def test_the_file_route_never_serves_an_svg_inline(client):
    chat = _chat(client)
    meta = client.post(
        f"/api/v1/documents?chat_id={chat['id']}&name=logo.svg", content=SVG.encode()
    ).json()["dokument"]
    served = client.get(f"/api/v1/documents/{meta['id']}/file")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("text/plain")
    assert served.headers["content-disposition"].startswith("attachment")


def test_the_picture_wall_still_refuses_an_svg(client):
    answer = client.post(
        "/api/v1/images", content=SVG.encode(), headers={"Content-Type": "image/svg+xml"}
    )
    assert answer.status_code == 415


def test_a_png_still_goes_the_picture_way(client):
    answer = client.post(
        "/api/v1/images",
        content=b"\x89PNG\r\n\x1a\n" + b"testbild",
        headers={"Content-Type": "image/png"},
    )
    assert answer.status_code == 201


def test_sound_and_video_files_are_still_refused_as_documents(client):
    chat = _chat(client)
    for name in ("song.mp3", "film.mp4"):
        answer = client.post(
            f"/api/v1/documents?chat_id={chat['id']}&name={name}", content=b"data"
        )
        assert answer.status_code == 415, name
