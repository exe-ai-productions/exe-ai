"""The head of the model detail page: a long name stays in its block.

The page is Svelte, drawn in a browser; what can be held here is its source:
the rule that keeps the name in one line and cuts it with an ellipsis, the
title that carries the full name, and the rules that must not change next to
it (the block may shrink, the information on the right does not give way, the
line under the name is cut the same way).
"""

from __future__ import annotations

import re
from pathlib import Path

QUELLE = Path(__file__).resolve().parent.parent / "frontend/src/teile/Modelldetail.svelte"


def _rule(selector: str) -> str:
    quelle = QUELLE.read_text(encoding="utf-8")
    treffer = re.search(r"^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", quelle, re.MULTILINE)
    assert treffer, f"no rule for {selector}"
    return treffer.group(1)


def test_the_name_stays_in_one_line_and_is_cut_with_an_ellipsis():
    regel = _rule(".name")
    assert "white-space: nowrap" in regel
    assert "overflow: hidden" in regel
    assert "text-overflow: ellipsis" in regel


def test_the_full_name_stands_in_the_title():
    quelle = QUELLE.read_text(encoding="utf-8")
    assert re.search(r'<div class="name" title=\{name\}>\{name\}</div>', quelle)


def test_the_neighbours_keep_their_rules():
    """Silence probe: the block of the name may shrink, the information on the
    right does not give way, the line under the name is cut as before."""
    assert "min-width: 0" in _rule(".wer")
    assert "flex: none" in _rule(".zeichenreihe")
    unter = _rule(".unter")
    assert "white-space: nowrap" in unter
    assert "text-overflow: ellipsis" in unter
