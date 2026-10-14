"""The dust of a picture being painted carries no state colour: blue means a
state (running, active), and which grain is lit depends on a counter, not on a
state. Every ninth grain is lit in the plain text colour instead; the glow of a
settled grain is its own rule and stays.
"""

from __future__ import annotations

import re
from pathlib import Path

STAGE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "teile" / "Bildfuellung.svelte"


def test_no_grain_of_the_dust_is_blue():
    source = STAGE.read_text(encoding="utf-8")
    assert "el.className = 'korn' + (i % 9 === 0 ? ' hell' : '')" in source
    assert ".staub :global(.korn.hell) { background: var(--text); }" in source
    for rule in re.findall(r"\.staub[^{]*\{[^}]*\}", source):
        if "box-shadow" in rule:
            continue
        assert "--blau" not in rule, rule
