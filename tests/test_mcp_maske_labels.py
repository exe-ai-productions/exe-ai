"""The two fields of a hand-made client id in the MCP mask carry their name
as a label above the field and no placeholder inside it — the way their
neighbours do."""

from __future__ import annotations

import re
from pathlib import Path

MASK = (
    Path(__file__).resolve().parent.parent / "frontend" / "src" / "teile" / "MCPMaske.svelte"
).read_text(encoding="utf-8")


def _block(bind: str) -> str:
    """The label element that holds the field bound to ``bind``."""
    found = re.search(r"<label class=\"feldblock\">(?:(?!</label>).)*?bind:value=\{" + bind, MASK, re.S)
    assert found, bind
    return MASK[found.start(): MASK.index("</label>", found.start())]


def test_client_id_and_secret_have_their_name_as_label_above_the_field():
    for bind, key in (("kennung", "verbindungen.kennung"), ("geheimnis", "verbindungen.geheimnis")):
        block = _block(bind)
        assert f"{{t('{key}')}}" in block
        assert block.index("class=\"label\"") < block.index("<input")


def test_no_field_of_the_mask_puts_its_name_in_a_placeholder():
    placeholders = re.findall(r"placeholder=\{t\([^)]*\)\}", MASK)
    assert placeholders == []


def test_the_sign_in_button_still_waits_for_a_client_id():
    assert "disabled={arbeitet || (verlangt === 'oauth_kennung' && !kennung)}" in MASK


def test_the_client_secret_shows_as_dots_and_is_not_filled_by_the_browser():
    block = _block("geheimnis")
    field = block[block.index("<input"):]
    assert 'type="password"' in field
    assert 'autocomplete="off"' in field


def test_the_client_id_and_the_api_key_field_stay_as_they_are():
    """Silence probe: only the secret is hidden — the id stays readable, the
    API key field keeps its type and its way of not being filled."""
    id_block = _block("kennung")
    assert "type=" not in id_block[id_block.index("<input"):]
    key_block = _block("apiKey")
    key_field = key_block[key_block.index("<input"):]
    assert 'type="password"' in key_field
    assert 'autocomplete="off"' in key_field
