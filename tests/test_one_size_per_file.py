"""A file has one size: the card in the chat and the tab beside it name the
same number in the same unit — bytes up to 1 KB, whole KB up to 1 MB, MB with
one decimal after that."""

from __future__ import annotations

import json

import pytest

from tests.test_dokumentkarte import _catalogue, needs_node
from tests.test_document_view import _module_functions, _upload
from tests.test_hintergrundmeldung import _node


def _facts(card: dict) -> str:
    """The line the card builds, over the real catalogue and the real
    function of the delivered file."""
    script = (
        _catalogue()
        + "const t = (key, values = {}) => `${key}:${values.zahl ?? ''}`;\n"
        + _module_functions("pageCount", "fileFacts")
        + f"console.log(JSON.stringify(fileFacts({json.dumps(card)})))"
    )
    return json.loads(_node(script))


def _tab_facts(size: int) -> str:
    """The line of the tab for a text of exactly that many bytes."""
    script = (
        _catalogue()
        + f"console.log(JSON.stringify(dateiFakten({{art: 'html', inhalt: 'x'.repeat({size})}})))"
    )
    return json.loads(_node(script))


@needs_node
@pytest.mark.parametrize(
    ("size", "shown"),
    [(0, "0 B"), (296, "296 B"), (1023, "1023 B"), (12288, "12 KB"), (1572864, "1.5 MB")],
)
def test_card_and_tab_name_the_same_size(size, shown):
    assert _facts({"typ": "html", "size_bytes": size}) == f"HTML · {shown}"
    assert _tab_facts(size) == f"HTML · {shown}"


@needs_node
def test_a_card_without_a_number_shows_no_size():
    assert _facts({"typ": "html", "size_bytes": None}) == "HTML"
    assert _facts({"typ": "pdf", "size_bytes": 2048, "seiten": 2}) == "PDF · 2 KB · nachricht.dokument_seiten:2"


def test_the_card_of_an_upload_carries_the_bytes_unrounded(client):
    card = _upload(client, "small.html", b"<p>" + b"x" * 293)
    assert card["size_bytes"] == 296
    assert "kb" not in card


def test_a_row_without_a_size_gives_no_number():
    from app.api.v1.dokumente import meta_bauen
    from app.db.models import Document

    row = Document(
        id="d1", chat_id="c1", filename="old.txt", created_at="2024-01-01T00:00:00",
        size_bytes=None, pages=None,
    )
    assert meta_bauen(row).size_bytes is None
