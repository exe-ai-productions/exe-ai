"""Settings › Agents: an agent file that cannot be read gives the mask's place
back to the list, and the list is read again.

The page held the list it had loaded while the file was still sound; after
the mask reported the broken head it showed that agent from the old list,
empty, with no warning box, until something loaded the list again. Read off
the source, the way the other interface tests do.
"""

from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "src" / "teile"
MASKE = (FRONTEND / "Agentenmaske.svelte").read_text(encoding="utf-8")
SEITE = (FRONTEND / "SystemPrompt.svelte").read_text(encoding="utf-8")


def test_both_ways_an_unreadable_file_reaches_the_page_through_one_callback():
    assert "onunlesbar" in MASKE.split("$props()", 1)[0].rsplit("let {", 1)[1]
    # The head that cannot be read, and the file that cannot be opened.
    assert MASKE.count("onunlesbar ? onunlesbar() : onabbrechen?.()") == 2


def test_the_page_closes_the_mask_and_reads_the_list_again():
    aufruf = SEITE.split("<Agentenmaske", 1)[1].split("/>", 1)[0]
    assert "onunlesbar={() => { maske = null; dateienLaden() }}" in aufruf


def test_silence_cancel_and_finish_do_not_reload_the_list():
    """Cancel still only closes the mask; saving goes its own way."""
    aufruf = SEITE.split("<Agentenmaske", 1)[1].split("/>", 1)[0]
    assert "onabbrechen={() => (maske = null)}" in aufruf
    assert "onfertig={maskeFertig}" in aufruf
    # The button of the mask calls the callback without a reload.
    assert 'onclick={() => onabbrechen?.()}' in MASKE
