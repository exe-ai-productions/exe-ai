"""The page of messages names the size of the pictures a message carries, so
the window holds their room before they load."""

from __future__ import annotations

import io

from PIL import Image


def _upload(client, width: int, height: int) -> str:
    data = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(data, "PNG")
    reply = client.post("/api/v1/images", content=data.getvalue(), headers={"Content-Type": "image/png"})
    assert reply.status_code == 201
    return reply.json()["bild"]


def _stored_with_orientation(config, name: str, width: int, height: int, orientation: int) -> str:
    """A picture a camera wrote, put into the picture folder as it came (an
    upload strips the metadata by default, and with it the orientation)."""
    from app.api.v1.bilder import bilder_verzeichnis

    exif = Image.Exif()
    exif[0x0112] = orientation
    folder = bilder_verzeichnis(config)
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), (30, 30, 200)).save(folder / name, "JPEG", exif=exif)
    return name


def _page(client, chat_id: str, names: list[str]) -> dict:
    client.app.state.repositories.messages.speichern(
        chat_id=chat_id, role="user", content="look", anhaenge=names
    )
    rows = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    return rows[-1]


def test_a_message_names_the_size_of_each_attached_picture(client, chat_id):
    wide = _upload(client, 12, 5)
    tall = _upload(client, 4, 9)
    row = _page(client, chat_id, [wide, tall])
    assert row["attachment_sizes"] == {
        wide: {"width": 12, "height": 5},
        tall: {"width": 4, "height": 9},
    }


def test_a_picture_a_camera_turned_is_sized_the_way_it_is_shown(client, chat_id, config):
    turned = _stored_with_orientation(config, "turned.jpg", 8, 3, 6)
    upright = _stored_with_orientation(config, "upright.jpg", 8, 3, 1)
    row = _page(client, chat_id, [turned, upright])
    assert row["attachment_sizes"][turned] == {"width": 3, "height": 8}
    assert row["attachment_sizes"][upright] == {"width": 8, "height": 3}


def test_an_attachment_the_library_does_not_read_has_no_entry_and_the_page_still_loads(client, chat_id):
    known = _upload(client, 6, 6)
    row = _page(client, chat_id, [known, "gone.png", "../../config.yaml"])
    assert row["attachment_sizes"] == {known: {"width": 6, "height": 6}}
    assert row["anhaenge"] == [known, "gone.png", "../../config.yaml"]


def test_a_message_without_pictures_carries_no_sizes(client, chat_id):
    client.app.state.repositories.messages.speichern(chat_id=chat_id, role="user", content="plain")
    rows = client.get(f"/api/v1/chats/{chat_id}/messages").json()["nachrichten"]
    assert rows[-1]["attachment_sizes"] is None
