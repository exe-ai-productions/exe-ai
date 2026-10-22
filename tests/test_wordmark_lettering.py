"""The wordmark: the lettering stands as tall as the mark beside it.

The flat top of the first letter meets the mark's upper edge and the line
below stands on its lower edge, in the file the README shows and in the one
the program shows. The outlines are read from the files and measured as
curves, so the test needs no renderer.
"""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "readme": ROOT / "docs" / "site" / "wordmark.svg",
    "program": ROOT / "frontend" / "src" / "stil" / "wordmark.svg",
}
SVG = "{http://www.w3.org/2000/svg}"
TOLERANCE = 0.5

# The three outlines of the mark, as they have always been drawn.
MARK = ("117f49a061", "bdc7196e2a", "461675a2e8")
GREY = "rgb(56.078431%, 55.686275%, 52.54902%)"
FILLS = {
    "readme": ["#8f8e86"] * 4 + [GREY],
    "program": [f"url(#linear-pattern-{n})" for n in range(4)] + [GREY],
}
# The four gradients the program's file carries: where each one runs and
# every stop on it, in order.
GRADIENTS = "eac2ea9b73"

Box = tuple[float, float, float, float]


def _placement(text: str, start: tuple[float, float, float]) -> tuple[float, float, float]:
    """One uniform scale and one shift, from a list of translate and scale."""
    scale, dx, dy = start
    # Anything else would be measured as if it stood unmoved.
    assert not re.sub(r"(translate|scale)\([^)]*\)|\s", "", text), text
    for name, inner in re.findall(r"(translate|scale)\(([^)]*)\)", text):
        numbers = [float(n) for n in re.split(r"[ ,]+", inner.strip())]
        if name == "scale":
            scale *= numbers[0]
        else:
            dx += scale * numbers[0]
            dy += scale * (numbers[1] if len(numbers) > 1 else 0.0)
    return scale, dx, dy


def _span(a: float, b: float, c: float, d: float) -> tuple[float, float]:
    """Lowest and highest value of one cubic curve along one axis."""
    values = [a, d]
    qa, qb, qc = 3 * (-a + 3 * b - 3 * c + d), 6 * (a - 2 * b + c), 3 * (b - a)
    roots: list[float] = []
    if abs(qa) < 1e-12:
        if abs(qb) > 1e-12:
            roots.append(-qc / qb)
    else:
        inside = qb * qb - 4 * qa * qc
        if inside >= 0:
            roots += [(-qb + sign * math.sqrt(inside)) / (2 * qa) for sign in (1, -1)]
    for t in roots:
        if 0 < t < 1:
            u = 1 - t
            values.append(u**3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t**3 * d)
    return min(values), max(values)


def _shapes(d: str) -> list[Box]:
    """The box of every closed shape in one outline."""
    # Only moves, straight lines, cubic curves and closings are read here.
    assert set(re.findall(r"[A-Za-z]", d)) <= set("MLCZ"), sorted(set(re.findall(r"[A-Za-z]", d)))
    boxes: list[Box] = []
    tokens = re.findall(r"[MLCZ]|-?\d*\.?\d+(?:e-?\d+)?", d)
    xs: list[float] = []
    ys: list[float] = []
    here = (0.0, 0.0)
    i = 0
    while i < len(tokens):
        command = tokens[i]
        i += 1
        if command == "Z":
            continue
        count = 6 if command == "C" else 2
        numbers = [float(n) for n in tokens[i:i + count]]
        i += count
        if command == "M" and xs:
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
            xs, ys = [], []
        if command == "C":
            xs += _span(here[0], numbers[0], numbers[2], numbers[4])
            ys += _span(here[1], numbers[1], numbers[3], numbers[5])
        here = (numbers[-2], numbers[-1])
        xs.append(here[0])
        ys.append(here[1])
    if xs:
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return boxes


def _outlines(root: ET.Element) -> list[tuple[str, str, list[Box]]]:
    """Every outline in drawing order: its fill, its digest, its placed shapes."""
    found: list[tuple[str, str, list[Box]]] = []

    def walk(node: ET.Element, placement: tuple[float, float, float]) -> None:
        scale, dx, dy = placement = _placement(node.get("transform", ""), placement)
        if node.tag == SVG + "path":
            d = node.get("d", "")
            placed = [(scale * a + dx, scale * b + dy, scale * c + dx, scale * e + dy) for a, b, c, e in _shapes(d)]
            found.append((node.get("fill", ""), hashlib.sha256(d.encode()).hexdigest()[:10], placed))
        for child in node:
            if child.tag != SVG + "defs":
                walk(child, placement)

    walk(root, (1.0, 0.0, 0.0))
    return found


def _measure(name: str) -> dict[str, float]:
    root = ET.parse(FILES[name]).getroot()
    outlines = _outlines(root)
    mark = [box for _, _, boxes in outlines[:3] for box in boxes]
    # A lone starting point without a stroke draws nothing and has no size.
    title, line = ([box for box in boxes if box[2] > box[0]] for _, _, boxes in outlines[3:5])
    # The first letter is the one furthest left; the line below stands where
    # most of its letters end, the few with a tail hang lower.
    first = min(title, key=lambda box: box[0])
    baseline = Counter(round(box[3], 2) for box in line).most_common(1)[0][0]
    width, height = (float(n) for n in root.get("viewBox", "").split()[2:])
    return {
        "mark_top": min(box[1] for box in mark),
        "mark_bottom": max(box[3] for box in mark),
        "title_top": first[1],
        "baseline": baseline,
        "right": max(box[2] for box in title + line),
        "bottom": max(box[3] for box in title + line),
        "width": width,
        "height": height,
    }


@pytest.mark.parametrize("name", sorted(FILES))
def test_the_lettering_is_as_tall_as_the_mark(name: str) -> None:
    m = _measure(name)
    assert abs(m["title_top"] - m["mark_top"]) <= TOLERANCE, m
    assert abs(m["baseline"] - m["mark_bottom"]) <= TOLERANCE, m


@pytest.mark.parametrize("name", sorted(FILES))
def test_the_lettering_ends_inside_the_drawing(name: str) -> None:
    m = _measure(name)
    assert m["right"] <= m["width"], m
    assert m["bottom"] <= m["height"], m


@pytest.mark.parametrize("name", sorted(FILES))
def test_the_mark_and_the_colours_stay_as_they_were(name: str) -> None:
    root = ET.parse(FILES[name]).getroot()
    outlines = _outlines(root)
    assert tuple(digest for _, digest, _ in outlines[:3]) == MARK
    assert [fill for fill, _, _ in outlines] == FILLS[name]
    # The mark itself is not moved or resized: it still spans its old height.
    m = _measure(name)
    assert (m["mark_top"], m["mark_bottom"]) == pytest.approx((10.104, 169.862), abs=0.005)


def test_the_gradients_of_the_program_stay_as_they_were() -> None:
    root = ET.parse(FILES["program"]).getroot()
    told = "|".join(
        " ".join(f"{key}={value}" for key, value in sorted(node.attrib.items()))
        for gradient in root.iter(SVG + "linearGradient")
        for node in (gradient, *gradient)
    )
    assert hashlib.sha256(told.encode()).hexdigest()[:10] == GRADIENTS


def test_the_images_carry_the_size_of_the_drawing() -> None:
    """A width and height that differ from the drawing would squeeze it."""
    for name, path in FILES.items():
        root = ET.parse(path).getroot()
        width, height = root.get("viewBox", "").split()[2:]
        assert (root.get("width"), root.get("height")) == (width, height), name
    width, height = ET.parse(FILES["program"]).getroot().get("viewBox", "").split()[2:]
    for part in ("Erststart.svelte", "Updatekarte.svelte"):
        source = (ROOT / "frontend" / "src" / "teile" / part).read_text(encoding="utf-8")
        assert f'src={{wordmark}} width="{width}" height="{height}"' in source, part
    # The README shows the heading drawing at a width of its own; a width alone keeps the proportions
    # of the drawing, a height beside it could squeeze it.
    hero = ROOT / "docs" / "site" / "hero-light.svg"
    width = float(ET.parse(hero).getroot().get("viewBox", "").split()[2])
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    tag = re.search(r'<img src="docs/site/hero-light\.svg"[^>]*>', readme)
    assert tag, "the README no longer shows the heading drawing"
    assert "height=" not in tag.group(0), tag.group(0)
    shown = re.search(r'\bwidth="(\d+)"', tag.group(0))
    assert shown and 0 < int(shown.group(1)) <= width, tag.group(0)
