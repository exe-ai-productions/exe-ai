"""The shortcuts page: its section headings stand without a rule behind them.

The rows of the list off the Mac (no "Quit", "Minimise" instead of "Put in the
Dock", keys in words) are held by `tests/test_microphone_key.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "teile" / "Shortcuts.svelte"


def test_the_section_headings_have_no_rule_behind_them():
    page = PAGE.read_text(encoding="utf-8")
    style = page.split("<style>", 1)[1]
    # No pseudo-element of either spelling, and no border on the heading itself.
    assert not re.search(r"\.blocktitel\s*:{1,2}(?:after|before)", style)
    assert not re.search(r"\.blocktitel[^{]*\{[^}]*border", style)
    # The heading is still there, for the microphone and for each group.
    assert page.count('class="blocktitel tafelkopf"') == 2
