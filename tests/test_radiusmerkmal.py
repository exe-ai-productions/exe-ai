"""A radius token the styles named but nobody asked for.

``global.css`` used to carry ``--radius: 10px`` from a time before the corner
was written where it is used. Nothing read it: the house corner is 9, spelled
out at every place that needs one, and 10 is a value the product uses nowhere.
A token that is declared and never consumed is worse than no token — the next
component reaching for "the house radius" would find a number the product does
not use.

The check is a pair on purpose. The first test names the token that was
removed, so it falls over the moment the line comes back — in the palette or
in any component's own style block. The second is the silence probe: the same
reading applied to a token that IS consumed must stay quiet, or the first test
would only be proving that the reading is broken.
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "frontend" / "src"
STILENDUNGEN = {".css", ".svelte", ".js", ".ts"}


def _stilquellen() -> list[Path]:
    return [
        datei
        for datei in sorted(QUELLE.rglob("*"))
        if datei.is_file() and datei.suffix in STILENDUNGEN
    ]


def _deklarationen(name: str) -> list[str]:
    """Every source file that DECLARES this custom property.

    The whole tree, not only the palette file: a component declaring the token
    in its own ``<style>`` block and leaving it unused would be the very
    regression this guards, and a reading that looks at the palette alone
    would not see it.

    Three shapes declare a custom property, and all three count. A line of its
    own is the usual one; a one-liner or an inline attribute puts it mid-line
    (``:root { --radius: 10px }``, ``style="--radius:10px"``); and JavaScript
    sets it through ``setProperty``. Anchoring on the start of a line would see
    only the first, while promising to watch them all.

    The lookbehind is what keeps ``border-radius:`` out: without it the dash
    in front would make every 9px corner a hit. A longer name that merely
    begins the same way stays its own token, because the colon has to follow
    the name — ``--radius-gross:`` does not match ``--radius``.
    """
    muster = (
        re.compile(rf"(?<![\w-]){re.escape(name)}\s*:"),
        re.compile(rf"setProperty\(\s*['\"]{re.escape(name)}['\"]"),
    )
    return [
        str(datei.relative_to(WURZEL))
        for datei in _stilquellen()
        if any(m.search(datei.read_text(encoding="utf-8", errors="ignore")) for m in muster)
    ]


def _verbraucher(name: str) -> list[str]:
    """Every source file that READS this custom property.

    Not ``\\b`` at the end: that would let ``var(--radius-gross)`` count as a
    reader of ``--radius``, because a boundary sits between the letter and the
    dash. Any future token whose name merely starts the same way stays its own
    token.
    """
    muster = re.compile(rf"var\(\s*{re.escape(name)}(?![\w-])")
    return [
        str(datei.relative_to(WURZEL))
        for datei in _stilquellen()
        if muster.search(datei.read_text(encoding="utf-8", errors="ignore"))
    ]


def test_der_tote_radius_ist_weg() -> None:
    """Neither declared nor read — the token is gone, not just unused."""
    assert _deklarationen("--radius") == [], (
        "--radius is declared again. The house corner is 9 and is written "
        "where it is used; a token nobody reads only invites a component to "
        "adopt a value the product does not use."
    )
    assert _verbraucher("--radius") == []


def test_ein_benutztes_merkmal_bleibt_unbeanstandet() -> None:
    """The silence probe: the same reading on a token that is really used."""
    assert _deklarationen("--linie-stark")
    assert _verbraucher("--linie-stark"), (
        "The reading found no consumer for a token the components use "
        "everywhere, so the test above would pass for the wrong reason."
    )
