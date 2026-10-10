"""Every uppercase heading in the frontend carries the one house form.

Seventeen headings used to set their own font-size, weight, letter-spacing
and colour, each a little differently — sixteen different forms for one
kind of thing. The house form lives in exactly one place,
`frontend/src/stil/global.css`'s `.tafelkopf`; a rule that still declares
those properties itself, instead of adding the class and leaving typography
to that one place, is the old mistake again.

`text-transform: uppercase` is the marker: every heading has it, and
nothing else in the house does (checked separately below). A rule that
carries it AND one of the properties `.tafelkopf` already owns has not
made the move yet.
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend" / "src"

# Confirmed against the code: not headings at all, so
# their own uppercase styling stays theirs.
AUSNAHMEN = {
    "Warteblasen.svelte",
}

# The properties `.tafelkopf` already owns — a heading rule may not set
# any of these itself.
EIGENE_REGELN = re.compile(
    r"(?<![-\w])(font-size|font-weight|letter-spacing|color|font)\s*:", re.IGNORECASE
)

_REGEL = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _svelte_dateien():
    for pfad in sorted(FRONTEND.rglob("*.svelte")):
        if "node_modules" in str(pfad):
            continue
        if pfad.name in AUSNAHMEN:
            continue
        yield pfad


def _style_block(text: str) -> str:
    treffer = re.search(r"<style[^>]*>(.*)</style>", text, re.DOTALL)
    return treffer.group(1) if treffer else ""


def test_keine_ueberschrift_setzt_ihre_eigene_schriftregel():
    verstoesse = []
    for pfad in _svelte_dateien():
        style = _style_block(pfad.read_text(encoding="utf-8"))
        for selektor, koerper in _REGEL.findall(style):
            if "text-transform" not in koerper or "uppercase" not in koerper:
                continue
            eigene = EIGENE_REGELN.findall(koerper)
            if eigene:
                verstoesse.append(
                    f"{pfad.relative_to(WURZEL)} {selektor.strip()}: setzt {sorted(set(eigene))} "
                    "selbst statt .tafelkopf zu tragen"
                )
    assert not verstoesse, "\n".join(verstoesse)


def test_die_ausnahmeliste_ist_noch_die_einzige():
    """Silence proof for the test above: outside the two excused files, no
    `.svelte` file may declare `text-transform: uppercase` at all — the
    house form carries it in class="tafelkopf", never in a local rule."""
    treffer = []
    for pfad in sorted(FRONTEND.rglob("*.svelte")):
        if "node_modules" in str(pfad) or pfad.name in AUSNAHMEN:
            continue
        text = pfad.read_text(encoding="utf-8")
        if "text-transform" in text and "uppercase" in text:
            treffer.append(str(pfad.relative_to(WURZEL)))
    assert not treffer, f"own text-transform: uppercase outside the exception list: {treffer}"
