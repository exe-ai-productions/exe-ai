"""The arrow under an answer is `rotate-cw` of Lucide, drawn as it is.

The old circular arrow of the catalogue had its tip at the start of the arc
instead of its end and looked broken. All three places that drew it now draw
the two paths of `rotate-cw`: the arrow under the last answer (and under a
failed one, where it asks again), the arrow under one's own message
("send again"), and the sign `neu_laden` the preview's reload button wears.
The licence text of the drawing stands in THIRD_PARTY_NOTICES.md; the code
itself carries no note.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEILE = ROOT / "frontend" / "src" / "teile"
SOURCE = ROOT / "frontend" / "src"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"

ARC = "M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"
TIP = "M21 3v5h-5"
OLD_ARROW = "M20 11a8 8 0 10-2.3 5.7"


def _paths_in(text: str) -> list[str]:
    return re.findall(r'<path d="([^"]+)"', text)


def test_the_arrow_under_an_answer_and_under_ones_own_message_draw_rotate_cw():
    message = (TEILE / "Nachricht.svelte").read_text(encoding="utf-8")
    drawn = [d for d in _paths_in(message) if d in (ARC, TIP)]
    # Two buttons (send again, regenerate), two paths each.
    assert drawn.count(ARC) == 2 and drawn.count(TIP) == 2, drawn
    for button in re.findall(r"<svg[^>]*>\s*<path d=\"" + re.escape(ARC) + r"\" />", message):
        assert 'viewBox="0 0 24 24"' in button
        assert 'stroke-width="2"' in button
        assert 'stroke-linecap="round"' in button and 'stroke-linejoin="round"' in button


def test_the_sign_neu_laden_draws_the_same_two_paths():
    signs = (TEILE / "Hauszeichen.svelte").read_text(encoding="utf-8")
    branch = re.search(r"\{:else if zeichen === 'neu_laden'\}([\s\S]*?)\{:else if", signs)
    assert branch, "the sign neu_laden is missing"
    assert _paths_in(branch.group(1)) == [ARC, TIP]


def test_the_old_arrow_stands_nowhere_in_the_frontend_source():
    carriers = sorted(
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*")
        if path.suffix in {".svelte", ".js", ".css"} and OLD_ARROW in path.read_text(encoding="utf-8")
    )
    assert carriers == []


def test_the_licence_of_the_drawing_is_named_and_the_code_names_no_one():
    notices = " ".join(NOTICES.read_text(encoding="utf-8").split())
    assert "## Lucide — ISC License, MIT License" in notices
    assert "Lucide Contributors" in notices and "Cole Bemis" in notices
    # The code carries no note about where the drawing came from.
    for name in ("Nachricht.svelte", "Hauszeichen.svelte"):
        source = (TEILE / name).read_text(encoding="utf-8")
        assert "lucide" not in source.lower(), name


def test_the_copy_sign_is_unchanged():
    """The silence check: Copy keeps the drawing it always had."""
    message = (TEILE / "Nachricht.svelte").read_text(encoding="utf-8")
    assert message.count('<rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 012-2h10" />') >= 1
