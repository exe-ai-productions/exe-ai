"""Settings › Tools file stands in a block; the other text pages fill the page.

The tools file takes the form of an agent's instruction: 320 px high, the text
scrolls inside it, the corner drags it taller, and the block of keys stands
under it. The credentials, the configuration, the system prompt and the memory
fill the page with their field. Read off the source, the way the other
interface tests do.
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


def test_only_the_tools_file_asks_for_the_block():
    call = _call()
    assert "block={istTools}" in call
    assert "volleHoehe={!istTools}" in call
    assert "istZugangsdaten" not in PAGE
    # Exactly this page: the flag names one page.
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


def test_the_two_file_pages_take_the_page_down_to_the_foot():
    """The credentials and the configuration give the field the height of the
    page through the frame's own switch, and the field ends above the foot."""
    frame = PAGE.split("<Menueseite", 1)[1].split(">", 1)[0]
    assert "festeHoehe={istWerkzeuge || istCronjobs || agentList || istDatei}" in frame
    assert "fillsFoot={istCronjobs || agentList}" in frame
    assert 'class:file={istDatei}' in PAGE
    assert "margin-bottom: 18px;" in _rule(PAGE, ".editorboden.file")


def test_silence_the_other_text_pages_keep_the_full_height_field():
    """The credentials, the configuration, the system prompt and the memory
    use the full-height field; only the tools file is a block."""
    # The page flag of the file warning box is unchanged: both file pages.
    assert _derived("istDatei") == "art === 'konfiguration' || art === 'zugangsdaten'"
    # A field that is no block still has the full-height rule it always had.
    assert ".feld.volleHoehe textarea {" in FIELD
