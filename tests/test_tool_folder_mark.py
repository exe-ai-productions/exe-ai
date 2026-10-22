"""The folder mark of a tool is the open folder of the house, not a closed one.

`Werkzeugzeichen.svelte` draws its own marks and hands the rest to the house
signs; the branch `ordner` stands before that hand-over, so what it draws is
what `list_dir`, `create_folder` and the servers that name the folder show.
It draws the same two paths as the house's open folder
(`Hauszeichen.svelte`), scaled from the 24 grid of that sign onto the 64 grid
of the tool marks, and keeps the stroke-by-stroke drawing of a running call.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL_MARKS = ROOT / "frontend/src/teile/Werkzeugzeichen.svelte"
HOUSE_SIGNS = ROOT / "frontend/src/teile/Hauszeichen.svelte"
CATALOGUE = ROOT / "frontend/src/lib/werkzeugkatalog.js"

SCALE = 64 / 24
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _branch(text: str, head: str) -> str:
    """The markup of one `{:else if zeichen === ...}` branch, up to the next."""
    start = text.index(head)
    end = text.index("{:else", start + len(head))
    return text[start:end]


def _tool_folder() -> str:
    return _branch(TOOL_MARKS.read_text(encoding="utf-8"), "{:else if zeichen === 'ordner'}")


def _tool_paths() -> list[tuple[str, dict[str, str]]]:
    """Each path of the tool folder with its attributes."""
    found = []
    for tag in re.findall(r"<path(.*?)/>", _tool_folder(), re.S):
        attributes = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
        style = re.search(r"--laenge:(\d+(?:\.\d+)?)", attributes.get("style", ""))
        attributes["laenge"] = style.group(1) if style else ""
        found.append((attributes["d"], attributes))
    return found


def _house_folder_paths() -> list[str]:
    text = HOUSE_SIGNS.read_text(encoding="utf-8")
    branch = _branch(text, "{:else if zeichen === 'ordner' || zeichen === 'folder_plus'}")
    return re.findall(r'<path d="([^"]+)"', branch)[:2]


def _length(path: str) -> float:
    """The length of a path of absolute M, H, V, L and Z commands."""
    assert not re.search(r"[^MHVLZ\d\s.\-]", path), f"a command this helper cannot measure: {path}"
    tokens = re.findall(r"[MHVLZ]|-?\d+(?:\.\d+)?", path)
    x = y = x0 = y0 = 0.0
    total = 0.0
    index = 0
    while index < len(tokens):
        command = tokens[index]
        index += 1
        if command == "M":
            x, y = float(tokens[index]), float(tokens[index + 1])
            x0, y0 = x, y
            index += 2
        elif command == "H":
            new = float(tokens[index])
            total += abs(new - x)
            x = new
            index += 1
        elif command == "V":
            new = float(tokens[index])
            total += abs(new - y)
            y = new
            index += 1
        elif command == "L":
            nx, ny = float(tokens[index]), float(tokens[index + 1])
            total += math.hypot(nx - x, ny - y)
            x, y = nx, ny
            index += 2
        else:  # Z
            total += math.hypot(x0 - x, y0 - y)
            x, y = x0, y0
    return total


def test_the_tool_folder_draws_the_two_paths_of_the_open_house_folder_scaled():
    tool = [d for d, _ in _tool_paths()]
    house = _house_folder_paths()
    assert len(tool) == 2 and len(house) == 2, (tool, house)
    for drawn, original in zip(tool, house, strict=True):
        assert re.findall(r"[MHVLZ]", drawn) == re.findall(r"[MHVLZ]", original), (drawn, original)
        drawn_numbers = [float(n) for n in NUMBER.findall(drawn)]
        scaled = [float(n) * SCALE for n in NUMBER.findall(original)]
        assert len(drawn_numbers) == len(scaled)
        for got, want in zip(drawn_numbers, scaled, strict=True):
            assert abs(got - want) <= 0.05, (drawn, original)


def test_the_tool_folder_is_no_longer_the_closed_one():
    assert "M8 20 V15 H26 L31 22 H56 V49 H8 Z" not in TOOL_MARKS.read_text(encoding="utf-8")
    assert "M8 30 H56" not in _tool_folder()


def test_the_open_folder_keeps_the_stroke_widths_and_the_stroke_by_stroke_drawing():
    paths = _tool_paths()
    assert [a["stroke-width"] for _, a in paths] == ["5", "4.5"]
    assert [a["class"] for _, a in paths] == ["strich z1", "strich z2"]
    branch = _tool_folder()
    assert 'class:laeuft={animiert}' in branch and 'class:werkzeug={istWerkzeug}' in branch
    assert 'viewBox="0 0 64 64"' in branch


def test_every_stroke_has_a_dash_length_that_covers_its_path():
    # The stroke is drawn by a dash as long as the path; a shorter one would
    # leave a gap at its end, a far longer one would draw late.
    for d, attributes in _tool_paths():
        length = _length(d)
        assert length <= float(attributes["laenge"]) <= length + 3, (d, length, attributes["laenge"])


def test_the_house_folder_signs_stay_as_they_were():
    text = HOUSE_SIGNS.read_text(encoding="utf-8")
    assert '<path d="M3.75 18 V6 H9.75 L11.63 8.25 H18 V11.25" />' in text
    assert '<path d="M3.75 18 H16.5 L20.25 11.25 H7.5 Z" />' in text
    assert '<path d="M21 2.5v4M19 4.5h4" stroke-width="1.8" />' in text


@pytest.mark.parametrize(
    ("table", "name"),
    [
        ("NACH_WERKZEUG", "list_dir"),
        ("NACH_WERKZEUG", "create_folder"),
        ("NACH_SERVER", "drive"),
        ("NACH_SERVER", "linear"),
    ],
)
def test_the_tools_and_servers_that_name_the_folder_still_lead_to_it(table, name):
    block = re.search(rf"{table}\s*=\s*\{{(.*?)\n\}}", CATALOGUE.read_text(encoding="utf-8"), re.S)
    assert block, table
    entries = dict(re.findall(r"^\s*([\w-]+):\s*'([a-z_]+)',", block.group(1), re.M))
    assert entries[name] == "ordner"


def test_silence_the_other_tool_marks_are_untouched():
    text = TOOL_MARKS.read_text(encoding="utf-8")
    # A mark from before this one and one from after it in the file.
    assert '<circle class="strich z1" cx="32" cy="32" r="24" stroke-width="5" style="--laenge:152" />' in text
    assert 'd="M12 14 H52 V44 H30 L18 54 V44 H12 Z"' in text
    assert "{:else if zeichen !== RUECKFALL}" in text
