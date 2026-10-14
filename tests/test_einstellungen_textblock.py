"""Settings › Credentials and › Tools file: the text stands in a block.

Both pages used to show their text in a field that filled the whole page.
They now take the form of an agent's instruction: 320 px high, the text
scrolls inside it, the corner drags it taller. The configuration, the system
prompt and the memory keep the full-height field. Read off the source, the
way the other interface tests do.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "frontend/src/teile"
PAGE = (SRC / "SystemPrompt.svelte").read_text(encoding="utf-8")
FIELD = (SRC / "WachsendesFeld.svelte").read_text(encoding="utf-8")
INSTRUCTION = (SRC / "Agentenmaske.svelte").read_text(encoding="utf-8")


def _derived(name: str) -> str:
    """The expression a page flag is derived from."""
    return PAGE.split(f"const {name} = $derived(", 1)[1].split(")\n", 1)[0]


def _call() -> str:
    """The editor field the page falls back to, as the page writes it."""
    return PAGE.split("<WachsendesFeld\n          bind:this={feld}", 1)[1].split("/>", 1)[0]


def _rule(source: str, selector: str) -> str:
    """The declarations of the first rule that starts with ``selector``."""
    return source.split(f"{selector} {{", 1)[1].split("}", 1)[0]


def test_the_credentials_and_the_tools_file_ask_for_the_block():
    call = _call()
    assert "block={istZugangsdaten || istTools}" in call
    assert "volleHoehe={!(istZugangsdaten || istTools)}" in call
    # Exactly these two pages: the flags name one page each.
    assert _derived("istZugangsdaten") == "art === 'zugangsdaten'"
    assert _derived("istTools") == "art === 'tools_datei'"


def test_the_block_is_the_form_of_an_agents_instruction():
    block = _rule(FIELD, ".feld.block textarea")
    assert "height: 320px;" in block
    assert "resize: vertical;" in block
    assert "max-height: none;" in block
    # The instruction of an agent: the same height, the same way to drag it.
    prompt = _rule(INSTRUCTION, ".feld.prompt")
    assert "height: 320px;" in prompt and "resize: vertical;" in prompt
    # The field does not size itself to its text in a block, and it still
    # scrolls inside itself (the textarea's own rule).
    assert "if (!feld || volleHoehe || block) return" in FIELD
    assert "overflow-y: auto;" in _rule(FIELD, "textarea")


def test_silence_the_other_text_pages_keep_the_full_height_field():
    """The configuration, the system prompt and the memory fall back to the
    same field as before: full height, no block."""
    flags = {
        "zugangsdaten": _derived("istZugangsdaten") == "art === 'zugangsdaten'",
        "tools_datei": _derived("istTools") == "art === 'tools_datei'",
    }
    block_pages = {page for page, is_block in flags.items() if is_block}
    assert block_pages == {"zugangsdaten", "tools_datei"}
    # The page flag of the file warning box is unchanged: both file pages.
    assert _derived("istDatei") == "art === 'konfiguration' || art === 'zugangsdaten'"
    # A field that is no block still has the full-height rule it always had.
    assert ".feld.volleHoehe textarea {" in FIELD
