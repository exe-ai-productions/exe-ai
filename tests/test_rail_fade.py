"""The tool in the right rail reaches the row of signs in full strength.

Its last 40 px used to melt into that row through a mask, in every look: the
last row of a doc folder's tiles read as blurred. The mask is gone, and
with it the one switch that turned it off for the preview. The chat's own
fade above the input field is another surface and stays as it is.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAIL = ROOT / "frontend" / "src" / "teile" / "Arbeitsleiste.svelte"
APP = ROOT / "frontend" / "src" / "App.svelte"


def _declarations(source: str, selector: str) -> str:
    hit = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert hit, f"no rule for {selector}"
    return hit.group(1)


def test_the_tool_does_not_fade_at_the_foot_of_the_rail():
    rail = RAIL.read_text(encoding="utf-8")
    content = _declarations(rail, "\n  .inhalt")
    assert "mask" not in content
    assert "overflow: hidden;" in content
    assert ".inhalt.ganz" not in rail and "class:ganz" not in rail, "the switch for the fade is still there"


def test_the_chat_keeps_its_own_fade_above_the_input_field():
    """The silence check: the mask of the chat's history is not this one."""
    app = APP.read_text(encoding="utf-8")
    assert "--auslauf: 64px;" in app
