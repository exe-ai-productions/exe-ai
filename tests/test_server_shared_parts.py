"""The parts the server pages share, read off the source: the head signs of
"Memory" and "Network", the folder buttons of a card, the angle of the folding
head and the estimate line. The measures themselves are checked in a real
browser (`test_server_card_measures_chrome.py`); this file holds the places
where the numbers are written, so that a later edit cannot move them one by one.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEILE = ROOT / "frontend" / "src" / "teile"


def _source(name: str) -> str:
    return (TEILE / name).read_text(encoding="utf-8")


def _rule(style: str, selector: str) -> str:
    """The body of the first rule that starts with this selector."""
    return style.split(selector + " {", 1)[1].split("}", 1)[0]


# The drawing of the house icon chip-with-network, on its own 64 grid.
NETWORK_PIECES = (
    '<rect x="12" y="12" width="40" height="40" rx="7" stroke-width="5" />',
    '<path d="M24 5 V12 M40 5 V12 M24 52 V59 M40 52 V59" stroke-width="4.5" />',
    '<circle cx="32" cy="24" r="3.5" stroke-width="4.5" />',
    '<circle cx="23" cy="40" r="3.5" stroke-width="4.5" />',
    '<circle cx="41" cy="40" r="3.5" stroke-width="4.5" />',
    '<path d="M30 27.5 L25 36.5 M34 27.5 L39 36.5 M26.5 40 H37.5" stroke-width="4.5" />',
)


def test_the_memory_head_wears_the_chip_with_the_bolt():
    regler = _source("Serverregler.svelte")
    head = re.search(r"<Serverabschnitt\s[^>]*titel=\{t\('modell\.gruppe_speicher'\)\}[^>]*>", regler)
    assert head, "the memory section is gone"
    assert 'zeichen="chip_bolt"' in head.group(0)
    assert 'zeichen="server"' not in regler


def test_the_network_sign_is_the_chip_with_the_network_on_the_64_grid():
    signs = _source("Hauszeichen.svelte")
    branch = signs.split("{:else if zeichen === 'netzwerk'}", 1)[1].split("{:else if", 1)[0]
    for piece in NETWORK_PIECES:
        assert piece in branch, piece
    # The old cable with its two plugs is gone.
    assert 'width="5.5" height="4.5"' not in branch
    # The view of the sign is the 64 grid, written on the one line the other
    # tests read up to its end.
    lines = [line for line in signs.splitlines() if line.lstrip().startswith("const SICHTFELDER = ")]
    assert len(lines) == 1
    assert "netzwerk: '0 0 64 64'" in lines[0]
    assert "chip_bolt: '0 0 64 64'" in lines[0]


def test_the_network_sign_is_named_in_the_list_of_signs_as_the_chip():
    signs = _source("Hauszeichen.svelte")
    assert "the chip with a network" in signs
    assert "a network link (two plugs)" not in signs


def test_a_card_sets_the_folder_buttons_to_34_px_and_its_folder_row_is_one_of_56():
    section = _source("Serverabschnitt.svelte")
    style = section.split("<style>", 1)[1]
    assert "--ordnerknopf: 34px;" in _rule(style, ".karte")
    # The folder row is one of the rows of 56 now: no rule of its own for it.
    assert "min-height: 55px" not in style
    assert ":has(.knopfpaar)" not in style
    assert "min-height: 56px;" in _rule(style, ".karte > :global(.zeile)")


def test_silence_the_folder_buttons_outside_a_card_and_on_the_phone_keep_their_size():
    row = _source("Speicherortzeile.svelte")
    assert "width: var(--ordnerknopf, 30px);" in row and "height: var(--ordnerknopf, 30px);" in row
    phone = (ROOT / "frontend" / "src" / "phone" / "servers" / "StorageView.svelte").read_text(encoding="utf-8")
    assert "--ordnerknopf: 40px;" in phone
    # The size is set by the card and by the phone page, never by the row itself.
    assert "--ordnerknopf:" not in row.split("<style>", 1)[1]


def test_the_angle_of_the_folding_head_is_14_px():
    section = _source("Serverabschnitt.svelte")
    angle = re.search(r'<svg class="winkel"[^>]*>', section)
    assert angle
    assert 'width="14"' in angle.group(0) and 'height="14"' in angle.group(0)


def test_the_wired_memory_row_writes_both_numbers_through_the_number_display():
    regler = _source("Serverregler.svelte")
    line = next(row for row in regler.splitlines() if "modell.wired_von" in row)
    assert "wired: formatGb(schaetzung.gesamt, texte.sprache)" in line
    assert "total: formatGb(grenzeGb, texte.sprache)" in line
    assert "toFixed" not in line
    assert "import { formatGb } from '../lib/numberDisplay.js'" in regler


def test_the_comment_over_the_advanced_drawer_says_it_stands_open_on_start():
    regler = _source("Serverregler.svelte")
    assert "Shut by default" not in regler
    assert "let erweitertOffen = $state(true)" in regler
    assert "Open on start (see `erweitertOffen`); the head folds it away." in regler
    assert "never has to find out" not in regler
