"""The input bar's buttons never leave the bar.

When the window runs out of room the words go first (``narrow``). When even
that form does not fit, a second step follows (``tight``): the model picker
drops its lamps from the row — they stay on the model's own line in its menu
— and cuts the name shorter still, and the gaps close. The microphone and
the arrow are what the bar is for: they are never the ones to go. Both steps
are measured, and both come and go with the room the row has.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAR = (ROOT / "frontend" / "src" / "teile" / "Eingabeleiste.svelte").read_text(encoding="utf-8")
PICKER = (ROOT / "frontend" / "src" / "teile" / "Modellwahl.svelte").read_text(encoding="utf-8")


def _rule(source: str, selector: str) -> str:
    hit = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert hit, f"no rule for {selector}"
    return hit.group(1)


def test_the_bar_measures_a_second_step_when_the_narrow_form_does_not_fit():
    assert "let tight = $state(false)" in BAR
    assert "narrowWidth = neededWidth()" in BAR
    assert "if (narrowWidth > row.clientWidth + 1) {\n        tight = true" in BAR


def test_the_second_step_comes_and_goes_with_the_room_the_narrow_form_has():
    """A row that is already narrow and only changes its room: tight is
    set when the narrow form stops fitting, and taken back when it fits."""
    assert "const needsTight = row.clientWidth + 1 < narrowWidth" in BAR
    assert "if (needsTight !== tight) {\n          tight = needsTight" in BAR


def test_the_row_and_the_model_picker_wear_the_step():
    assert '<div class="bar-row" class:narrow class:tight bind:this={row}>' in BAR
    assert "{narrow} {tight}" in BAR
    assert "tight = false, label = $bindable('')" in PICKER
    assert '<button class="part" class:narrow class:tight' in PICKER


def test_tight_drops_the_lamps_from_the_row_and_cuts_the_name():
    assert "display: none;" in _rule(PICKER, ".part.tight .lamps")
    assert "max-width: 44px;" in _rule(PICKER, ".part.tight .name")
    assert "gap: 0;" in _rule(BAR, ".bar-row.tight .linkegruppe,\n  .bar-row.tight .rechts")


def test_the_lamps_stay_on_the_models_line_in_the_menu():
    """The silence check: the readings are not gone, only out of the row."""
    assert '<span class="tail-lamps">{@render lampRow(lamps(model))}</span>' in PICKER


def test_the_microphone_and_the_arrow_are_never_the_ones_to_go():
    right = BAR[BAR.index('<div class="rechts">'):BAR.index("</div>\n    </div>\n  </div>\n</div>")]
    for part in ("<Mikrofonknopf", '<button\n          class="aktion"'):
        before = right[: right.index(part)]
        assert "{#if" not in before.rsplit("{/if}", 1)[-1], f"{part} stands under a condition"
