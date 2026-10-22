"""The house's main buttons (``.wichtig``) share one size everywhere.

Twelve buttons used to carry eight different font sizes and paddings — one
size that happened to already match the target (``Frage.svelte`` among
them) and seven that did not. `font-size` and `padding` live on the shared
`.knopf` base rule, not on `.wichtig` itself, so giving `.wichtig` its own
size is the only way to change just the main button and leave its plain
siblings (Cancel, secondary actions) exactly as they were.

A file whose base rule already matches the target needs no override at all
— reading the base when `.wichtig` is silent is the point of this test.
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend" / "src"

ZIEL_GROESSE = "13px"
ZIEL_POLSTER = "7px 15px"

_KNOPF_BASIS = re.compile(r"(?<![.\w])\.knopf\s*\{")
_WICHTIG = re.compile(r"\.(?:knopf\.wichtig|wichtig)\s*\{")


def _block(text: str, treffer_ende: int) -> str:
    schluss = text.index("}", treffer_ende)
    return text[treffer_ende:schluss]


def _svelte_dateien():
    return sorted(p for p in FRONTEND.rglob("*.svelte") if "node_modules" not in str(p))


def _eigenschaft(block: str, name: str) -> str | None:
    treffer = re.search(rf"(?<!-){name}\s*:\s*([^;]+);", block)
    return treffer.group(1).strip() if treffer else None


def _aus_font_kurzform(block: str) -> str | None:
    # `font: 600 12.5px var(--schrift)` — the size sits between the weight
    # and the family, the one token that ends in a unit.
    treffer = re.search(r"font\s*:\s*[^;]*?(\d+(?:\.\d+)?px)", block)
    return treffer.group(1) if treffer else None


def _dateien_mit_wichtig_knopf():
    for pfad in _svelte_dateien():
        text = pfad.read_text(encoding="utf-8")
        treffer = _WICHTIG.search(text)
        if treffer:
            yield pfad, text, treffer.end()


def test_jeder_wichtig_knopf_traegt_dieselbe_groesse():
    """`.wichtig`, or its base `.knopf` when `.wichtig` is silent about it,
    must resolve to 13px / 7px 15px in every file that has a main button."""
    gepruefte = []
    for pfad, text, wichtig_ende in _dateien_mit_wichtig_knopf():
        wichtig_block = _block(text, wichtig_ende)

        basis_treffer = _KNOPF_BASIS.search(text)
        basis_block = _block(text, basis_treffer.end()) if basis_treffer else ""

        groesse = (
            _eigenschaft(wichtig_block, "font-size")
            or _aus_font_kurzform(wichtig_block)
            or _eigenschaft(basis_block, "font-size")
            or _aus_font_kurzform(basis_block)
        )
        polster = _eigenschaft(wichtig_block, "padding") or _eigenschaft(basis_block, "padding")

        gepruefte.append(pfad.name)
        assert groesse == ZIEL_GROESSE, (
            f"{pfad.relative_to(WURZEL)}: .wichtig resolves to {groesse!r}, expected {ZIEL_GROESSE!r}"
        )
        assert polster == ZIEL_POLSTER, (
            f"{pfad.relative_to(WURZEL)}: .wichtig resolves to {polster!r}, expected {ZIEL_POLSTER!r}"
        )

    # A silent count would pass on an empty list just as well — the eleven
    # named in the order (Verbindungen.svelte's own button moved into
    # MCPMaske.svelte, so its .wichtig rule no longer exists
    # there) is the floor this test actually has to clear. Ten since the
    # permission box went: its answers are rows in the one question box
    # now, none of them a main button. Nine since the catalogue page stopped
    # carrying a main button of its own: its download buttons are the rows
    # of the shared model page (Modelldetail.svelte).
    # Six since the foot buttons of the settings, the server mask and the
    # provider mask became the house button of the global stylesheet, which
    # the test below measures. Five since the skill form's foot became two
    # signs. Three since the model page and the cards of the catalogue carry
    # sign buttons only (download, cancel), measured in
    # tests/test_hauptknoepfe_glas.py.
    assert len(gepruefte) >= 3, f"only {len(gepruefte)} files with .wichtig found: {gepruefte}"


def test_the_house_button_carries_the_same_size():
    """The one button of the global stylesheet, quiet and main alike: the
    main form says nothing about size, so it resolves to the base rule."""
    text = (FRONTEND / "stil" / "global.css").read_text(encoding="utf-8")
    base = re.search(r"\n\.button\s*\{", text)
    assert base, "no .button rule in stil/global.css"
    block = _block(text, base.end())
    assert (_eigenschaft(block, "font-size") or _aus_font_kurzform(block)) == ZIEL_GROESSE
    assert _eigenschaft(block, "padding") == ZIEL_POLSTER
    main = re.search(r"\n\.button\.primary\s*\{", text)
    assert main, "no .button.primary rule in stil/global.css"
    main_block = _block(text, main.end())
    assert _eigenschaft(main_block, "font-size") is None and _aus_font_kurzform(main_block) is None
    assert _eigenschaft(main_block, "padding") is None
